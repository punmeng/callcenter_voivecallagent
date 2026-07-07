"""STT provider configuration loader.

Reads config/stt_config.toml and provides typed access to per-use-case STT
settings.  Falls back to sensible defaults when the file is absent.

Public API
----------
load_stt_config(path=None)  -> SttConfig
build_uc1_stt(settings, config=None)  -> SttAgent | _SttProviderAdapter
"""
from __future__ import annotations

import copy
import sys
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import Settings

# ─── Default values ───────────────────────────────────────────────────────────

_DEFAULT_CONFIG_PATH = Path("config/stt_config.toml")

_UC1_DEFAULT_PROVIDER = "azure-speech-stt"
_UC2_DEFAULT_PROVIDER = "azure-speech-stt"
_BENCHMARK_DEFAULT_PROVIDERS: list[str] = [
    "azure-speech-stt",
    "azure-speech-stt-fast",
    "azure-speech-stt-fast-phrase-list",
    "azure-speech-stt-rest",
    "mai-transcribe-1.5",
]

# ─── Config dataclasses ───────────────────────────────────────────────────────


@dataclass
class Uc1SttConfig:
    provider: str = _UC1_DEFAULT_PROVIDER
    phrase_list: bool = True
    languages: list[str] = field(default_factory=list)


@dataclass
class Uc2SttConfig:
    provider: str = _UC2_DEFAULT_PROVIDER


@dataclass
class BenchmarkSttConfig:
    default_providers: list[str] = field(
        default_factory=lambda: list(_BENCHMARK_DEFAULT_PROVIDERS)
    )
    parallel: bool = False


@dataclass
class SttConfig:
    uc1: Uc1SttConfig = field(default_factory=Uc1SttConfig)
    uc2: Uc2SttConfig = field(default_factory=Uc2SttConfig)
    benchmark: BenchmarkSttConfig = field(default_factory=BenchmarkSttConfig)


# ─── Loader ───────────────────────────────────────────────────────────────────


def load_stt_config(path: Path | None = None) -> SttConfig:
    """Load stt_config.toml; return defaults if the file does not exist."""
    config_path = path or _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return SttConfig()

    if sys.version_info >= (3, 11):
        import tomllib
        data: dict[str, Any] = tomllib.loads(
            config_path.read_text(encoding="utf-8")
        )
    else:
        data = _parse_toml_minimal(config_path.read_text(encoding="utf-8"))

    uc1_raw = data.get("uc1", {}) or {}
    uc2_raw = data.get("uc2", {}) or {}
    bench_raw = data.get("benchmark", {}) or {}

    uc1 = Uc1SttConfig(
        provider=str(uc1_raw.get("provider", _UC1_DEFAULT_PROVIDER)).strip(),
        phrase_list=bool(uc1_raw.get("phrase_list", True)),
        languages=[str(l).strip() for l in uc1_raw.get("languages", []) if str(l).strip()],
    )
    uc2 = Uc2SttConfig(
        provider=str(uc2_raw.get("provider", _UC2_DEFAULT_PROVIDER)).strip(),
    )
    raw_providers = bench_raw.get("default_providers", _BENCHMARK_DEFAULT_PROVIDERS)
    benchmark = BenchmarkSttConfig(
        default_providers=[str(p).strip() for p in raw_providers if str(p).strip()],
        parallel=bool(bench_raw.get("parallel", False)),
    )
    return SttConfig(uc1=uc1, uc2=uc2, benchmark=benchmark)


# ─── UC1 factory ──────────────────────────────────────────────────────────────


def build_uc1_stt(settings: "Settings", config: SttConfig | None = None) -> Any:
    """Return an SttAgent or _SttProviderAdapter for the provider in stt_config.toml [uc1].

    The returned object always exposes:
        transcribe_audio(audio_path: Path) -> Transcript
    """
    if config is None:
        config = load_stt_config()

    provider_name = config.uc1.provider

    # Apply per-use-case language override when specified in the config.
    effective_settings = settings
    if config.uc1.languages:
        effective_settings = copy.copy(settings)
        effective_settings.speech_languages = list(config.uc1.languages)

    # azure-speech-stt and azure-speech-stt-custom use SttAgent (supports diarization).
    if provider_name in ("azure-speech-stt", "azure-speech-stt-custom"):
        from .uc1_stt_agent import SttAgent
        return SttAgent(effective_settings, enable_phrase_list=config.uc1.phrase_list)

    # All other providers are adapted from the benchmark SttProvider interface.
    from .stt_benchmark import build_provider
    benchmark_provider = build_provider(provider_name)
    return _SttProviderAdapter(benchmark_provider)


# ─── Adapter: wraps SttProvider → Transcript interface ────────────────────────


class _SttProviderAdapter:
    """Wraps any benchmark SttProvider to expose the SttAgent.transcribe_audio() interface.

    Non-diarized providers (REST, GPT, MAI-Transcribe, fast) return a single turn
    attributed to 'Speaker'.  Duration is read from the WAV header.
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    def transcribe_audio(self, audio_path: Path) -> Any:
        from .models import Transcript, TranscriptTurn
        from .stt_benchmark import BenchmarkSample

        sample = BenchmarkSample(
            call_id=audio_path.stem,
            audio_path=audio_path,
            reference_text="",
            keywords=[],
            metadata={},
        )
        result = self._provider.transcribe(sample)
        transcript = Transcript()
        text = (result.hypothesis_text or "").strip()
        if text:
            duration = _wav_duration(audio_path)
            transcript.turns.append(
                TranscriptTurn(
                    speaker="Speaker",
                    offset_seconds=0.0,
                    duration_seconds=duration,
                    text=text,
                )
            )
            transcript.duration_seconds = duration
        return transcript


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / w.getframerate()
    except Exception:
        return 0.0


# ─── UC2 label helper ─────────────────────────────────────────────────────────


_PROVIDER_LABELS: dict[str, str] = {
    "azure-speech-stt": "Azure Speech SDK · auto-detect + diarization",
    "azure-speech-stt-fast": "Azure Speech SDK · fast (fixed locale)",
    "azure-speech-stt-fast-phrase-list": "Azure Speech SDK · fast (fixed locale)",
    "azure-speech-stt-rest": "Azure Speech REST · fast-transcription",
    "azure-speech-stt-custom": "Azure Speech · Custom Speech model",
    "azure-speech-stt-no-phrase-list": "Azure Speech SDK",
    "mai-transcribe-1.5": "MAI-Transcribe 1.5",
    "voice-live-realtime-azure-speech": "Voice Live gpt-realtime · Azure Speech STT (UC3 P1)",
    "voice-live-realtime-azure-speech-phrase-list": "Voice Live gpt-realtime · Azure Speech STT (UC3 P1)",
    "voice-live-realtime-gpt4o-transcribe": "Voice Live gpt-realtime · GPT-4o Transcribe (UC3 P2)",
    "voice-live-api": "Voice Live gpt-realtime · Azure Speech STT (UC3 P1)",
    "voice-live-api-gpt-realtime": "Voice Live gpt-realtime · GPT-4o Transcribe (UC3 P2)",
    "voice-live-api-mai-transcribe-1": "Voice Live gpt-realtime · MAI-Transcribe",
    "voice-live-api-gpt-4o-transcribe": "Voice Live gpt-realtime · GPT-4o Transcribe",
    "gpt-audio-transcribe": "Azure OpenAI Audio Transcription",
    "browser-web-speech": "Browser Web Speech API",
}


def provider_to_display_label(provider: str) -> str:
    """Convert a provider id from stt_config.toml to a human-readable UI label."""
    return _PROVIDER_LABELS.get(provider.strip().lower(), provider)


# ─── Minimal TOML parser (Python < 3.11 fallback) ────────────────────────────


def _parse_toml_minimal(text: str) -> dict[str, Any]:
    """Parse the subset of TOML used by stt_config.toml (string/bool/array/table)."""
    import re

    result: dict[str, Any] = {}
    current_section: dict[str, Any] = result
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^\[([^\]]+)\]$", stripped)
        if m:
            key = m.group(1).strip()
            current_section = {}
            result[key] = current_section
            continue
        kv = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.+)$", stripped)
        if kv:
            current_section[kv.group(1)] = _parse_toml_value(kv.group(2).strip())
    return result


def _parse_toml_value(raw: str) -> Any:
    if raw in ("true", "false"):
        return raw == "true"
    if (raw.startswith('"') and raw.endswith('"')) or (
        raw.startswith("'") and raw.endswith("'")
    ):
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        import re
        pairs = re.findall(r'"([^"]+)"|\'([^\']+)\'', raw)
        return [a or b for a, b in pairs]
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw
