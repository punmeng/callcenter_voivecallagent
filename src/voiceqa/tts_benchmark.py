"""TTS (text-to-speech) benchmark for VoiceCall Verify.

Mirrors the STT benchmark structure (``stt_benchmark.py``) but for the reverse
direction: text in, synthesized audio out.  It measures latency/performance and
keeps the generated audio artifacts for manual / MOS listening review.

Providers:
    voice-live-api      Azure AI Voice Live realtime speech synthesis (primary).
    azure-speech-tts    Azure Speech neural TTS via the Speech SDK (baseline).

Per-sample metrics captured:
    char_count               Number of characters synthesized.
    time_to_first_audio_ms   Latency from request to the first audio chunk.
    total_synthesis_ms       Wall-clock time to finish synthesizing.
    audio_duration_ms        Duration of the produced audio.
    real_time_factor         total_synthesis_ms / audio_duration_ms (lower is faster).

Quality (intelligibility/MOS) is intentionally NOT scored here; the WAV files are
kept under the run folder so a human can listen and rate them.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import math
import os
import struct
import sys
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import load_settings
from .uc1_stt_agent import build_speech_config

# Voice Live synthesizes pcm16 mono at 24 kHz by default.
VOICE_LIVE_TTS_SAMPLE_RATE = 24000
# Azure Speech SDK output format below is Riff24Khz16BitMonoPcm.
AZURE_SPEECH_TTS_SAMPLE_RATE = 24000


@dataclass
class TtsSample:
    sample_id: str
    text: str
    language: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TtsResult:
    sample_id: str
    provider: str
    audio_path: Path | None
    char_count: int
    time_to_first_audio_ms: float
    total_synthesis_ms: float
    audio_duration_ms: float
    real_time_factor: float
    error: str = ""


class TtsProvider:
    name: str

    def synthesize(self, sample: TtsSample, output_dir: Path) -> TtsResult:
        raise NotImplementedError()

    def display_name(self) -> str:
        return self.name


def _empty_result(sample: TtsSample, provider: str, error: str, elapsed_ms: float = 0.0) -> TtsResult:
    return TtsResult(
        sample_id=sample.sample_id,
        provider=provider,
        audio_path=None,
        char_count=len(sample.text),
        time_to_first_audio_ms=0.0,
        total_synthesis_ms=elapsed_ms,
        audio_duration_ms=0.0,
        real_time_factor=0.0,
        error=error,
    )


def _pcm16_duration_ms(pcm_bytes: int, sample_rate: int, channels: int = 1, sample_width: int = 2) -> float:
    frames = pcm_bytes / max(1, (sample_width * channels))
    return (frames / sample_rate) * 1000.0 if sample_rate > 0 else 0.0


def _write_pcm16_wav(path: Path, pcm: bytes, sample_rate: int, channels: int = 1, sample_width: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)


class AzureSpeechTtsProvider(TtsProvider):
    """Azure Speech neural TTS baseline via the Speech SDK.

    Deterministic text-to-speech: the exact input text is synthesized. The
    ``synthesizing`` event is used to capture time-to-first-audio while the audio
    is written straight to a WAV artifact.
    """

    name = "azure-speech-tts"

    def __init__(self, *, provider_name: str = "azure-speech-tts", voice_name: str | None = None) -> None:
        self.name = provider_name
        self._settings = load_settings()
        self._voice_name = (
            voice_name
            or os.getenv("AZURE_SPEECH_TTS_VOICE")
            or "zh-TW-HsiaoChenNeural"
        ).strip()

    def display_name(self) -> str:
        return f"{self.name} (voice={self._voice_name})"

    def synthesize(self, sample: TtsSample, output_dir: Path) -> TtsResult:
        import azure.cognitiveservices.speech as speechsdk

        try:
            speech_config = build_speech_config(self._settings)
        except Exception as exc:  # noqa: BLE001 - surface config gaps as sample errors
            return _empty_result(sample, self.name, f"Speech config error: {type(exc).__name__}: {exc}")

        speech_config.speech_synthesis_voice_name = self._voice_name
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm
        )

        audio_path = output_dir / self.name / f"{sample.sample_id}.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_config = speechsdk.audio.AudioOutputConfig(filename=str(audio_path))
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)

        first_audio_at: list[float] = []

        def _on_synthesizing(evt: speechsdk.SpeechSynthesisEventArgs) -> None:
            if not first_audio_at and evt.result and evt.result.audio_data:
                first_audio_at.append(time.perf_counter())

        synthesizer.synthesizing.connect(_on_synthesizing)

        started = time.perf_counter()
        result = synthesizer.speak_text_async(sample.text).get()
        finished = time.perf_counter()
        total_ms = (finished - started) * 1000.0

        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            detail = ""
            if result.reason == speechsdk.ResultReason.Canceled:
                cancellation = result.cancellation_details
                detail = f" ({cancellation.reason}: {cancellation.error_details})"
            return _empty_result(sample, self.name, f"Synthesis failed: {result.reason}{detail}", total_ms)

        audio_duration_ms = 0.0
        if result.audio_duration is not None:
            audio_duration_ms = result.audio_duration.total_seconds() * 1000.0
        if audio_duration_ms <= 0.0:
            audio_duration_ms = _pcm16_duration_ms(len(result.audio_data or b""), AZURE_SPEECH_TTS_SAMPLE_RATE)

        ttfa_ms = ((first_audio_at[0] - started) * 1000.0) if first_audio_at else total_ms
        rtf = (total_ms / audio_duration_ms) if audio_duration_ms > 0 else 0.0

        return TtsResult(
            sample_id=sample.sample_id,
            provider=self.name,
            audio_path=audio_path,
            char_count=len(sample.text),
            time_to_first_audio_ms=ttfa_ms,
            total_synthesis_ms=total_ms,
            audio_duration_ms=audio_duration_ms,
            real_time_factor=rtf,
        )


class VoiceLiveTtsProvider(TtsProvider):
    """Azure AI Voice Live realtime speech synthesis.

    Uses a pre-generated assistant message so the exact input text is spoken
    (deterministic TTS rather than free-form model generation). Audio arrives as
    ``response.audio.delta`` chunks; the first chunk gives time-to-first-audio and
    the accumulated PCM16 stream is written to a WAV artifact.
    """

    name = "voice-live-api"

    def __init__(
        self,
        *,
        provider_name: str = "voice-live-api",
        model_override: str | None = None,
        voice_override: str | None = None,
        timeout_seconds_override: float | None = None,
        strategy_override: str | None = None,
    ) -> None:
        self.name = provider_name
        self._endpoint = (os.getenv("AZURE_VOICELIVE_ENDPOINT") or "").strip()
        self._api_key = (os.getenv("AZURE_VOICELIVE_API_KEY") or "").strip()
        self._api_version = (os.getenv("AZURE_VOICELIVE_API_VERSION") or "2026-06-01-preview").strip()
        self._model = (model_override or os.getenv("AZURE_VOICELIVE_MODEL") or "gpt-realtime").strip()
        self._voice = (voice_override or os.getenv("AZURE_VOICELIVE_TTS_VOICE") or "alloy").strip()
        self._retry_count = int(os.getenv("VOICE_LIVE_TTS_RETRY_COUNT", "1"))
        self._strategy_override = (strategy_override or "").strip().lower() or None
        if timeout_seconds_override is not None:
            self._call_timeout_seconds = float(timeout_seconds_override)
        else:
            self._call_timeout_seconds = float(os.getenv("VOICE_LIVE_TTS_CALL_TIMEOUT_SECONDS", "45"))
        self._last_diagnostics = ""

    def display_name(self) -> str:
        return f"{self.name} (model={self._model}, voice={self._voice})"

    def _build_voice(self) -> Any:
        """Resolve the voice into an OpenAI voice name or Azure standard voice model."""
        from azure.ai.voicelive.models import AzureStandardVoice

        # Azure neural voices carry a locale prefix and a "Neural" suffix, e.g. zh-TW-HsiaoChenNeural.
        if "Neural" in self._voice or self._voice.count("-") >= 2:
            return AzureStandardVoice(name=self._voice)
        # Otherwise treat as an OpenAI voice name (alloy, echo, shimmer, ...).
        return self._voice

    def synthesize(self, sample: TtsSample, output_dir: Path) -> TtsResult:
        if not self._endpoint:
            return _empty_result(sample, self.name, "AZURE_VOICELIVE_ENDPOINT is not set")

        max_attempts = max(1, self._retry_count + 1)
        last_exc: Exception | None = None
        started = time.perf_counter()
        payload: dict[str, Any] | None = None
        self._last_diagnostics = ""

        for attempt in range(1, max_attempts + 1):
            try:
                payload = asyncio.run(
                    asyncio.wait_for(
                        self._synthesize_via_voicelive(sample.text),
                        timeout=self._call_timeout_seconds,
                    )
                )
                break
            except Exception as exc:  # noqa: BLE001 - retried below, reported on final failure
                last_exc = exc
                if attempt >= max_attempts:
                    break
                with contextlib.suppress(Exception):
                    time.sleep(min(2.0 * attempt, 5.0))

        total_ms = (time.perf_counter() - started) * 1000.0

        if payload is None:
            diag = f" Diagnostics: {self._last_diagnostics}" if self._last_diagnostics else ""
            reason = f"{type(last_exc).__name__}: {last_exc}" if last_exc else "unknown error"
            return _empty_result(sample, self.name, f"Voice Live synthesis failed: {reason}{diag}", total_ms)

        pcm: bytes = payload["pcm"]
        if not pcm:
            diag = f" Diagnostics: {self._last_diagnostics}" if self._last_diagnostics else ""
            return _empty_result(sample, self.name, f"Voice Live returned no audio.{diag}", total_ms)

        audio_path = output_dir / self.name / f"{sample.sample_id}.wav"
        _write_pcm16_wav(audio_path, pcm, VOICE_LIVE_TTS_SAMPLE_RATE)

        audio_duration_ms = _pcm16_duration_ms(len(pcm), VOICE_LIVE_TTS_SAMPLE_RATE)
        ttfa_ms = float(payload.get("time_to_first_audio_ms") or total_ms)
        rtf = (total_ms / audio_duration_ms) if audio_duration_ms > 0 else 0.0

        return TtsResult(
            sample_id=sample.sample_id,
            provider=self.name,
            audio_path=audio_path,
            char_count=len(sample.text),
            time_to_first_audio_ms=ttfa_ms,
            total_synthesis_ms=total_ms,
            audio_duration_ms=audio_duration_ms,
            real_time_factor=rtf,
        )

    async def _synthesize_via_voicelive(self, text: str) -> dict[str, Any]:
        from azure.core.credentials import AzureKeyCredential
        from azure.identity.aio import AzureCliCredential
        from azure.ai.voicelive.aio import connect
        from azure.ai.voicelive.models import (
            Modality,
            OutputAudioFormat,
            RequestSession,
        )

        cli_timeout = int((os.getenv("VOICE_LIVE_AZ_CLI_TIMEOUT_SECONDS") or "60").strip())
        credential = (
            AzureKeyCredential(self._api_key)
            if self._api_key
            else AzureCliCredential(process_timeout=cli_timeout)
        )

        # Voice Live is conversational. Two ways to make it "speak" a specific text:
        #   1. pre_generated_assistant_message => exact verbatim synthesis, but only
        #      produces audio for Azure standard/neural voices (OpenAI voices like
        #      'alloy' return text only).
        #   2. instructions ("read this aloud verbatim") => works for every voice,
        #      including OpenAI voices, at the cost of being LLM-driven.
        # We try (1) first for exactness, then fall back to (2) if no audio arrives.
        strategies = ["pregenerated", "instructions"]
        forced = (self._strategy_override or os.getenv("VOICE_LIVE_TTS_STRATEGY") or "").strip().lower()
        if forced in {"pregenerated", "instructions"}:
            strategies = [forced]

        all_events: list[str] = []
        used_strategy = ""
        pcm = b""
        ttfa_ms = 0.0

        try:
            async with connect(
                endpoint=self._endpoint,
                credential=credential,
                api_version=self._api_version,
                model=self._model,
            ) as connection:
                await connection.session.update(
                    session=RequestSession(
                        modalities=[Modality.AUDIO],
                        voice=self._build_voice(),
                        output_audio_format=OutputAudioFormat.PCM16,
                        turn_detection=None,
                    )
                )

                for strategy in strategies:
                    chunks, first_delay_ms, events = await self._collect_response(
                        connection, text, strategy
                    )
                    all_events.extend(events)
                    if chunks:
                        pcm = b"".join(chunks)
                        ttfa_ms = first_delay_ms
                        used_strategy = strategy
                        break
        finally:
            unique_events = list(dict.fromkeys(all_events))
            self._last_diagnostics = (
                f"strategy={used_strategy or '<none produced audio>'}; "
                f"events={unique_events[:12] or ['<none>']}"
            )
            close_method = getattr(credential, "close", None)
            if callable(close_method):
                await close_method()

        return {"pcm": pcm, "time_to_first_audio_ms": ttfa_ms}

    async def _collect_response(
        self, connection: Any, text: str, strategy: str
    ) -> tuple[list[bytes], float, list[str]]:
        """Send one response.create with the given strategy and collect audio chunks."""
        from azure.ai.voicelive.models import (
            AssistantMessageItem,
            Modality,
            OutputTextContentPart,
            ResponseCreateParams,
        )

        if strategy == "pregenerated":
            params = ResponseCreateParams(
                modalities=[Modality.AUDIO],
                pre_generated_assistant_message=AssistantMessageItem(
                    content=[OutputTextContentPart(text=text)],
                ),
            )
        else:
            params = ResponseCreateParams(
                modalities=[Modality.AUDIO],
                instructions=(
                    "You are a text-to-speech engine. Read the following text aloud "
                    "verbatim in its original language. Do not translate, summarize, "
                    "add, or omit anything.\n\n"
                    f"{text}"
                ),
            )

        audio_chunks: list[bytes] = []
        first_audio_at: float | None = None
        events: list[str] = []

        request_started = time.perf_counter()
        await connection.response.create(response=params)

        async for event in connection:
            event_type = str(getattr(event, "type", ""))
            if event_type:
                events.append(event_type)

            if event_type == "response.audio.delta":
                delta = getattr(event, "delta", None)
                if delta:
                    chunk = delta if isinstance(delta, (bytes, bytearray)) else base64.b64decode(delta)
                    if chunk:
                        if first_audio_at is None:
                            first_audio_at = time.perf_counter()
                        audio_chunks.append(bytes(chunk))

            elif event_type in {"response.audio.done", "response.done"}:
                break

            elif event_type == "error":
                error_message = str(getattr(event, "error", "") or "unknown error")
                raise RuntimeError(f"Voice Live server error: {error_message}")

        first_delay_ms = ((first_audio_at - request_started) * 1000.0) if first_audio_at is not None else 0.0
        return audio_chunks, first_delay_ms, events


def build_tts_provider(name: str) -> TtsProvider:
    normalized = name.strip().lower()
    if normalized == "voice-live-api":
        return VoiceLiveTtsProvider(provider_name="voice-live-api")
    if normalized == "gpt-realtime":
        # GPT Realtime speech synthesis via Voice Live using a native OpenAI voice.
        # OpenAI voices only produce audio with the model-driven "instructions"
        # strategy (pre-generated verbatim audio is Azure-neural-voice only), so
        # this scenario is pinned accordingly for a fair, working comparison.
        return VoiceLiveTtsProvider(
            provider_name="gpt-realtime",
            model_override=(os.getenv("GPT_REALTIME_MODEL") or os.getenv("AZURE_VOICELIVE_MODEL") or "gpt-realtime"),
            voice_override=(os.getenv("GPT_REALTIME_TTS_VOICE") or "marin"),
            strategy_override="instructions",
        )
    if normalized == "azure-speech-tts":
        return AzureSpeechTtsProvider()
    if normalized in {"mai-voice", "mai-voice-2"}:
        # MAI-Voice-2 is a multilingual neural TTS voice family served through the
        # Azure Speech SDK. Prebuilt voices (e.g. en-US-Harper:MAI-Voice-2) need no
        # deployment or gated access; only voice cloning/prompting is gated.
        return AzureSpeechTtsProvider(
            provider_name="mai-voice",
            voice_name=(os.getenv("MAI_VOICE_NAME") or "en-US-Harper:MAI-Voice-2"),
        )
    raise ValueError(f"Unsupported TTS provider: {name}")


def parse_tts_dataset(dataset_path: Path) -> list[TtsSample]:
    if not dataset_path.exists() or not dataset_path.is_file():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    default_language = (os.getenv("VOICE_LIVE_TRANSCRIPTION_LANGUAGE") or "zh-TW").strip()
    samples: list[TtsSample] = []
    for index, raw_line in enumerate(dataset_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at line {index}: {exc}") from exc

        sample_id = str(payload.get("sample_id") or payload.get("call_id") or "").strip()
        text = str(payload.get("text") or payload.get("reference_text") or "").strip()
        language = str(payload.get("language") or default_language).strip()

        if not sample_id or not text:
            raise ValueError(f"Dataset line {index} must include sample_id and text")

        samples.append(TtsSample(sample_id=sample_id, text=text, language=language, metadata=payload))

    if not samples:
        raise ValueError("Dataset has no valid rows")
    return samples


def _run_provider(provider: TtsProvider, samples: list[TtsSample], output_dir: Path) -> dict[str, Any]:
    results_path = output_dir / f"{provider.name}.results.jsonl"
    row_count = 0
    ok_count = 0
    ttfa_total = 0.0
    total_synth_total = 0.0
    audio_duration_total = 0.0
    rtf_total = 0.0
    char_total = 0

    with results_path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            try:
                result = provider.synthesize(sample, output_dir)
            except Exception as exc:  # noqa: BLE001 - keep the run going, record per-sample failure
                result = _empty_result(sample, provider.name, f"{type(exc).__name__}: {exc}")

            row_count += 1
            char_total += result.char_count
            if not result.error:
                ok_count += 1
                ttfa_total += result.time_to_first_audio_ms
                total_synth_total += result.total_synthesis_ms
                audio_duration_total += result.audio_duration_ms
                rtf_total += result.real_time_factor

            handle.write(
                json.dumps(
                    {
                        "sample_id": result.sample_id,
                        "provider": result.provider,
                        "char_count": result.char_count,
                        "audio_path": str(result.audio_path) if result.audio_path else "",
                        "time_to_first_audio_ms": round(result.time_to_first_audio_ms, 2),
                        "total_synthesis_ms": round(result.total_synthesis_ms, 2),
                        "audio_duration_ms": round(result.audio_duration_ms, 2),
                        "real_time_factor": round(result.real_time_factor, 4),
                        "error": result.error,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    denom = max(1, ok_count)
    success_rate = ok_count / max(1, row_count)
    return {
        "provider": provider.name,
        "provider_display": provider.display_name(),
        "samples": row_count,
        "success": ok_count,
        "success_rate": success_rate,
        "avg_char_count": char_total / max(1, row_count),
        "avg_time_to_first_audio_ms": ttfa_total / denom,
        "avg_total_synthesis_ms": total_synth_total / denom,
        "avg_audio_duration_ms": audio_duration_total / denom,
        "avg_real_time_factor": rtf_total / denom,
    }


def run_tts_benchmark(
    *,
    providers: list[TtsProvider],
    samples: list[TtsSample],
    output_dir: Path,
    max_workers: int = 1,
) -> Path:
    """Run the TTS benchmark across all providers and write a summary.

    When ``max_workers > 1`` providers run concurrently (network-bound work).
    Audio artifacts are saved under ``<output_dir>/<provider>/<sample_id>.wav``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if max_workers > 1 and len(providers) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        summary_rows: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(max_workers, len(providers))) as executor:
            future_map = {executor.submit(_run_provider, p, samples, output_dir): p for p in providers}
            for future in as_completed(future_map):
                summary_rows.append(future.result())
    else:
        summary_rows = [_run_provider(p, samples, output_dir) for p in providers]

    provider_order = {p.name: i for i, p in enumerate(providers)}
    summary_rows.sort(key=lambda r: provider_order.get(r["provider"], 9999))

    ranked_rows = sorted(
        summary_rows,
        key=lambda item: (-item["success_rate"], item["avg_time_to_first_audio_ms"], item["avg_real_time_factor"]),
    )

    lines = [
        "# TTS Benchmark Summary",
        "",
        "Text-to-speech latency/performance comparison. Generated audio is kept under "
        "each provider folder in this run for manual / MOS listening review.",
        "",
        "| Provider | Samples | Success | Avg Chars | Avg Time-to-First-Audio (ms) | Avg Total Synthesis (ms) | Avg Audio Duration (ms) | Avg Real-Time Factor |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in ranked_rows:
        provider_display = str(row.get("provider_display") or row["provider"])
        lines.append(
            "| "
            f"{provider_display} | "
            f"{row['samples']} | "
            f"{row['success']}/{row['samples']} | "
            f"{row['avg_char_count']:.1f} | "
            f"{row['avg_time_to_first_audio_ms']:.2f} | "
            f"{row['avg_total_synthesis_ms']:.2f} | "
            f"{row['avg_audio_duration_ms']:.2f} | "
            f"{row['avg_real_time_factor']:.4f} |"
        )
    lines.append("")
    lines.append(
        "Lower time-to-first-audio, total synthesis time, and real-time factor are better; "
        "higher success rate is better. Real-time factor < 1.0 means faster than realtime."
    )
    lines.append("")
    lines.append("## Recommendation")
    lines.append("")

    usable_rows = [r for r in ranked_rows if r["success"] > 0]
    if usable_rows:
        best = usable_rows[0]
        best_display = str(best.get("provider_display") or best["provider"])
        lines.append(
            f"- Most responsive in this run: `{best_display}` "
            f"(time-to-first-audio {best['avg_time_to_first_audio_ms']:.0f} ms, "
            f"real-time factor {best['avg_real_time_factor']:.2f})."
        )
        lines.append(
            "- Latency numbers only capture responsiveness. Listen to the saved WAV files before "
            "standardizing on a voice, since naturalness and pronunciation are not scored here."
        )
    else:
        lines.append(
            "- No provider produced audio in this run. Check credentials/endpoints "
            "(`AZURE_VOICELIVE_ENDPOINT`, `SPEECH_ENDPOINT`/`SPEECH_KEY`) and voice names."
        )

    summary_path = output_dir / "summary.md"
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    return summary_path
