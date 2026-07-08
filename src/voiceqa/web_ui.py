from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
import shutil
import traceback
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from dotenv import load_dotenv
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route

try:
    import markdown
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False

from .config import Settings, load_settings
from .agent_runtime import build_azure_openai_agent, build_foundry_agent
from .uc1_blob_reader import BlobReader
from .uc1_main import Uc1RunSummary, run_uc1
from .stt_config import load_stt_config, provider_to_display_label
from .stt_benchmark import BenchmarkSample, append_cost_report, build_provider, compute_evaluation, parse_dataset, run_benchmark
from .tts_benchmark import build_tts_provider, parse_tts_dataset, run_tts_benchmark
from .uc2_live_assistant import create_app as create_uc2_live_app
from .uc3_voice_agent import create_app as create_uc3_live_app


_DASHBOARD_TITLE = "VoiceCall Verify"
_BENCHMARK_ROOT = Path("reports/stt_benchmarks")
_TTS_BENCHMARK_ROOT = Path("reports/tts_benchmarks")
_TTS_SUPPORTED_PROVIDERS = [
    "voice-live-api",
    "gpt-realtime",
    "mai-voice",
    "azure-speech-tts",
]
_TTS_DEFAULT_PROVIDERS = ["voice-live-api", "azure-speech-tts"]
_TTS_DEFAULT_DATASET = "data/tts_benchmark.template.jsonl"

# Maps action button labels to i18n keys so buttons translate consistently.
_ACTION_LABEL_KEYS = {
    "Open live console": "btn_open_live",
    "Open voice call": "btn_open_voice",
    "Run quality check": "btn_run_quality",
    "Open STT benchmark": "btn_open_stt",
    "Open TTS benchmark": "btn_open_tts",
}

# Friendly home names + aligned "what it does" descriptions per use case.
_HOME_NAME_EN = {
    "uc1": "Voice Call Quality",
    "uc2": "Real-time Call Assistant",
    "uc3": "Voice Live Call",
    "benchmark": "STT Benchmark",
    "tts-benchmark": "TTS Benchmark",
}
_HOME_DESC_EN = {
    "uc1": "Offline batch quality check — transcribe recorded calls and score them against a rubric into a Markdown QA report.",
    "uc2": "Live agent copilot — surfaces next-best-action, compliance, and answer cards in real time during a call.",
    "uc3": "Fully automated AI voice agent that talks to the caller (speech-to-speech) and escalates specific inquiries to billing, IT, or expert agents.",
    "benchmark": "Compare STT models for accuracy, latency, and cost across multiple providers.",
    "tts-benchmark": "Compare TTS voices for latency and real-time factor, keeping the generated audio for listening review.",
}
_UC1_SUPPORTED_PROVIDERS = [
    "azure-speech-stt",
    "azure-speech-stt-custom",
    "azure-speech-stt-fast",
    "azure-speech-stt-fast-phrase-list",
    "azure-speech-stt-rest",
    "mai-transcribe-1.5",
    "gpt-audio-transcribe",
    "voice-live-api",
]
_BENCHMARK_SUPPORTED_PROVIDERS = [
    "azure-speech-stt",
    "azure-speech-stt-fast",
    "azure-speech-stt-fast-phrase-list",
    "azure-speech-stt-rest",
    "azure-speech-stt-custom",
    "mai-transcribe-1.5",
    "gpt-audio-transcribe",
    "voice-live-realtime-azure-speech",
    "voice-live-realtime-azure-speech-phrase-list",
    "voice-live-realtime-gpt4o-transcribe",
]

# STT providers that send a phrase list (used to render a phrase-list pill in the UI).
_PHRASE_LIST_PROVIDERS = {
    "azure-speech-stt",
    "azure-speech-stt-fast-phrase-list",
    "azure-speech-stt-custom",
    "voice-live-realtime-azure-speech-phrase-list",
}


def _phrase_list_pill(provider_id: str) -> str:
    """Small colored pill showing whether a provider uses the phrase list."""
    on = provider_id in _PHRASE_LIST_PROVIDERS
    color = "#22c55e" if on else "#8b8b9a"
    bg = "rgba(34,197,94,.15)" if on else "rgba(139,139,154,.15)"
    text = "phrase list ✓" if on else "no phrase list"
    return (
        f"<span style=\"font-size:.7em; font-weight:600; color:{color}; background:{bg}; "
        f"padding:2px 8px; border-radius:999px; white-space:nowrap;\">{text}</span>"
    )


@dataclass
class UseCaseCard:
    id: str
    name: str
    short_name: str
    summary: str
    value: str
    route: str
    voice_model: str
    details: list[str]
    actions: list[tuple[str, str]]


@dataclass
class BenchmarkRun:
    run_id: str
    summary_path: Path
    providers: list[dict[str, Any]]
    cost_rows: list[dict[str, str]]
    recommendation: str | None
    excerpt: str


@dataclass
class Uc1AudioItem:
  path: str
  name: str
  duration_seconds: float | None
  size_bytes: int | None


@dataclass
class BenchmarkRunSummary:
    run_id: str
    source_path: str
    providers: list[str]
    total_items: int
    success_count: int
    error_count: int
    summary_path: str
    provider_rows: list[dict[str, Any]]
    result_files: list[str]
    reference_dataset_path: str | None = None


_USE_CASE_CARDS = [
    UseCaseCard(
        id="uc1",
        name="UC1 Blob Audio to Markdown QA Report",
        short_name="UC1",
        summary="Offline batch processing for call recordings.",
        value="Turns a recorded call into a scored QA report with rubric evidence, phrase boosting, and correction-aware transcription.",
        route="/uc1",
        voice_model="Azure Speech Service (default) / configurable per config/stt_config.toml",
        details=[
            "Reads audio from Blob Storage or local files.",
            "Uses Azure Speech transcription, phrase list boosting, and post-STT corrections.",
            "Scores the transcript against rubric rules and writes Markdown + JSON artifacts.",
        ],
        actions=[
            ("Run quality check", "/uc1"),
        ],
    ),
    UseCaseCard(
        id="uc2",
        name="UC2 Real-time Call Assistant",
        short_name="UC2",
        summary="Live coaching for agents during customer calls.",
        value="Shows next-best-action, compliance, and answer cards in real time while tracking token usage and audio duration.",
        route="/uc2",
        voice_model="Azure Speech Service (default) / configurable per config/stt_config.toml",
        details=[
            "Uses a Foundry-hosted assistant and keeps a rolling transcript window.",
            "Surfaces STT model, LLM model, token usage, and call audio duration in the UI.",
            "Can also emit a post-call summary in Traditional Chinese.",
        ],
        actions=[
            ("Open live console", "/uc2/live"),
        ],
    ),
    UseCaseCard(
        id="uc3",
        name="UC3 Voice Live Call (gpt-realtime + TTS)",
        short_name="UC3",
        summary="Fully automated AI voice agent that talks to the caller.",
        value="A speech-to-speech voice bot on Azure AI Voice Live (gpt-realtime): it listens, understands, and replies in voice, and routes specific inquiries to billing, IT, or expert Foundry agents before speaking the answer back.",
        route="/uc3",
        voice_model="Azure AI Voice Live (gpt-realtime) + neural/OpenAI TTS voice",
        details=[
            "Streams microphone audio to Voice Live and plays synthesized replies in the browser.",
            "Native STT + LLM + TTS in one realtime session with server-side turn detection.",
            "Escalates specific questions to Foundry billing, IT, or expert agents via function calling, then reads the answer aloud.",
        ],
        actions=[
            ("Open voice call", "/uc3/live"),
        ],
    ),
    UseCaseCard(
        id="benchmark",
        name="STT Benchmark Matrix",
        short_name="STT Benchmark",
        summary="Compare STT accuracy, latency, and cost across multiple providers.",
        value="Lets you compare Azure Speech, MAI-Transcribe, GPT audio transcription, and Voice Live variants from a single benchmark page.",
        route="/benchmark",
        voice_model="azure-speech-stt, azure-speech-stt-fast, azure-speech-stt-rest, mai-transcribe-1.5, gpt-audio-transcribe, voice-live-realtime-azure-speech, voice-live-realtime-gpt4o-transcribe",
        details=[
            "Reads benchmark runs from reports/stt_benchmarks.",
            "Shows provider averages for WER, CER, keyword recall, latency, and audio cost.",
            "Uses config/stt_config.toml for the default provider list.",
        ],
        actions=[
            ("Open STT benchmark", "/benchmark"),
        ],
    ),
    UseCaseCard(
        id="tts-benchmark",
        name="TTS Benchmark Matrix",
        short_name="TTS Benchmark",
        summary="Compare text-to-speech voices on latency and real-time factor.",
        value="Benchmarks Voice Live (gpt-realtime), MAI-Voice-2, and Azure neural voices, keeping the generated audio for listening review.",
        route="/tts-benchmark",
        voice_model="voice-live-api (gpt-realtime), gpt-realtime, mai-voice (MAI-Voice-2), azure-speech-tts",
        details=[
            "Reads TTS benchmark runs from reports/tts_benchmarks.",
            "Shows time-to-first-audio, total synthesis time, and real-time factor per provider.",
            "Plays back generated audio artifacts directly in the browser.",
        ],
        actions=[
            ("Open TTS benchmark", "/tts-benchmark"),
        ],
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# Data loading helpers
# ──────────────────────────────────────────────────────────────────────────────


def _current_config() -> dict[str, Any]:
    cfg = load_stt_config()
    return {
        "uc1_provider": cfg.uc1.provider,
        "uc1_provider_label": provider_to_display_label(cfg.uc1.provider),
        "uc1_phrase_list": cfg.uc1.phrase_list,
        "uc1_languages": cfg.uc1.languages,
        "uc2_provider": cfg.uc2.provider,
        "uc2_provider_label": provider_to_display_label(cfg.uc2.provider),
        "benchmark_default_providers": cfg.benchmark.default_providers,
        "benchmark_parallel": cfg.benchmark.parallel,
    }


_SUMMARY_ROW_RE = re.compile(
  r"^\|\s*(?P<provider>[^|]+?)\s*\|\s*(?P<samples>\d+)\s*\|\s*(?P<wer>[0-9.]+)\s*\|\s*(?P<cer>[0-9.]+)\s*\|\s*(?P<keyword>[0-9.]+)\s*\|\s*(?P<confidence>[0-9.]+)\s*\|\s*(?P<latency>[0-9.]+)\s*\|\s*(?P<cost>[0-9.]+|N/A)\s*\|\s*(?P<decision>[0-9.]+)\s*\|$"
)
_COST_ROW_RE = re.compile(
    r"^\|\s*(?P<provider>[^|]+?)\s*\|\s*(?P<cost>[^|]+?)\s*\|$"
)
# Rows in the "## Corrected Transcript View" table: provider + 4 numeric columns.
_CORRECTED_ROW_RE = re.compile(
    r"^\|\s*(?P<provider>[^|]+?)\s*\|\s*(?P<cwer>[0-9.]+)\s*\|\s*(?P<ccer>[0-9.]+)\s*\|\s*(?P<ckeyword>[0-9.]+)\s*\|\s*(?P<cconf>[0-9.]+)\s*\|$"
)


def _parse_corrected_metrics(content: str) -> dict[str, dict[str, float]]:
    """Parse the '## Corrected Transcript View' table into
    ``{provider_display: {avg_corrected_wer, avg_corrected_cer, ...}}``."""
    result: dict[str, dict[str, float]] = {}
    in_corrected = False
    for line in content.splitlines():
        if line.startswith("## Corrected Transcript View"):
            in_corrected = True
            continue
        if line.startswith("## ") and not line.startswith("## Corrected Transcript View"):
            in_corrected = False
        if not in_corrected:
            continue
        match = _CORRECTED_ROW_RE.match(line)
        if not match:
            continue
        provider = match.group("provider").strip()
        if provider.lower() == "provider":
            continue
        result[provider] = {
            "avg_corrected_wer": float(match.group("cwer")),
            "avg_corrected_cer": float(match.group("ccer")),
            "avg_corrected_keyword_recall": float(match.group("ckeyword")),
            "avg_corrected_confidence": float(match.group("cconf")),
        }
    return result


def _merge_corrected_metrics(
    rows: list[dict[str, Any]], corrected: dict[str, dict[str, float]]
) -> None:
    """Merge parsed corrected metrics into provider rows (matched by display name)."""
    for row in rows:
        corr = corrected.get(str(row.get("provider", "")))
        if corr:
            row.update(corr)


def _scan_benchmark_runs(root: Path = _BENCHMARK_ROOT) -> list[BenchmarkRun]:
    if not root.exists():
        return []

    runs: list[BenchmarkRun] = []
    for run_dir in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        summary_path = run_dir / "summary.md"
        if not summary_path.exists():
            continue

        content = summary_path.read_text(encoding="utf-8")
        providers: list[dict[str, Any]] = []
        cost_rows: list[dict[str, str]] = []
        recommendation: str | None = None
        excerpt_lines: list[str] = []
        in_summary_table = False
        in_cost_table = False

        for line in content.splitlines():
            if len(excerpt_lines) < 12:
                excerpt_lines.append(line)

            if line.startswith("| Provider | Samples | Avg WER"):
                in_summary_table = True
                in_cost_table = False
                continue
            if line.startswith("## Cost Estimate"):
                in_summary_table = False
                in_cost_table = True
                continue
            if line.startswith("## ") and not line.startswith("## Cost Estimate"):
                in_summary_table = False
                in_cost_table = False
            if in_summary_table:
                match = _SUMMARY_ROW_RE.match(line)
                if match:
                    providers.append(
                        {
                            "provider": match.group("provider").strip(),
                            "samples": int(match.group("samples")),
                            "avg_wer": float(match.group("wer")),
                            "avg_cer": float(match.group("cer")),
                            "avg_keyword_recall": float(match.group("keyword")),
                            "avg_confidence": float(match.group("confidence") or 0.0),
                            "avg_latency_ms": float(match.group("latency")),
                        "estimated_cost_usd": None if match.group("cost") == "N/A" else float(match.group("cost")),
                        "decision_score": float(match.group("decision")),
                        }
                    )
            if in_cost_table:
                match = _COST_ROW_RE.match(line)
                if match and match.group("provider") != "Provider":
                    cost_rows.append(
                        {
                            "provider": match.group("provider").strip(),
                            "cost": match.group("cost").strip(),
                        }
                    )
            if line.startswith("- Recommended default:") and recommendation is None:
                recommendation = line[2:].strip()

        _merge_corrected_metrics(providers, _parse_corrected_metrics(content))

        runs.append(
            BenchmarkRun(
                run_id=run_dir.name,
                summary_path=summary_path,
                providers=providers,
                cost_rows=cost_rows,
                recommendation=recommendation,
                excerpt="\n".join(excerpt_lines).strip(),
            )
        )

    return runs


def _benchmark_overview() -> dict[str, Any]:
    runs = _scan_benchmark_runs()
    latest = runs[0] if runs else None
    return {
        "runs": runs,
        "latest": latest,
    }


def _default_uc1_source_path(settings: Settings) -> str:
    # Prefer the folder so the UC1 page lists every *.wav for browse/select.
    if settings.local_audio_dir:
        return str(settings.local_audio_dir)
    if settings.local_audio_path:
        return str(Path(settings.local_audio_path).parent)
    return ""


def _default_benchmark_reference_dataset() -> str:
    candidates = [
        Path("data/stt_benchmark.template.jsonl"),
        Path("data/stt_benchmark.jsonl"),
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate).replace("\\", "/")
    return ""


def _apply_uc1_source_override(settings: Settings, source_path_override: str | None) -> Settings:
    if not source_path_override:
        return settings

    source_path = Path(source_path_override).expanduser()
    settings.input_source = "local"
    settings.input_blob_name = None
    settings.input_prefix = None

    if source_path.exists() and source_path.is_file():
        settings.local_audio_path = source_path
        settings.local_audio_dir = None
        return settings

    if source_path.exists() and source_path.is_dir():
        settings.local_audio_path = None
        settings.local_audio_dir = source_path
        return settings

    if source_path.suffix.lower() in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
        settings.local_audio_path = source_path
        settings.local_audio_dir = None
    else:
        settings.local_audio_path = None
        settings.local_audio_dir = source_path
    return settings


def _uc1_run_result_html(run_summary: Uc1RunSummary | None) -> str:
    if run_summary is None:
        return ""

    def _build_report_cell(call):
        if not call.report_path:
            return "<td>-</td>"
        report_name = Path(call.report_path).name
        safe_path = escape(call.report_path, quote=True)
        return f'<td><a href="/api/uc1/report?path={safe_path}" style="color:#a78bfa; text-decoration:underline; cursor:pointer;" onclick="return viewReport(event)">{escape(report_name)}</a></td>'

    rows = "".join(
        f"<tr>"
        f"<td>{escape(call.call_id)}</td>"
        f"<td>{escape(call.stt_status)}</td>"
        f"<td>{call.pass_count}</td>"
        f"<td>{call.fail_count}</td>"
        f"<td>{call.total_tokens}</td>"
        f"{_build_report_cell(call)}"
        f"<td>{escape(call.error or '')}</td>"
        f"</tr>"
        for call in run_summary.calls
    ) or "<tr><td colspan='7' class='muted'>No call-level output.</td></tr>"

    return f"""
    <section class="section">
      <div class="panel">
        <h4>Quality check result</h4>
        <div class="chip-row">
          <span class="chip"><strong>Provider</strong> {escape(provider_to_display_label(run_summary.provider))}</span>
          <span class="chip"><strong>Source mode</strong> {escape(run_summary.source_mode.upper())}</span>
          <span class="chip"><strong>Total items</strong> {run_summary.total_items}</span>
          <span class="chip"><strong>Success</strong> {run_summary.success_count}</span>
          <span class="chip"><strong>Errors</strong> {run_summary.error_count}</span>
        </div>
        <div class="table-wrap" style="margin-top: 12px;">
          <table>
            <thead>
              <tr><th>Call</th><th>STT</th><th>Pass</th><th>Fail</th><th>Total Tokens</th><th>Report</th><th>Error</th></tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
      </div>
    </section>

    <div id="reportModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1000; overflow:auto;">
      <div style="background:#1a1a1a; margin:20px auto; padding:20px; border-radius:12px; max-width:90%; max-height:80vh; overflow:auto; border:1px solid rgba(255,255,255,0.15);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
          <h3 id="reportTitle" style="margin:0; color:#a78bfa;"></h3>
          <button onclick="closeReport()" style="background:none; border:none; color:#fff; font-size:24px; cursor:pointer; padding:0;">&times;</button>
        </div>
        <div id="reportContent" style="color:#e0e0e0; line-height:1.6;"></div>
      </div>
    </div>

    <style>
      #reportContent h1, #reportContent h2, #reportContent h3, #reportContent h4, #reportContent h5, #reportContent h6 {{
        color: #a78bfa;
        margin-top: 1.2em;
        margin-bottom: 0.6em;
      }}
      #reportContent h1 {{ font-size: 1.8em; }}
      #reportContent h2 {{ font-size: 1.6em; }}
      #reportContent h3 {{ font-size: 1.4em; }}
      #reportContent p {{ margin: 0.6em 0; }}
      #reportContent ul, #reportContent ol {{
        margin: 0.6em 0;
        padding-left: 2em;
      }}
      #reportContent li {{ margin: 0.3em 0; }}
      #reportContent code {{
        background: rgba(255,255,255,0.1);
        padding: 0.2em 0.4em;
        border-radius: 3px;
        font-family: monospace;
        font-size: 0.9em;
        color: #a78bfa;
      }}
      #reportContent pre {{
        background: rgba(0,0,0,0.3);
        padding: 1em;
        border-radius: 6px;
        overflow-x: auto;
        border-left: 3px solid #a78bfa;
        font-family: monospace;
        font-size: 0.85em;
        margin: 0.6em 0;
      }}
      #reportContent table {{
        border-collapse: collapse;
        width: 100%;
        margin: 1em 0;
      }}
      #reportContent th {{
        background: rgba(167,139,250,0.1);
        border: 1px solid rgba(255,255,255,0.2);
        padding: 0.5em;
        text-align: left;
        color: #a78bfa;
        font-weight: bold;
      }}
      #reportContent td {{
        border: 1px solid rgba(255,255,255,0.2);
        padding: 0.5em;
      }}
      #reportContent blockquote {{
        border-left: 3px solid #a78bfa;
        padding-left: 1em;
        margin-left: 0;
        color: #b0b0b0;
      }}
      #reportContent a {{
        color: #a78bfa;
        text-decoration: underline;
      }}
    </style>

    <script>
      function viewReport(event) {{
        event.preventDefault();
        const href = event.target.href;
        const url = new URL(href);
        const path = url.searchParams.get('path');
        fetch('/api/uc1/report?path=' + encodeURIComponent(path))
          .then(r => r.json())
          .then(data => {{
            document.getElementById('reportTitle').textContent = data.name || 'Report';
            const contentDiv = document.getElementById('reportContent');
            if (data.is_html) {{
              contentDiv.innerHTML = data.content;
            }} else {{
              contentDiv.textContent = data.content;
            }}
            document.getElementById('reportModal').style.display = 'block';
          }})
          .catch(err => alert('Error loading report: ' + err));
        return false;
      }}
      function closeReport() {{
        document.getElementById('reportModal').style.display = 'none';
      }}
      document.getElementById('reportModal').onclick = function(e) {{
        if (e.target === this) closeReport();
      }};
    </script>
    """


def _benchmark_source_audio_items(source_path: str | None) -> list[Uc1AudioItem]:
    if not source_path:
        return []

    path = Path(source_path).expanduser()
    candidates: list[Path] = []
    if path.exists() and path.is_file():
        candidates = [path]
    elif path.exists() and path.is_dir():
        candidates = sorted([p for p in path.iterdir() if p.is_file()])
    else:
        return []

    allowed = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
    items: list[Uc1AudioItem] = []
    for candidate in candidates:
        if candidate.suffix.lower() not in allowed:
            continue
        items.append(
            Uc1AudioItem(
                path=str(candidate),
                name=candidate.name,
                duration_seconds=_wav_duration(candidate),
                size_bytes=candidate.stat().st_size if candidate.exists() else None,
            )
        )
    return items


def _reference_lookup_from_dataset(reference_dataset_path: str | None) -> dict[str, BenchmarkSample]:
    if not reference_dataset_path:
        return {}

    dataset_path = Path(reference_dataset_path).expanduser()
    if not dataset_path.exists() or not dataset_path.is_file():
        raise FileNotFoundError(f"Reference dataset not found: {dataset_path}")

    samples = parse_dataset(dataset_path)
    lookup: dict[str, BenchmarkSample] = {}
    for sample in samples:
        call_key = sample.call_id.strip().lower()
        stem_key = sample.audio_path.stem.strip().lower()
        name_key = sample.audio_path.name.strip().lower()
        if call_key:
            lookup[call_key] = sample
        if stem_key:
            lookup[stem_key] = sample
        if name_key:
            lookup[name_key] = sample
    return lookup


def _benchmark_provider_rows_html(
    rows: list[dict[str, Any]],
    *,
    colspan: int = 11,
    with_details: bool = False,
    with_success: bool = False,
    run_id: str = "",
) -> str:
    """Render provider metric rows with a threshold-based quality color per row:
    green when WER and CER are both < 0.10; else yellow when corrected WER and CER
    are both < 0.15; else grey. Confidence < 0.70 overrides the whole row to red.
    The Tuning button is only offered when confidence < 0.85."""
    if not rows:
        return f"<tr><td colspan='{colspan}' class='muted'>No provider rows found.</td></tr>"

    def row_color(r: dict[str, Any]) -> str:
        conf = float(r.get("avg_confidence", 0.0) or 0.0)
        wer = float(r.get("avg_wer", 0.0) or 0.0)
        cer = float(r.get("avg_cer", 0.0) or 0.0)
        cwer = float(r.get("avg_corrected_wer", 0.0) or 0.0)
        ccer = float(r.get("avg_corrected_cer", 0.0) or 0.0)
        if conf < 0.70:
            return "#ef4444"  # red — whole line
        if wer < 0.10 and cer < 0.10:
            return "#22c55e"  # green
        if cwer < 0.15 and ccer < 0.15:
            return "#f59e0b"  # yellow
        return "#9ca3af"  # grey

    def td(value: float, fmt: str, color: str) -> str:
        return f"<td style=\"color:{color}; font-weight:600;\">{format(value, fmt)}</td>"

    out: list[str] = []
    for r in rows:
        conf = float(r.get("avg_confidence", 0.0) or 0.0)
        color = row_color(r)
        success_cell = ""
        if with_success:
            counted = int(r.get("counted", r.get("samples", 0)) or 0)
            attempted = int(r.get("attempted", counted) or 0)
            if attempted and counted == attempted:
                success_color = "#22c55e"
            elif counted > 0:
                success_color = "#f59e0b"
            else:
                success_color = "#ef4444"
            success_cell = (
                f"<td style=\"color:{success_color}; font-weight:700;\">{counted}/{attempted}</td>"
            )
        row_html = (
            "<tr>"
            f"<td>{escape(str(r.get('provider', '')))}</td>"
            f"<td>{int(r.get('samples', 0) or 0)}</td>"
            + success_cell
            + td(float(r.get("avg_wer", 0.0) or 0.0), ".4f", color)
            + td(float(r.get("avg_cer", 0.0) or 0.0), ".4f", color)
            + td(float(r.get("avg_keyword_recall", 0.0) or 0.0), ".4f", color)
            + td(float(r.get("avg_confidence", 0.0) or 0.0), ".4f", color)
            + td(float(r.get("avg_corrected_wer", 0.0) or 0.0), ".4f", color)
            + td(float(r.get("avg_corrected_cer", 0.0) or 0.0), ".4f", color)
            + td(float(r.get("avg_corrected_confidence", 0.0) or 0.0), ".4f", color)
            + td(float(r.get("avg_latency_ms", 0.0) or 0.0), ".2f", color)
        )
        if with_details:
            # summary.md shows a verbose display name for Voice Live providers
            # (e.g. "...-phrase-list (session=..., phrase_list=on)"); the details are
            # keyed by the bare provider name (the .results.jsonl file stem), so strip
            # anything from the first " (" to match.
            provider_key = str(r.get("provider", "")).split(" (", 1)[0].strip()
            prov_json = escape(json.dumps(provider_key), quote=True)
            row_html += (
                "<td><button style=\"background:rgba(167,139,250,.18); color:#c4b5fd; "
                "border:1px solid rgba(167,139,250,.45); border-radius:999px; padding:6px 12px; "
                f"cursor:pointer; font-weight:600;\" onclick=\"openProviderDetails({prov_json})\">Details</button>"
            )
            if run_id and conf < 0.85:
                run_json = escape(json.dumps(run_id), quote=True)
                row_html += (
                    " <button style=\"background:rgba(52,211,153,.16); color:#6ee7b7; "
                    "border:1px solid rgba(52,211,153,.45); border-radius:999px; padding:6px 12px; "
                    "cursor:pointer; font-weight:600; margin-left:6px;\" "
                    f"onclick=\"openProviderTuning({prov_json}, {run_json})\">Tuning</button>"
                )
            row_html += "</td>"
        row_html += "</tr>"
        out.append(row_html)
    return "".join(out)


def _benchmark_run_result_html(run_summary: BenchmarkRunSummary | None) -> str:
    if run_summary is None:
        return ""

    provider_details: dict[str, list[dict[str, Any]]] = {}
    for result_file in run_summary.result_files:
        if not result_file.endswith(".results.jsonl"):
            continue

        provider_name = Path(result_file).name[: -len(".results.jsonl")]
        details: list[dict[str, Any]] = []
        try:
            for raw_line in Path(result_file).read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    continue
                details.append(
                    {
                        "call_id": str(payload.get("call_id") or ""),
                        "reference_text": str(payload.get("reference_text") or ""),
                        "hypothesis_text": str(payload.get("hypothesis_text") or ""),
                        "wer": float(payload.get("wer") or 0.0),
                        "cer": float(payload.get("cer") or 0.0),
                        "keyword_recall": float(payload.get("keyword_recall") or 0.0),
                    "confidence": float(payload.get("confidence") or 0.0),
                        "latency_ms": float(payload.get("latency_ms") or 0.0),
                        "corrected_hypothesis_text": str(payload.get("corrected_hypothesis_text") or ""),
                        "corrected_wer": float(payload.get("corrected_wer") or 0.0),
                        "corrected_cer": float(payload.get("corrected_cer") or 0.0),
                        "corrected_keyword_recall": float(payload.get("corrected_keyword_recall") or 0.0),
                        "corrected_confidence": float(payload.get("corrected_confidence") or 0.0),
                        "error": str(payload.get("error") or ""),
                    }
                )
        except Exception:
            details = []

        provider_details[provider_name] = details

    provider_details_js = json.dumps(provider_details, ensure_ascii=False).replace("</", "<\\/")

    provider_rows = _benchmark_provider_rows_html(
        run_summary.provider_rows, colspan=12, with_details=True, with_success=True, run_id=run_summary.run_id
    )

    artifact_rows = "".join(
        f"<tr><td><a href=\"/api/uc1/report?path={escape(path, quote=True)}\" style=\"color:#a78bfa; text-decoration:underline;\" onclick=\"return viewBenchmarkArtifact(event)\">{escape(Path(path).name)}</a></td><td>{escape(path)}</td></tr>"
        for path in run_summary.result_files
        if path.lower().endswith(".md")
    ) or "<tr><td colspan='2' class='muted'>No result artifact files.</td></tr>"

    return f"""
    <section class="section">
      <div class="panel">
        <h4>Benchmark run result</h4>
        <div class="chip-row">
          <span class="chip"><strong>Run ID</strong> {escape(run_summary.run_id)}</span>
          <span class="chip"><strong>Source</strong> {escape(run_summary.source_path)}</span>
          <span class="chip"><strong>Reference dataset</strong> {escape(run_summary.reference_dataset_path or 'none')}</span>
          <span class="chip"><strong>Providers</strong> {escape(', '.join(run_summary.providers))}</span>
          <span class="chip"><strong>Total items</strong> {run_summary.total_items}</span>
          <span class="chip"><strong>Success</strong> {run_summary.success_count}</span>
          <span class="chip"><strong>Errors</strong> {run_summary.error_count}</span>
        </div>
        <div class="score-legend" style="display:flex; flex-wrap:wrap; gap:14px; margin-top:12px; padding:10px 12px; border:1px solid var(--border); border-radius:12px; background:rgba(255,255,255,0.03); font-size:0.82rem;">
          <span style="font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:0.06em;">Score colors</span>
          <span style="display:inline-flex; align-items:center; gap:6px;"><span style="width:12px; height:12px; border-radius:3px; background:#22c55e; display:inline-block;"></span>Green — WER &lt; 0.10 and CER &lt; 0.10</span>
          <span style="display:inline-flex; align-items:center; gap:6px;"><span style="width:12px; height:12px; border-radius:3px; background:#f59e0b; display:inline-block;"></span>Yellow — Corr WER &lt; 0.15 and Corr CER &lt; 0.15</span>
          <span style="display:inline-flex; align-items:center; gap:6px;"><span style="width:12px; height:12px; border-radius:3px; background:#9ca3af; display:inline-block;"></span>Grey — otherwise</span>
          <span style="display:inline-flex; align-items:center; gap:6px;"><span style="width:12px; height:12px; border-radius:3px; background:#ef4444; display:inline-block;"></span>Red — Confidence &lt; 0.70 (Need LLM Tunning)</span>
        </div>
        <div class="table-wrap" style="margin-top: 12px;">
          <table class="bench-table">
            <thead>
              <tr><th>Provider</th><th>Samples</th><th>Success/Total</th><th>WER</th><th>CER</th><th>Keyword Recall</th><th>Confidence</th><th>Corr WER</th><th>Corr CER</th><th>Corr Confidence</th><th>Latency (ms)</th><th>Details</th></tr>
            </thead>
            <tbody>{provider_rows}</tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="panel">
        <h4>Run artifacts</h4>
        <div class="chip-row">
          <span class="chip"><strong>Summary</strong> <a href="/api/uc1/report?path={escape(run_summary.summary_path, quote=True)}" style="color:#a78bfa; text-decoration:underline;" onclick="return viewBenchmarkArtifact(event)">{escape(Path(run_summary.summary_path).name)}</a></span>
        </div>
        <div class="table-wrap" style="margin-top: 12px;">
          <table>
            <thead><tr><th>File</th><th>Path</th></tr></thead>
            <tbody>{artifact_rows}</tbody>
          </table>
        </div>
      </div>
    </section>

    <div id="benchmarkArtifactModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1000; overflow:auto;">
      <div style="background:#1a1a1a; margin:20px auto; padding:20px; border-radius:12px; max-width:90%; max-height:80vh; overflow:auto; border:1px solid rgba(255,255,255,0.15);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
          <h3 id="benchmarkArtifactTitle" style="margin:0; color:#a78bfa;"></h3>
          <button onclick="closeBenchmarkArtifact()" style="background:none; border:none; color:#fff; font-size:24px; cursor:pointer; padding:0;">&times;</button>
        </div>
        <div id="benchmarkArtifactContent" style="color:#e0e0e0; line-height:1.6;"></div>
      </div>
    </div>

    <div id="providerDetailModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6); z-index:1001; overflow:auto;">
      <div style="background:#171324; margin:20px auto; padding:20px; border-radius:12px; max-width:1000px; max-height:84vh; overflow:auto; border:1px solid rgba(255,255,255,0.15);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
          <h3 id="providerDetailTitle" style="margin:0; color:#c4b5fd;"></h3>
          <button onclick="closeProviderDetails()" style="background:none; border:none; color:#fff; font-size:24px; cursor:pointer; padding:0;">&times;</button>
        </div>
        <div id="providerDetailBody" style="color:#e0e0e0; line-height:1.6;"></div>
      </div>
    </div>

    <div id="providerTuningModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6); z-index:1002; overflow:auto;">
      <div style="background:#122018; margin:20px auto; padding:20px; border-radius:12px; max-width:1000px; max-height:84vh; overflow:auto; border:1px solid rgba(52,211,153,0.3);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
          <h3 id="providerTuningTitle" style="margin:0; color:#6ee7b7;"></h3>
          <button onclick="closeProviderTuning()" style="background:none; border:none; color:#fff; font-size:24px; cursor:pointer; padding:0;">&times;</button>
        </div>
        <div id="providerTuningBody" style="color:#e0e0e0; line-height:1.6;"></div>
      </div>
    </div>

    <script>
      const benchmarkProviderDetails = {provider_details_js};

      function openProviderDetails(providerName) {{
        const items = benchmarkProviderDetails[providerName] || [];
        const title = document.getElementById('providerDetailTitle');
        const body = document.getElementById('providerDetailBody');
        title.textContent = providerName + ' - Details';

        if (!items.length) {{
          body.innerHTML = '<div style="padding:12px; border:1px solid rgba(255,255,255,.15); border-radius:8px;">No sample details found for this provider.</div>';
          document.getElementById('providerDetailModal').style.display = 'block';
          return;
        }}

        const safe = (value) => {{
          const el = document.createElement('div');
          el.textContent = String(value ?? '');
          return el.innerHTML;
        }};

        const cards = items.map((item) => {{
          const expected = item.reference_text ? safe(item.reference_text) : '<span style="opacity:.7;">[empty/no reference]</span>';
          const response = item.hypothesis_text ? safe(item.hypothesis_text) : '<span style="opacity:.7;">[empty response]</span>';
          const corrected = item.corrected_hypothesis_text ? safe(item.corrected_hypothesis_text) : '<span style="opacity:.7;">[no change]</span>';
          const error = item.error ? '<div style="margin-top:8px; padding:8px; border:1px solid rgba(239,68,68,.55); border-radius:8px; color:#fca5a5;">' + safe(item.error) + '</div>' : '';
          return `
            <div style="border:1px solid rgba(255,255,255,.14); border-radius:10px; padding:14px; margin-bottom:12px; background:rgba(255,255,255,.03);">
              <div style="font-weight:700; color:#c4b5fd; margin-bottom:8px;">${{safe(item.call_id || 'unknown')}}</div>
              <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px;">
                <div style="padding:10px; border-radius:8px; border-left:4px solid #34d399; background:rgba(255,255,255,.03);">
                  <div style="font-weight:700; color:#86efac; margin-bottom:6px;">Expected</div>
                  <div style="white-space:pre-wrap; word-break:break-word;">${{expected}}</div>
                </div>
                <div style="padding:10px; border-radius:8px; border-left:4px solid #f87171; background:rgba(255,255,255,.03);">
                  <div style="font-weight:700; color:#fca5a5; margin-bottom:6px;">Model Response</div>
                  <div style="white-space:pre-wrap; word-break:break-word;">${{response}}</div>
                </div>
                <div style="padding:10px; border-radius:8px; border-left:4px solid #60a5fa; background:rgba(255,255,255,.03);">
                  <div style="font-weight:700; color:#93c5fd; margin-bottom:6px;">Corrected Response</div>
                  <div style="white-space:pre-wrap; word-break:break-word;">${{corrected}}</div>
                </div>
              </div>
              <div style="display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:8px; margin-top:10px;">
                <div style="padding:8px; border:1px solid rgba(255,255,255,.12); border-radius:8px;"><div style="opacity:.75; font-size:12px;">WER</div><div style="font-weight:700;">${{Number(item.wer || 0).toFixed(4)}}</div></div>
                <div style="padding:8px; border:1px solid rgba(255,255,255,.12); border-radius:8px;"><div style="opacity:.75; font-size:12px;">CER</div><div style="font-weight:700;">${{Number(item.cer || 0).toFixed(4)}}</div></div>
                <div style="padding:8px; border:1px solid rgba(255,255,255,.12); border-radius:8px;"><div style="opacity:.75; font-size:12px;">Keyword Recall</div><div style="font-weight:700;">${{Number(item.keyword_recall || 0).toFixed(4)}}</div></div>
                <div style="padding:8px; border:1px solid rgba(255,255,255,.12); border-radius:8px;"><div style="opacity:.75; font-size:12px;">Confidence</div><div style="font-weight:700;">${{Number(item.confidence || 0).toFixed(4)}}</div></div>
                <div style="padding:8px; border:1px solid rgba(96,165,250,.35); border-radius:8px;"><div style="opacity:.75; font-size:12px;">Corr WER</div><div style="font-weight:700; color:#93c5fd;">${{Number(item.corrected_wer || 0).toFixed(4)}}</div></div>
                <div style="padding:8px; border:1px solid rgba(96,165,250,.35); border-radius:8px;"><div style="opacity:.75; font-size:12px;">Corr CER</div><div style="font-weight:700; color:#93c5fd;">${{Number(item.corrected_cer || 0).toFixed(4)}}</div></div>
                <div style="padding:8px; border:1px solid rgba(96,165,250,.35); border-radius:8px;"><div style="opacity:.75; font-size:12px;">Corr Confidence</div><div style="font-weight:700; color:#93c5fd;">${{Number(item.corrected_confidence || 0).toFixed(4)}}</div></div>
                <div style="padding:8px; border:1px solid rgba(255,255,255,.12); border-radius:8px;"><div style="opacity:.75; font-size:12px;">Latency (ms)</div><div style="font-weight:700;">${{Number(item.latency_ms || 0).toFixed(2)}}</div></div>
              </div>
              ${{error}}
            </div>
          `;
        }}).join('');

        body.innerHTML = cards;
        document.getElementById('providerDetailModal').style.display = 'block';
      }}

      function closeProviderDetails() {{
        document.getElementById('providerDetailModal').style.display = 'none';
      }}

      const tuningSafe = (value) => {{
        const el = document.createElement('div');
        el.textContent = String(value ?? '');
        return el.innerHTML;
      }};

      function openProviderTuning(providerName, runId) {{
        const title = document.getElementById('providerTuningTitle');
        const body = document.getElementById('providerTuningBody');
        title.textContent = providerName + ' - LLM Tuning';
        body.innerHTML = '<div style="padding:14px; border:1px solid rgba(52,211,153,.35); border-radius:8px;">Running LLM meaning-correction over transcripts… this may take a moment.</div>';
        document.getElementById('providerTuningModal').style.display = 'block';

        fetch('/benchmark/tune', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ provider: providerName, run_id: runId }}),
        }})
          .then(async (r) => {{
            const data = await r.json();
            if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
            return data;
          }})
          .then((data) => {{
            const items = data.items || [];
            const summary = `
              <div style="display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:8px; margin-bottom:14px;">
                <div style="padding:8px; border:1px solid rgba(255,255,255,.12); border-radius:8px;"><div style="opacity:.75; font-size:12px;">Avg WER (raw → tuned)</div><div style="font-weight:700;">${{Number(data.avg_wer||0).toFixed(4)}} → <span style="color:#6ee7b7;">${{Number(data.avg_tuned_wer||0).toFixed(4)}}</span></div></div>
                <div style="padding:8px; border:1px solid rgba(255,255,255,.12); border-radius:8px;"><div style="opacity:.75; font-size:12px;">Avg CER (raw → tuned)</div><div style="font-weight:700;">${{Number(data.avg_cer||0).toFixed(4)}} → <span style="color:#6ee7b7;">${{Number(data.avg_tuned_cer||0).toFixed(4)}}</span></div></div>
                <div style="padding:8px; border:1px solid rgba(255,255,255,.12); border-radius:8px;"><div style="opacity:.75; font-size:12px;">Avg Tuned Confidence</div><div style="font-weight:700; color:#6ee7b7;">${{Number(data.avg_tuned_confidence||0).toFixed(4)}}</div></div>
              </div>`;
            const cards = items.map((item) => {{
              const original = item.hypothesis_text ? tuningSafe(item.hypothesis_text) : '<span style="opacity:.7;">[empty]</span>';
              const tuned = item.tuned_text ? tuningSafe(item.tuned_text) : '<span style="opacity:.7;">[no output]</span>';
              const expected = item.reference_text ? tuningSafe(item.reference_text) : '<span style="opacity:.7;">[no reference]</span>';
              const error = item.error ? '<div style="margin-top:8px; padding:8px; border:1px solid rgba(239,68,68,.55); border-radius:8px; color:#fca5a5;">' + tuningSafe(item.error) + '</div>' : '';
              return `
                <div style="border:1px solid rgba(255,255,255,.14); border-radius:10px; padding:14px; margin-bottom:12px; background:rgba(255,255,255,.03);">
                  <div style="font-weight:700; color:#6ee7b7; margin-bottom:8px;">${{tuningSafe(item.call_id || 'unknown')}}</div>
                  <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px;">
                    <div style="padding:10px; border-radius:8px; border-left:4px solid #34d399; background:rgba(255,255,255,.03);"><div style="font-weight:700; color:#86efac; margin-bottom:6px;">Expected</div><div style="white-space:pre-wrap; word-break:break-word;">${{expected}}</div></div>
                    <div style="padding:10px; border-radius:8px; border-left:4px solid #f87171; background:rgba(255,255,255,.03);"><div style="font-weight:700; color:#fca5a5; margin-bottom:6px;">Raw STT</div><div style="white-space:pre-wrap; word-break:break-word;">${{original}}</div></div>
                    <div style="padding:10px; border-radius:8px; border-left:4px solid #34d399; background:rgba(52,211,153,.06);"><div style="font-weight:700; color:#6ee7b7; margin-bottom:6px;">LLM Tuned</div><div style="white-space:pre-wrap; word-break:break-word;">${{tuned}}</div></div>
                  </div>
                  <div style="display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:8px; margin-top:10px;">
                    <div style="padding:8px; border:1px solid rgba(255,255,255,.12); border-radius:8px;"><div style="opacity:.75; font-size:12px;">WER → Tuned</div><div style="font-weight:700;">${{Number(item.wer||0).toFixed(4)}} → <span style="color:#6ee7b7;">${{Number(item.tuned_wer||0).toFixed(4)}}</span></div></div>
                    <div style="padding:8px; border:1px solid rgba(255,255,255,.12); border-radius:8px;"><div style="opacity:.75; font-size:12px;">CER → Tuned</div><div style="font-weight:700;">${{Number(item.cer||0).toFixed(4)}} → <span style="color:#6ee7b7;">${{Number(item.tuned_cer||0).toFixed(4)}}</span></div></div>
                    <div style="padding:8px; border:1px solid rgba(255,255,255,.12); border-radius:8px;"><div style="opacity:.75; font-size:12px;">Tuned Keyword Recall</div><div style="font-weight:700; color:#6ee7b7;">${{Number(item.tuned_keyword_recall||0).toFixed(4)}}</div></div>
                    <div style="padding:8px; border:1px solid rgba(255,255,255,.12); border-radius:8px;"><div style="opacity:.75; font-size:12px;">Tuned Confidence</div><div style="font-weight:700; color:#6ee7b7;">${{Number(item.tuned_confidence||0).toFixed(4)}}</div></div>
                  </div>
                  ${{error}}
                </div>`;
            }}).join('');
            body.innerHTML = summary + (cards || '<div style="padding:12px;">No samples found.</div>');
          }})
          .catch((err) => {{
            body.innerHTML = '<div style="padding:14px; border:1px solid rgba(239,68,68,.55); border-radius:8px; color:#fca5a5;">Tuning failed: ' + tuningSafe(err.message || err) + '</div>';
          }});
      }}

      function closeProviderTuning() {{
        document.getElementById('providerTuningModal').style.display = 'none';
      }}

      function viewBenchmarkArtifact(event) {{
        event.preventDefault();
        const href = event.target.href;
        const url = new URL(href);
        const path = url.searchParams.get('path');
        fetch('/api/uc1/report?path=' + encodeURIComponent(path))
          .then(r => r.json())
          .then(data => {{
            document.getElementById('benchmarkArtifactTitle').textContent = data.name || 'Artifact';
            const contentDiv = document.getElementById('benchmarkArtifactContent');
            if (data.is_html) {{
              contentDiv.innerHTML = data.content;
            }} else {{
              contentDiv.textContent = data.content;
            }}
            document.getElementById('benchmarkArtifactModal').style.display = 'block';
          }})
          .catch(err => alert('Error loading artifact: ' + err));
        return false;
      }}
      function closeBenchmarkArtifact() {{
        document.getElementById('benchmarkArtifactModal').style.display = 'none';
      }}
      document.getElementById('benchmarkArtifactModal').onclick = function(e) {{
        if (e.target === this) closeBenchmarkArtifact();
      }};
      document.getElementById('providerDetailModal').onclick = function(e) {{
        if (e.target === this) closeProviderDetails();
      }};
      document.getElementById('providerTuningModal').onclick = function(e) {{
        if (e.target === this) closeProviderTuning();
      }};
    </script>
    """


_TUNING_INSTRUCTIONS = (
    "You are a speech-to-text transcript correction assistant for a Traditional Chinese "
    "(zh-TW) call center. You are given a raw STT hypothesis that may contain "
    "mis-recognized words (wrong homophones, garbled English technical terms, etc.). "
    "Rewrite it into the most likely INTENDED utterance based on meaning and context.\n"
    "Rules:\n"
    "- Output Traditional Chinese; keep English technical terms in English (e.g. Hardware RD, Software RD, Job).\n"
    "- Fix obvious homophone/phonetic errors and spacing, but do NOT add, remove, or invent content.\n"
    "- Do NOT translate, summarize, or explain.\n"
    "- Return ONLY the corrected transcript text on a single line, with no quotes or labels."
)


def _domain_glossary_terms() -> list[str]:
    """Canonical domain terms (from corrections.json keys) that the LLM should
    map phonetic mishearings back to, e.g. 'Hardware RD', '貨況', '遠傳'."""
    try:
        path = Path(load_settings().corrections_path)
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    seen: list[str] = []
    for key in data.keys():
        term = str(key).strip()
        if term and term not in seen:
            seen.append(term)
    return seen


def _build_tuning_instructions() -> str:
    """Base tuning instructions plus a domain glossary so the LLM corrects
    domain jargon (e.g. '號位RD'/'哈維亞比較' -> 'Hardware RD') reliably."""
    terms = _domain_glossary_terms()
    if not terms:
        return _TUNING_INSTRUCTIONS
    glossary = ", ".join(terms[:80])
    return (
        _TUNING_INSTRUCTIONS
        + "\nDomain glossary — if the transcript contains a phonetic or garbled mishearing "
        "of any of these, correct it to the exact canonical form (do not otherwise force "
        "them in): " + glossary + "."
    )


def _build_tuning_agent(settings: Settings) -> Any:
    """Build an LLM agent used for meaning-based transcript correction.

    Prefers a dedicated Foundry tuning agent (STT_TUNING_AGENT_NAME), then a Foundry
    model deployment, then Azure OpenAI — mirroring the QaJudge fallback chain."""
    endpoint = (settings.foundry_project_endpoint or "").strip()
    tuning_agent_name = (os.getenv("STT_TUNING_AGENT_NAME") or "").strip()
    tuning_agent_version = (os.getenv("STT_TUNING_AGENT_VERSION") or "").strip() or None
    model_deployment = (settings.foundry_model_deployment_name or "").strip()
    instructions = _build_tuning_instructions()

    if endpoint and tuning_agent_name:
        return build_foundry_agent(
            name="VoiceCall STT Tuning",
            instructions=instructions,
            project_endpoint=endpoint,
            agent_name=tuning_agent_name,
            agent_version=tuning_agent_version,
        )
    if endpoint and model_deployment:
        return build_foundry_agent(
            name="VoiceCall STT Tuning",
            instructions=instructions,
            project_endpoint=endpoint,
            model=model_deployment,
        )
    if settings.aoai_endpoint:
        return build_azure_openai_agent(
            name="VoiceCall STT Tuning",
            instructions=instructions,
            model=settings.aoai_deployment,
            azure_endpoint=settings.aoai_endpoint.strip().rstrip("/"),
            api_version=settings.aoai_api_version,
            api_key=settings.aoai_api_key or None,
        )
    raise ValueError(
        "LLM tuning requires FOUNDRY_PROJECT_ENDPOINT (+ agent name or model deployment) "
        "or AOAI_ENDPOINT."
    )


def _load_provider_result_rows(run_id: str, provider: str) -> tuple[Path, list[dict[str, Any]]]:
    """Locate and load a provider's per-sample benchmark results for a run."""
    safe_run = Path(run_id).name  # prevent path traversal
    run_dir = _BENCHMARK_ROOT / safe_run
    provider_key = str(provider).split(" (", 1)[0].strip()
    results_path = run_dir / f"{provider_key}.results.jsonl"
    if not results_path.exists():
        raise FileNotFoundError(f"No results file for provider '{provider_key}' in run '{safe_run}'.")

    rows: list[dict[str, Any]] = []
    for raw_line in results_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return results_path, rows


async def _tune_provider_transcripts(run_id: str, provider: str) -> dict[str, Any]:
    """Run LLM meaning-correction over a provider's transcripts and re-score them."""
    settings = load_settings()
    _, rows = _load_provider_result_rows(run_id, provider)
    agent = _build_tuning_agent(settings)
    semaphore = asyncio.Semaphore(int(os.getenv("STT_TUNING_CONCURRENCY", "4")))

    async def _tune_one(row: dict[str, Any]) -> dict[str, Any]:
        reference = str(row.get("reference_text") or "")
        hypothesis = str(row.get("hypothesis_text") or "")
        rule_hint = str(row.get("corrected_hypothesis_text") or "")
        keywords = row.get("keywords") if isinstance(row.get("keywords"), list) else []
        raw_wer = float(row.get("wer") or 0.0)
        raw_cer = float(row.get("cer") or 0.0)

        tuned_text = hypothesis
        error = ""
        if hypothesis.strip():
            try:
                # Feed the RAW transcript (preserves phonetic evidence) plus the
                # deterministic dictionary output as a non-binding hint, so the LLM
                # has both signals without inheriting rule-based mistakes.
                prompt = (
                    "Correct this STT transcript to its most likely intended meaning.\n"
                    f"Raw transcript: {hypothesis}"
                )
                if rule_hint.strip() and rule_hint.strip() != hypothesis.strip():
                    prompt += (
                        f"\nRule-based guess (a hint only — prefer the raw transcript if the "
                        f"hint looks wrong): {rule_hint}"
                    )
                async with semaphore:
                    response = await agent.run(prompt)
                text = getattr(response, "text", None)
                tuned_text = (text if isinstance(text, str) else str(response)).strip()
            except Exception as exc:  # noqa: BLE001 - report per-sample, keep others running
                error = f"{type(exc).__name__}: {exc}"
                tuned_text = hypothesis

        tuned_eval = compute_evaluation(reference, tuned_text, keywords, has_error=bool(error))
        return {
            "call_id": str(row.get("call_id") or ""),
            "reference_text": reference,
            "hypothesis_text": hypothesis,
            "tuned_text": tuned_text,
            "wer": raw_wer,
            "cer": raw_cer,
            "tuned_wer": tuned_eval.wer,
            "tuned_cer": tuned_eval.cer,
            "tuned_keyword_recall": tuned_eval.keyword_recall,
            "tuned_confidence": tuned_eval.confidence,
            "error": error,
        }

    items = await asyncio.gather(*(_tune_one(row) for row in rows))
    count = max(1, len(items))
    return {
        "provider": str(provider).split(" (", 1)[0].strip(),
        "run_id": Path(run_id).name,
        "items": items,
        "avg_wer": sum(i["wer"] for i in items) / count,
        "avg_tuned_wer": sum(i["tuned_wer"] for i in items) / count,
        "avg_cer": sum(i["cer"] for i in items) / count,
        "avg_tuned_cer": sum(i["tuned_cer"] for i in items) / count,
        "avg_tuned_confidence": sum(i["tuned_confidence"] for i in items) / count,
    }


def _parse_summary_provider_rows(summary_path: Path) -> list[dict[str, Any]]:
    if not summary_path.exists():
        return []

    content = summary_path.read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for line in content.splitlines():
        match = _SUMMARY_ROW_RE.match(line)
        if not match:
            continue
        rows.append(
            {
                "provider": match.group("provider").strip(),
                "samples": int(match.group("samples")),
                "avg_wer": float(match.group("wer")),
                "avg_cer": float(match.group("cer")),
                "avg_keyword_recall": float(match.group("keyword")),
                "avg_confidence": float(match.group("confidence") or 0.0),
                "avg_latency_ms": float(match.group("latency")),
            }
        )
    _merge_corrected_metrics(rows, _parse_corrected_metrics(content))
    return rows


def _build_benchmark_samples_from_source(
  source_path: str,
  reference_dataset_path: str | None = None,
  selected_paths: list[str] | None = None,
) -> list[BenchmarkSample]:
  source_candidate = Path(source_path).expanduser()
  if source_candidate.exists() and source_candidate.is_file() and source_candidate.suffix.lower() == ".jsonl":
    # If source itself is a dataset JSONL, use it directly.
    return parse_dataset(source_candidate)

  reference_lookup = _reference_lookup_from_dataset(reference_dataset_path)
  items = _benchmark_source_audio_items(source_path)
  # Optional WAV multi-select: keep only the files the user picked on the dashboard.
  if selected_paths:
    wanted = {str(p).strip() for p in selected_paths if str(p).strip()}
    items = [item for item in items if item.path in wanted]
  samples: list[BenchmarkSample] = []
  for item in items:
    audio_path = Path(item.path)
    call_key = audio_path.stem.strip().lower()
    name_key = audio_path.name.strip().lower()
    matched = reference_lookup.get(call_key) or reference_lookup.get(name_key)
    if matched is None or not matched.reference_text.strip():
      raise ValueError(
        f"Missing reference_text for benchmark audio '{audio_path.name}'. Add a matching row to the reference dataset before running the benchmark."
      )
    samples.append(
      BenchmarkSample(
        call_id=audio_path.stem,
        audio_path=audio_path,
        reference_text=matched.reference_text,
        keywords=matched.keywords,
        metadata={"audio_duration_seconds": item.duration_seconds or 0.0},
      )
    )
  return samples


def _run_benchmark_from_source(
    source_path: str,
    provider_ids: list[str],
    reference_dataset_path: str | None = None,
    selected_paths: list[str] | None = None,
) -> BenchmarkRunSummary:
    providers = [build_provider(provider_id) for provider_id in provider_ids]
    samples = _build_benchmark_samples_from_source(source_path, reference_dataset_path, selected_paths)
    if not samples:
        raise ValueError("No audio files found in the selected source path.")

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = _BENCHMARK_ROOT / run_id
    summary_path = run_benchmark(
        providers=providers,
        samples=samples,
        output_dir=output_dir,
        max_workers=1,
    )
    append_cost_report(summary_path, samples, providers)

    provider_rows = _parse_summary_provider_rows(summary_path)
    result_files = [str(summary_path)]
    counts_by_provider: dict[str, tuple[int, int]] = {}
    for provider in providers:
        results_path = output_dir / f"{provider.name}.results.jsonl"
        if results_path.exists():
            result_files.append(str(results_path))
            attempted = 0
            skipped = 0
            try:
                for raw_line in results_path.read_text(encoding="utf-8").splitlines():
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    payload = json.loads(raw_line)
                    attempted += 1
                    if isinstance(payload, dict) and payload.get("skipped"):
                        skipped += 1
            except Exception:
                pass
            counts_by_provider[provider.name] = (attempted - skipped, attempted)
        readable_path = output_dir / f"{provider.name}.readable.md"
        if readable_path.exists():
            result_files.append(str(readable_path))

    # Attach success/total counts to each provider row (rows are keyed by the
    # summary display name, which may carry a " (session=...)" suffix).
    for row in provider_rows:
        bare_name = str(row.get("provider", "")).split(" (", 1)[0].strip()
        if bare_name in counts_by_provider:
            counted, attempted = counts_by_provider[bare_name]
            row["counted"] = counted
            row["attempted"] = attempted

    error_count = 0
    success_count = 0
    for row in provider_rows:
        sample_count = int(row.get("samples", 0))
        if sample_count <= 0:
            error_count += 1
        else:
            success_count += 1

    return BenchmarkRunSummary(
        run_id=run_id,
        source_path=source_path,
        providers=[provider.name for provider in providers],
        total_items=len(samples),
        success_count=success_count,
        error_count=error_count,
        summary_path=str(summary_path),
        provider_rows=provider_rows,
        result_files=result_files,
        reference_dataset_path=reference_dataset_path,
    )


def _uc1_page(
    message: str | None = None,
    run_summary: Uc1RunSummary | None = None,
    source_path_override: str | None = None,
    stt_provider_override: str | None = None,
) -> str:
    cfg = _current_config()
    default_settings = load_settings()

    source_path_value = (source_path_override or _default_uc1_source_path(default_settings)).strip()
    page_settings = _apply_uc1_source_override(load_settings(), source_path_value or None)

    selected_provider = (stt_provider_override or cfg["uc1_provider"]).strip()
    provider_ids = list(_UC1_SUPPORTED_PROVIDERS)
    if selected_provider and selected_provider not in provider_ids:
        provider_ids.append(selected_provider)

    audio_items = _uc1_audio_items(page_settings)
    source_label = (
        str(page_settings.local_audio_path)
        if page_settings.local_audio_path
        else str(page_settings.local_audio_dir)
        if page_settings.local_audio_dir
        else "No local WAV source configured"
    )
    source_mode = page_settings.input_source.upper()

    provider_options = "".join(
        f"<option value=\"{escape(provider_id)}\"{' selected' if provider_id == selected_provider else ''}>"
        f"{escape(provider_to_display_label(provider_id))} ({escape(provider_id)})"
        f"</option>"
        for provider_id in provider_ids
    )

    audio_rows = "".join(
      f"<tr>"
      f"<td><input type='radio' name='run_target' value=\"{escape(item.path, quote=True)}\" form='uc1form'{' checked' if idx == 0 else ''} /></td>"
      f"<td>{escape(item.name)}</td>"
      f"<td>{escape(item.path)}</td>"
      f"<td>{escape(_format_seconds(item.duration_seconds))}</td>"
      f"<td>{escape(_human_size(item.size_bytes))}</td>"
      f"<td><audio class='preview-player' controls preload='none' src='/api/audio/preview?path={escape(quote(item.path, safe=''), quote=True)}'></audio></td>"
      f"</tr>"
      for idx, item in enumerate(audio_items)
    ) or "<tr><td colspan='6' class='muted'>No audio files found.</td></tr>"

    message_html = ""
    if message:
        message_html = f"""
        <section class="section">
          <div class="panel">
            <h4 data-i18n-text="bench_status">Run status</h4>
            <div class="summary-box">{escape(message)}</div>
          </div>
        </section>
        """

    result_html = _uc1_run_result_html(run_summary)

    body = f"""
    <section class="hero">
      <div class="hero-grid">
        <div>
          <span class="eyebrow" data-i18n-text="uc1p_eyebrow">UC1 quality check</span>
          <h2 data-i18n-text="uc1p_h2">Run quality check and review the result directly on this page.</h2>
          <p class="lead" data-i18n="uc1p_lead">
            You can change the local source path and STT method for this run. The report summary and per-call results
            are shown below immediately after the job completes.
          </p>
          <div class="chip-row">
            <span class="chip"><strong data-i18n-text="uc1p_source_mode">Source mode</strong> {escape(source_mode)}</span>
            <span class="chip"><strong data-i18n-text="uc1p_source_path">Source path</strong> {escape(source_label)}</span>
            <span class="chip"><strong data-i18n-text="uc1p_stt">STT</strong> {escape(provider_to_display_label(selected_provider))}</span>
          </div>
          <form id="uc1form" method="post" action="/uc1/run" style="margin-top:14px;">
            <div class="split">
              <div>
                <label for="source_path" data-i18n-text="uc1p_label_source">Source path (file or folder)</label>
                <input id="source_path" name="source_path" type="text" value="{escape(source_path_value)}" placeholder="e.g. C:/temp or C:/calls/demo.wav" style="width:100%; margin-top:6px;" />
              </div>
              <div>
                <label for="stt_provider" data-i18n-text="uc1p_label_stt">STT method</label>
                <select id="stt_provider" name="stt_provider" form="uc1form" style="width:100%; margin-top:6px;">{provider_options}</select>
              </div>
            </div>
            <div class="cta-row">
              <button class="btn primary" type="submit" data-i18n-text="uc1p_btn_run">Run quality check</button>
              <button class="btn" type="submit" formaction="/uc1/list" data-i18n-text="uc1p_btn_list">List files</button>
            </div>
          </form>
        </div>
        <div class="panel">
          <h4 data-i18n-text="uc1p_what">What this page does</h4>
          <ul class="detail-list">
            <li data-i18n-text="uc1p_w1">Shows each local audio file that UC1 will process from the selected source path.</li>
            <li data-i18n-text="uc1p_w2">Runs speech recognition, rubric scoring, and Markdown report generation.</li>
            <li data-i18n-text="uc1p_w3">Shows run status, pass/fail counts, token usage, and report paths on-page.</li>
          </ul>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <div>
          <h3 data-i18n-text="uc1p_preview">Source audio preview</h3>
          <p data-i18n="uc1p_preview_desc">Pick a file to check, listen with the player, then Run quality check.</p>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th data-i18n-text="uc1p_select">Select</th><th data-i18n-text="bench_table_file">File</th><th data-i18n-text="bench_table_path">Path</th><th data-i18n-text="bench_table_duration">Duration</th><th data-i18n-text="bench_table_size">Size</th><th data-i18n-text="bench_table_play">Play</th></tr>
          </thead>
          <tbody>{audio_rows}</tbody>
        </table>
      </div>
    </section>
    {message_html}
    {result_html}
    """
    return _page_shell("UC1", "uc1", body, cfg["uc1_provider_label"])


def _wav_duration(path: Path) -> float | None:
  try:
    import wave

    with wave.open(str(path), "rb") as wav_file:
      frame_rate = wav_file.getframerate()
      if frame_rate <= 0:
        return None
      return wav_file.getnframes() / frame_rate
  except Exception:
    return None


def _human_size(size_bytes: int | None) -> str:
  if size_bytes is None:
    return "Unknown"
  value = float(size_bytes)
  for unit in ["B", "KB", "MB", "GB"]:
    if value < 1024 or unit == "GB":
      return f"{value:.1f} {unit}"
    value /= 1024
  return f"{value:.1f} GB"


def _format_seconds(value: float | None) -> str:
  if value is None:
    return "Unknown"
  return f"{value:.2f}s"


def _uc1_audio_items(settings: Settings | None = None) -> list[Uc1AudioItem]:
  resolved_settings = settings or load_settings()
  reader = BlobReader(resolved_settings)

  items: list[Uc1AudioItem] = []
  try:
    for item in reader.list_input_audio_items():
      item_path = Path(item)
      items.append(
        Uc1AudioItem(
          path=str(item_path),
          name=item_path.name,
          duration_seconds=_wav_duration(item_path),
          size_bytes=item_path.stat().st_size if item_path.exists() else None,
        )
      )
  except Exception as exc:
    items.append(
      Uc1AudioItem(
        path="",
        name=f"Unable to list audio: {exc}",
        duration_seconds=None,
        size_bytes=None,
      )
    )
  return items


# ──────────────────────────────────────────────────────────────────────────────
# HTML helpers
# ──────────────────────────────────────────────────────────────────────────────


def _page_shell(title: str, active: str, body: str, stt_method: str = "Configured") -> str:
    nav_items = [
        ("/", "Home", "home"),
        ("/uc1", "UC1", "uc1"),
        ("/uc2", "UC2", "uc2"),
        ("/uc3", "UC3", "uc3"),
        ("/benchmark", "STT Benchmark", "benchmark"),
        ("/tts-benchmark", "TTS Benchmark", "tts-benchmark"),
    ]
    nav_html = "".join(
        f'<a class="nav-link{" active" if key == active else ""}" href="{href}" data-key="{key}">{label}</a>'
        for href, label, key in nav_items
    )
    stt_html = (
      f'<div id="sttMethod" class="stt-method"><strong>STT:</strong> <span id="sttMethodLabel">{escape(stt_method)}</span></div>'
      if stt_method.strip()
      else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)} · VoiceCall Verify</title>
  <style>
    :root {{
      --bg-base: #0f172a;
      --text: #ecf0ff;
      --muted: #c9d0e8;
      --surface: rgba(18, 22, 34, 0.72);
      --surface-strong: rgba(29, 35, 54, 0.5);
      --border: rgba(196, 205, 238, 0.22);
      --accent: #7aa0ff;
      --accent-2: #67d9ff;
      --accent-soft: rgba(122, 160, 255, 0.16);
      --summary: rgba(103, 217, 255, 0.12);
      --summary-border: rgba(122, 160, 255, 0.24);
      --shadow: 0 22px 52px rgba(8, 10, 20, 0.4);
    }}
    * {{ box-sizing: border-box; }}
    html {{ font-size: 17.5px; }}
    html, body {{ height: 100%; }}
    body {{
      margin: 0;
      color: var(--text);
      background:
        linear-gradient(165deg, rgba(30, 33, 63, 0.24), rgba(19, 22, 36, 0.76)),
        radial-gradient(circle at 20% 14%, rgba(255, 174, 174, 0.46), transparent 40%),
        radial-gradient(circle at 82% 8%, rgba(120, 117, 255, 0.34), transparent 38%),
        radial-gradient(circle at 50% 112%, rgba(145, 191, 255, 0.27), transparent 45%),
        url('https://images.unsplash.com/photo-1542273917363-3b1817f69a2d?auto=format&fit=crop&w=1800&q=80') center / cover no-repeat,
        var(--bg-base);
      font-family: "Aptos Display", "Aptos", "Segoe UI Variable", "Trebuchet MS", sans-serif;
    }}
    a {{ color: #464feb; text-decoration: none; }}
    tr th, tr td {{ border: 1px solid rgba(196, 205, 238, 0.16); }}
    tr th {{ background-color: rgba(122, 160, 255, 0.18); color: var(--text); }}
    code {{ color: #dbe6ff; background: rgba(12, 16, 28, 0.58); border: 1px solid rgba(187, 201, 244, 0.22); border-radius: 8px; padding: 2px 7px; }}
    .wrap {{ max-width: 1320px; margin: 0 auto; padding: 20px; animation: rise 0.55s ease; }}
    .topbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 24px;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .brand-pill {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(16, 20, 32, 0.76);
      border: 1px solid var(--border);
      box-shadow: var(--shadow);
      font-weight: 700;
      letter-spacing: 0.3px;
      color: #dbe6ff;
    }}
    .ms-mark {{
      width: 14px;
      height: 14px;
      background:
        linear-gradient(#f35325, #f35325) 0 0 / 6px 6px no-repeat,
        linear-gradient(#81bc06, #81bc06) 8px 0 / 6px 6px no-repeat,
        linear-gradient(#05a6f0, #05a6f0) 0 8px / 6px 6px no-repeat,
        linear-gradient(#ffba08, #ffba08) 8px 8px / 6px 6px no-repeat;
      border-radius: 2px;
      flex: 0 0 auto;
    }}
    .status-row {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .nav {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
    .nav-link {{
      font-size: 0.86rem;
      padding: 5px 10px;
      border-radius: 999px;
      background: rgba(200, 210, 244, 0.2);
      color: #d8e2ff;
      font-weight: 700;
      border: 1px solid rgba(210, 219, 255, 0.3);
      transition: transform 0.14s ease, filter 0.14s ease;
      white-space: nowrap;
    }}
    .nav-link.active {{
      color: #072c1f;
      background: #8bf7c4;
      border-color: transparent;
    }}
    .nav-link:hover {{ transform: translateY(-1px); filter: brightness(1.03); }}
    .lang-selector {{
      display: flex; gap: 8px; align-items: center;
    }}
    .lang-btn {{
      padding: 6px 14px; border-radius: 6px; border: 1px solid rgba(150, 170, 220, 0.4);
      background: rgba(50, 65, 110, 0.6); color: #b8c8e8; font-weight: 700; font-size: 0.8rem;
      cursor: pointer; transition: all 0.2s ease;
    }}
    .lang-btn.active {{
      background: rgba(100, 120, 180, 0.8); color: #fff; border-color: rgba(150, 170, 220, 0.8);
    }}
    .lang-btn:hover {{
      transform: translateY(-1px); filter: brightness(1.05);
    }}
    .stt-method {{
      font-size: 0.8rem; color: #b8c8e8; padding: 6px 14px; border-radius: 6px;
      background: rgba(100, 140, 220, 0.2); border: 1px solid rgba(122, 160, 255, 0.35); flex-shrink: 0;
    }}
    .stt-method strong {{
      color: #7aa0ff;
    }}
    @media (max-width: 1100px) {{
      .topbar {{ flex-direction: column; align-items: flex-start; }}
      .status-row, .nav {{ width: 100%; }}
    }}
    .hero {{
      margin-top: 22px; padding: 30px; border-radius: 28px;
      background: var(--surface);
      border: 1px solid var(--border); box-shadow: var(--shadow); overflow: hidden; backdrop-filter: blur(12px);
    }}
    .hero-grid {{ display: grid; grid-template-columns: 1.4fr 0.8fr; gap: 18px; align-items: start; }}
    .eyebrow {{
      display: inline-flex; align-items: center; gap: 8px; padding: 7px 11px; border-radius: 999px;
      background: var(--accent-soft); color: var(--accent); border: 1px solid rgba(122, 160, 255, 0.24);
      font-size: 0.82rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.08em;
    }}
    h2 {{ margin: 14px 0 12px; font-size: clamp(2rem, 3.2vw, 2.75rem); line-height: 1.1; text-shadow: 0 12px 34px rgba(7, 10, 18, 0.45); }}
    .lead {{ color: var(--muted); font-size: 1.18rem; line-height: 1.65; max-width: 70ch; }}
    .stats {{ display: grid; gap: 12px; }}
    .stat {{
      padding: 14px 16px; border-radius: 18px; background: rgba(12, 16, 28, 0.56);
      border: 1px solid var(--border);
    }}
    .stat .k {{ color: var(--muted); font-size: 0.84rem; text-transform: uppercase; letter-spacing: 0.08em; }}
    .stat .v {{ margin-top: 8px; font-size: 1.02rem; line-height: 1.45; }}
    .section {{ margin-top: 18px; }}
    .section-head {{ display: flex; align-items: end; justify-content: space-between; gap: 12px; margin-bottom: 12px; }}
    .section-head h3 {{ margin: 0; font-size: 1.5rem; }}
    .section-head p {{ margin: 0; color: var(--muted); font-size: 1.02rem; }}
    .grid {{ display: grid; gap: 14px; }}
    .grid.cards {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .card {{
      border-radius: 18px; padding: 18px; background: var(--surface);
      border: 1px solid var(--border); box-shadow: var(--shadow); backdrop-filter: blur(10px);
    }}
    .card h4 {{ margin: 0 0 8px; font-size: 1.32rem; }}
    .card p {{ margin: 0; color: var(--muted); line-height: 1.6; font-size: 1.05rem; }}
    .chip-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }}
    .chip {{
      display: inline-flex; align-items: center; gap: 8px; padding: 9px 13px; border-radius: 999px;
      background: rgba(14, 18, 30, 0.64); border: 1px solid var(--border); color: var(--text); font-size: 0.98rem;
    }}
    .chip strong {{ color: #dbe6ff; }}
    .cta-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }}
    .btn {{
      display: inline-flex; align-items: center; justify-content: center; padding: 12px 18px; border-radius: 14px;
      border: 1px solid rgba(194, 206, 242, 0.3); background: rgba(94, 112, 168, 0.23);
      color: var(--text); font-weight: 800; font-size: 1.02rem; cursor: pointer; transition: transform 0.14s ease, filter 0.14s ease;
    }}
    .btn.primary {{ background: linear-gradient(140deg, #6584ff, #3d63ee); border-color: transparent; }}
    .btn:hover, .nav-link:hover {{ transform: translateY(-1px); filter: brightness(1.03); }}
    input, select, textarea, button {{ font: inherit; }}
    input, select, textarea {{
      border-radius: 12px; border: 1px solid rgba(194, 206, 242, 0.3); padding: 10px 12px;
      background: rgba(18, 23, 36, 0.84); color: var(--text);
    }}
    input:focus, select:focus, textarea:focus {{ outline: 2px solid rgba(125, 182, 255, 0.85); outline-offset: 1px; }}
    input[type="checkbox"] {{ accent-color: #6584ff; }}
    label {{ color: var(--muted); font-weight: 700; }}
    .table-wrap {{ overflow: auto; border-radius: 18px; border: 1px solid var(--border); background: rgba(12, 16, 28, 0.72); backdrop-filter: blur(8px); }}
    table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
    th, td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid rgba(198, 209, 240, 0.16); }}
    th {{ color: var(--muted); font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.08em; }}
    .bench-table {{ min-width: 0; table-layout: fixed; font-size: 0.8rem; }}
    .bench-table th, .bench-table td {{ padding: 7px 8px; word-break: break-word; letter-spacing: 0.02em; }}
    .bench-table td:first-child, .bench-table th:first-child {{ width: 17%; }}
    .preview-player {{ width: 170px; height: 34px; }}
    tr:last-child td {{ border-bottom: none; }}
    .muted {{ color: var(--muted); }}
    .split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .panel {{ border-radius: 18px; padding: 18px; background: var(--surface); border: 1px solid var(--border); box-shadow: var(--shadow); backdrop-filter: blur(10px); }}
    .panel h4 {{ margin: 0 0 10px; }}
    .summary-box {{ white-space: pre-wrap; line-height: 1.5; color: #dbe6ff; background: var(--summary); padding: 14px; border-radius: 16px; border: 1px solid var(--summary-border); }}
    .footer {{ margin-top: 18px; color: var(--muted); font-size: 0.9rem; }}
    .detail-list {{ margin: 0; padding-left: 18px; color: var(--muted); line-height: 1.7; }}
    @keyframes rise {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    @media (max-width: 1100px) {{
      .grid.cards, .hero-grid, .split {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body data-stt-method="{escape(stt_method)}">
  <div class="wrap">
    <header class="topbar">
      <div class="brand-pill">
        <span class="ms-mark" aria-hidden="true"></span>
        <span>Microsoft Voice QA</span>
      </div>
      <div class="lang-selector">
        <button class="lang-btn active" id="langBtnEn" data-lang="en">English</button>
        <button class="lang-btn" id="langBtnZh" data-lang="zh">繁體中文</button>
      </div>
      <div class="status-row">
        {stt_html}
        <nav class="nav">{nav_html}</nav>
      </div>
    </header>
    {body}
    <div class="footer" data-i18n="footer">Powered by Microsoft Innovation Hub</div>
  </div>
  <script>
    // i18n translations - comprehensive
    const i18n = {{
      en: {{
        // Navigation
        home: "Home",
        uc1: "UC1",
        uc2: "UC2",
        uc3: "UC3",
        benchmark: "STT Benchmark",
        ttsbenchmark: "TTS Benchmark",
        // Home page
        home_eyebrow: "Call center Voice AI practices",
        home_h2: "Explore real-world Voice AI scenarios for modern contact centers",
        home_lead: "Evaluate how different Voice AI approaches perform across common call center use cases\u2014from post-call quality analysis and real-time agent assistance to fully automated voice interactions.",
        home_uc1_label: "UC1",
        home_uc2_label: "UC2",
        home_uc3_label: "UC3",
        home_benchmark_label: "Benchmark default",
        home_btn_live: "Open live assistant",
        home_btn_voice: "Open voice call",
        home_open_label: "Choose a use case",
        home_what_does: "What it does",
        home_method: "Voice method",
        home_name_uc1: "Voice Call Quality",
        home_name_uc2: "Real-time Call Assistant",
        home_name_uc3: "Voice Live Call",
        home_name_benchmark: "STT Benchmark",
        home_name_tts_benchmark: "TTS Benchmark",
        home_desc_uc1: "Offline batch quality check — transcribe recorded calls and score them against a rubric into a Markdown QA report.",
        home_desc_uc2: "Live agent copilot — surfaces next-best-action, compliance, and answer cards in real time during a call.",
        home_desc_uc3: "Fully automated AI voice agent that talks to the caller (speech-to-speech) and escalates specific inquiries to billing, IT, or expert agents.",
        home_desc_benchmark: "Compare STT models for accuracy, latency, and cost across multiple providers.",
        home_desc_tts_benchmark: "Compare TTS voices for latency and real-time factor, keeping the generated audio for listening review.",
        home_stats_uc1: "UC1",
        home_stats_uc2: "UC2",
        home_stats_uc3: "UC3",
        home_stats_benchmark: "Benchmark",
        home_section_cases: "Use cases",
        home_section_cases_desc: "Click a use case on the left to see what it does and which voice method it uses.",
        home_card_btn: "Open page",
        vm_title: "Default voice methods",
        vm_stt: "STT · speech-to-text",
        vm_tts: "TTS · text-to-speech",
        vm_improve: "Improve with",
        vm_stt_skills: "phrase list, custom speech (fine-tuning), locale/language, post-STT corrections",
        vm_tts_skills: "neural/HD voice, SSML style & prosody, custom/personal voice, locale",
        // UC1 page
        uc1_eyebrow: "UC1 page",
        uc1_h2: "Quality assurance transcription with batch processing",
        uc1_what_does: "What this use case does",
        uc1_recommended: "Recommended when",
        uc1_rec_1: "You want speaker-aware batch QA reports.",
        uc1_rec_2: "You need phrase boosting for product names and call-center terms.",
        uc1_rec_3: "You want the safest default for Traditional Chinese with mixed English.",
        // UC2 page
        uc2_eyebrow: "UC2 page",
        uc2_h2: "Real-time call center assistance",
        uc2_what_does: "What this use case does",
        uc2_rec_1: "You want real-time agent guidance during calls.",
        uc2_rec_2: "You want the UI to surface STT mode and LLM mode clearly.",
        uc2_rec_3: "You want to compare browser STT, Azure Speech, or Voice Live labels.",
        uc2_recommended: "Recommended when",
        uc2_btn_live: "Open live console",
        uc2_btn_back: "Back to UC2 page",
        // Benchmark page
        bench_eyebrow: "Benchmark page",
        bench_h2: "Run benchmark and inspect all runs in one place.",
        bench_lead: "Select a local source folder and one or more STT methods to run benchmark directly from this page. Existing run history under reports/stt_benchmarks is listed below.",
        bench_source_path: "Source path (WAV file or folder)",
        bench_reference_dataset: "Reference dataset JSONL (optional)",
        bench_stt_methods: "STT methods (multi-select)",
        bench_btn_run: "Run benchmark",
        bench_btn_script: "Open run script guide",
        bench_btn_home: "Back home",
        bench_btn_delete: "Delete old reports",
        bench_latest_rec: "Latest recommendation",
        bench_no_rec: "No recommendation yet.",
        bench_latest_run: "Latest run",
        bench_none: "none",
        bench_source_preview: "Source audio preview",
        bench_source_preview_desc: "These files will be included in the next benchmark run.",
        bench_table_file: "File",
        bench_table_path: "Path",
        bench_table_duration: "Duration",
        bench_table_size: "Size",
        bench_table_play: "Play",
        bench_latest: "Latest benchmark",
        bench_latest_desc: "Provider averages from the most recent run.",
        bench_cost_estimate: "Cost estimate",
        bench_why_matters: "Why this matters",
        bench_why_1: "Use WER and CER to compare transcription correctness.",
        bench_why_2: "Use latency to decide whether a model is suitable for real-time assistant flows.",
        bench_why_3: "Use the cost table to separate production choices from research-only options.",
        bench_history: "Benchmark history",
        bench_history_desc: "Each run includes the parsed provider table plus the summary excerpt.",
        bench_table_provider: "Provider",
        bench_table_samples: "Samples",
        bench_table_wer: "WER",
        bench_table_cer: "CER",
        bench_table_recall: "Keyword Recall",
        bench_table_confidence: "Confidence",
        bench_table_latency: "Latency (ms)",
        bench_table_cost: "Estimated cost",
        bench_status: "Run status",
        bench_summary_excerpt: "Summary excerpt",
        bench_run_summary: "Summary",
        bench_no_runs: "No benchmark runs found yet.",
        bench_no_audio: "No audio files found in the selected path.",
        // UC3 page + shared use-case detail
        uc3_eyebrow: "UC3 page",
        uc3_h2: "Automated voice call (gpt-realtime + TTS)",
        uc3_what_does: "What this use case does",
        uc1_lead: "Offline batch QA: turn recorded calls into scored Markdown reports with rubric evidence and phrase boosting.",
        uc2_lead: "Live coaching: surface next-best-action, compliance, and answer cards in real time while tracking token usage.",
        uc3_lead: "A fully automated AI voice agent that talks to the caller — it listens, understands, replies in voice, and escalates specific inquiries to billing, IT, or expert agents.",
        uc1_b1: "Reads audio from Blob Storage or local files and transcribes with Azure Speech.",
        uc1_b2: "Applies phrase-list boosting and post-STT corrections for domain terms.",
        uc1_b3: "Scores the transcript against rubric rules and writes Markdown + JSON.",
        uc2_b1: "Live transcript window with compliance and next-best-action cards.",
        uc2_b2: "Open the live console to exercise the full assistant.",
        uc2_b3: "Reports STT mode, LLM mode, token usage, and call audio duration.",
        uc3_b1: "Speech-to-speech: the AI agent talks directly to the caller in real time.",
        uc3_b2: "Open the voice call and speak into your microphone.",
        uc3_b3: "Specific inquiries route to billing, IT, or expert agents, then are spoken back as TTS.",
        btn_open_live: "Open live console",
        btn_open_voice: "Open voice call",
        btn_open_benchmark: "Open benchmark page",
        btn_open_bench_details: "Open benchmark details",
        btn_run_matrix: "Run matrix script",
        btn_open_tts: "Open TTS benchmark",
        btn_run_quality: "Run quality check",
        btn_open_stt: "Open STT benchmark",
        uc1_improve: "phrase list, custom speech (fine-tuning), locale/language, post-STT corrections",
        uc2_improve: "STT phrase list & locale, agent instructions/prompt, LLM model choice, transcript window size",
        uc3_improve: "voice selection, transcription model (azure-speech / mai-transcribe-1 / gpt-4o-transcribe), expert agent, VAD & barge-in tuning",
        // UC1 run page
        uc1p_eyebrow: "UC1 quality check",
        uc1p_h2: "Run quality check and review the result on this page.",
        uc1p_lead: "Change the local source path and STT method for this run. The report summary and per-call results appear below once the job completes.",
        uc1p_source_mode: "Source mode",
        uc1p_source_path: "Source path",
        uc1p_stt: "STT",
        uc1p_label_source: "Source path (file or folder)",
        uc1p_label_stt: "STT method",
        uc1p_btn_run: "Run quality check",
        uc1p_btn_list: "List files",
        uc1p_select: "Select",
        uc1p_what: "What this page does",
        uc1p_w1: "Shows each local audio file that UC1 will process from the selected source path.",
        uc1p_w2: "Runs speech recognition, rubric scoring, and Markdown report generation.",
        uc1p_w3: "Shows run status, pass/fail counts, token usage, and report paths on-page.",
        uc1p_preview: "Source audio preview",
        uc1p_preview_desc: "Pick a file to check, listen with the player, then Run quality check.",
        // TTS benchmark page
        tts_eyebrow: "TTS benchmark page",
        tts_h2: "Compare text-to-speech voices in one place.",
        tts_lead: "Benchmark TTS latency/performance across Voice Live (gpt-realtime), MAI-Voice-2, and Azure neural voices. Generated audio is kept for listening review.",
        tts_label_dataset: "Dataset JSONL (sample_id, text, language?)",
        tts_providers: "TTS providers (multi-select)",
        tts_parallel: "Run providers in parallel",
        tts_btn_run: "Run TTS benchmark",
        tts_latest: "Latest run",
        tts_tip1: "Lower time-to-first-audio and real-time factor are better.",
        tts_tip2: "Real-time factor < 1.0 means faster than realtime.",
        tts_tip3: "Naturalness is not auto-scored — listen to the WAVs.",
        tts_section_latest: "Latest TTS benchmark",
        tts_section_latest_desc: "Provider averages from the most recent run.",
        tts_history: "TTS benchmark history",
        tts_history_desc: "Each run includes the parsed provider table plus the summary excerpt.",
        tts_th_provider: "Provider",
        tts_th_samples: "Samples",
        tts_th_success: "Success",
        tts_th_ttfa: "Time-to-First-Audio (ms)",
        tts_th_synth: "Total Synthesis (ms)",
        tts_th_dur: "Audio Duration (ms)",
        tts_th_rtf: "Real-Time Factor",
        tts_run_result: "Run result",
        tts_audio_suffix: "generated audio",
        tts_th_sample: "Sample",
        // Common
        voice_model: "Voice model",
        provider: "Provider",
        route: "Route",
        phrase_list: "Phrase list",
        languages: "Languages",
        voice_input: "Voice input path",
        config_title: "Config",
        footer: "Powered by Microsoft Innovation Hub"
      }},
      zh: {{
        // Navigation
        home: "首頁",
        uc1: "UC1",
        uc2: "UC2",
        uc3: "UC3",
        benchmark: "STT 基準測試",
        ttsbenchmark: "TTS 基準測試",
        // Home page
        home_eyebrow: "客服中心語音 AI 實踐",
        home_h2: "探索現代客服中心的實際語音 AI 使用情境",
        home_lead: "評估不同的語音 AI 方法在常見客服中心使用案例中的表現——從通話後品質分析、即時座席協助，到完全自動的語音互動。",
        home_uc1_label: "UC1",
        home_uc2_label: "UC2",
        home_uc3_label: "UC3",
        home_benchmark_label: "基準預設",
        home_btn_live: "打開實時助手",
        home_btn_voice: "打開語音通話",
        home_open_label: "選擇使用案例",
        home_what_does: "功能說明",
        home_method: "語音方法",
        home_name_uc1: "語音通話品質",
        home_name_uc2: "實時通話助手",
        home_name_uc3: "語音即時通話",
        home_name_benchmark: "STT 基準測試",
        home_name_tts_benchmark: "TTS 基準測試",
        home_desc_uc1: "離線批量品質檢查——轉錄錄音通話並依評分準則評分，產生 Markdown QA 報告。",
        home_desc_uc2: "實時坐席助手——在通話中即時顯示下一步最佳行動、合規與答案卡片。",
        home_desc_uc3: "完全自動的 AI 語音代理，直接與來電者對話（語音對語音），並將特定查詢轉交專家代理。",
        home_desc_benchmark: "比較不同提供者的 STT 模型在準確度、延遲與成本上的表現。",
        home_desc_tts_benchmark: "比較 TTS 語音的延遲與實時因子，並保留產生的音訊供聆聽檢視。",
        home_stats_uc1: "UC1",
        home_stats_uc2: "UC2",
        home_stats_uc3: "UC3",
        home_stats_benchmark: "基準測試",
        home_section_cases: "使用案例",
        home_section_cases_desc: "點擊左側的使用案例，查看它的功能及使用的語音方法。",
        home_card_btn: "打開頁面",
        vm_title: "預設語音方法",
        vm_stt: "STT · 語音轉文字",
        vm_tts: "TTS · 文字轉語音",
        vm_improve: "可改善方式",
        vm_stt_skills: "短語清單、自訂語音（微調）、地區/語言、轉錄後修正",
        vm_tts_skills: "神經/HD 語音、SSML 風格與韻律、自訂/個人語音、地區設定",
        // UC1 page
        uc1_eyebrow: "UC1 頁面",
        uc1_h2: "使用批量處理進行品質保證轉錄",
        uc1_what_does: "此使用案例的作用",
        uc1_recommended: "建議在以下情況使用",
        uc1_rec_1: "您想要具有說話者識別的批量 QA 報告。",
        uc1_rec_2: "您需要為產品名稱和客服術語進行短語提升。",
        uc1_rec_3: "您想要繁體中文與混合英文的最安全預設。",
        // UC2 page
        uc2_eyebrow: "UC2 頁面",
        uc2_h2: "實時呼叫中心協助",
        uc2_what_does: "此使用案例的作用",
        uc2_rec_1: "您想要在通話期間獲得實時客服指導。",
        uc2_rec_2: "您想要清楚地在 UI 中顯示 STT 模式和 LLM 模式。",
        uc2_rec_3: "您想要比較瀏覽器 STT、Azure Speech 或 Voice Live 標籤。",
        uc2_recommended: "建議在以下情況使用",
        uc2_btn_live: "打開實時主控台",
        uc2_btn_back: "返回 UC2 頁面",
        // Benchmark page
        bench_eyebrow: "基準測試頁面",
        bench_h2: "在一個地方運行基準測試並檢查所有執行。",
        bench_lead: "選擇本地源資料夾和一個或多個 STT 方法，以直接從此頁面運行基準測試。 reports/stt_benchmarks 下的現有運行歷史列在下方。",
        bench_source_path: "源路徑（WAV 檔案或資料夾）",
        bench_reference_dataset: "參考數據集 JSONL（可選）",
        bench_stt_methods: "STT 方法（多選）",
        bench_btn_run: "運行基準測試",
        bench_btn_script: "打開運行指令碼指南",
        bench_btn_home: "返回首頁",
        bench_btn_delete: "刪除舊報告",
        bench_latest_rec: "最新建議",
        bench_no_rec: "尚無建議。",
        bench_latest_run: "最新運行",
        bench_none: "無",
        bench_source_preview: "源音訊預覽",
        bench_source_preview_desc: "下一個基準測試運行將包括這些檔案。",
        bench_table_file: "檔案",
        bench_table_path: "路徑",
        bench_table_duration: "時長",
        bench_table_size: "大小",
        bench_table_play: "播放",
        bench_latest: "最新基準測試",
        bench_latest_desc: "來自最近運行的提供者平均值。",
        bench_cost_estimate: "成本估計",
        bench_why_matters: "為什麼這很重要",
        bench_why_1: "使用 WER 和 CER 比較轉錄的正確性。",
        bench_why_2: "使用延遲來決定模型是否適合實時助手流。",
        bench_why_3: "使用成本表將生產選擇與僅研究選項分開。",
        bench_history: "基準測試歷史",
        bench_history_desc: "每個運行都包括解析的提供者表加上摘要摘錄。",
        bench_table_provider: "提供者",
        bench_table_samples: "樣本數",
        bench_table_wer: "WER",
        bench_table_cer: "CER",
        bench_table_recall: "關鍵詞回憶率",
        bench_table_confidence: "信心度",
        bench_table_latency: "延遲（毫秒）",
        bench_table_cost: "估計成本",
        bench_status: "運行狀態",
        bench_summary_excerpt: "摘要摘錄",
        bench_run_summary: "摘要",
        bench_no_runs: "尚未找到基準測試運行。",
        bench_no_audio: "在選定的路徑中找不到音訊檔案。",
        // UC3 page + shared use-case detail
        uc3_eyebrow: "UC3 頁面",
        uc3_h2: "自動語音通話（gpt-realtime + TTS）",
        uc3_what_does: "此使用案例的作用",
        uc1_lead: "離線批量 QA：將錄音通話轉換成含評分準則佐證與短語增強的評分 Markdown 報告。",
        uc2_lead: "實時協助：在通話中即時顯示下一步最佳行動、合規與答案卡片，同時追蹤權杖用量。",
        uc3_lead: "完全自動的 AI 語音代理，直接與來電者對話——聆聽、理解、以語音回覆，並將特定查詢轉交專家代理。",
        uc1_b1: "從 Blob 儲存體或本機檔案讀取音訊，並以 Azure Speech 轉錄。",
        uc1_b2: "套用短語清單增強與轉錄後修正以處理專業術語。",
        uc1_b3: "依評分準則規則為轉錄評分，並輸出 Markdown 與 JSON。",
        uc2_b1: "實時逐字稿視窗，附合規與下一步最佳行動卡片。",
        uc2_b2: "從下方按鈕打開實時控制台以體驗完整助手。",
        uc2_b3: "回報 STT 模式、LLM 模式、權杖用量與通話音訊時長。",
        uc3_b1: "語音對語音：AI 代理即時直接與來電者對話。",
        uc3_b2: "打開語音通話並對著麥克風說話。",
        uc3_b3: "特定查詢會轉交專家代理，再以 TTS 語音回覆。",
        btn_open_live: "打開實時控制台",
        btn_open_voice: "打開語音通話",
        btn_open_benchmark: "打開基準測試頁面",
        btn_open_bench_details: "打開基準測試詳情",
        btn_run_matrix: "執行矩陣腳本",
        btn_open_tts: "打開 TTS 基準測試",
        btn_run_quality: "執行品質檢查",
        btn_open_stt: "打開 STT 基準測試",
        uc1_improve: "短語清單、自訂語音（微調）、地區/語言、轉錄後修正",
        uc2_improve: "STT 短語清單與地區、代理指示/提示、LLM 模型選擇、逐字稿視窗大小",
        uc3_improve: "語音選擇、轉錄模型（azure-speech / mai-transcribe-1 / gpt-4o-transcribe）、專家代理、VAD 與插話調校",
        // UC1 run page
        uc1p_eyebrow: "UC1 品質檢查",
        uc1p_h2: "在此頁面執行品質檢查並檢視結果。",
        uc1p_lead: "可變更本次執行的本機來源路徑與 STT 方法。工作完成後，報告摘要與各通話結果會顯示於下方。",
        uc1p_source_mode: "來源模式",
        uc1p_source_path: "來源路徑",
        uc1p_stt: "STT",
        uc1p_label_source: "來源路徑（檔案或資料夾）",
        uc1p_label_stt: "STT 方法",
        uc1p_btn_run: "執行品質檢查",
        uc1p_btn_list: "列出檔案",
        uc1p_select: "選擇",
        uc1p_what: "此頁面的作用",
        uc1p_w1: "顯示 UC1 將從選定來源路徑處理的每個本機音訊檔案。",
        uc1p_w2: "執行語音辨識、評分準則評分與 Markdown 報告產生。",
        uc1p_w3: "在頁面上顯示執行狀態、通過/失敗數、權杖用量與報告路徑。",
        uc1p_preview: "來源音訊預覽",
        uc1p_preview_desc: "選擇要檢查的檔案，使用播放器試聽，然後執行品質檢查。",
        // TTS benchmark page
        tts_eyebrow: "TTS 基準測試頁面",
        tts_h2: "在一處比較文字轉語音的語音。",
        tts_lead: "在 Voice Live（gpt-realtime）、MAI-Voice-2 與 Azure 神經語音之間進行 TTS 延遲/效能基準測試。產生的音訊會保留以供聆聽檢視。",
        tts_label_dataset: "資料集 JSONL（sample_id、text、language?）",
        tts_providers: "TTS 提供者（可多選）",
        tts_parallel: "並行執行提供者",
        tts_btn_run: "執行 TTS 基準測試",
        tts_latest: "最新執行",
        tts_tip1: "首次音訊時間與實時因子越低越好。",
        tts_tip2: "實時因子 < 1.0 表示比實時更快。",
        tts_tip3: "自然度不會自動評分——請聆聽 WAV 檔案。",
        tts_section_latest: "最新 TTS 基準測試",
        tts_section_latest_desc: "來自最近一次執行的提供者平均值。",
        tts_history: "TTS 基準測試歷史",
        tts_history_desc: "每次執行都包含解析後的提供者表格及摘要摘錄。",
        tts_th_provider: "提供者",
        tts_th_samples: "樣本數",
        tts_th_success: "成功",
        tts_th_ttfa: "首次音訊時間（毫秒）",
        tts_th_synth: "總合成時間（毫秒）",
        tts_th_dur: "音訊時長（毫秒）",
        tts_th_rtf: "實時因子",
        tts_run_result: "執行結果",
        tts_audio_suffix: "產生的音訊",
        tts_th_sample: "樣本",
        // Common
        voice_model: "語音模型",
        provider: "提供者",
        route: "路由",
        phrase_list: "短語列表",
        languages: "語言",
        voice_input: "語音輸入路徑",
        config_title: "設定",
        footer: "技術支援：Microsoft Innovation Hub"
      }}
    }};
    
    let currentLang = localStorage.getItem('voicecall-lang') || 'en';
    
    function setLanguage(lang) {{
      if (!i18n[lang]) lang = 'en';
      currentLang = lang;
      localStorage.setItem('voicecall-lang', lang);
      
      // Update button states
      document.getElementById('langBtnEn').classList.toggle('active', lang === 'en');
      document.getElementById('langBtnZh').classList.toggle('active', lang === 'zh');
      
      // Update nav links
      const navLinks = document.querySelectorAll('.nav-link');
      const navOrder = ['home', 'uc1', 'uc2', 'uc3', 'benchmark', 'ttsbenchmark'];
      navLinks.forEach((link, idx) => {{
        if (navOrder[idx]) link.textContent = i18n[lang][navOrder[idx]];
      }});
      
      // Update all elements with data-i18n attribute
      document.querySelectorAll('[data-i18n]').forEach(el => {{
        const key = el.dataset.i18n;
        if (i18n[lang][key]) {{
          if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {{
            el.placeholder = i18n[lang][key];
          }} else if (el.tagName === 'LABEL') {{
            el.textContent = i18n[lang][key];
          }} else {{
            el.innerHTML = i18n[lang][key];
          }}
        }}
      }});
      
      // Update all elements with data-i18n-text attribute (for text nodes)
      document.querySelectorAll('[data-i18n-text]').forEach(el => {{
        const key = el.dataset.i18nText;
        if (i18n[lang][key]) {{
          el.textContent = i18n[lang][key];
        }}
      }});
    }}
    
    // Update STT method display from config
    function updateSttMethod() {{
      const sttLabel = document.getElementById('sttMethodLabel');
      if (!sttLabel) return;
      // Get from body data attribute
      const sttValue = document.body.dataset.sttMethod || 'Configured';
      sttLabel.textContent = sttValue;
    }}
    
    // Language button event listeners
    document.getElementById('langBtnEn').addEventListener('click', () => setLanguage('en'));
    document.getElementById('langBtnZh').addEventListener('click', () => setLanguage('zh'));
    
    // Initialize
    setLanguage(currentLang);
    updateSttMethod();
  </script>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────────────────────
# Page renderers
# ──────────────────────────────────────────────────────────────────────────────


def _home_page() -> str:
    cfg = _current_config()

    # Voice method shown per use case: UC1/UC2 reflect the configured STT provider;
    # the others advertise their fixed method from the catalog card.
    method_by_id = {
        "uc1": cfg["uc1_provider_label"],
        "uc2": cfg["uc2_provider_label"],
    }

    def _key(cid: str) -> str:
        return cid.replace("-", "_")

    nav_buttons = "".join(
        f'<button type="button" class="uc-nav-btn{" active" if idx == 0 else ""}" '
        f'data-uc="{card.id}" onclick="selectUseCase(\'{card.id}\')" '
        f'data-i18n-text="home_name_{_key(card.id)}">{escape(_HOME_NAME_EN.get(card.id, card.short_name))}</button>'
        for idx, card in enumerate(_USE_CASE_CARDS)
    )

    def _detail_block(card: UseCaseCard, idx: int) -> str:
        method = method_by_id.get(card.id, card.voice_model)
        actions = "".join(
            f'<a class="btn{" primary" if i == 0 else ""}" href="{href}"'
            + (f' data-i18n-text="{_ACTION_LABEL_KEYS[label]}"' if label in _ACTION_LABEL_KEYS else "")
            + f">{escape(label)}</a>"
            for i, (label, href) in enumerate(card.actions)
        ) or f'<a class="btn primary" href="{card.route}">Open page</a>'
        hidden = "" if idx == 0 else " hidden"
        return f"""
        <article class="card uc-detail" id="detail-{card.id}"{hidden}>
          <div class="eyebrow">{escape(card.short_name)}</div>
          <h4 data-i18n-text="home_name_{_key(card.id)}">{escape(_HOME_NAME_EN.get(card.id, card.name))}</h4>
          <p data-i18n="home_desc_{_key(card.id)}">{escape(_HOME_DESC_EN.get(card.id, card.summary))}</p>
          <div class="chip-row" style="margin-top:8px;">
            <span class="chip"><strong data-i18n-text="home_method">Voice method</strong> {escape(method)}</span>
          </div>
          <div class="cta-row">{actions}</div>
        </article>
        """

    detail_blocks = "".join(_detail_block(card, idx) for idx, card in enumerate(_USE_CASE_CARDS))

    stt_default = cfg["uc1_provider_label"]
    tts_voice = (
        os.getenv("AZURE_VOICELIVE_TTS_VOICE")
        or os.getenv("AZURE_SPEECH_TTS_VOICE")
        or "zh-TW-HsiaoChenNeural"
    ).strip()

    body = f"""
    <section class="hero">
      <div class="hero-grid">
        <div>
          <span class="eyebrow" data-i18n-text="home_eyebrow">Call center Voice AI practices</span>
          <h2 data-i18n="home_h2">Explore real-world Voice AI scenarios for modern contact centers</h2>
          <p class="lead" data-i18n="home_lead">
            Evaluate how different Voice AI approaches perform across common call center use cases—from post-call
            quality analysis and real-time agent assistance to fully automated voice interactions.
          </p>
        </div>
        <div class="panel voice-methods">
          <h4 data-i18n-text="vm_title">Default voice methods</h4>
          <div class="vm-block">
            <div class="vm-k" data-i18n-text="vm_stt">STT · speech-to-text</div>
            <div class="vm-v">{escape(stt_default)}</div>
            <div class="vm-tips"><strong data-i18n-text="vm_improve">Improve with</strong>: <span data-i18n-text="vm_stt_skills">phrase list, custom speech (fine-tuning), locale/language, post-STT corrections</span></div>
          </div>
          <div class="vm-block">
            <div class="vm-k" data-i18n-text="vm_tts">TTS · text-to-speech</div>
            <div class="vm-v">{escape(tts_voice)}</div>
            <div class="vm-tips"><strong data-i18n-text="vm_improve">Improve with</strong>: <span data-i18n-text="vm_tts_skills">neural/HD voice, SSML style &amp; prosody, custom/personal voice, locale</span></div>
          </div>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <div>
          <h3 data-i18n-text="home_section_cases">Use cases</h3>
          <p data-i18n="home_section_cases_desc">Click a use case on the left to see what it does and which voice method it uses.</p>
        </div>
      </div>
      <div class="home-explorer">
        <div class="panel home-explorer-nav">
          <h4 data-i18n-text="home_open_label">Choose a use case</h4>
          <div class="home-nav-list">
            {nav_buttons}
          </div>
        </div>
        <div class="home-explorer-detail">
          {detail_blocks}
        </div>
      </div>
    </section>

    <style>
      .home-explorer {{ display: grid; grid-template-columns: minmax(230px, 280px) 1fr; gap: 18px; align-items: stretch; }}
      .home-explorer-nav {{ display: flex; flex-direction: column; }}
      .home-explorer-nav h4 {{ margin: 0 0 4px; font-size: 1.15rem; }}
      .home-nav-list {{ display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }}
      .uc-nav-btn {{
        width: 100%; text-align: left; padding: 15px 18px; border-radius: 14px;
        border: 1px solid var(--border); background: var(--surface-strong); color: var(--text);
        cursor: pointer; font-weight: 700; font-family: inherit; font-size: 1.05rem;
        transition: transform .15s ease, filter .15s ease;
      }}
      .uc-nav-btn:hover {{ transform: translateY(-1px); filter: brightness(1.08); }}
      .uc-nav-btn.active {{ background: var(--accent-soft); border-color: var(--accent); }}
      .home-explorer-detail {{ display: flex; flex-direction: column; }}
      .home-explorer-detail .uc-detail {{ height: 100%; }}
      .uc-detail h4 {{ font-size: 1.5rem; }}
      .uc-detail p {{ font-size: 1.12rem; }}
      .voice-methods h4 {{ margin: 0 0 6px; }}
      .voice-methods .vm-block {{ padding: 14px 0; border-top: 1px solid var(--border); }}
      .voice-methods .vm-block:first-of-type {{ border-top: none; }}
      .voice-methods .vm-k {{ font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent); font-weight: 800; }}
      .voice-methods .vm-v {{ margin-top: 6px; font-size: 1.15rem; font-weight: 800; }}
      .voice-methods .vm-tips {{ margin-top: 6px; color: var(--muted); font-size: 0.98rem; line-height: 1.5; }}
      @media (max-width: 780px) {{ .home-explorer {{ grid-template-columns: 1fr; }} }}
    </style>

    <script>
      function selectUseCase(id) {{
        document.querySelectorAll('.uc-detail').forEach(function (el) {{
          el.hidden = (el.id !== 'detail-' + id);
        }});
        document.querySelectorAll('.uc-nav-btn').forEach(function (b) {{
          b.classList.toggle('active', b.dataset.uc === id);
        }});
      }}
    </script>
    """
    return _page_shell(_DASHBOARD_TITLE, "home", body, "")


def _use_case_page(card: UseCaseCard) -> str:
    cfg = _current_config()
    if card.id == "uc1":
        provider = cfg["uc1_provider_label"]
    elif card.id == "uc2":
        provider = cfg["uc2_provider_label"]
    elif card.id == "uc3":
        provider = card.voice_model
    else:
        provider = ", ".join(cfg["benchmark_default_providers"])

    bullets_en = {
        "uc1": [
            "Reads audio from Blob Storage or local files and transcribes with Azure Speech.",
            "Applies phrase-list boosting and post-STT corrections for domain terms.",
            "Scores the transcript against rubric rules and writes Markdown + JSON.",
        ],
        "uc2": [
            "Live transcript window with compliance and next-best-action cards.",
            "Open the live console to exercise the full assistant.",
            "Reports STT mode, LLM mode, token usage, and call audio duration.",
        ],
        "uc3": [
            "Speech-to-speech: the AI agent talks directly to the caller in real time.",
            "Open the voice call and speak into your microphone.",
            "Specific inquiries route to billing, IT, or expert agents, then are spoken back as TTS.",
        ],
    }.get(card.id, [])
    lead_en = {
        "uc1": "Offline batch QA: turn recorded calls into scored Markdown reports with rubric evidence and phrase boosting.",
        "uc2": "Live coaching: surface next-best-action, compliance, and answer cards in real time while tracking token usage.",
        "uc3": "A fully automated AI voice agent that talks to the caller — it listens, understands, replies in voice, and escalates specific inquiries to billing, IT, or expert agents.",
    }.get(card.id, card.value)

    details_html = "".join(
        f'<li data-i18n-text="{card.id}_b{index}">{escape(text)}</li>'
        for index, text in enumerate(bullets_en, start=1)
    )

    improve_en = {
        "uc1": "phrase list, custom speech (fine-tuning), locale/language, post-STT corrections",
        "uc2": "STT phrase list & locale, agent instructions/prompt, LLM model choice, transcript window size",
        "uc3": "voice selection, transcription model (azure-speech / mai-transcribe-1 / gpt-4o-transcribe), expert agent, VAD & barge-in tuning",
    }.get(card.id, "")
    improve_html = (
        '<div class="chip-row" style="margin-top:12px;">'
        '<span class="chip"><strong data-i18n-text="vm_improve">Improve with</strong> '
        f'<span data-i18n-text="{card.id}_improve">{escape(improve_en)}</span></span></div>'
        if improve_en
        else ""
    )

    actions_html = "".join(
        f'<a class="btn{" primary" if index == 0 else ""}" href="{href}"'
        + (f' data-i18n-text="{_ACTION_LABEL_KEYS[label]}"' if label in _ACTION_LABEL_KEYS else "")
        + f">{escape(label)}</a>"
        for index, (label, href) in enumerate(card.actions)
    )

    body = f"""
    <section class="hero">
      <div class="hero-grid">
        <div>
          <span class="eyebrow" data-i18n-text="{card.id}_eyebrow">{escape(card.short_name)} page</span>
          <h2 data-i18n-text="{card.id}_h2">{escape(card.name)}</h2>
          <p class="lead" data-i18n="{card.id}_lead">{escape(lead_en)}</p>
          <div class="chip-row">
            <span class="chip"><strong data-i18n-text="voice_model">Voice model</strong> {escape(provider)}</span>
            <span class="chip"><strong data-i18n-text="route">Route</strong> {escape(card.route)}</span>
          </div>
          <div class="cta-row">{actions_html}</div>
        </div>
        <div class="panel">
          <h4 data-i18n-text="{card.id}_what_does">What this use case does</h4>
          <ul class="detail-list">{details_html}</ul>
          {improve_html}
        </div>
      </div>
    </section>
    """
    if card.id == "uc1":
        stt_label = cfg["uc1_provider_label"]
    elif card.id == "uc2":
        stt_label = cfg["uc2_provider_label"]
    elif card.id == "uc3":
        stt_label = "Voice Live (gpt-realtime)"
    else:
        stt_label = cfg["benchmark_default_providers"][0] if cfg["benchmark_default_providers"] else "Configured"
    return _page_shell(card.name, card.id, body, stt_label)


def _benchmark_page(
    message: str | None = None,
    run_summary: BenchmarkRunSummary | None = None,
    source_path_override: str | None = None,
  reference_dataset_override: str | None = None,
    selected_providers_override: list[str] | None = None,
    selected_wavs_override: list[str] | None = None,
) -> str:
    cfg = _current_config()
    overview = _benchmark_overview()
    runs: list[BenchmarkRun] = overview["runs"]
    latest = overview["latest"]
    selected_source_path = (source_path_override or "data/benchmark_audio").strip()
    selected_reference_dataset = (reference_dataset_override or _default_benchmark_reference_dataset()).strip()
    selected_providers = selected_providers_override or list(cfg["benchmark_default_providers"])
    provider_ids = list(_BENCHMARK_SUPPORTED_PROVIDERS)
    for provider_id in selected_providers:
        if provider_id and provider_id not in provider_ids:
            provider_ids.append(provider_id)

    source_items = _benchmark_source_audio_items(selected_source_path)
    # WAV multi-select: default to all files checked; preserve the user's choice on re-render.
    if selected_wavs_override is not None:
        selected_wav_set = {p for p in selected_wavs_override if p}
    else:
        selected_wav_set = {item.path for item in source_items}
    wav_checkboxes = "".join(
        f"<label style=\"display:inline-flex; align-items:center; gap:8px; margin:4px 12px 4px 0;\">"
        f"<input type=\"checkbox\" name=\"selected_wavs\" value=\"{escape(item.path, quote=True)}\"{' checked' if item.path in selected_wav_set else ''} />"
        f"<span>{escape(item.name)}</span>"
        "</label>"
        for item in source_items
    ) or "<span class='muted'>No audio files found in the selected path.</span>"
    source_rows = "".join(
      f"<tr>"
      f"<td>{escape(item.name)}</td>"
      f"<td>{escape(item.path)}</td>"
      f"<td>{escape(_format_seconds(item.duration_seconds))}</td>"
      f"<td>{escape(_human_size(item.size_bytes))}</td>"
      f"<td><audio class='preview-player' controls preload='none' src='/api/audio/preview?path={escape(quote(item.path, safe=''), quote=True)}'></audio></td>"
      f"</tr>"
      for item in source_items
    ) or "<tr><td colspan='5' class='muted'>No audio files found in the selected path.</td></tr>"

    provider_checkboxes = "".join(
        "<label style=\"display:flex; align-items:flex-start; gap:10px; padding:8px 11px; "
        "border:1px solid rgba(255,255,255,.09); border-radius:10px; margin:6px 0; cursor:pointer;\">"
        f"<input type=\"checkbox\" name=\"providers\" value=\"{escape(provider_id)}\"{' checked' if provider_id in selected_providers else ''} style=\"margin-top:4px;\" />"
        "<span style=\"display:flex; flex-direction:column; gap:3px; min-width:0;\">"
        f"<span style=\"font-weight:600;\">{escape(provider_to_display_label(provider_id))} {_phrase_list_pill(provider_id)}</span>"
        f"<span style=\"font-size:.76em; color:#8b8b9a; font-family:ui-monospace,SFMono-Regular,Menlo,monospace;\">{escape(provider_id)}</span>"
        "</span>"
        "</label>"
        for provider_id in provider_ids
    )

    message_html = ""
    if message:
        message_html = f"""
        <section class="section">
          <div class="panel">
            <h4>Run status</h4>
            <div class="summary-box">{escape(message)}</div>
          </div>
        </section>
        """

    run_result_html = _benchmark_run_result_html(run_summary)

    latest_table_html = "<p class='muted'>No benchmark runs found yet.</p>"
    latest_cost_html = ""
    latest_recommendation = ""
    if latest:
        rows = _benchmark_provider_rows_html(latest.providers, colspan=10, with_details=False)
        latest_table_html = f"""
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Provider</th><th>Samples</th><th>WER</th><th>CER</th><th>Keyword Recall</th><th>Confidence</th><th>Corr WER</th><th>Corr CER</th><th>Corr Confidence</th><th>Latency (ms)</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        """
        if latest.cost_rows:
            cost_rows = "".join(
                f"<tr><td>{escape(row['provider'])}</td><td>{escape(row['cost'])}</td></tr>"
                for row in latest.cost_rows
            )
            latest_cost_html = f"""
            <div class="panel">
              <h4>Cost estimate</h4>
              <div class="table-wrap">
                <table>
                  <thead><tr><th>Provider</th><th>Estimated cost</th></tr></thead>
                  <tbody>{cost_rows}</tbody>
                </table>
              </div>
            </div>
            """
        latest_recommendation = latest.recommendation or ""

    run_cards = []
    for run in runs:
        run_table = "<p class='muted'>No parsed provider rows found.</p>"
        if run.providers:
            run_rows = _benchmark_provider_rows_html(run.providers, colspan=10, with_details=False)
            run_table = f"""
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Provider</th><th>Samples</th><th>WER</th><th>CER</th><th>Keyword Recall</th><th>Confidence</th><th>Corr WER</th><th>Corr CER</th><th>Corr Confidence</th><th>Latency (ms)</th>
                  </tr>
                </thead>
                <tbody>{run_rows}</tbody>
              </table>
            </div>
            """
        cost_html = ""
        if run.cost_rows:
            cost_rows = "".join(
                f"<tr><td>{escape(row['provider'])}</td><td>{escape(row['cost'])}</td></tr>"
                for row in run.cost_rows
            )
            cost_html = f"""
            <div class="panel" style="margin-top: 12px;">
              <h4>Cost</h4>
              <div class="table-wrap">
                <table>
                  <thead><tr><th>Provider</th><th>Cost</th></tr></thead>
                  <tbody>{cost_rows}</tbody>
                </table>
              </div>
            </div>
            """
        snippet = escape(run.excerpt or "(no excerpt)")
        run_cards.append(
            f"""
            <article class="card">
              <div class="chip-row">
                <span class="chip"><strong>Run</strong> {escape(run.run_id)}</span>
                <span class="chip"><strong>Summary</strong> {escape(run.summary_path.as_posix())}</span>
              </div>
              <div style="margin-top: 12px;">{run_table}</div>
              {cost_html}
              <div class="panel" style="margin-top: 12px;">
                <h4>Summary excerpt</h4>
                <div class="summary-box">{snippet}</div>
              </div>
            </article>
            """
        )

    run_cards_html = "".join(run_cards) if run_cards else "<p class='muted'>No benchmark runs available yet.</p>"

    body = f"""
    <section class="hero">
      <div class="hero-grid">
        <div>
          <span class="eyebrow" data-i18n-text="bench_eyebrow">Benchmark page</span>
          <h2 data-i18n="bench_h2">Run benchmark and inspect all runs in one place.</h2>
          <p class="lead" data-i18n="bench_lead">
            Select a local source folder and one or more STT methods to run benchmark directly from this page.
            Existing run history under <code>reports/stt_benchmarks</code> is listed below.
          </p>
          <form method="post" action="/benchmark/run" style="margin-top:12px;">
            <label for="benchmark_source_path" data-i18n-text="bench_source_path">Source path (WAV file or folder)</label>
            <input id="benchmark_source_path" name="source_path" type="text" value="{escape(selected_source_path)}" placeholder="e.g. data/benchmark_audio" style="width:100%; margin-top:6px;" />
            <label for="benchmark_reference_dataset" style="margin-top:10px; display:block;" data-i18n-text="bench_reference_dataset">Reference dataset JSONL (optional)</label>
            <input id="benchmark_reference_dataset" name="reference_dataset_path" type="text" value="{escape(selected_reference_dataset)}" placeholder="e.g. data/stt_benchmark.jsonl" style="width:100%; margin-top:6px;" />
            <div class="panel" style="margin-top:12px;">
              <h4 style="margin-top:0;" data-i18n-text="bench_stt_methods">STT methods (multi-select)</h4>
              <div>{provider_checkboxes}</div>
            </div>
            <div class="panel" style="margin-top:12px;">
              <h4 style="margin-top:0;" data-i18n-text="bench_wav_files">WAV files to compare (multi-select)</h4>
              <div>{wav_checkboxes}</div>
            </div>
            <div class="cta-row">
              <button class="btn primary" type="submit" data-i18n-text="bench_btn_run">Run benchmark</button>
              <a class="btn" href="/benchmark/script" data-i18n-text="bench_btn_script">Open run script guide</a>
            </div>
          </form>
          <form method="post" action="/benchmark/delete-reports" style="margin-top:8px;" onsubmit="return confirm('Delete ALL existing STT benchmark reports under reports/stt_benchmarks? This cannot be undone.');">
            <button class="btn" type="submit" style="border-color:rgba(239,68,68,.55); color:#fca5a5;" data-i18n-text="bench_btn_delete">Delete old reports</button>
          </form>
        </div>
        <div class="panel">
          <h4 data-i18n-text="bench_latest_rec">Latest recommendation</h4>
          <div class="summary-box">{escape(latest_recommendation or 'No recommendation yet.')}</div>
          <div style="margin-top: 12px;" class="muted">Latest run: {escape(latest.run_id if latest else 'none')}</div>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <div>
          <h3 data-i18n-text="bench_source_preview">Source audio preview</h3>
          <p data-i18n="bench_source_preview_desc">These files will be included in the next benchmark run.</p>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th data-i18n-text="bench_table_file">File</th><th data-i18n-text="bench_table_path">Path</th><th data-i18n-text="bench_table_duration">Duration</th><th data-i18n-text="bench_table_size">Size</th><th data-i18n-text="bench_table_play">Play</th></tr>
          </thead>
          <tbody>{source_rows}</tbody>
        </table>
      </div>
    </section>

    {message_html}
    {run_result_html}

    <section class="section">
      <div class="section-head">
        <div>
          <h3 data-i18n-text="bench_latest">Latest benchmark</h3>
          <p data-i18n="bench_latest_desc">Provider averages from the most recent run.</p>
        </div>
      </div>
      {latest_table_html}
    </section>

    <section class="section split">
      {latest_cost_html}
      <div class="panel">
        <h4 data-i18n-text="bench_why_matters">Why this matters</h4>
        <ul class="detail-list">
          <li data-i18n-text="bench_why_1">Use WER and CER to compare transcription correctness.</li>
          <li data-i18n-text="bench_why_2">Use latency to decide whether a model is suitable for real-time assistant flows.</li>
          <li data-i18n-text="bench_why_3">Use the cost table to separate production choices from research-only options.</li>
        </ul>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <div>
          <h3 data-i18n-text="bench_history">Benchmark history</h3>
          <p data-i18n="bench_history_desc">Each run includes the parsed provider table plus the summary excerpt.</p>
        </div>
      </div>
      <div class="grid">{run_cards_html}</div>
    </section>
    """
    benchmark_stt = cfg["benchmark_default_providers"][0] if cfg["benchmark_default_providers"] else "Configured"
    return _page_shell("Benchmark", "benchmark", body, benchmark_stt)


async def _home(_: Request) -> HTMLResponse:
    return HTMLResponse(_home_page())


async def _uc1(_: Request) -> HTMLResponse:
  return HTMLResponse(_uc1_page())


async def _uc1_run(request: Request) -> HTMLResponse:
  source_path: str | None = None
  stt_provider: str | None = None
  run_summary: Uc1RunSummary | None = None

  try:
    form = await request.form()
    source_path_raw = str(form.get("source_path") or "").strip()
    run_target_raw = str(form.get("run_target") or "").strip()
    stt_provider_raw = str(form.get("stt_provider") or "").strip()
    source_path = source_path_raw or None
    stt_provider = stt_provider_raw or None
    # Prefer the file the user selected in the list; fall back to the typed path.
    run_target = run_target_raw or source_path

    run_summary = await run_uc1(
      source_path_override=run_target,
      stt_provider_override=stt_provider,
    )

    if run_summary.exit_code == 0:
      message = "UC1 quality check completed successfully. Results are shown below."
    elif run_summary.exit_code == 1:
      message = run_summary.message or "No input audio found for this source path."
    else:
      message = run_summary.message or "UC1 quality check finished with errors."
  except Exception as exc:
    message = f"UC1 quality check failed: {exc}\n\n{traceback.format_exc()}"

  return HTMLResponse(
    _uc1_page(
      message=message,
      run_summary=run_summary,
      source_path_override=source_path,
      stt_provider_override=stt_provider,
    )
  )


async def _uc1_list(request: Request) -> HTMLResponse:
  source_path: str | None = None
  stt_provider: str | None = None
  try:
    form = await request.form()
    source_path = str(form.get("source_path") or "").strip() or None
    stt_provider = str(form.get("stt_provider") or "").strip() or None
    message = None
  except Exception as exc:
    message = f"Could not list files: {exc}"

  return HTMLResponse(
    _uc1_page(
      message=message,
      source_path_override=source_path,
      stt_provider_override=stt_provider,
    )
  )



async def _uc2(_: Request) -> HTMLResponse:
    return HTMLResponse(_use_case_page(_USE_CASE_CARDS[1]))


async def _uc3(_: Request) -> HTMLResponse:
    return HTMLResponse(_use_case_page(_USE_CASE_CARDS[2]))


async def _benchmark(_: Request) -> HTMLResponse:
    return HTMLResponse(_benchmark_page())


# ──────────────────────────────────────────────────────────────────────────────
# TTS benchmark (dashboard)
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class TtsBenchmarkRun:
    run_id: str
    summary_path: Path
    providers: list[dict[str, Any]]
    excerpt: str


def _parse_tts_summary_rows(content: str) -> list[dict[str, Any]]:
    """Parse the provider table out of a TTS benchmark summary.md."""
    rows: list[dict[str, Any]] = []
    in_table = False

    def _num(value: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    for line in content.splitlines():
        if line.startswith("| Provider ") and "Time-to-First-Audio" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---") or line.startswith("| ---"):
            continue
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 8:
            continue
        rows.append(
            {
                "provider": cells[0],
                "samples": cells[1],
                "success": cells[2],
                "avg_char_count": _num(cells[3]),
                "avg_time_to_first_audio_ms": _num(cells[4]),
                "avg_total_synthesis_ms": _num(cells[5]),
                "avg_audio_duration_ms": _num(cells[6]),
                "avg_real_time_factor": _num(cells[7]),
            }
        )
    return rows


def _scan_tts_benchmark_runs(root: Path = _TTS_BENCHMARK_ROOT) -> list[TtsBenchmarkRun]:
    if not root.exists():
        return []
    runs: list[TtsBenchmarkRun] = []
    for run_dir in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        summary_path = run_dir / "summary.md"
        if not summary_path.exists():
            continue
        content = summary_path.read_text(encoding="utf-8")
        excerpt = "\n".join(content.splitlines()[:12]).strip()
        runs.append(
            TtsBenchmarkRun(
                run_id=run_dir.name,
                summary_path=summary_path,
                providers=_parse_tts_summary_rows(content),
                excerpt=excerpt,
            )
        )
    return runs


def _tts_run_audio_items(run_dir: Path) -> dict[str, list[Uc1AudioItem]]:
    """Map each provider folder in a run to its generated WAV artifacts."""
    result: dict[str, list[Uc1AudioItem]] = {}
    if not run_dir.exists():
        return result
    for provider_dir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
        wavs: list[Uc1AudioItem] = []
        for wav in sorted(provider_dir.glob("*.wav")):
            wavs.append(
                Uc1AudioItem(
                    path=str(wav),
                    name=wav.name,
                    duration_seconds=_wav_duration(wav),
                    size_bytes=wav.stat().st_size if wav.exists() else None,
                )
            )
        if wavs:
            result[provider_dir.name] = wavs
    return result


def _run_tts_benchmark_from_dataset(
    dataset_path: str, provider_ids: list[str], parallel: bool
) -> str:
    providers = [build_tts_provider(provider_id) for provider_id in provider_ids]
    samples = parse_tts_dataset(Path(dataset_path))
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = _TTS_BENCHMARK_ROOT / run_id
    max_workers = len(providers) if parallel else 1
    run_tts_benchmark(
        providers=providers,
        samples=samples,
        output_dir=output_dir,
        max_workers=max_workers,
    )
    return run_id


def _tts_provider_table_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='muted'>No parsed provider rows found.</p>"
    body_rows = "".join(
        "<tr>"
        f"<td>{escape(str(row['provider']))}</td>"
        f"<td>{escape(str(row['samples']))}</td>"
        f"<td>{escape(str(row['success']))}</td>"
        f"<td>{row['avg_time_to_first_audio_ms']:.0f}</td>"
        f"<td>{row['avg_total_synthesis_ms']:.0f}</td>"
        f"<td>{row['avg_audio_duration_ms']:.0f}</td>"
        f"<td>{row['avg_real_time_factor']:.3f}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th data-i18n-text="tts_th_provider">Provider</th><th data-i18n-text="tts_th_samples">Samples</th><th data-i18n-text="tts_th_success">Success</th>
            <th data-i18n-text="tts_th_ttfa">Time-to-First-Audio (ms)</th><th data-i18n-text="tts_th_synth">Total Synthesis (ms)</th>
            <th data-i18n-text="tts_th_dur">Audio Duration (ms)</th><th data-i18n-text="tts_th_rtf">Real-Time Factor</th>
          </tr>
        </thead>
        <tbody>{body_rows}</tbody>
      </table>
    </div>
    """


def _tts_audio_players_html(run_id: str) -> str:
    audio_by_provider = _tts_run_audio_items(_TTS_BENCHMARK_ROOT / run_id)
    if not audio_by_provider:
        return ""
    blocks: list[str] = []
    for provider, items in audio_by_provider.items():
        rows = "".join(
            f"<tr><td>{escape(item.name)}</td>"
            f"<td>{escape(_format_seconds(item.duration_seconds))}</td>"
            f"<td><audio class='preview-player' controls preload='none' "
            f"src='/api/audio/preview?path={escape(quote(item.path, safe=''), quote=True)}'></audio></td></tr>"
            for item in items
        )
        blocks.append(
            f"""
            <div class="panel" style="margin-top:12px;">
              <h4>{escape(provider)} — <span data-i18n-text="tts_audio_suffix">generated audio</span></h4>
              <div class="table-wrap">
                <table>
                  <thead><tr><th data-i18n-text="tts_th_sample">Sample</th><th data-i18n-text="bench_table_duration">Duration</th><th data-i18n-text="bench_table_play">Play</th></tr></thead>
                  <tbody>{rows}</tbody>
                </table>
              </div>
            </div>
            """
        )
    return "".join(blocks)


def _tts_benchmark_page(
    message: str | None = None,
    run_id: str | None = None,
    dataset_override: str | None = None,
    selected_providers_override: list[str] | None = None,
) -> str:
    runs = _scan_tts_benchmark_runs()
    latest = runs[0] if runs else None
    selected_dataset = (dataset_override or _TTS_DEFAULT_DATASET).strip()
    selected_providers = selected_providers_override or list(_TTS_DEFAULT_PROVIDERS)

    provider_checkboxes = "".join(
        "<label style=\"display:inline-flex; align-items:center; gap:8px; margin:4px 12px 4px 0;\">"
        f"<input type=\"checkbox\" name=\"providers\" value=\"{escape(provider_id)}\""
        f"{' checked' if provider_id in selected_providers else ''} />"
        f"<span>{escape(provider_id)}</span>"
        "</label>"
        for provider_id in _TTS_SUPPORTED_PROVIDERS
    )

    message_html = ""
    if message:
        message_html = f"""
        <section class="section">
          <div class="panel"><h4 data-i18n-text="bench_status">Run status</h4><div class="summary-box">{escape(message)}</div></div>
        </section>
        """

    result_html = ""
    if run_id:
        result_run = next((r for r in runs if r.run_id == run_id), None)
        if result_run:
            result_html = f"""
            <section class="section">
              <div class="panel">
                <h4><span data-i18n-text="tts_run_result">Run result</span> — {escape(run_id)}</h4>
                {_tts_provider_table_html(result_run.providers)}
              </div>
              {_tts_audio_players_html(run_id)}
            </section>
            """

    latest_html = "<p class='muted'>No TTS benchmark runs found yet.</p>"
    if latest:
        latest_html = _tts_provider_table_html(latest.providers)

    run_cards = "".join(
        f"""
        <article class="card">
          <div class="chip-row">
            <span class="chip"><strong>Run</strong> {escape(run.run_id)}</span>
            <span class="chip"><strong>Summary</strong> {escape(run.summary_path.as_posix())}</span>
          </div>
          <div style="margin-top:12px;">{_tts_provider_table_html(run.providers)}</div>
          <div class="panel" style="margin-top:12px;">
            <h4>Summary excerpt</h4>
            <div class="summary-box">{escape(run.excerpt or '(no excerpt)')}</div>
          </div>
        </article>
        """
        for run in runs
    ) or "<p class='muted'>No TTS benchmark runs available yet.</p>"

    body = f"""
    <section class="hero">
      <div class="hero-grid">
        <div>
          <span class="eyebrow" data-i18n-text="tts_eyebrow">TTS benchmark page</span>
          <h2 data-i18n-text="tts_h2">Compare text-to-speech voices in one place.</h2>
          <p class="lead" data-i18n="tts_lead">
            Benchmark TTS latency/performance across Voice Live (gpt-realtime), MAI-Voice-2,
            and Azure neural voices. Generated audio is kept under
            <code>reports/tts_benchmarks</code> for listening review.
          </p>
          <form method="post" action="/tts-benchmark/run" style="margin-top:12px;">
            <label for="tts_dataset" data-i18n-text="tts_label_dataset">Dataset JSONL ({{sample_id, text, language?}})</label>
            <input id="tts_dataset" name="dataset" type="text" value="{escape(selected_dataset)}"
                   placeholder="e.g. data/tts_benchmark.template.jsonl" style="width:100%; margin-top:6px;" />
            <div class="panel" style="margin-top:12px;">
              <h4 style="margin-top:0;" data-i18n-text="tts_providers">TTS providers (multi-select)</h4>
              <div>{provider_checkboxes}</div>
              <label style="display:inline-flex; align-items:center; gap:8px; margin-top:10px;">
                <input type="checkbox" name="parallel" value="1" checked /> <span data-i18n-text="tts_parallel">Run providers in parallel</span>
              </label>
            </div>
            <div class="cta-row">
              <button class="btn primary" type="submit" data-i18n-text="tts_btn_run">Run TTS benchmark</button>
              <a class="btn" href="/" data-i18n-text="bench_btn_home">Back home</a>
            </div>
          </form>
        </div>
        <div class="panel">
          <h4 data-i18n-text="tts_latest">Latest run</h4>
          <div class="muted">{escape(latest.run_id if latest else 'none')}</div>
          <ul class="detail-list" style="margin-top:12px;">
            <li data-i18n-text="tts_tip1">Lower time-to-first-audio and real-time factor are better.</li>
            <li data-i18n-text="tts_tip2">Real-time factor &lt; 1.0 means faster than realtime.</li>
            <li data-i18n-text="tts_tip3">Naturalness is not auto-scored — listen to the WAVs.</li>
          </ul>
        </div>
      </div>
    </section>

    {message_html}
    {result_html}

    <section class="section">
      <div class="section-head"><div><h3 data-i18n-text="tts_section_latest">Latest TTS benchmark</h3>
        <p data-i18n="tts_section_latest_desc">Provider averages from the most recent run.</p></div></div>
      {latest_html}
    </section>

    <section class="section">
      <div class="section-head"><div><h3 data-i18n-text="tts_history">TTS benchmark history</h3>
        <p data-i18n="tts_history_desc">Each run includes the parsed provider table plus the summary excerpt.</p></div></div>
      <div class="grid">{run_cards}</div>
    </section>
    """
    return _page_shell("TTS Benchmark", "tts-benchmark", body, "Voice Live / MAI-Voice / Azure TTS")


async def _tts_benchmark(_: Request) -> HTMLResponse:
    return HTMLResponse(_tts_benchmark_page())


async def _tts_benchmark_run(request: Request) -> HTMLResponse:
    dataset = _TTS_DEFAULT_DATASET
    selected_providers: list[str] = []
    run_id: str | None = None
    try:
        form = await request.form()
        dataset = str(form.get("dataset") or _TTS_DEFAULT_DATASET).strip()
        parallel = bool(form.get("parallel"))
        selected_providers = [
            str(provider).strip()
            for provider in form.getlist("providers")
            if str(provider).strip()
        ]
        if not selected_providers:
            raise ValueError("Please select at least one TTS provider.")
        if not Path(dataset).exists():
            raise ValueError(f"Dataset not found: {dataset}")

        run_id = await asyncio.to_thread(
            _run_tts_benchmark_from_dataset, dataset, selected_providers, parallel
        )
        message = "TTS benchmark completed. Results and audio are shown below."
    except Exception as exc:  # noqa: BLE001 - surface run errors in the page
        message = f"TTS benchmark run failed: {exc}"

    return HTMLResponse(
        _tts_benchmark_page(
            message=message,
            run_id=run_id,
            dataset_override=dataset,
            selected_providers_override=selected_providers or None,
        )
    )


async def _benchmark_run(request: Request) -> HTMLResponse:
  source_path = ""
  reference_dataset_path = ""
  selected_providers: list[str] = []
  run_summary: BenchmarkRunSummary | None = None
  try:
    form = await request.form()
    source_path = str(form.get("source_path") or "").strip()
    reference_dataset_path = str(form.get("reference_dataset_path") or "").strip()
    if not reference_dataset_path:
      reference_dataset_path = _default_benchmark_reference_dataset()
    selected_providers = [
      str(provider).strip()
      for provider in form.getlist("providers")
      if str(provider).strip()
    ]
    selected_wavs = [
      str(wav).strip()
      for wav in form.getlist("selected_wavs")
      if str(wav).strip()
    ]

    if not source_path:
      raise ValueError("Please provide a WAV source path.")
    if not selected_providers:
      raise ValueError("Please select at least one STT method.")

    run_summary = await asyncio.to_thread(
      _run_benchmark_from_source,
      source_path,
      selected_providers,
      (reference_dataset_path or None),
      (selected_wavs or None),
    )
    message = "Benchmark completed. Summary and artifacts are shown below."
  except Exception as exc:
    message = f"Benchmark run failed: {exc}"

  return HTMLResponse(
    _benchmark_page(
      message=message,
      run_summary=run_summary,
      source_path_override=source_path,
      reference_dataset_override=reference_dataset_path,
      selected_providers_override=selected_providers,
      selected_wavs_override=(selected_wavs or None),
    )
  )


async def _benchmark_delete_reports(_: Request) -> HTMLResponse:
  """Delete all existing STT benchmark run reports under reports/stt_benchmarks."""
  deleted = 0
  errors: list[str] = []
  try:
    if _BENCHMARK_ROOT.exists():
      for child in _BENCHMARK_ROOT.iterdir():
        if child.name == ".gitkeep":
          continue
        try:
          if child.is_dir():
            shutil.rmtree(child)
          else:
            child.unlink()
          deleted += 1
        except Exception as exc:
          errors.append(f"{child.name}: {exc}")
    if errors:
      message = f"Deleted {deleted} report(s); some could not be removed: {'; '.join(errors)}"
    else:
      message = f"Deleted {deleted} old benchmark report(s) under reports/stt_benchmarks."
  except Exception as exc:
    message = f"Failed to delete reports: {exc}"

  return HTMLResponse(_benchmark_page(message=message))


async def _benchmark_script(_: Request) -> HTMLResponse:
    body = """
    <section class="hero">
      <div class="hero-grid">
        <div>
          <span class="eyebrow">Run guide</span>
          <h2>Benchmark script entrypoint</h2>
          <p class="lead">Use the matrix script to generate or refresh benchmark runs, then return here to inspect the results.</p>
          <div class="chip-row">
            <span class="chip"><strong>Config</strong> config/stt_config.toml</span>
            <span class="chip"><strong>Script</strong> start_stt_benchmark_matrix.ps1</span>
          </div>
          <div class="cta-row">
            <a class="btn primary" href="/benchmark">Back to benchmark</a>
            <a class="btn" href="/">Home</a>
          </div>
        </div>
          <div class="panel">
          <h4>Example</h4>
          <div class="summary-box">.\\start_stt_benchmark_matrix.ps1 -UseConfigDefaults -Parallel</div>
        </div>
      </div>
    </section>
    """
    return HTMLResponse(_page_shell("Benchmark script", "benchmark", body))


async def _uc2_live_unavailable(_: Request) -> HTMLResponse:
    body = """
    <section class="hero">
      <div class="hero-grid">
        <div>
          <span class="eyebrow">UC2 live console</span>
          <h2>Foundry runtime not configured yet</h2>
          <p class="lead">
            The live assistant page needs FOUNDRY_PROJECT_ENDPOINT or VOICE_ASSIST_PROJECT_ENDPOINT.
            You can still use the dashboard, UC1 pages, and benchmark views without it.
          </p>
          <div class="cta-row">
            <a class="btn primary" href="/uc2">Back to UC2 page</a>
            <a class="btn" href="/">Home</a>
          </div>
        </div>
        <div class="panel">
          <h4>What to set</h4>
          <ul class="detail-list">
            <li>FOUNDRY_PROJECT_ENDPOINT</li>
            <li>FOUNDRY_MODEL_DEPLOYMENT_NAME or VOICE_ASSIST_MODEL_DEPLOYMENT_NAME</li>
            <li>FOUNDRY_AGENT_NAME / FOUNDRY_AGENT_VERSION if you want a named hosted agent</li>
          </ul>
        </div>
      </div>
    </section>
    """
    return HTMLResponse(_page_shell("UC2 live console", "uc2", body))


async def _api_benchmarks(_: Request) -> JSONResponse:
    cfg = _current_config()
    overview = _benchmark_overview()
    runs = []
    for run in overview["runs"]:
        runs.append(
            {
                "run_id": run.run_id,
                "summary_path": run.summary_path.as_posix(),
                "providers": run.providers,
                "cost_rows": run.cost_rows,
                "recommendation": run.recommendation,
                "excerpt": run.excerpt,
            }
        )
    return JSONResponse(
        {
            "config": cfg,
            "runs": runs,
            "latest_run": runs[0] if runs else None,
        }
    )


# ──────────────────────────────────────────────────────────────────────────────
# App factory / entrypoint
# ──────────────────────────────────────────────────────────────────────────────


async def _api_uc1_report(request: Request) -> JSONResponse:
    """Serve markdown report content as HTML-converted JSON."""
    path = request.query_params.get("path", "")
    if not path:
        return JSONResponse({"error": "Missing path parameter"}, status_code=400)
    
    # Ensure path is safe (no directory traversal)
    try:
        resolved = Path(path).resolve()
        if not resolved.exists():
            return JSONResponse({"error": "Report not found"}, status_code=404)
        
        with open(resolved, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Convert markdown to HTML if markdown library is available.
        html_content = content
        if HAS_MARKDOWN:
          try:
            html_content = markdown.markdown(
              content,
              extensions=["tables", "fenced_code", "codehilite"],
            )
            # Defensive sanitization before returning HTML for modal rendering.
            html_content = re.sub(r"(?is)<script.*?>.*?</script>", "", html_content)
            html_content = re.sub(r"(?is)<style.*?>.*?</style>", "", html_content)
            html_content = re.sub(r"\son[a-zA-Z]+\s*=\s*(['\"]).*?\1", "", html_content)
            html_content = re.sub(r"\son[a-zA-Z]+\s*=\s*[^\s>]+", "", html_content)
            html_content = re.sub(
              r"(?i)\s(href|src)\s*=\s*(['\"])\s*javascript:[^'\"]*\2",
              r" \1=\"#\"",
              html_content,
            )
          except Exception:
            # Fallback to plain content if conversion fails.
            html_content = f"<pre>{escape(content)}</pre>"
        else:
          # Fallback: wrap in pre tag if markdown library not available.
          html_content = f"<pre>{escape(content)}</pre>"
        
        return JSONResponse({
            "name": resolved.name,
            "content": html_content,
            "path": str(path),
            "is_html": True
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _api_audio_preview(request: Request) -> Response:
    path = request.query_params.get("path", "").strip()
    if not path:
        return JSONResponse({"error": "Missing path parameter"}, status_code=400)

    try:
        resolved = Path(path).expanduser().resolve()
    except Exception:
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    if not resolved.exists() or not resolved.is_file():
        return JSONResponse({"error": "Audio file not found"}, status_code=404)

    if resolved.suffix.lower() not in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
        return JSONResponse({"error": "Unsupported audio format"}, status_code=400)

    media_type, _ = mimetypes.guess_type(str(resolved))
    return FileResponse(str(resolved), media_type=media_type or "application/octet-stream")


_FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
    "<rect width='64' height='64' rx='12' fill='#0f6cbd'/>"
    "<path d='M32 14a8 8 0 0 1 8 8v10a8 8 0 0 1-16 0V22a8 8 0 0 1 8-8z' fill='#fff'/>"
    "<path d='M20 32a12 12 0 0 0 24 0M32 44v6' stroke='#fff' stroke-width='4' "
    "stroke-linecap='round' fill='none'/>"
    "</svg>"
)


async def _benchmark_tune(request: Request) -> JSONResponse:
    """Run LLM meaning-correction ('tuning') over a provider's transcripts for a run."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    run_id = str((payload or {}).get("run_id") or "").strip()
    provider = str((payload or {}).get("provider") or "").strip()
    if not run_id or not provider:
        return JSONResponse({"error": "run_id and provider are required."}, status_code=400)

    try:
        result = await _tune_provider_transcripts(run_id, provider)
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001 - surface unexpected failures to the UI
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)

    return JSONResponse(result)


async def _favicon(request: Request) -> Response:
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml")


def create_app() -> InvocationAgentServerHost:
    load_dotenv(override=False)
    try:
        live_uc2_app = create_uc2_live_app()
    except ValueError:
        live_uc2_app = InvocationAgentServerHost(
            routes=[Route("/", _uc2_live_unavailable, methods=["GET"], name="uc2_live_unavailable")]
        )
    live_uc3_app = create_uc3_live_app()

    routes = [
        Route("/", _home, methods=["GET"], name="home"),
        Route("/favicon.ico", _favicon, methods=["GET"], name="favicon"),
        Route("/uc1", _uc1, methods=["GET"], name="uc1"),
        Route("/uc1/run", _uc1_run, methods=["POST"], name="uc1_run"),
        Route("/uc1/list", _uc1_list, methods=["POST"], name="uc1_list"),
        Route("/api/uc1/report", _api_uc1_report, methods=["GET"], name="api_uc1_report"),
        Route("/api/audio/preview", _api_audio_preview, methods=["GET"], name="api_audio_preview"),
        Route("/uc2", _uc2, methods=["GET"], name="uc2"),
        Route("/uc3", _uc3, methods=["GET"], name="uc3"),
        Route("/benchmark", _benchmark, methods=["GET"], name="benchmark"),
        Route("/benchmark/run", _benchmark_run, methods=["POST"], name="benchmark_run"),
        Route("/benchmark/tune", _benchmark_tune, methods=["POST"], name="benchmark_tune"),
        Route("/benchmark/delete-reports", _benchmark_delete_reports, methods=["POST"], name="benchmark_delete_reports"),
        Route("/benchmark/script", _benchmark_script, methods=["GET"], name="benchmark_script"),
        Route("/tts-benchmark", _tts_benchmark, methods=["GET"], name="tts_benchmark"),
        Route("/tts-benchmark/run", _tts_benchmark_run, methods=["POST"], name="tts_benchmark_run"),
        Route("/api/benchmarks", _api_benchmarks, methods=["GET"], name="api_benchmarks"),
        Mount("/uc2/live", app=live_uc2_app, name="uc2_live"),
        Mount("/uc3/live", app=live_uc3_app, name="uc3_live"),
    ]
    return InvocationAgentServerHost(routes=routes)


def main() -> None:
    create_app().run()
