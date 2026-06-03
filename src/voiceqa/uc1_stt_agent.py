from __future__ import annotations

import json
import threading
from pathlib import Path

import azure.cognitiveservices.speech as speechsdk
from azure.identity import AzureCliCredential

from .config import Settings
from .corrections import CorrectionEngine
from .models import Transcript, TranscriptTurn


class SttAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.corrections = CorrectionEngine.from_file(settings.corrections_path)

    def transcribe_audio(self, audio_path: Path) -> Transcript:
        speech_config = self._build_speech_config()
        speech_config.output_format = speechsdk.OutputFormat.Detailed
        speech_config.request_word_level_timestamps()
        speech_config.set_property_by_name("SpeechRecognition_RequestWordLevelCorrections", "true")

        audio_config = speechsdk.audio.AudioConfig(filename=str(audio_path))
        auto_lang_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=self.settings.speech_languages
        )
        recognizer = speechsdk.transcription.ConversationTranscriber(
            speech_config=speech_config,
            audio_config=audio_config,
            auto_detect_source_language_config=auto_lang_config,
        )

        self._attach_phrase_list(recognizer)

        transcript = Transcript()
        done = threading.Event()

        def _on_transcribed(evt: speechsdk.SessionEventArgs) -> None:
            result = evt.result
            if result.reason != speechsdk.ResultReason.RecognizedSpeech:
                return

            text = self.corrections.apply(result.text)
            offset_seconds = result.offset / 10_000_000
            duration_seconds = result.duration / 10_000_000
            speaker = result.speaker_id or "Unknown"

            transcript.turns.append(
                TranscriptTurn(
                    speaker=speaker,
                    offset_seconds=offset_seconds,
                    duration_seconds=duration_seconds,
                    text=text,
                )
            )

            raw_json = result.properties.get_property(
                speechsdk.PropertyId.SpeechServiceResponse_JsonResult
            )
            if raw_json:
                parsed = json.loads(raw_json)
                nbest = parsed.get("NBest")
                if isinstance(nbest, list):
                    transcript.nbest_samples.append({"offset": offset_seconds, "nbest": nbest[:3]})

        def _on_completed(_: speechsdk.SessionEventArgs) -> None:
            done.set()

        recognizer.transcribed.connect(_on_transcribed)
        recognizer.session_stopped.connect(_on_completed)
        recognizer.canceled.connect(_on_completed)

        recognizer.start_transcribing_async().get()
        done.wait()
        recognizer.stop_transcribing_async().get()

        if transcript.turns:
            final_turn = transcript.turns[-1]
            transcript.duration_seconds = final_turn.offset_seconds + final_turn.duration_seconds

        return transcript

    def _build_speech_config(self) -> speechsdk.SpeechConfig:
        if self.settings.speech_endpoint and self.settings.speech_key:
            config = speechsdk.SpeechConfig(endpoint=self.settings.speech_endpoint, subscription=self.settings.speech_key)
        elif self.settings.speech_endpoint and not self.settings.speech_key:
            # Keyless local auth path: uses Azure CLI token from `az login`.
            config = speechsdk.SpeechConfig(
                token_credential=AzureCliCredential(),
                endpoint=self.settings.speech_endpoint,
            )
        elif self.settings.speech_key and self.settings.speech_region:
            config = speechsdk.SpeechConfig(subscription=self.settings.speech_key, region=self.settings.speech_region)
        else:
            raise ValueError(
                "Set one of: (1) SPEECH_KEY + SPEECH_REGION, (2) SPEECH_KEY + SPEECH_ENDPOINT, "
                "or (3) SPEECH_ENDPOINT only for Entra ID auth via az login."
            )

        if self.settings.speech_custom_endpoint_id:
            config.endpoint_id = self.settings.speech_custom_endpoint_id

        return config

    def _attach_phrase_list(self, recognizer: speechsdk.Recognizer) -> None:
        phrase_path = self.settings.phrase_list_path
        if not phrase_path.exists():
            return

        grammar = speechsdk.PhraseListGrammar.from_recognizer(recognizer)
        for line in phrase_path.read_text(encoding="utf-8").splitlines():
            phrase = line.strip()
            if phrase:
                grammar.addPhrase(phrase)