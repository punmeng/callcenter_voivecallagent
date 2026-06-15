from __future__ import annotations

import json
import math
import mimetypes
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
import asyncio
import base64
import contextlib
import wave
from dataclasses import dataclass
from html import escape as html_escape
from pathlib import Path
from typing import Any

from .config import load_settings
from .corrections import CorrectionEngine
from .uc1_stt_agent import SttAgent


@dataclass
class BenchmarkSample:
    call_id: str
    audio_path: Path
    reference_text: str
    keywords: list[str]
    metadata: dict[str, Any]


@dataclass
class InferenceResult:
    call_id: str
    provider: str
    hypothesis_text: str
    latency_ms: float
    error: str = ""


@dataclass
class BenchmarkEvaluation:
    wer: float
    cer: float
    keyword_recall: float
    confidence: float


@dataclass
class BenchmarkScoringProfile:
    accuracy_weight: float
    latency_weight: float
    cost_weight: float


class SttProvider:
    name: str

    def transcribe(self, sample: BenchmarkSample) -> InferenceResult:
        raise NotImplementedError()

    def display_name(self) -> str:
        return self.name


class AzureSpeechProvider(SttProvider):
    name = "azure-speech-stt"

    def __init__(
        self,
        *,
        provider_name: str = "azure-speech-stt",
        use_phrase_list: bool = True,
        custom_endpoint_id: str | None = None,
        enable_corrections: bool = False,
    ) -> None:
        settings = load_settings()
        self.name = provider_name
        if custom_endpoint_id:
            settings.speech_custom_endpoint_id = custom_endpoint_id
        self._stt = SttAgent(
            settings,
            enable_phrase_list=use_phrase_list,
            enable_corrections=enable_corrections,
        )

    def transcribe(self, sample: BenchmarkSample) -> InferenceResult:
        started = time.perf_counter()
        transcript = self._stt.transcribe_audio(sample.audio_path)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return InferenceResult(
            call_id=sample.call_id,
            provider=self.name,
            hypothesis_text=transcript.full_text,
            latency_ms=elapsed_ms,
        )


class DatasetFieldProvider(SttProvider):
    def __init__(self, name: str, field_name: str, fallback_fields: list[str] | None = None) -> None:
        self.name = name
        self._field_name = field_name
        self._fallback_fields = fallback_fields or []

    def transcribe(self, sample: BenchmarkSample) -> InferenceResult:
        value = sample.metadata.get(self._field_name)
        if not isinstance(value, str) or not value.strip():
            for field in self._fallback_fields:
                candidate = sample.metadata.get(field)
                if isinstance(candidate, str) and candidate.strip():
                    value = candidate
                    break
        hypothesis = str(value).strip() if isinstance(value, str) else ""
        if not hypothesis:
            raise ValueError(
                f"Sample '{sample.call_id}' is missing dataset field '{self._field_name}'. "
                "Populate provider hypotheses in dataset first or implement live adapter."
            )
        return InferenceResult(
            call_id=sample.call_id,
            provider=self.name,
            hypothesis_text=hypothesis,
            latency_ms=0.0,
        )


class VoiceLiveProvider(SttProvider):
    name = "voice-live-api"

    def __init__(
        self,
        *,
        provider_name: str = "voice-live-api",
        transcription_model_override: str | None = None,
        model_override: str | None = None,
        timeout_seconds_override: float | None = None,
    ) -> None:
        self.name = provider_name
        self._endpoint = (os.getenv("AZURE_VOICELIVE_ENDPOINT") or "").strip()
        self._api_key = (os.getenv("AZURE_VOICELIVE_API_KEY") or "").strip()
        self._api_version = (os.getenv("AZURE_VOICELIVE_API_VERSION") or "2026-06-01-preview").strip()
        self._model = (model_override or os.getenv("AZURE_VOICELIVE_MODEL") or "gpt-realtime").strip()
        self._transcription_model = (
            transcription_model_override
            or os.getenv("VOICE_LIVE_TRANSCRIPTION_MODEL")
            or "azure-speech"
        ).strip()
        self._transcription_language = (os.getenv("VOICE_LIVE_TRANSCRIPTION_LANGUAGE") or "zh-TW").strip()
        self._chunk_size_bytes = int(os.getenv("VOICE_LIVE_AUDIO_CHUNK_BYTES", "2400"))
        self._retry_count = int(os.getenv("VOICE_LIVE_RETRY_COUNT", "1"))
        if timeout_seconds_override is not None:
            self._call_timeout_seconds = float(timeout_seconds_override)
        else:
            self._call_timeout_seconds = float(os.getenv("VOICE_LIVE_CALL_TIMEOUT_SECONDS", "25"))
        self._fallback = DatasetFieldProvider(name=self.name, field_name="voice_live_hypothesis")
        self._last_live_diagnostics = ""

    def display_name(self) -> str:
        return (
            f"{self.name} "
            f"(session={self._model}, transcription={self._transcription_model}, lang={self._transcription_language})"
        )

    def transcribe(self, sample: BenchmarkSample) -> InferenceResult:
        if not self._endpoint:
            return self._fallback.transcribe(sample)
        if not sample.audio_path.exists() or not sample.audio_path.is_file():
            return self._fallback.transcribe(sample)

        max_attempts = max(1, self._retry_count + 1)
        last_exc: Exception | None = None
        started = time.perf_counter()
        transcript = ""
        self._last_live_diagnostics = ""
        for attempt in range(1, max_attempts + 1):
            try:
                transcript = asyncio.run(
                    asyncio.wait_for(
                        self._transcribe_via_voicelive(sample.audio_path),
                        timeout=self._call_timeout_seconds,
                    )
                )
                break
            except Exception as exc:
                last_exc = exc
                if attempt >= max_attempts:
                    break
                # Retry transient transport/auth delays once by default.
                wait_seconds = min(2.0 * attempt, 5.0)
                with contextlib.suppress(Exception):
                    time.sleep(wait_seconds)

        elapsed_ms = (time.perf_counter() - started) * 1000

        if last_exc is not None and not transcript:
            # Prefer explicit failure details when fallback field is not available.
            print(f"[{self.name}] live call failed: {type(last_exc).__name__}: {last_exc}", file=sys.stderr)
            try:
                return self._fallback.transcribe(sample)
            except Exception:
                return InferenceResult(
                    call_id=sample.call_id,
                    provider=self.name,
                    hypothesis_text="",
                    latency_ms=elapsed_ms,
                    error=f"Live call failed: {type(last_exc).__name__}: {last_exc}",
                )

        if not transcript.strip():
            diagnostics = f" Diagnostics: {self._last_live_diagnostics}" if self._last_live_diagnostics else ""
            return InferenceResult(
                call_id=sample.call_id,
                provider=self.name,
                hypothesis_text="",
                latency_ms=elapsed_ms,
                error=(
                    "Live call succeeded but returned empty transcript. "
                    "Check audio quality/language or switch Voice Live transcription model."
                    f"{diagnostics}"
                ),
            )

        return InferenceResult(
            call_id=sample.call_id,
            provider=self.name,
            hypothesis_text=transcript.strip(),
            latency_ms=elapsed_ms,
        )

    async def _transcribe_via_voicelive(self, audio_path: Path) -> str:
        from azure.core.credentials import AzureKeyCredential
        from azure.identity.aio import AzureCliCredential
        from azure.ai.voicelive.aio import connect
        from azure.ai.voicelive.models import (
            AudioInputTranscriptionOptions,
            InputAudioFormat,
            Modality,
            RequestSession,
            ServerVad,
        )

        audio_bytes = self._read_pcm16_mono_24k(audio_path)

        cli_timeout = int((os.getenv("VOICE_LIVE_AZ_CLI_TIMEOUT_SECONDS") or "60").strip())
        credential = AzureKeyCredential(self._api_key) if self._api_key else AzureCliCredential(process_timeout=cli_timeout)
        transcript_parts: list[str] = []
        committed_item_id: str | None = None
        transcription_done = False
        response_done_seen = False
        response_done_at = 0.0
        response_wait_seconds = float(os.getenv("VOICE_LIVE_RESPONSE_WAIT_SECONDS", "2.0"))
        transcription_error: str = ""
        event_types_seen: list[str] = []
        event_debug_samples: list[str] = []

        try:
            async with connect(
                endpoint=self._endpoint,
                credential=credential,
                api_version=self._api_version,
                model=self._model,
            ) as connection:
                session_config = RequestSession(
                    modalities=[Modality.TEXT],
                    input_audio_format=InputAudioFormat.PCM16,
                    input_audio_sampling_rate=24000,
                    input_audio_transcription=AudioInputTranscriptionOptions(
                        model=self._transcription_model,
                        language=self._transcription_language,
                    ),
                    turn_detection=ServerVad(
                        threshold=0.5,
                        prefix_padding_ms=300,
                        silence_duration_ms=500,
                    ),
                )

                await connection.session.update(session=session_config)

                for index in range(0, len(audio_bytes), self._chunk_size_bytes):
                    chunk = audio_bytes[index:index + self._chunk_size_bytes]
                    encoded = base64.b64encode(chunk).decode("utf-8")
                    await connection.input_audio_buffer.append(audio=encoded)

                await connection.input_audio_buffer.commit()

                async for event in connection:
                    event_type = str(getattr(event, "type", ""))
                    if event_type:
                        event_types_seen.append(event_type)
                    if len(event_debug_samples) < 6:
                        event_debug_samples.append(self._summarize_live_event(event))

                    if event_type == "input_audio_buffer.committed":
                        item_id = getattr(event, "item_id", None)
                        if isinstance(item_id, str) and item_id.strip():
                            committed_item_id = item_id

                    text = self._extract_transcript_from_event(event)
                    if text:
                        transcript_parts.append(text)

                    if event_type == "conversation.item.input_audio_transcription.failed":
                        err = getattr(event, "error", None)
                        if isinstance(err, dict):
                            transcription_error = str(err.get("message") or err.get("code") or "transcription failed")
                        else:
                            transcription_error = "transcription failed"
                        transcription_done = True

                    if event_type == "conversation.item.input_audio_transcription.completed":
                        event_item_id = getattr(event, "item_id", None)
                        if committed_item_id is None or event_item_id == committed_item_id:
                            transcription_done = True

                    if event_type == "response.done":
                        response_done_seen = True
                        response_done_at = time.perf_counter()

                    if event_type == "error":
                        raise RuntimeError(f"Voice Live server error: {getattr(event, 'error', None)}")

                    # Per API docs, input transcription can arrive before OR after response events.
                    if transcription_done:
                        break

                    if response_done_seen and (time.perf_counter() - response_done_at) >= response_wait_seconds:
                        break
        finally:
            self._last_live_diagnostics = self._build_live_diagnostics(
                event_types_seen=event_types_seen,
                event_debug_samples=event_debug_samples,
                committed_item_id=committed_item_id,
                transcription_done=transcription_done,
                response_done_seen=response_done_seen,
                transcription_error=transcription_error,
                transcript_parts=transcript_parts,
            )
            close_method = getattr(credential, "close", None)
            if callable(close_method):
                await close_method()

        if transcription_error:
            raise RuntimeError(f"Voice Live transcription failed: {transcription_error}")

        return self._dedupe_and_join(transcript_parts)

    @staticmethod
    def _read_pcm16_mono_24k(audio_path: Path) -> bytes:
        """Read WAV and auto-convert to mono PCM16 24kHz (required by Voice Live)."""
        import struct
        with wave.open(str(audio_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frame_rate = wav_file.getframerate()
            raw = wav_file.readframes(wav_file.getnframes())

        # Step 1: ensure 16-bit samples
        if sample_width == 1:
            # 8-bit unsigned -> 16-bit signed
            samples = struct.unpack(f"{len(raw)}B", raw)
            raw = struct.pack(f"{len(samples)}h", *(s * 256 - 32768 for s in samples))
            sample_width = 2
        elif sample_width != 2:
            raise ValueError(f"Voice Live adapter only supports 8/16-bit WAV; got {sample_width*8}-bit: {audio_path}")

        n_frames = len(raw) // (sample_width * channels)

        # Step 2: mix down to mono
        if channels > 1:
            frames = struct.unpack(f"{n_frames * channels}h", raw)
            # Pick the strongest channel instead of averaging to avoid voice attenuation.
            channel_samples = [frames[c::channels] for c in range(channels)]
            channel_energy = [sum(s * s for s in samples) for samples in channel_samples]
            best_channel_index = max(range(channels), key=lambda i: channel_energy[i])
            mono = list(channel_samples[best_channel_index])
        else:
            mono = list(struct.unpack(f"{n_frames}h", raw))

        # Step 2.5: normalize gain for very quiet audio.
        peak = max((abs(s) for s in mono), default=0)
        if 0 < peak < 8000:
            scale = min(6.0, 14000.0 / peak)
            mono = [max(-32768, min(32767, int(s * scale))) for s in mono]

        raw = struct.pack(f"{n_frames}h", *mono)

        # Step 3: resample to 24000 Hz via linear interpolation
        if frame_rate != 24000:
            src_len = n_frames
            dst_len = int(src_len * 24000 / frame_rate)
            src_samples = struct.unpack(f"{src_len}h", raw)
            resampled: list[int] = []
            for i in range(dst_len):
                src_pos = i * (src_len - 1) / max(dst_len - 1, 1)
                lo = int(src_pos)
                hi = min(lo + 1, src_len - 1)
                frac = src_pos - lo
                sample = int(src_samples[lo] * (1 - frac) + src_samples[hi] * frac)
                resampled.append(max(-32768, min(32767, sample)))
            raw = struct.pack(f"{dst_len}h", *resampled)

        return raw

    @staticmethod
    def _extract_transcript_from_event(event: Any) -> str:
        event_type = str(getattr(event, "type", "")).upper()

        if "INPUT" in event_type and "TRANSCRIPTION" in event_type:
            for key in ("transcript", "text", "delta"):
                value = getattr(event, key, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        item = getattr(event, "item", None)
        if item is not None and str(getattr(item, "role", "")).lower() in {"user", "input"}:
            for key in ("transcript", "text"):
                value = getattr(item, key, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()

            content = getattr(item, "content", None)
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        value = part.get("transcript") or part.get("text")
                        if isinstance(value, str) and value.strip():
                            return value.strip()

        # Some SDK model classes expose dict payloads directly.
        if isinstance(event, dict):
            value = event.get("transcript") or event.get("text") or event.get("delta")
            if isinstance(value, str) and value.strip():
                return value.strip()

        return ""

    @staticmethod
    def _dedupe_and_join(parts: list[str]) -> str:
        merged: list[str] = []
        for part in parts:
            text = part.strip()
            if not text:
                continue
            if merged and merged[-1] == text:
                continue
            merged.append(text)
        return " ".join(merged)

    @staticmethod
    def _summarize_live_event(event: Any) -> str:
        event_type = str(getattr(event, "type", "") or "<missing>")
        fields: list[str] = []
        for key in ("item_id", "transcript", "text", "delta", "error"):
            value = getattr(event, key, None)
            if isinstance(value, str) and value.strip():
                compact = value.strip().replace("\n", " ")
                fields.append(f"{key}={compact[:80]}")
            elif value is not None and key == "error":
                fields.append(f"error={value}")
        if not fields and isinstance(event, dict):
            for key in ("item_id", "transcript", "text", "delta", "error"):
                value = event.get(key)
                if isinstance(value, str) and value.strip():
                    compact = value.strip().replace("\n", " ")
                    fields.append(f"{key}={compact[:80]}")
                elif value is not None and key == "error":
                    fields.append(f"error={value}")
        suffix = ", ".join(fields) if fields else "no transcript fields"
        return f"{event_type} ({suffix})"

    @staticmethod
    def _build_live_diagnostics(
        *,
        event_types_seen: list[str],
        event_debug_samples: list[str],
        committed_item_id: str | None,
        transcription_done: bool,
        response_done_seen: bool,
        transcription_error: str,
        transcript_parts: list[str],
    ) -> str:
        unique_event_types = list(dict.fromkeys(event_types_seen))
        details = [
            f"session_model events={unique_event_types[:8] or ['<none>']}",
            f"committed_item_id={committed_item_id or '<none>'}",
            f"transcription_done={transcription_done}",
            f"response_done_seen={response_done_seen}",
            f"transcript_parts={len(transcript_parts)}",
        ]
        if transcription_error:
            details.append(f"transcription_error={transcription_error}")
        if event_debug_samples:
            details.append(f"samples={event_debug_samples}")
        return "; ".join(details)


class MaiTranscribeProvider(SttProvider):
    name = "mai-transcribe-1.5"

    def __init__(self) -> None:
        self._endpoint = (os.getenv("AZURE_SPEECH_ENDPOINT") or os.getenv("SPEECH_ENDPOINT") or "").strip()
        self._api_key = (os.getenv("AZURE_SPEECH_KEY") or os.getenv("SPEECH_KEY") or "").strip()
        self._api_version = (os.getenv("MAI_TRANSCRIBE_API_VERSION") or "2025-10-15").strip()
        self._aad_token_scope = "https://cognitiveservices.azure.com/.default"
        self._fallback = DatasetFieldProvider(
            name=self.name,
            field_name="mai_transcribe_hypothesis",
            fallback_fields=["mai_voice_hypothesis"],
        )

    def transcribe(self, sample: BenchmarkSample) -> InferenceResult:
        # Fallback mode keeps benchmark runnable when keys/endpoints are unavailable.
        if not self._endpoint:
            return self._fallback.transcribe(sample)

        if not sample.audio_path.exists() or not sample.audio_path.is_file():
            return self._fallback.transcribe(sample)

        started = time.perf_counter()
        payload = self._call_api(sample.audio_path)
        elapsed_ms = (time.perf_counter() - started) * 1000
        text = self._extract_text(payload)
        if not text:
            raise ValueError(
                f"MAI-Transcribe response missing transcript text for '{sample.call_id}': {json.dumps(payload, ensure_ascii=False)[:500]}"
            )

        return InferenceResult(
            call_id=sample.call_id,
            provider=self.name,
            hypothesis_text=text,
            latency_ms=elapsed_ms,
        )

    def _call_api(self, audio_path: Path) -> dict[str, Any]:
        url = f"{self._endpoint.rstrip('/')}/speechtotext/transcriptions:transcribe?api-version={self._api_version}"
        content_type, body = self._build_multipart_body(audio_path)
        headers = {
            "Content-Type": content_type,
        }
        if self._api_key:
            headers["Ocp-Apim-Subscription-Key"] = self._api_key
        else:
            token = self._get_aad_access_token()
            if not token:
                raise RuntimeError("MAI-Transcribe requires SPEECH_KEY or Azure AD token via az login.")
            headers["Authorization"] = f"Bearer {token}"

        request = urllib.request.Request(
            url=url,
            method="POST",
            data=body,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = response.read().decode("utf-8")
                parsed = json.loads(payload)
                return parsed if isinstance(parsed, dict) else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"MAI-Transcribe HTTP {exc.code}: {detail}") from exc

    @staticmethod
    def _build_multipart_body(audio_path: Path) -> tuple[str, bytes]:
        boundary = f"----voiceqa-{uuid.uuid4().hex}"
        audio_mime = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
        definition = {
            "enhancedMode": {
                "enabled": True,
                "task": "transcribe",
            }
        }

        chunks: list[bytes] = []
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                'Content-Disposition: form-data; name="audio"; filename="'
                + audio_path.name
                + '"\r\n'
            ).encode("utf-8")
        )
        chunks.append(f"Content-Type: {audio_mime}\r\n\r\n".encode("utf-8"))
        chunks.append(audio_path.read_bytes())
        chunks.append("\r\n".encode("utf-8"))

        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append('Content-Disposition: form-data; name="definition"\r\n'.encode("utf-8"))
        chunks.append("Content-Type: application/json\r\n\r\n".encode("utf-8"))
        chunks.append(json.dumps(definition, ensure_ascii=False).encode("utf-8"))
        chunks.append("\r\n".encode("utf-8"))

        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(chunks)
        return f"multipart/form-data; boundary={boundary}", body

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""

        direct_text = payload.get("text") or payload.get("transcript")
        if isinstance(direct_text, str) and direct_text.strip():
            return direct_text.strip()

        combined = payload.get("combinedPhrases")
        if isinstance(combined, list):
            for item in combined:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        return text.strip()

        phrases = payload.get("phrases")
        if isinstance(phrases, list):
            parts: list[str] = []
            for phrase in phrases:
                if isinstance(phrase, dict):
                    text = phrase.get("text") or phrase.get("display") or phrase.get("lexical")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            if parts:
                return " ".join(parts)

        return ""

    def _get_aad_access_token(self) -> str:
        try:
            from azure.identity import AzureCliCredential

            credential = AzureCliCredential()
            token = credential.get_token(self._aad_token_scope)
            return token.token if token and token.token else ""
        except Exception:
            return ""


class AzureSpeechNoPhraseListProvider(AzureSpeechProvider):
    name = "azure-speech-stt-no-phrase-list"

    def __init__(self) -> None:
        super().__init__(provider_name=self.name, use_phrase_list=False)


class AzureSpeechFastProvider(SttProvider):
    """Azure Speech SpeechRecognizer with a fixed locale — no LID, no diarization.

    Fastest SDK path: eliminates auto-language-detection (LID) and ConversationTranscriber
    speaker-diarization overhead. Use when the source language is known (default: first
    locale in SPEECH_LANGUAGES, usually zh-TW for Traditional Chinese).

    Compare against azure-speech-stt to quantify the latency cost of LID + diarization.
    Optionally add phrase-list boosting via azure-speech-stt-fast-phrase-list.
    """

    name = "azure-speech-stt-fast"

    def __init__(
        self,
        *,
        provider_name: str = "azure-speech-stt-fast",
        use_phrase_list: bool = False,
        enable_corrections: bool = False,
    ) -> None:
        self.name = provider_name
        settings = load_settings()
        self._agent = SttAgent(
            settings,
            enable_phrase_list=use_phrase_list,
            enable_corrections=enable_corrections,
        )
        self._locale = settings.speech_languages[0] if settings.speech_languages else "zh-TW"

    def transcribe(self, sample: BenchmarkSample) -> InferenceResult:
        import azure.cognitiveservices.speech as speechsdk

        speech_config = self._agent._build_speech_config()
        speech_config.speech_recognition_language = self._locale
        audio_config = speechsdk.audio.AudioConfig(filename=str(sample.audio_path))
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )
        self._agent._attach_phrase_list(recognizer)

        parts: list[str] = []
        done = threading.Event()

        def _on_recognized(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
                parts.append(evt.result.text.strip())

        def _on_done(_: speechsdk.SessionEventArgs) -> None:
            done.set()

        recognizer.recognized.connect(_on_recognized)
        recognizer.session_stopped.connect(_on_done)
        recognizer.canceled.connect(_on_done)

        started = time.perf_counter()
        recognizer.start_continuous_recognition_async().get()
        done.wait(timeout=120)
        recognizer.stop_continuous_recognition_async().get()
        elapsed_ms = (time.perf_counter() - started) * 1000

        return InferenceResult(
            call_id=sample.call_id,
            provider=self.name,
            hypothesis_text=" ".join(parts).strip(),
            latency_ms=elapsed_ms,
        )


class AzureSpeechRestProvider(SttProvider):
    """Azure Speech fast transcription REST API (synchronous, single-file).

    Uses the POST /speechtotext/transcriptions:transcribe endpoint with standard Azure
    Speech locale-based recognition (no MAI model). Useful for comparing REST vs SDK
    latency on the same Azure Speech resource; also lower cost than real-time SDK.

    Requires SPEECH_ENDPOINT (cognitiveservices.azure.com) + SPEECH_KEY or az login.
    Override API version with AZURE_SPEECH_REST_API_VERSION (default: 2024-11-15).
    """

    name = "azure-speech-stt-rest"

    def __init__(self) -> None:
        settings = load_settings()
        self._endpoint = (settings.speech_endpoint or "").strip().rstrip("/")
        self._api_key = settings.speech_key or ""
        self._api_version = (os.getenv("AZURE_SPEECH_REST_API_VERSION") or "2024-11-15").strip()
        self._locale = settings.speech_languages[0] if settings.speech_languages else "zh-TW"
        self._aad_scope = "https://cognitiveservices.azure.com/.default"

    def transcribe(self, sample: BenchmarkSample) -> InferenceResult:
        if not self._endpoint:
            raise RuntimeError(
                "azure-speech-stt-rest requires SPEECH_ENDPOINT (cognitiveservices.azure.com endpoint)."
            )
        started = time.perf_counter()
        payload = self._call_api(sample.audio_path)
        elapsed_ms = (time.perf_counter() - started) * 1000
        text = self._extract_text(payload)
        if not text:
            raise ValueError(
                f"azure-speech-stt-rest: empty transcript for '{sample.call_id}': "
                f"{json.dumps(payload, ensure_ascii=False)[:300]}"
            )
        return InferenceResult(
            call_id=sample.call_id,
            provider=self.name,
            hypothesis_text=text,
            latency_ms=elapsed_ms,
        )

    def _call_api(self, audio_path: Path) -> dict[str, Any]:
        url = f"{self._endpoint}/speechtotext/transcriptions:transcribe?api-version={self._api_version}"
        definition = {"locales": [self._locale]}
        content_type, body = self._build_multipart_body(audio_path, definition)
        headers: dict[str, str] = {"Content-Type": content_type}
        if self._api_key:
            headers["Ocp-Apim-Subscription-Key"] = self._api_key
        else:
            headers["Authorization"] = f"Bearer {self._get_aad_token()}"
        req = urllib.request.Request(url=url, method="POST", data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                return payload if isinstance(payload, dict) else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"azure-speech-stt-rest HTTP {exc.code}: {detail}") from exc

    @staticmethod
    def _build_multipart_body(audio_path: Path, definition: dict) -> tuple[str, bytes]:
        boundary = f"----voiceqa-{uuid.uuid4().hex}"
        audio_mime = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
        chunks: list[bytes] = []
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="audio"; filename="{audio_path.name}"\r\n'.encode())
        chunks.append(f"Content-Type: {audio_mime}\r\n\r\n".encode())
        chunks.append(audio_path.read_bytes())
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(b'Content-Disposition: form-data; name="definition"\r\n')
        chunks.append(b"Content-Type: application/json\r\n\r\n")
        chunks.append(json.dumps(definition, ensure_ascii=False).encode())
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        return f"multipart/form-data; boundary={boundary}", b"".join(chunks)

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        direct = payload.get("text") or payload.get("transcript")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        combined = payload.get("combinedPhrases")
        if isinstance(combined, list):
            for item in combined:
                if isinstance(item, dict):
                    t = item.get("text")
                    if isinstance(t, str) and t.strip():
                        return t.strip()
        phrases = payload.get("phrases")
        if isinstance(phrases, list):
            parts: list[str] = []
            for p in phrases:
                if isinstance(p, dict):
                    t = p.get("text") or p.get("display") or p.get("lexical")
                    if isinstance(t, str) and t.strip():
                        parts.append(t.strip())
            if parts:
                return " ".join(parts)
        return ""

    def _get_aad_token(self) -> str:
        try:
            from azure.identity import AzureCliCredential
            token = AzureCliCredential().get_token(self._aad_scope).token
            return token or ""
        except Exception as exc:
            raise RuntimeError(f"AAD token failed for azure-speech-stt-rest: {exc}") from exc


class GptAudioTranscribeProvider(SttProvider):
    """Azure OpenAI audio transcriptions endpoint (e.g. gpt-4o-transcribe).

    Supports Traditional Chinese (zh-TW) mixed with English. Transcription language
    is taken from the first locale in SPEECH_LANGUAGES (default: zh-TW).

    Requires AOAI_ENDPOINT and AOAI_API_KEY (or AOAI_USE_ENTRA_ID=true).
    Override the target model with GPT_AUDIO_TRANSCRIBE_DEPLOYMENT
    (default: gpt-4o-transcribe). Suitable for comparing GPT-family accuracy vs
    dedicated speech services.
    """

    name = "gpt-audio-transcribe"

    def __init__(self) -> None:
        settings = load_settings()
        env_deployment = (os.getenv("GPT_AUDIO_TRANSCRIBE_DEPLOYMENT") or "").strip()
        settings_deployment = (settings.aoai_deployment or "").strip()

        def _looks_audio_transcribe_model(name: str) -> bool:
            normalized = name.lower()
            return (
                "transcribe" in normalized
                or "whisper" in normalized
                or normalized.startswith("gpt-4o-mini-transcribe")
            )

        if env_deployment:
            self._deployment = env_deployment
        elif settings_deployment and _looks_audio_transcribe_model(settings_deployment):
            self._deployment = settings_deployment
        else:
            # Do not implicitly reuse chat deployment names (for example gpt-5.x)
            # for audio transcription operations.
            self._deployment = "gpt-4o-transcribe"
            if settings_deployment and not _looks_audio_transcribe_model(settings_deployment):
                print(
                    (
                        "[gpt-audio-transcribe] AOAI deployment "
                        f"'{settings_deployment}' does not look audio-compatible; "
                        "falling back to 'gpt-4o-transcribe'. "
                        "Set GPT_AUDIO_TRANSCRIBE_DEPLOYMENT to override."
                    ),
                    file=sys.stderr,
                )
        # Strip /openai/v1 or /openai path suffixes to reach the bare resource URL.
        raw = (settings.aoai_endpoint or "").rstrip("/")
        for suffix in ("/openai/v1", "/openai"):
            if raw.endswith(suffix):
                raw = raw[: -len(suffix)]
                break
        self._base_url = raw
        self._api_key = settings.aoai_api_key or ""
        self._api_version = settings.aoai_api_version or "2024-10-21"
        self._use_entra_id = settings.aoai_use_entra_id
        self._entra_scope = settings.aoai_scope
        lang = settings.speech_languages[0] if settings.speech_languages else "zh-TW"
        self._language = lang  # Azure OpenAI audio API accepts BCP-47 (e.g. zh-TW)

    def transcribe(self, sample: BenchmarkSample) -> InferenceResult:
        if not self._base_url:
            raise RuntimeError("gpt-audio-transcribe requires AOAI_ENDPOINT.")
        if not self._api_key and not self._use_entra_id:
            raise RuntimeError(
                "gpt-audio-transcribe requires AOAI_API_KEY or AOAI_USE_ENTRA_ID=true."
            )
        started = time.perf_counter()
        text = self._call_api(sample.audio_path)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return InferenceResult(
            call_id=sample.call_id,
            provider=self.name,
            hypothesis_text=text,
            latency_ms=elapsed_ms,
        )

    def _call_api(self, audio_path: Path) -> str:
        url = (
            f"{self._base_url}/openai/deployments/{self._deployment}"
            f"/audio/transcriptions?api-version={self._api_version}"
        )
        boundary = f"----voiceqa-{uuid.uuid4().hex}"
        audio_mime = mimetypes.guess_type(audio_path.name)[0] or "audio/wav"

        def _field(name: str, value: bytes, content_type: str | None = None, filename: str | None = None) -> bytes:
            disp = f'Content-Disposition: form-data; name="{name}"'
            if filename:
                disp += f'; filename="{filename}"'
            header_line = disp + "\r\n"
            if content_type:
                header_line += f"Content-Type: {content_type}\r\n"
            return f"--{boundary}\r\n".encode() + header_line.encode() + b"\r\n" + value + b"\r\n"

        body = (
            _field("file", audio_path.read_bytes(), content_type=audio_mime, filename=audio_path.name)
            + _field("model", self._deployment.encode())
            + _field("language", self._language.encode())
            + _field("response_format", b"json")
            + f"--{boundary}--\r\n".encode()
        )

        headers: dict[str, str] = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if self._api_key:
            headers["api-key"] = self._api_key
        else:
            try:
                from azure.identity import AzureCliCredential
                token = AzureCliCredential().get_token(self._entra_scope).token
                headers["Authorization"] = f"Bearer {token}"
            except Exception as exc:
                raise RuntimeError(f"Entra ID token failed for gpt-audio-transcribe: {exc}") from exc

        req = urllib.request.Request(url=url, method="POST", data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                return str(payload.get("text") or "").strip()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            if "OperationNotSupported" in detail or "audioTranscriptions operation does not work" in detail:
                raise RuntimeError(
                    (
                        "gpt-audio-transcribe operation is not supported by deployment "
                        f"'{self._deployment}'. Configure GPT_AUDIO_TRANSCRIBE_DEPLOYMENT "
                        "to an audio transcription model deployment (for example gpt-4o-transcribe). "
                        f"Raw error: HTTP {exc.code}: {detail}"
                    )
                ) from exc
            raise RuntimeError(f"gpt-audio-transcribe HTTP {exc.code}: {detail}") from exc


class AzureSpeechCustomProvider(AzureSpeechProvider):
    name = "azure-speech-stt-custom"

    def __init__(self) -> None:
        custom_endpoint_id = (
            os.getenv("AZURE_SPEECH_CUSTOM_ENDPOINT_ID")
            or os.getenv("SPEECH_CUSTOM_ENDPOINT_ID")
            or ""
        ).strip()
        if not custom_endpoint_id:
            raise ValueError(
                "azure-speech-stt-custom requires AZURE_SPEECH_CUSTOM_ENDPOINT_ID (or SPEECH_CUSTOM_ENDPOINT_ID)."
            )
        super().__init__(
            provider_name=self.name,
            use_phrase_list=True,
            custom_endpoint_id=custom_endpoint_id,
        )


def _tokenize_words(text: str) -> list[str]:
    normalized = _normalize_eval_text(text, keep_spaces=True)
    if not normalized:
        return []

    # For Chinese-heavy text, use character-level CJK tokenization while preserving
    # contiguous Latin/number terms as whole tokens.
    has_cjk = bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", normalized))
    if has_cjk:
        return re.findall(
            r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]|[a-z0-9]+(?:[._-][a-z0-9]+)*",
            normalized,
        )

    return re.findall(r"[a-z0-9]+(?:[._'-][a-z0-9]+)*", normalized)


def _tokenize_chars(text: str) -> list[str]:
    normalized = _normalize_eval_text(text, keep_spaces=False)
    return list(normalized)


def _normalize_eval_text(text: str, *, keep_spaces: bool) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("\r", " ").replace("\n", " ").replace("\t", " ")

    parts: list[str] = []
    for char in normalized:
        category = unicodedata.category(char)
        if char.isspace():
            if keep_spaces:
                parts.append(" ")
            continue
        if category.startswith("P"):
            if keep_spaces:
                parts.append(" ")
            continue
        parts.append(char.lower())

    if not keep_spaces:
        return "".join(parts)
    return " ".join("".join(parts).split())


def _levenshtein_distance(lhs: list[str], rhs: list[str]) -> int:
    if not lhs:
        return len(rhs)
    if not rhs:
        return len(lhs)

    prev = list(range(len(rhs) + 1))
    for i, left_token in enumerate(lhs, start=1):
        curr = [i] + [0] * len(rhs)
        for j, right_token in enumerate(rhs, start=1):
            cost = 0 if left_token == right_token else 1
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + cost,
            )
        prev = curr
    return prev[-1]


def compute_wer(reference: str, hypothesis: str) -> float:
    ref_tokens = _tokenize_words(reference)
    hyp_tokens = _tokenize_words(hypothesis)
    if not ref_tokens:
        return 0.0 if not hyp_tokens else 1.0
    distance = _levenshtein_distance(ref_tokens, hyp_tokens)
    return distance / len(ref_tokens)


def compute_cer(reference: str, hypothesis: str) -> float:
    ref_tokens = _tokenize_chars(reference)
    hyp_tokens = _tokenize_chars(hypothesis)
    if not ref_tokens:
        return 0.0 if not hyp_tokens else 1.0
    distance = _levenshtein_distance(ref_tokens, hyp_tokens)
    return distance / len(ref_tokens)


def compute_keyword_recall(reference_keywords: list[str], hypothesis: str) -> float:
    if not reference_keywords:
        return 1.0
    hyp_normalized = hypothesis.lower()
    hits = sum(1 for keyword in reference_keywords if keyword.lower() in hyp_normalized)
    return hits / len(reference_keywords)


def compute_confidence(wer: float, cer: float, keyword_recall: float, *, has_error: bool = False) -> float:
    """Compute a normalized confidence score (0-1) from benchmark metrics.

    Heuristic weighting:
    - WER (45%): lower is better
    - CER (35%): lower is better
    - Keyword Recall (20%): higher is better
    """
    if has_error:
        return 0.0

    score = (0.45 * (1.0 - wer)) + (0.35 * (1.0 - cer)) + (0.20 * keyword_recall)
    return max(0.0, min(1.0, score))


def compute_evaluation(reference_text: str, hypothesis_text: str, keywords: list[str], *, has_error: bool = False) -> BenchmarkEvaluation:
    wer = compute_wer(reference_text, hypothesis_text)
    cer = compute_cer(reference_text, hypothesis_text)
    keyword_recall = compute_keyword_recall(keywords, hypothesis_text)
    confidence = compute_confidence(wer, cer, keyword_recall, has_error=has_error)
    return BenchmarkEvaluation(
        wer=wer,
        cer=cer,
        keyword_recall=keyword_recall,
        confidence=confidence,
    )


def load_scoring_profile() -> BenchmarkScoringProfile:
    accuracy_weight = _read_weight_env("BENCHMARK_ACCURACY_WEIGHT", 0.7)
    latency_weight = _read_weight_env("BENCHMARK_LATENCY_WEIGHT", 0.2)
    cost_weight = _read_weight_env("BENCHMARK_COST_WEIGHT", 0.1)
    total_weight = accuracy_weight + latency_weight + cost_weight
    if total_weight <= 0:
        return BenchmarkScoringProfile(accuracy_weight=0.7, latency_weight=0.2, cost_weight=0.1)
    return BenchmarkScoringProfile(
        accuracy_weight=accuracy_weight / total_weight,
        latency_weight=latency_weight / total_weight,
        cost_weight=cost_weight / total_weight,
    )


def _read_weight_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(0.0, value)


def parse_dataset(dataset_path: Path) -> list[BenchmarkSample]:
    if not dataset_path.exists() or not dataset_path.is_file():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    samples: list[BenchmarkSample] = []
    for index, raw_line in enumerate(dataset_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at line {index}: {exc}") from exc

        call_id = str(payload.get("call_id") or "").strip()
        audio_path_raw = str(payload.get("audio_path") or "").strip()
        reference_text = str(payload.get("reference_text") or "").strip()
        keywords_raw = payload.get("keywords") or []

        if not call_id or not audio_path_raw or not reference_text:
            raise ValueError(f"Dataset line {index} must include call_id, audio_path, and reference_text")

        keywords: list[str] = []
        if isinstance(keywords_raw, list):
            keywords = [str(item).strip() for item in keywords_raw if str(item).strip()]

        samples.append(
            BenchmarkSample(
                call_id=call_id,
                audio_path=Path(audio_path_raw),
                reference_text=reference_text,
                keywords=keywords,
                metadata=payload,
            )
        )

    if not samples:
        raise ValueError("Dataset has no valid rows")
    return samples


def _is_voice_live_transport_error(message: str) -> bool:
    text = (message or "").lower()
    return (
        "cannot write to closing transport" in text
        or "failed to establish websocket connection" in text
        or "winerror 64" in text
        or "connection reset" in text
        or "connection aborted" in text
    )


def _run_provider(
    provider: SttProvider,
    samples: list[BenchmarkSample],
    output_dir: Path,
) -> dict[str, Any]:
    """Run all samples for a single provider and return its summary row."""
    results_path = output_dir / f"{provider.name}.results.jsonl"
    provider_display_name = provider.display_name()
    row_count = 0
    wer_total = 0.0
    cer_total = 0.0
    keyword_total = 0.0
    confidence_total = 0.0
    corrected_wer_total = 0.0
    corrected_cer_total = 0.0
    corrected_keyword_total = 0.0
    corrected_confidence_total = 0.0
    latency_total = 0.0
    provider_blocked_error: str | None = None
    correction_engine = CorrectionEngine.from_file(load_settings().corrections_path)

    with results_path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            if provider.name.startswith("azure-speech-stt") and not sample.audio_path.exists():
                raise FileNotFoundError(
                    f"Audio file not found for call '{sample.call_id}': {sample.audio_path}"
                )

            if provider_blocked_error:
                result = InferenceResult(
                    call_id=sample.call_id,
                    provider=provider.name,
                    hypothesis_text="",
                    latency_ms=0.0,
                    error=provider_blocked_error,
                )
                error_message = provider_blocked_error
            else:
                error_message = ""
                try:
                    result = provider.transcribe(sample)
                except Exception as exc:
                    error_message = f"{type(exc).__name__}: {exc}"
                    print(
                        f"[{provider.name}] sample '{sample.call_id}' failed: {error_message}",
                        file=sys.stderr,
                    )
                    if provider.name.startswith("voice-live-api") and _is_voice_live_transport_error(error_message):
                        provider_blocked_error = (
                            "Voice Live transport unavailable in this run; "
                            "remaining samples skipped for this provider. "
                            f"First error: {error_message}"
                        )
                    result = InferenceResult(
                        call_id=sample.call_id,
                        provider=provider.name,
                        hypothesis_text="",
                        latency_ms=0.0,
                        error=error_message,
                    )

            raw_eval = compute_evaluation(
                sample.reference_text,
                result.hypothesis_text,
                sample.keywords,
                has_error=bool(result.error or error_message),
            )
            corrected_hypothesis = correction_engine.apply(result.hypothesis_text)
            corrected_eval = compute_evaluation(
                sample.reference_text,
                corrected_hypothesis,
                sample.keywords,
                has_error=bool(result.error or error_message),
            )

            record = {
                "call_id": sample.call_id,
                "provider": provider.name,
                "provider_display": provider_display_name,
                "audio_path": str(sample.audio_path),
                "reference_text": sample.reference_text,
                "hypothesis_text": result.hypothesis_text,
                "wer": raw_eval.wer,
                "cer": raw_eval.cer,
                "keyword_recall": raw_eval.keyword_recall,
                "confidence": raw_eval.confidence,
                "corrected_hypothesis_text": corrected_hypothesis,
                "corrected_wer": corrected_eval.wer,
                "corrected_cer": corrected_eval.cer,
                "corrected_keyword_recall": corrected_eval.keyword_recall,
                "corrected_confidence": corrected_eval.confidence,
                "latency_ms": result.latency_ms,
                "error": result.error or error_message,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

            row_count += 1
            wer_total += raw_eval.wer
            cer_total += raw_eval.cer
            keyword_total += raw_eval.keyword_recall
            confidence_total += raw_eval.confidence
            corrected_wer_total += corrected_eval.wer
            corrected_cer_total += corrected_eval.cer
            corrected_keyword_total += corrected_eval.keyword_recall
            corrected_confidence_total += corrected_eval.confidence
            latency_total += result.latency_ms

    return {
        "provider": provider.name,
        "provider_display": provider_display_name,
        "samples": row_count,
        "avg_wer": wer_total / max(1, row_count),
        "avg_cer": cer_total / max(1, row_count),
        "avg_keyword_recall": keyword_total / max(1, row_count),
        "avg_confidence": confidence_total / max(1, row_count),
        "avg_corrected_wer": corrected_wer_total / max(1, row_count),
        "avg_corrected_cer": corrected_cer_total / max(1, row_count),
        "avg_corrected_keyword_recall": corrected_keyword_total / max(1, row_count),
        "avg_corrected_confidence": corrected_confidence_total / max(1, row_count),
        "avg_latency_ms": latency_total / max(1, row_count),
    }


def run_benchmark(
    *,
    providers: list[SttProvider],
    samples: list[BenchmarkSample],
    output_dir: Path,
    max_workers: int = 1,
) -> Path:
    """Run the benchmark across all providers.

    When max_workers > 1, providers execute concurrently via ThreadPoolExecutor,
    which reduces total wall-clock time when the bottleneck is network I/O.
    Sample ordering within each provider is still sequential.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    total_audio_seconds = sum(
        float(sample.metadata.get("audio_duration_seconds") or 0.0)
        for sample in samples
        if isinstance(sample.metadata.get("audio_duration_seconds"), (int, float))
        and not math.isnan(float(sample.metadata.get("audio_duration_seconds") or 0.0))
    )

    if max_workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        summary_rows: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(max_workers, len(providers))) as executor:
            future_map = {
                executor.submit(_run_provider, p, samples, output_dir): p
                for p in providers
            }
            for future in as_completed(future_map):
                summary_rows.append(future.result())
    else:
        summary_rows = [_run_provider(p, samples, output_dir) for p in providers]

    # Preserve original provider ordering in the summary table.
    provider_order = {p.name: i for i, p in enumerate(providers)}
    summary_rows.sort(key=lambda r: provider_order.get(r["provider"], 9999))

    scoring_profile = load_scoring_profile()
    for row in summary_rows:
        row["estimated_cost_usd"] = estimate_audio_cost_usd(row["provider"], total_audio_seconds)

    _apply_decision_scores(summary_rows, scoring_profile)

    summary_path = output_dir / "summary.md"
    ranked_rows = sorted(
        summary_rows,
        key=lambda item: (-item.get("decision_score", 0.0), item["avg_wer"], item["avg_latency_ms"]),
    )
    best_row = ranked_rows[0]
    voice_live_rows = [row for row in ranked_rows if row["provider"].startswith("voice-live-api")]
    voice_live_failed = any(row["avg_keyword_recall"] <= 0.0 or row["avg_wer"] >= 1.0 for row in voice_live_rows)
    best_voice_live = min(
        voice_live_rows,
        key=lambda item: (-item.get("decision_score", 0.0), item["avg_wer"], item["avg_latency_ms"]),
    ) if voice_live_rows else None

    lines = [
        "# STT Benchmark Summary",
        "",
        "| Provider | Samples | Avg WER | Avg CER | Avg Keyword Recall | Avg Confidence | Avg Latency (ms) | Est. Cost (USD) | Decision Score |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in ranked_rows:
        provider_display = str(row.get("provider_display") or row["provider"])
        estimated_cost = row.get("estimated_cost_usd")
        estimated_cost_text = f"{estimated_cost:.4f}" if isinstance(estimated_cost, (int, float)) else "N/A"
        lines.append(
            "| "
            f"{provider_display} | "
            f"{row['samples']} | "
            f"{row['avg_wer']:.4f} | "
            f"{row['avg_cer']:.4f} | "
            f"{row['avg_keyword_recall']:.4f} | "
            f"{row.get('avg_confidence', 0.0):.4f} | "
            f"{row['avg_latency_ms']:.2f} | "
            f"{estimated_cost_text} | "
            f"{row.get('decision_score', 0.0):.4f} |"
        )
    lines.append("")
    lines.append("Lower WER/CER, latency, and cost are better; higher keyword recall, confidence, and decision score are better.")
    lines.append(
        "Raw transcript metrics drive the recommendation. Corrected transcript metrics are reported separately so post-processing does not bias provider ranking."
    )
    lines.append("")
    lines.append("## Recommendation")
    lines.append("")
    best_row_display = str(best_row.get("provider_display") or best_row["provider"])
    lines.append(
        f"- Recommended default: `{best_row_display}`. It has the best weighted decision score in this run based on raw accuracy, latency, and estimated cost."
    )
    if best_voice_live is not None:
        best_voice_live_display = str(best_voice_live.get("provider_display") or best_voice_live["provider"])
        lines.append(
            f"- Best Voice Live option in this run: `{best_voice_live_display}`. Use it only if you specifically want Voice Live behavior and can accept its current quality tradeoffs."
        )
        if voice_live_failed:
            lines.append(
                "- Voice Live is not suitable for this environment yet: the live runs failed to produce usable transcripts, so Azure Speech STT is the safer choice for now."
            )
    if best_row["provider"].startswith("azure-speech-stt"):
        lines.append("- If you want the safest quality choice for production-style transcription on this dataset, stay with Azure Speech STT.")
    elif best_row["provider"].startswith("voice-live-api"):
        lines.append("- Voice Live is the strongest option here, but verify stability and latency on a larger sample set before standardizing it.")
    else:
        lines.append(f"- If cost matters more than quality, compare `{best_row_display}` against the lowest-cost candidate in your own dataset before deciding.")

    lines.append("")
    lines.append("## Corrected Transcript View")
    lines.append("")
    lines.append("| Provider | Avg Corrected WER | Avg Corrected CER | Avg Corrected Keyword Recall | Avg Corrected Confidence |")
    lines.append("|---|---:|---:|---:|---:|")
    for row in ranked_rows:
        provider_display = str(row.get("provider_display") or row["provider"])
        lines.append(
            "| "
            f"{provider_display} | "
            f"{row.get('avg_corrected_wer', 0.0):.4f} | "
            f"{row.get('avg_corrected_cer', 0.0):.4f} | "
            f"{row.get('avg_corrected_keyword_recall', 0.0):.4f} | "
            f"{row.get('avg_corrected_confidence', 0.0):.4f} |"
        )
    lines.append("")
    lines.append("## Voice Model Benchmark")
    lines.append("")
    lines.append("This section maps benchmark outputs to a table-aligned decision approach:")
    lines.append("- STT quality sector: choose the provider with the best WER/CER and stable keyword recall from the table above.")
    if best_voice_live is not None:
        best_voice_live_display = str(best_voice_live.get("provider_display") or best_voice_live["provider"])
        lines.append(
            f"- Voice service sector (managed realtime): current Voice Live default path is `{best_voice_live_display}`. "
            "Use this when you need realtime conversation/tool-calling style workflows, not only raw STT."
        )
    lines.append(
        "- STT-only production sector: prefer Azure Speech STT or MAI-Transcribe based on quality/cost targets; "
        "use Voice Live primarily when you also need conversational voice capabilities."
    )
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    
    # Generate interactive HTML report
    html_path = generate_html_report(output_dir, summary_rows, samples)
    print(f"Interactive HTML report generated: {html_path}")
    
    return summary_path


def generate_html_report(
    output_dir: Path,
    summary_rows: list[dict[str, Any]],
    samples: list[BenchmarkSample],
) -> Path:
    """Generate an interactive HTML report with detail buttons for each provider."""
    # Load all results JSONL files
    provider_results: dict[str, list[dict[str, Any]]] = {}
    for row in summary_rows:
        provider_name = row["provider"]
        results_path = output_dir / f"{provider_name}.results.jsonl"
        if results_path.exists():
            results = []
            for line in results_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            provider_results[provider_name] = results

    # Sort summary rows by metrics
    ranked_rows = sorted(
        summary_rows,
        key=lambda item: (
            item["avg_wer"],
            item["avg_cer"],
            -item["avg_keyword_recall"],
            -item.get("avg_confidence", 0.0),
            item["avg_latency_ms"],
        ),
    )

    # Build the HTML
    html_lines = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "  <meta charset='UTF-8'>",
        "  <meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        "  <title>STT Benchmark Report</title>",
        "  <style>",
        "    * { margin: 0; padding: 0; box-sizing: border-box; }",
        "    body {",
        "      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', sans-serif;",
        "      background: #f0f2f5;",
        "      padding: 40px 20px;",
        "      min-height: 100vh;",
        "    }",
        "    .container { max-width: 1600px; margin: 0 auto; }",
        "    .header { text-align: center; margin-bottom: 50px; }",
        "    .header h1 { font-size: 2.8em; color: #1a1a1a; margin-bottom: 10px; font-weight: 700; }",
        "    .header p { font-size: 1.1em; color: #666; }",
        "    .table-wrapper { background: white; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.12); overflow: hidden; }",
        "    table { width: 100%; border-collapse: collapse; }",
        "    table thead { background: linear-gradient(135deg, #2d1b69 0%, #3d2678 100%); color: white; }",
        "    table th { padding: 20px 16px; text-align: left; font-weight: 600; font-size: 0.95em; letter-spacing: 0.5px; text-transform: uppercase; }",
        "    table th:last-child { text-align: right; }",
        "    table td { padding: 18px 16px; border-bottom: 1px solid #e8e8e8; color: #333; font-size: 0.95em; }",
        "    table tbody tr { transition: all 0.2s ease; }",
        "    table tbody tr:hover { background: #f8f9fa; }",
        "    table tbody tr.best-row { background: #e8f5e9; }",
        "    table tbody tr.best-row:hover { background: #d4edda; }",
        "    .provider-name { font-weight: 600; color: #1a1a1a; }",
        "    .numeric { text-align: right; font-family: 'Monaco', 'Courier New', monospace; font-size: 0.9em; }",
        "    .action-cell { text-align: right; }",
        "    .detail-btn {",
        "      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);",
        "      color: white;",
        "      border: none;",
        "      padding: 10px 24px;",
        "      border-radius: 6px;",
        "      cursor: pointer;",
        "      font-size: 0.85em;",
        "      font-weight: 600;",
        "      transition: all 0.3s ease;",
        "      box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);",
        "    }",
        "    .detail-btn:hover {",
        "      transform: translateY(-2px);",
        "      box-shadow: 0 6px 16px rgba(102, 126, 234, 0.4);",
        "    }",
        "    .detail-btn:active { transform: translateY(0); }",
        "    .details-panel { display: none; padding: 40px; background: #f9f9f9; border-top: 1px solid #e0e0e0; }",
        "    .details-panel.active { display: block; animation: slideDown 0.4s ease; }",
        "    @keyframes slideDown { from { opacity: 0; transform: translateY(-20px); } to { opacity: 1; transform: translateY(0); } }",
        "    .close-btn { float: right; background: #e0e0e0; color: #333; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-weight: 500; }",
        "    .close-btn:hover { background: #d0d0d0; }",
        "    .sample-card { margin-bottom: 24px; padding: 20px; background: white; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; }",
        "    .sample-header { font-weight: 700; color: #667eea; margin-bottom: 14px; font-size: 1.05em; }",
        "    .comparison-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }",
        "    .comparison-col { padding: 14px; background: #fafafa; border-radius: 6px; border: 1px solid #e8e8e8; }",
        "    .comparison-col.reference { border-left: 4px solid #4caf50; }",
        "    .comparison-col.hypothesis { border-left: 4px solid #f44336; }",
        "    .col-label { font-weight: 700; font-size: 0.85em; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px; }",
        "    .col-label.reference { color: #2e7d32; }",
        "    .col-label.hypothesis { color: #c62828; }",
        "    .col-text { font-size: 0.95em; line-height: 1.6; word-break: break-word; color: #333; }",
        "    .empty-text { color: #999; font-style: italic; }",
        "    .error-box { padding: 12px; background: #ffebee; border: 1px solid #ef5350; border-radius: 4px; color: #c62828; font-weight: 500; margin-bottom: 12px; }",
        "    .metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 14px; }",
        "    .metric-box { padding: 12px; background: white; border: 1px solid #e0e0e0; border-radius: 4px; text-align: center; }",
        "    .metric-label { font-size: 0.75em; font-weight: 600; color: #666; text-transform: uppercase; margin-bottom: 6px; }",
        "    .metric-value { font-size: 1.1em; font-weight: 700; color: #667eea; font-family: monospace; }",
        "  </style>",
        "</head>",
        "<body>",
        "  <div class='container'>",
        "    <div class='header'>",
        "      <h1>STT Benchmark Report</h1>",
        "      <p>Speech-to-Text Quality Analysis</p>",
        "    </div>",
        "    <div class='table-wrapper'>",
        "      <table>",
        "        <thead>",
        "          <tr>",
        "            <th>Provider</th>",
        "            <th class='numeric'>Samples</th>",
        "            <th class='numeric'>WER</th>",
        "            <th class='numeric'>CER</th>",
        "            <th class='numeric'>Keyword Recall</th>",
        "            <th class='numeric'>Confidence</th>",
        "            <th class='numeric'>Latency (ms)</th>",
        "            <th></th>",
        "          </tr>",
        "        </thead>",
        "        <tbody>",
    ]

    best_provider = ranked_rows[0]["provider"] if ranked_rows else ""
    for row in ranked_rows:
        provider_name = str(row["provider"])
        provider_display = str(row.get("provider_display") or provider_name)
        provider_safe = html_escape(provider_display)
        provider_id_safe = html_escape(provider_name)
        provider_dom_id = re.sub(r"[^a-zA-Z0-9_-]", "-", provider_name)
        is_best = row["provider"] == best_provider
        row_class = " class='best-row'" if is_best else ""
        html_lines.extend([
            f"          <tr{row_class}>",
            f"            <td class='provider-name'>{provider_safe}<div style='font-size: 0.78em; color: #777; font-weight: 500; margin-top: 4px;'>{provider_id_safe}</div></td>",
            f"            <td class='numeric'>{row['samples']}</td>",
            f"            <td class='numeric'>{row['avg_wer']:.4f}</td>",
            f"            <td class='numeric'>{row['avg_cer']:.4f}</td>",
            f"            <td class='numeric'>{row['avg_keyword_recall']:.4f}</td>",
            f"            <td class='numeric'>{row.get('avg_confidence', 0.0):.4f}</td>",
            f"            <td class='numeric'>{row['avg_latency_ms']:.2f}</td>",
            f"            <td class='action-cell'><button class='detail-btn' onclick='toggleDetails(this, \"{provider_dom_id}\")'>Details</button></td>",
            "          </tr>",
            "          <tr style='display: none;'>",
            "            <td colspan='8'>",
            f"              <div id='details-{provider_dom_id}' class='details-panel'>",
            f"                <button class='close-btn' onclick='toggleDetails(this, \"{provider_dom_id}\")'>Close</button>",
            "                <div style='clear: both; padding-top: 10px;'>",
            f"                  <div class='sample-header' style='margin-bottom: 16px;'>Provider: {provider_safe}</div>",
        ])

        results = provider_results.get(row["provider"], [])
        for result in results:
            call_id = result.get("call_id", "unknown")
            reference = result.get("reference_text", "")
            hypothesis = result.get("hypothesis_text", "")
            wer = result.get("wer", 0.0)
            cer = result.get("cer", 0.0)
            keyword_recall = result.get("keyword_recall", 0.0)
            confidence = result.get("confidence", 0.0)
            latency = result.get("latency_ms", 0.0)
            error = result.get("error", "")

            call_id_display = html_escape(str(call_id))
            reference_display = html_escape(reference) if reference.strip() else "[empty/no reference]"
            hypothesis_display = html_escape(hypothesis) if hypothesis.strip() else "[empty response]"
            error_html = f"<div class='error-box'>Error: {html_escape(error)}</div>" if error else ""

            html_lines.extend([
                "                  <div class='sample-card'>",
                f"                    <div class='sample-header'>Call: {call_id_display}</div>",
                f"                    {error_html}",
                "                    <div class='comparison-grid'>",
                "                      <div class='comparison-col reference'>",
                "                        <div class='col-label reference'>✓ Expected</div>",
                f"                        <div class='col-text'>{reference_display}</div>",
                "                      </div>",
                "                      <div class='comparison-col hypothesis'>",
                "                        <div class='col-label hypothesis'>📝 Model Response</div>",
                f"                        <div class='col-text'>{hypothesis_display}</div>",
                "                      </div>",
                "                    </div>",
                "                    <div class='metrics-grid' style='grid-template-columns: repeat(5, 1fr);'>",
                f"                      <div class='metric-box'><div class='metric-label'>WER</div><div class='metric-value'>{wer:.4f}</div></div>",
                f"                      <div class='metric-box'><div class='metric-label'>CER</div><div class='metric-value'>{cer:.4f}</div></div>",
                f"                      <div class='metric-box'><div class='metric-label'>Keyword Recall</div><div class='metric-value'>{keyword_recall:.4f}</div></div>",
                f"                      <div class='metric-box'><div class='metric-label'>Confidence</div><div class='metric-value'>{float(confidence):.4f}</div></div>",
                f"                      <div class='metric-box'><div class='metric-label'>Latency</div><div class='metric-value'>{latency:.0f}ms</div></div>",
                "                    </div>",
                "                  </div>",
            ])

        html_lines.extend([
                "                </div>",
                "              </div>",
                "            </td>",
                "          </tr>",
        ])

    html_lines.extend([
        "        </tbody>",
        "      </table>",
        "    </div>",
        "  </div>",
        "  <script>",
        "    function toggleDetails(btn, detailsId) {",
        "      const detailsRow = btn.closest('tr').nextElementSibling;",
        "      const detailsPanel = document.getElementById('details-' + detailsId);",
        "      const isVisible = detailsRow.style.display !== 'none';",
        "      ",
        "      if (isVisible) {",
        "        detailsRow.style.display = 'none';",
        "        detailsPanel.classList.remove('active');",
        "        btn.textContent = 'Details';",
        "      } else {",
        "        detailsRow.style.display = '';",
        "        detailsPanel.classList.add('active');",
        "        btn.textContent = 'Hide';",
        "        setTimeout(() => { detailsRow.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, 100);",
        "      }",
        "    }",
        "  </script>",
        "</body>",
        "</html>",
    ])

    html_path = output_dir / "report.html"
    html_path.write_text("\n".join(html_lines), encoding="utf-8")
    return html_path


def build_provider(name: str) -> SttProvider:
    normalized = name.strip().lower()
    if normalized == "azure-speech-stt":
        return AzureSpeechProvider()
    if normalized == "azure-speech-stt-no-phrase-list":
        return AzureSpeechNoPhraseListProvider()
    if normalized == "azure-speech-stt-custom":
        return AzureSpeechCustomProvider()
    if normalized == "voice-live-api":
        return VoiceLiveProvider(provider_name="voice-live-api")
    if normalized == "voice-live-api-gpt-4o-transcribe":
        # gpt-4o-transcribe input transcription is not valid for some cascaded pipelines (e.g., gpt-5.4).
        # Use a dedicated real-time model unless explicitly overridden.
        gpt4o_model = (os.getenv("VOICE_LIVE_GPT4O_TRANSCRIBE_MODEL") or "gpt-realtime").strip()
        return VoiceLiveProvider(
            provider_name="voice-live-api-gpt-4o-transcribe",
            transcription_model_override="gpt-4o-transcribe",
            model_override=gpt4o_model,
            timeout_seconds_override=float(os.getenv("VOICE_LIVE_GPT4O_TIMEOUT_SECONDS", "45")),
        )
    if normalized == "voice-live-api-mai-transcribe-1":
        mai_model = (os.getenv("VOICE_LIVE_MAI_TRANSCRIBE_MODEL") or "gpt-realtime").strip()
        return VoiceLiveProvider(
            provider_name="voice-live-api-mai-transcribe-1",
            transcription_model_override="mai-transcribe-1",
            model_override=mai_model,
            timeout_seconds_override=float(os.getenv("VOICE_LIVE_MAI_TIMEOUT_SECONDS", "90")),
        )
    if normalized in {"mai-transcribe-1.5", "mai-voice"}:
        return MaiTranscribeProvider()
    if normalized == "azure-speech-stt-fast":
        return AzureSpeechFastProvider()
    if normalized == "azure-speech-stt-fast-phrase-list":
        return AzureSpeechFastProvider(
            provider_name="azure-speech-stt-fast-phrase-list",
            use_phrase_list=True,
        )
    if normalized == "azure-speech-stt-rest":
        return AzureSpeechRestProvider()
    if normalized == "gpt-audio-transcribe":
        return GptAudioTranscribeProvider()
    raise ValueError(f"Unsupported provider: {name}")


def _apply_decision_scores(summary_rows: list[dict[str, Any]], scoring_profile: BenchmarkScoringProfile) -> None:
    confidence_values = [float(row.get("avg_confidence", 0.0)) for row in summary_rows]
    latency_values = [float(row.get("avg_latency_ms", 0.0)) for row in summary_rows]
    cost_values = [float(row["estimated_cost_usd"]) for row in summary_rows if isinstance(row.get("estimated_cost_usd"), (int, float))]

    for row in summary_rows:
        accuracy_component = _normalize_higher_better(float(row.get("avg_confidence", 0.0)), confidence_values)
        latency_component = _normalize_lower_better(float(row.get("avg_latency_ms", 0.0)), latency_values)
        if isinstance(row.get("estimated_cost_usd"), (int, float)) and cost_values:
            cost_component = _normalize_lower_better(float(row["estimated_cost_usd"]), cost_values)
            decision_score = (
                scoring_profile.accuracy_weight * accuracy_component
                + scoring_profile.latency_weight * latency_component
                + scoring_profile.cost_weight * cost_component
            )
        else:
            available = scoring_profile.accuracy_weight + scoring_profile.latency_weight
            accuracy_weight = scoring_profile.accuracy_weight / available if available > 0 else 0.0
            latency_weight = scoring_profile.latency_weight / available if available > 0 else 0.0
            cost_component = None
            decision_score = (
                accuracy_weight * accuracy_component
                + latency_weight * latency_component
            )

        row["accuracy_component"] = accuracy_component
        row["latency_component"] = latency_component
        row["cost_component"] = cost_component
        row["decision_score"] = max(0.0, min(1.0, decision_score))


def _normalize_higher_better(value: float, population: list[float]) -> float:
    if not population:
        return 0.0
    low = min(population)
    high = max(population)
    if math.isclose(low, high):
        return 1.0
    return (value - low) / (high - low)


def _normalize_lower_better(value: float, population: list[float]) -> float:
    if not population:
        return 0.0
    low = min(population)
    high = max(population)
    if math.isclose(low, high):
        return 1.0
    return (high - value) / (high - low)


def estimate_audio_cost_usd(provider: str, total_audio_seconds: float) -> float | None:
    audio_hours = total_audio_seconds / 3600.0

    def _rate(name: str, default: float) -> float:
        raw = (os.getenv(name) or "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    if provider in {"azure-speech-stt", "azure-speech-stt-no-phrase-list",
                     "azure-speech-stt-custom", "azure-speech-stt-fast",
                     "azure-speech-stt-fast-phrase-list"}:
        # Azure Speech real-time STT (SDK path). Default: $1.00/audio-hour.
        return audio_hours * _rate("AZURE_SPEECH_STT_REALTIME_HOURLY_USD", 1.0)
    if provider == "azure-speech-stt-rest":
        # Fast transcription REST endpoint. Lower cost than real-time. Default: $0.33/audio-hour.
        return audio_hours * _rate("AZURE_SPEECH_STT_REST_HOURLY_USD", 0.33)
    if provider.startswith("voice-live-api"):
        # Proxy default: real-time STT + one enhanced add-on (e.g., LID).
        # Override with your contracted Voice Live effective audio-hour rate.
        return audio_hours * _rate("VOICE_LIVE_AUDIO_HOURLY_USD", 1.3)
    if provider == "mai-transcribe-1.5":
        # Proxy default for MAI-Transcribe audio-hour processing.
        return audio_hours * _rate("MAI_TRANSCRIBE_AUDIO_HOURLY_USD", 1.0)
    if provider == "gpt-audio-transcribe":
        # GPT-4o audio transcription is token-based; this is a per-audio-hour proxy.
        # Override with GPT_AUDIO_TRANSCRIBE_HOURLY_USD for your contracted rate.
        return audio_hours * _rate("GPT_AUDIO_TRANSCRIBE_HOURLY_USD", 72.0)
    return None


def append_cost_report(summary_path: Path, samples: list[BenchmarkSample], providers: list[SttProvider]) -> None:
    total_audio_seconds = 0.0
    for sample in samples:
        duration = sample.metadata.get("audio_duration_seconds")
        if isinstance(duration, (int, float)) and not math.isnan(duration):
            total_audio_seconds += float(duration)

    if total_audio_seconds <= 0:
        return

    lines: list[str] = ["", "## Cost Estimate (Audio)", "", "| Provider | Estimated Cost (USD) |", "|---|---:|"]
    for provider in providers:
        cost = estimate_audio_cost_usd(provider.name, total_audio_seconds)
        if cost is None:
            lines.append(f"| {provider.name} | N/A (set pricing model) |")
        else:
            lines.append(f"| {provider.name} | {cost:.4f} |")

    with summary_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")