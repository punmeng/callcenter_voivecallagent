"""UC3 - Voice Live call (gpt-realtime speech-to-speech + TTS).

Unlike UC2 (which only *assists* a human agent), UC3 is a fully automated AI
voice agent that talks directly to the caller. It uses the Azure AI Voice Live
API with a ``gpt-realtime`` session to do speech-to-speech natively:

    caller mic --> browser --> this backend --> Voice Live (STT + LLM + TTS)
    caller ears <-- browser <-- this backend <-- Voice Live audio deltas

The browser streams PCM16 (24 kHz mono) microphone frames over a WebSocket. This
backend relays them into a Voice Live realtime connection and streams the
model's synthesized audio back to the browser to play.

Expert-agent handoff
--------------------
After the model understands the caller's question it answers small talk itself.
For *specific* inquiries (e.g. billing / account checkout) it calls the
``escalate_to_expert`` function tool. This backend then runs a dedicated Foundry
"expert" agent to produce the authoritative answer, feeds that answer back into
the Voice Live session as a function-call output, and asks the model to speak the
result via TTS. Control returns to the live voice conversation afterwards.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from dotenv import load_dotenv
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .agent_runtime import build_foundry_agent

_UI_HTML_PATH = Path("assets/uc3_voice_call_ui.html")
_PROMPT_PATH = Path("assets/uc3_agent_prompt.txt")
_BILLING_PROMPT_PATH = Path("assets/uc3_billing_agent_prompt.txt")
_IT_PROMPT_PATH = Path("assets/uc3_it_agent_prompt.txt")

# Voice Live realtime audio is PCM16 mono. UC3 uses 24 kHz end to end so the
# browser can capture and play back without resampling.
UC3_SAMPLE_RATE = 24000

# The function tool the model calls to route a specific inquiry to an expert.
EXPERT_TOOL_NAME = "escalate_to_expert"
# The function tool the model calls to look up the caller's bill amount.
BILLING_TOOL_NAME = "query_billing"
# The function tool the model calls for IT questions (software RD, hardware RD, OA).
IT_TOOL_NAME = "query_it_support"


_DEFAULT_PROMPT = (
    "You are a friendly Traditional Chinese speaking call-center voice agent. "
    "Greet the caller warmly, understand their request, and keep every reply VERY short "
    "for spoken delivery — 1 sentence when possible, at most 2 (under ~30 Chinese "
    "characters); one idea per turn, ask a brief follow-up instead of explaining at length. "
    "When the caller asks about their bill amount, "
    "how much they owe, their invoice, or a due date, call the query_billing function "
    "with a concise 'question' (and 'account_ref' if the caller gives an account or "
    "phone number). When the caller asks about software R&D, hardware R&D, or office "
    "automation (OA), call the query_it_support function with a concise 'question' and "
    "a 'category' (software-rd, hardware-rd, or oa). For other specific account, "
    "payment, or order-status questions, call the escalate_to_expert function instead. "
    "Never guess account-specific figures or internal IT details; call a function and "
    "read the returned answer back naturally. Speak Traditional Chinese unless the "
    "caller clearly prefers English."
)


@dataclass
class VoiceCallSession:
    """Per-connection metrics for a UC3 voice call."""

    session_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    user_turns: int = 0
    assistant_turns: int = 0
    expert_handoffs: int = 0
    billing_handoffs: int = 0
    it_handoffs: int = 0


@dataclass
class ConversationRecorder:
    """Records both sides of the call (mic + agent audio) into a mono WAV.

    Both streams are PCM16 mono at ``UC3_SAMPLE_RATE``. Each chunk is stamped with
    its arrival offset so overlapping speech is time-aligned and summed into one
    mono track — the format UC1's diarization handles best.
    """

    sample_rate: int = UC3_SAMPLE_RATE
    active: bool = False
    _start_perf: float = 0.0
    _chunks: list[tuple[int, bytes]] = field(default_factory=list)
    _ends: dict[str, int] = field(default_factory=dict)

    def start(self) -> None:
        self.active = True
        self._start_perf = time.perf_counter()
        self._chunks = []
        self._ends = {}

    def add(self, pcm: bytes, source: str) -> None:
        """Queue a PCM16 chunk from ``source`` ("user" or "agent").

        Each source is laid out consecutively: a chunk starts at the later of its
        arrival time or the source's running end. Voice Live streams the agent's
        audio in bursts faster than real time, so anchoring to arrival time alone
        would overlap the agent chunks and double the voice — this prevents that
        while still letting the two sources overlap each other (barge-in).
        """
        if not self.active or not pcm:
            return
        samples = len(pcm) // 2
        if samples <= 0:
            return
        arrival = int((time.perf_counter() - self._start_perf) * self.sample_rate)
        running_end = self._ends.get(source, 0)
        pos = max(arrival, running_end)
        self._ends[source] = pos + samples
        self._chunks.append((max(0, pos), pcm))

    def has_audio(self) -> bool:
        return bool(self._chunks)

    def reset(self) -> None:
        self.active = False
        self._chunks = []
        self._ends = {}

    def write(self, path: Path) -> float:
        """Mix all chunks into a mono WAV at ``path``; return duration in seconds."""
        import numpy as np

        if not self._chunks:
            return 0.0
        parsed: list[tuple[int, Any]] = []
        total = 0
        for offset, pcm in self._chunks:
            arr = np.frombuffer(pcm, dtype="<i2")
            if arr.size == 0:
                continue
            parsed.append((offset, arr))
            end = offset + arr.shape[0]
            if end > total:
                total = end
        if total <= 0:
            return 0.0
        acc = np.zeros(total, dtype=np.int32)
        for offset, arr in parsed:
            acc[offset : offset + arr.shape[0]] += arr
        np.clip(acc, -32768, 32767, out=acc)
        out = acc.astype("<i2")
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(out.tobytes())
        return total / self.sample_rate


def _uc1_source_dir() -> Path:
    """Folder where UC3 recordings are saved (UC1's source folder by default)."""
    override = (os.getenv("UC3_RECORDING_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    from .config import load_settings

    settings = load_settings()
    if settings.local_audio_dir:
        return Path(settings.local_audio_dir)
    if settings.local_audio_path:
        return Path(settings.local_audio_path).parent
    return Path("data/benchmark_audio")


async def _finish_recording(recorder: ConversationRecorder, websocket: WebSocket | None) -> None:
    """Write the current recording to UC1's source folder and notify the browser."""
    if not recorder.has_audio() and not recorder.active:
        return
    recorder.active = False
    if not recorder.has_audio():
        recorder.reset()
        return
    target_dir = _uc1_source_dir()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"uc3_call_{ts}.wav"
    try:
        duration = await asyncio.to_thread(recorder.write, target)
    except Exception as exc:  # noqa: BLE001 - surface a save error, keep the call alive
        if websocket is not None:
            await _safe_ws_send(
                websocket,
                {"type": "recording_error", "message": f"{type(exc).__name__}: {exc}"},
            )
        recorder.reset()
        return
    recorder.reset()
    if websocket is not None:
        await _safe_ws_send(
            websocket,
            {
                "type": "recording_saved",
                "path": str(target),
                "duration_seconds": round(duration, 2),
            },
        )



def _resolve_prompt() -> str:
    if _PROMPT_PATH.exists() and _PROMPT_PATH.is_file():
        text = _PROMPT_PATH.read_text(encoding="utf-8").strip()
        if text:
            return text
    return _DEFAULT_PROMPT


# Allow-lists for the per-call method selectors exposed in the UI. Overrides that
# are not in these sets are ignored and the env/default value is used instead — this
# keeps arbitrary strings from the browser out of the Voice Live session request.
_UC3_MODEL_OPTIONS = {"gpt-realtime", "gpt-4o-realtime-preview"}
_UC3_TRANSCRIPTION_OPTIONS = {
    "azure-speech",
    "gpt-4o-transcribe",
    "gpt-4o-mini-transcribe",
    "gpt-4o-transcribe-diarize",
    "mai-transcribe-1",
    "whisper-1",
}
_UC3_VOICE_OPTIONS = {
    "zh-TW-HsiaoChenNeural",
    "zh-CN-XiaoxiaoNeural",
    "en-US-JennyNeural",
    "en-US-AvaNeural",
    "ja-JP-NanamiNeural",
    "ko-KR-SunHiNeural",
    # MAI-Voice-2 prebuilt voices are served via the Azure Speech SDK, so they only
    # apply to the Azure-TTS pipelines (voicelive-tts / classic), not the all-in-one
    # Voice Live pipeline. Voice IDs use the '<locale>-<Name>:MAI-Voice-2' form.
    # zh-CN-Mei is Simplified-Mandarin; it reads Chinese text (including Traditional)
    # in Mandarin (there is no Traditional zh-TW MAI-Voice-2 voice at present).
    "en-US-Harper:MAI-Voice-2",
    "zh-CN-Mei:MAI-Voice-2",
}


def _resolve_model(override: str | None = None) -> str:
    if override and override.strip() in _UC3_MODEL_OPTIONS:
        return override.strip()
    return (
        os.getenv("UC3_VOICE_LIVE_MODEL")
        or os.getenv("AZURE_VOICELIVE_MODEL")
        or "gpt-realtime"
    ).strip()


def _resolve_voice(override: str | None = None) -> str:
    if override and override.strip() in _UC3_VOICE_OPTIONS:
        return override.strip()
    return (
        os.getenv("UC3_VOICE_LIVE_VOICE")
        or os.getenv("AZURE_VOICELIVE_TTS_VOICE")
        or "zh-TW-HsiaoChenNeural"
    ).strip()


# Exact opening line spoken to the caller (verbatim via pre-generated message).
_DEFAULT_WELCOME = "微軟創新中心你好，我是你的客服小助手，請問有什麼可以為您服務的嗎？"


def _resolve_welcome() -> str:
    return (os.getenv("UC3_WELCOME") or _DEFAULT_WELCOME).strip()


def _resolve_transcription_language() -> str:
    return (os.getenv("VOICE_LIVE_TRANSCRIPTION_LANGUAGE") or "zh-TW").strip()


def _resolve_transcription_model(override: str | None = None) -> str:
    """Model used to transcribe the caller's speech (STT) inside the Voice Live session.

    Supported values include: azure-speech, mai-transcribe-1, whisper-1,
    gpt-4o-transcribe, gpt-4o-mini-transcribe, gpt-4o-transcribe-diarize.
    """
    if override and override.strip() in _UC3_TRANSCRIPTION_OPTIONS:
        return override.strip()
    return (os.getenv("UC3_TRANSCRIPTION_MODEL") or "azure-speech").strip()


def _build_voice(voice: str) -> Any:
    """Resolve a voice string into an OpenAI voice name or an Azure standard voice."""
    from azure.ai.voicelive.models import AzureStandardVoice

    if "Neural" in voice or voice.count("-") >= 2:
        return AzureStandardVoice(name=voice)
    return voice


# ──────────────────────────────────────────────────────────────────────────────
# Classic pipeline (Azure Speech STT + Foundry LLM + Azure Speech TTS, no Voice Live)
# ──────────────────────────────────────────────────────────────────────────────


_CLASSIC_INSTRUCTIONS = (
    "You are a friendly Traditional Chinese speaking call-center voice agent. "
    "Greet warmly, understand the caller's request, and keep every reply VERY short "
    "for spoken delivery — 1 sentence when possible, at most 2 (under ~30 Chinese "
    "characters). One idea per turn; ask a brief follow-up instead of long explanations. "
    "Speak Traditional Chinese unless the caller clearly prefers another language. "
    "Answer directly and conversationally; do not mention tools, systems, or functions."
)


def _classic_llm_model() -> str:
    """Foundry chat deployment used for the classic pipeline's 'think' step."""
    return (os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME") or "").strip()


def _classic_llm_configured() -> bool:
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT") or os.getenv("UC3_FOUNDRY_PROJECT_ENDPOINT")
    return bool(endpoint and _classic_llm_model())


def _build_classic_agent() -> Any:
    endpoint = (
        os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        or os.getenv("UC3_FOUNDRY_PROJECT_ENDPOINT")
        or ""
    ).strip()
    return build_foundry_agent(
        name="VoiceCallUC3Classic",
        instructions=_CLASSIC_INSTRUCTIONS,
        project_endpoint=endpoint,
        model=_classic_llm_model(),
    )


def _classic_compose_prompt(history: list[tuple[str, str]]) -> str:
    """Build a short rolling-context prompt for the classic chat LLM."""
    latest = history[-1][1] if history else ""
    prior = history[:-1][-6:]
    if not prior:
        return f"客戶：{latest}\n請以客服身分用一到兩句簡短口語回覆。"
    lines = []
    for role, txt in prior:
        who = "客戶" if role == "user" else "客服"
        lines.append(f"{who}：{txt}")
    convo = "\n".join(lines)
    return (
        f"對話紀錄：\n{convo}\n\n客戶最新的一句：{latest}\n"
        "請以客服身分，延續上文，用一到兩句簡短口語回覆。"
    )


async def _run_classic_llm(agent: Any, history: list[tuple[str, str]]) -> str:
    if agent is None:
        return "不好意思，客服系統目前無法回覆，請稍後再試。"
    try:
        result = await agent.run(_classic_compose_prompt(history))
        answer = (getattr(result, "text", "") or "").strip()
        return answer or "不好意思，能再說一次嗎？"
    except Exception as exc:  # noqa: BLE001 - keep the call alive with a spoken fallback
        return f"抱歉，處理時發生問題（{type(exc).__name__}），請稍後再試。"


def _apply_speech_control(text: str) -> str:
    """Return SSML inner markup with pronunciation control applied to a spoken reply.

    CUSTOMIZATION POINT — tweak how the answer is spoken. The default reads any run
    of 2+ digits digit-by-digit (e.g. "101" -> "1-0-1", "0800" -> "0-8-0-0") using
    ``<say-as interpret-as="digits">``. To keep money/amounts as cardinals, refine the
    regex (e.g. skip tokens preceded by "NT$"/"NTD") or branch on context here.
    """
    import html
    import re

    escaped = html.escape(text or "", quote=False)
    return re.sub(
        r"\d{2,}",
        lambda m: f'<say-as interpret-as="digits">{m.group(0)}</say-as>',
        escaped,
    )


def _build_ssml(text: str, voice_name: str, lang: str) -> str:
    inner = _apply_speech_control(text)
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xml:lang="{lang}"><voice name="{voice_name}">{inner}</voice></speak>'
    )


def _synthesize_controlled(text: str, voice_name: str) -> bytes:
    """Synthesize ``text`` to raw PCM16 24 kHz via Azure Speech TTS, applying the
    SSML pronunciation control in :func:`_apply_speech_control` (blocking)."""
    import azure.cognitiveservices.speech as speechsdk

    from .config import load_settings
    from .uc1_stt_agent import build_speech_config

    speech = (text or "").strip()
    if not speech:
        return b""
    speech_config = build_speech_config(load_settings())
    speech_config.speech_synthesis_voice_name = voice_name
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm
    )
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    ssml = _build_ssml(speech, voice_name, _resolve_transcription_language())
    result = synthesizer.speak_ssml_async(ssml).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return bytes(result.audio_data or b"")
    return b""


async def _classic_stream_pcm(
    websocket: WebSocket, pcm: bytes, recorder: ConversationRecorder
) -> None:
    """Chunk raw PCM16 and send it to the browser as base64 'audio' messages."""
    if not pcm:
        return
    # 200 ms per chunk at 24 kHz mono / 16-bit = 4800 samples * 2 bytes.
    chunk_bytes = 4800 * 2
    for i in range(0, len(pcm), chunk_bytes):
        chunk = pcm[i : i + chunk_bytes]
        recorder.add(chunk, "agent")
        await _safe_ws_send(
            websocket,
            {"type": "audio", "audio": base64.b64encode(chunk).decode("ascii")},
        )


# ──────────────────────────────────────────────────────────────────────────────
# Expert agent handoff
# ──────────────────────────────────────────────────────────────────────────────


def _expert_agent_configured() -> bool:
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT") or os.getenv("UC3_FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        return False
    # Only a UC3-specific expert agent counts as a named agent; we deliberately do
    # NOT inherit FOUNDRY_AGENT_NAME so the UC1 judge is never reused as the expert.
    has_named_agent = bool(os.getenv("UC3_EXPERT_AGENT_NAME"))
    has_model = bool(
        os.getenv("UC3_EXPERT_MODEL_DEPLOYMENT_NAME") or os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME")
    )
    return has_named_agent or has_model


def _build_expert_agent() -> Any:
    endpoint = (
        os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        or os.getenv("UC3_FOUNDRY_PROJECT_ENDPOINT")
        or ""
    ).strip()
    agent_name = (os.getenv("UC3_EXPERT_AGENT_NAME") or "").strip() or None
    agent_version = (
        os.getenv("UC3_EXPERT_AGENT_VERSION") or os.getenv("FOUNDRY_AGENT_VERSION") or ""
    ).strip() or None
    model = (
        os.getenv("UC3_EXPERT_MODEL_DEPLOYMENT_NAME")
        or os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME")
        or ""
    ).strip() or None

    instructions = (
        "You are a call-center domain expert. Answer the caller's specific question "
        "(billing, account, payment, or order status) accurately and concisely in "
        "the caller's language. Return only the answer text, no preamble, suitable "
        "to be read aloud to the caller."
    )
    return build_foundry_agent(
        name="VoiceCallExpert",
        instructions=instructions,
        project_endpoint=endpoint,
        agent_name=agent_name,
        agent_version=agent_version,
        model=model,
        allow_preview=True,
        use_portal_instructions=True,
    )


async def _run_expert(agent: Any, question: str, topic: str) -> str:
    """Invoke the Foundry expert agent and return the spoken-answer text."""
    if agent is None:
        return (
            "很抱歉，專家系統目前尚未設定，我無法查詢這個問題。"
            "請稍後再試，或由專人為您服務。"
        )
    prompt = question.strip()
    if topic.strip():
        prompt = f"[{topic.strip()}] {prompt}"
    try:
        result = await agent.run(prompt)
        answer = (getattr(result, "text", "") or "").strip()
        return answer or "抱歉，我目前查不到這個資訊。"
    except Exception as exc:  # noqa: BLE001 - surface a spoken fallback, keep the call alive
        return f"抱歉，查詢時發生問題（{type(exc).__name__}）。我先幫您記錄，稍後再回覆。"


# ──────────────────────────────────────────────────────────────────────────────
# Billing agent handoff
# ──────────────────────────────────────────────────────────────────────────────


def _billing_agent_configured() -> bool:
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT") or os.getenv("UC3_FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        return False
    return bool(
        os.getenv("UC3_BILLING_AGENT_NAME")
        or os.getenv("UC3_BILLING_MODEL_DEPLOYMENT_NAME")
        or os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME")
    )


def _billing_instructions() -> str:
    if _BILLING_PROMPT_PATH.exists() and _BILLING_PROMPT_PATH.is_file():
        text = _BILLING_PROMPT_PATH.read_text(encoding="utf-8").strip()
        if text:
            return text
    return (
        "You are a call-center billing specialist. Answer the caller's billing question "
        "— especially the current bill amount, due date, and recent charges — accurately "
        "and concisely in the caller's language. Return only the spoken answer text, no "
        "preamble. If you do not have the account data, say so briefly and offer to have "
        "a human follow up."
    )


def _build_billing_agent() -> Any:
    endpoint = (
        os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        or os.getenv("UC3_FOUNDRY_PROJECT_ENDPOINT")
        or ""
    ).strip()
    agent_name = (os.getenv("UC3_BILLING_AGENT_NAME") or "").strip() or None
    agent_version = (os.getenv("UC3_BILLING_AGENT_VERSION") or "").strip() or None
    model = (
        os.getenv("UC3_BILLING_MODEL_DEPLOYMENT_NAME")
        or os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME")
        or ""
    ).strip() or None
    return build_foundry_agent(
        name="VoiceCallBilling",
        instructions=_billing_instructions(),
        project_endpoint=endpoint,
        agent_name=agent_name,
        agent_version=agent_version,
        model=model,
        allow_preview=True,
        use_portal_instructions=True,
    )


async def _run_billing(agent: Any, question: str, account_ref: str) -> str:
    """Invoke the Foundry billing agent and return the spoken-answer text."""
    if agent is None:
        return (
            "很抱歉，帳單查詢系統目前尚未設定，我無法查詢您的帳單金額。"
            "請稍後再試，或由專人為您服務。"
        )
    prompt = question.strip() or "查詢本期帳單金額。"
    if account_ref.strip():
        prompt = f"[account: {account_ref.strip()}] {prompt}"
    try:
        result = await agent.run(prompt)
        answer = (getattr(result, "text", "") or "").strip()
        return answer or "抱歉，我目前查不到您的帳單資訊。"
    except Exception as exc:  # noqa: BLE001 - surface a spoken fallback, keep the call alive
        return f"抱歉，查詢帳單時發生問題（{type(exc).__name__}）。我先幫您記錄，稍後再回覆。"


# ──────────────────────────────────────────────────────────────────────────────
# IT support agent handoff (software RD / hardware RD / OA)
# ──────────────────────────────────────────────────────────────────────────────


def _it_agent_configured() -> bool:
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT") or os.getenv("UC3_FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        return False
    return bool(
        os.getenv("UC3_IT_AGENT_NAME")
        or os.getenv("UC3_IT_MODEL_DEPLOYMENT_NAME")
        or os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME")
    )


def _it_instructions() -> str:
    if _IT_PROMPT_PATH.exists() and _IT_PROMPT_PATH.is_file():
        text = _IT_PROMPT_PATH.read_text(encoding="utf-8").strip()
        if text:
            return text
    return (
        "You are a corporate IT support specialist covering software R&D, hardware R&D, "
        "and office automation (OA). Answer the caller's IT question accurately and "
        "concisely in the caller's language, using your knowledge base. Return only the "
        "spoken answer text, no preamble. If you do not have the information, say so "
        "briefly and offer to open a ticket or have a human follow up."
    )


def _build_it_agent() -> Any:
    endpoint = (
        os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        or os.getenv("UC3_FOUNDRY_PROJECT_ENDPOINT")
        or ""
    ).strip()
    agent_name = (os.getenv("UC3_IT_AGENT_NAME") or "").strip() or None
    agent_version = (os.getenv("UC3_IT_AGENT_VERSION") or "").strip() or None
    model = (
        os.getenv("UC3_IT_MODEL_DEPLOYMENT_NAME")
        or os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME")
        or ""
    ).strip() or None
    return build_foundry_agent(
        name="VoiceCallITSupport",
        instructions=_it_instructions(),
        project_endpoint=endpoint,
        agent_name=agent_name,
        agent_version=agent_version,
        model=model,
        allow_preview=True,
        use_portal_instructions=True,
    )


async def _run_it(agent: Any, question: str, category: str) -> str:
    """Invoke the Foundry IT support agent and return the spoken-answer text."""
    if agent is None:
        return (
            "很抱歉，IT 支援系統目前尚未設定，我無法回答這個問題。"
            "我先幫您開立工單，稍後由 IT 專人跟進。"
        )
    prompt = question.strip() or "IT 支援問題。"
    if category.strip():
        prompt = f"[{category.strip()}] {prompt}"
    try:
        result = await agent.run(prompt)
        answer = (getattr(result, "text", "") or "").strip()
        return answer or "抱歉，我目前查不到相關的 IT 資訊。"
    except Exception as exc:  # noqa: BLE001 - surface a spoken fallback, keep the call alive
        return f"抱歉，查詢 IT 資訊時發生問題（{type(exc).__name__}）。我先幫您開立工單，稍後回覆。"


# ──────────────────────────────────────────────────────────────────────────────
# App factory
# ──────────────────────────────────────────────────────────────────────────────


def create_app() -> InvocationAgentServerHost:
    load_dotenv(override=False)

    async def audio_ws_endpoint(websocket: WebSocket) -> None:
        # The UI picks the pipeline via a query param.
        #   "classic"       -> Azure Speech STT + Foundry LLM + Azure Speech TTS (no Voice Live)
        #   "voicelive-tts" -> Voice Live for STT + reasoning (text-only output), then our
        #                       own Azure Speech TTS speaks the answer so pronunciation can be
        #                       controlled (e.g. read "101" as "1-0-1").
        #   anything else   -> Voice Live all-in-one (STT + reasoning + TTS bundled)
        pipeline = (websocket.query_params.get("pipeline") or "").strip().lower()
        if pipeline == "classic":
            await _handle_voice_ws_classic(websocket)
        elif pipeline == "voicelive-tts":
            await _handle_voice_ws(websocket, external_tts=True)
        else:
            await _handle_voice_ws(websocket)

    routes = [
        Route("/", _serve_ui, methods=["GET"], name="uc3_ui"),
        Route("/health", _health, methods=["GET"], name="uc3_health"),
        WebSocketRoute("/audio_ws", audio_ws_endpoint, name="uc3_audio_ws"),
    ]
    return InvocationAgentServerHost(routes=routes)


async def _serve_ui(_: Request) -> HTMLResponse:
    if _UI_HTML_PATH.exists() and _UI_HTML_PATH.is_file():
        return HTMLResponse(_UI_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<h1>UC3 UI not found</h1><p>Expected assets/uc3_voice_call_ui.html</p>",
        status_code=500,
    )


async def _health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "use_case": "uc3-voice-live-call",
            "voice_live_endpoint_configured": bool(os.getenv("AZURE_VOICELIVE_ENDPOINT")),
            "model": _resolve_model(),
            "voice": _resolve_voice(),
            "transcription_model": _resolve_transcription_model(),
            "expert_agent_configured": _expert_agent_configured(),
            "billing_agent_configured": _billing_agent_configured(),
            "it_agent_configured": _it_agent_configured(),
            "classic_pipeline_configured": _classic_llm_configured(),
        }
    )


async def _safe_ws_send(websocket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await websocket.send_text(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


async def _capture_close_reason(connection: Any) -> str:
    """Read the next server frame to extract the WebSocket close code/reason, if any."""
    from azure.ai.voicelive.aio import ConnectionClosed

    try:
        await asyncio.wait_for(connection.recv(), timeout=3.0)
    except ConnectionClosed as cc:
        return f"code {cc.code}: {cc.reason or 'no reason given'}"
    except Exception:  # noqa: BLE001 - best-effort diagnostics only
        return ""
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# Browser <-> Voice Live relay
# ──────────────────────────────────────────────────────────────────────────────


async def _handle_voice_ws(websocket: WebSocket, external_tts: bool = False) -> None:
    await websocket.accept()
    session = VoiceCallSession(session_id=f"uc3-{int(time.time() * 1000)}")
    recorder = ConversationRecorder()

    endpoint = (os.getenv("AZURE_VOICELIVE_ENDPOINT") or "").strip()
    if not endpoint:
        await _safe_ws_send(
            websocket,
            {"type": "error", "message": "AZURE_VOICELIVE_ENDPOINT is not set."},
        )
        await websocket.close()
        return

    try:
        from azure.core.credentials import AzureKeyCredential
        from azure.identity.aio import AzureCliCredential
        from azure.ai.voicelive.aio import ConnectionClosed, connect
        from azure.ai.voicelive.models import (
            AudioInputTranscriptionOptions,
            AzureSemanticVad,
            FunctionTool,
            Modality,
            InputAudioFormat,
            OutputAudioFormat,
            RequestSession,
            ServerVad,
        )
    except Exception as exc:  # noqa: BLE001 - missing SDK becomes a UI-visible error
        await _safe_ws_send(
            websocket,
            {"type": "error", "message": f"Voice Live SDK unavailable: {type(exc).__name__}: {exc}"},
        )
        await websocket.close()
        return

    api_key = (os.getenv("AZURE_VOICELIVE_API_KEY") or "").strip()
    api_version = (os.getenv("AZURE_VOICELIVE_API_VERSION") or "2026-06-01-preview").strip()
    # Per-call method selectors from the UI (validated against allow-lists).
    _q = websocket.query_params
    model = _resolve_model(_q.get("model"))
    voice = _resolve_voice(_q.get("voice"))
    # MAI-Voice / Azure-TTS-only voices (their IDs contain ':') are not valid Voice Live
    # session voices. In external-TTS mode Voice Live doesn't speak anyway, so keep its
    # voice field on a known-good neural voice; the real TTS voice below drives Azure
    # Speech synthesis.
    session_voice = "zh-TW-HsiaoChenNeural" if ":" in voice else voice
    transcription_model = _resolve_transcription_model(_q.get("transcription"))
    cli_timeout = int((os.getenv("VOICE_LIVE_AZ_CLI_TIMEOUT_SECONDS") or "60").strip())

    credential = (
        AzureKeyCredential(api_key)
        if api_key
        else AzureCliCredential(process_timeout=cli_timeout)
    )

    expert_agent: Any = None
    if _expert_agent_configured():
        try:
            expert_agent = _build_expert_agent()
        except Exception as exc:  # noqa: BLE001 - degrade to spoken fallback
            await _safe_ws_send(
                websocket,
                {"type": "status", "message": f"Expert agent unavailable: {type(exc).__name__}: {exc}"},
            )

    billing_agent: Any = None
    if _billing_agent_configured():
        try:
            billing_agent = _build_billing_agent()
        except Exception as exc:  # noqa: BLE001 - degrade to spoken fallback
            await _safe_ws_send(
                websocket,
                {"type": "status", "message": f"Billing agent unavailable: {type(exc).__name__}: {exc}"},
            )

    it_agent: Any = None
    if _it_agent_configured():
        try:
            it_agent = _build_it_agent()
        except Exception as exc:  # noqa: BLE001 - degrade to spoken fallback
            await _safe_ws_send(
                websocket,
                {"type": "status", "message": f"IT agent unavailable: {type(exc).__name__}: {exc}"},
            )

    expert_tool = FunctionTool(
        name=EXPERT_TOOL_NAME,
        description=(
            "Escalate a specific caller inquiry (account, payment, or order status) to "
            "the domain expert. Call this instead of guessing whenever the caller needs "
            "authoritative account-specific information that is NOT about the bill amount."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The caller's specific question, phrased for the expert.",
                },
                "topic": {
                    "type": "string",
                    "description": "Short category, e.g. account, payment, order-status.",
                },
            },
            "required": ["question"],
        },
    )

    billing_tool = FunctionTool(
        name=BILLING_TOOL_NAME,
        description=(
            "Look up the caller's billing information — especially the current bill "
            "amount, how much they owe, their invoice, or the payment due date. Call "
            "this whenever the caller asks about their bill or amount owed, instead of "
            "guessing."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The caller's billing question, e.g. current bill amount or due date.",
                },
                "account_ref": {
                    "type": "string",
                    "description": "Optional account/member number or phone digits, if the caller provided one.",
                },
            },
            "required": ["question"],
        },
    )

    it_tool = FunctionTool(
        name=IT_TOOL_NAME,
        description=(
            "Answer an internal IT question about software R&D, hardware R&D, or office "
            "automation (OA). Call this whenever the caller asks about software R&D, "
            "hardware R&D, or OA topics, instead of guessing."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The caller's IT question, phrased for the IT specialist.",
                },
                "category": {
                    "type": "string",
                    "description": "One of: software-rd, hardware-rd, oa.",
                    "enum": ["software-rd", "hardware-rd", "oa"],
                },
            },
            "required": ["question"],
        },
    )

    try:
        async with connect(
            endpoint=endpoint,
            credential=credential,
            api_version=api_version,
            model=model,
        ) as connection:
            # Voice Live requires an Azure semantic VAD when the input transcription model
            # is azure-speech; other transcription models (gpt-4o-transcribe, etc.) use
            # ServerVad. Both keep create_response + interrupt_response for barge-in.
            if transcription_model.strip().lower() == "azure-speech":
                turn_detection: Any = AzureSemanticVad(
                    threshold=0.5,
                    prefix_padding_ms=300,
                    silence_duration_ms=500,
                    create_response=True,
                    interrupt_response=True,
                )
            else:
                turn_detection = ServerVad(
                    threshold=0.5,
                    prefix_padding_ms=300,
                    silence_duration_ms=500,
                    create_response=True,
                    interrupt_response=True,
                )
            try:
                await connection.session.update(
                    session=RequestSession(
                        model=model,
                        modalities=(
                            [Modality.TEXT]
                            if external_tts
                            else [Modality.AUDIO, Modality.TEXT]
                        ),
                        voice=_build_voice(session_voice),
                        instructions=_resolve_prompt(),
                        input_audio_format=InputAudioFormat.PCM16,
                        output_audio_format=OutputAudioFormat.PCM16,
                        input_audio_sampling_rate=UC3_SAMPLE_RATE,
                        input_audio_transcription=AudioInputTranscriptionOptions(
                            model=transcription_model,
                            language=_resolve_transcription_language(),
                        ),
                        turn_detection=turn_detection,
                        tools=[billing_tool, it_tool, expert_tool],
                        tool_choice="auto",
                        temperature=0.7,
                    )
                )
            except ConnectionClosed as cc:
                await _safe_ws_send(
                    websocket,
                    {
                        "type": "error",
                        "message": (
                            f"Voice Live closed the session (code {cc.code}): "
                            f"{cc.reason or 'no reason given'}. Check that model "
                            f"'{model}' and transcription model "
                            f"'{transcription_model}' are available on this "
                            f"resource for api-version '{api_version}'."
                        ),
                    },
                )
                raise
            except Exception as session_exc:  # noqa: BLE001 - surface the true close reason
                reason = await _capture_close_reason(connection)
                hint = (
                    f"Check that model '{model}' and transcription model "
                    f"'{transcription_model}' are available on this resource "
                    f"for api-version '{api_version}'."
                )
                detail = reason or f"{type(session_exc).__name__}: {session_exc}"
                await _safe_ws_send(
                    websocket,
                    {"type": "error", "message": f"Voice Live rejected the session ({detail}). {hint}"},
                )
                raise

            await _safe_ws_send(
                websocket,
                {
                    "type": "ready",
                    "session_id": session.session_id,
                    "pipeline": "voicelive-tts" if external_tts else "voicelive",
                    "model": model,
                    "voice": voice,
                    "transcription_model": transcription_model,
                    "transcription_language": _resolve_transcription_language(),
                    "tts": "azure-speech (controlled)" if external_tts else "voice-live",
                    "sample_rate": UC3_SAMPLE_RATE,
                    "expert_agent_configured": expert_agent is not None,
                    "billing_agent_configured": billing_agent is not None,
                    "it_agent_configured": it_agent is not None,
                },
            )

            # Greet the caller first. In external-TTS mode we synthesize the welcome
            # with our own Azure Speech TTS (so pronunciation control applies); the
            # all-in-one Voice Live mode speaks it verbatim via a pre-generated message.
            from azure.ai.voicelive.models import (
                AssistantMessageItem,
                OutputTextContentPart,
                ResponseCreateParams,
            )

            if external_tts:
                welcome = _resolve_welcome()
                session.assistant_turns += 1
                await _safe_ws_send(
                    websocket,
                    {
                        "type": "assistant_transcript",
                        "text": welcome,
                        "assistant_turns": session.assistant_turns,
                    },
                )
                welcome_pcm = await asyncio.to_thread(_synthesize_controlled, welcome, voice)
                await _classic_stream_pcm(websocket, welcome_pcm, recorder)
            else:
                await connection.response.create(
                    response=ResponseCreateParams(
                        modalities=[Modality.AUDIO, Modality.TEXT],
                        pre_generated_assistant_message=AssistantMessageItem(
                            content=[OutputTextContentPart(text=_resolve_welcome())],
                        ),
                    )
                )

            uplink = asyncio.create_task(_pump_browser_to_voicelive(websocket, connection, recorder))
            downlink = asyncio.create_task(
                _pump_voicelive_to_browser(
                    websocket, connection, session, expert_agent, billing_agent, it_agent,
                    recorder, external_tts, voice,
                )
            )
            done, pending = await asyncio.wait(
                {uplink, downlink}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                    await _safe_ws_send(
                        websocket,
                        {"type": "error", "message": f"{type(exc).__name__}: {exc}"},
                    )
    except Exception as exc:  # noqa: BLE001 - surface connection errors to the UI
        await _safe_ws_send(
            websocket,
            {"type": "error", "message": f"Voice Live connection failed: {type(exc).__name__}: {exc}"},
        )
    finally:
        with contextlib.suppress(Exception):
            if recorder.active:
                await _finish_recording(recorder, None)
        close_method = getattr(credential, "close", None)
        if callable(close_method):
            with contextlib.suppress(Exception):
                await close_method()
        with contextlib.suppress(Exception):
            await websocket.close()


async def _handle_voice_ws_classic(websocket: WebSocket) -> None:
    """Classic pipeline: Azure Speech STT -> Foundry LLM -> Azure Speech TTS.

    This path does NOT use the Voice Live API. Browser PCM16 24 kHz frames are fed
    into an Azure Speech continuous recognizer; each final utterance runs the chat
    LLM, and the reply is synthesized with Azure Speech TTS and streamed back.
    """
    await websocket.accept()
    session = VoiceCallSession(session_id=f"uc3c-{int(time.time() * 1000)}")
    recorder = ConversationRecorder()
    loop = asyncio.get_running_loop()

    q = websocket.query_params
    voice = _resolve_voice(q.get("voice"))

    if not _classic_llm_configured():
        await _safe_ws_send(
            websocket,
            {
                "type": "error",
                "message": (
                    "Classic pipeline needs a chat LLM. Set FOUNDRY_PROJECT_ENDPOINT and "
                    "FOUNDRY_MODEL_DEPLOYMENT_NAME."
                ),
            },
        )
        await websocket.close()
        return

    try:
        import azure.cognitiveservices.speech as speechsdk

        from .config import load_settings
        from .uc1_stt_agent import build_speech_config
    except Exception as exc:  # noqa: BLE001 - missing SDK becomes a UI-visible error
        await _safe_ws_send(
            websocket,
            {"type": "error", "message": f"Azure Speech SDK unavailable: {type(exc).__name__}: {exc}"},
        )
        await websocket.close()
        return

    try:
        settings = load_settings()
        speech_config = build_speech_config(settings)
        agent = _build_classic_agent()
    except Exception as exc:  # noqa: BLE001 - surface config/agent errors to the UI
        await _safe_ws_send(
            websocket,
            {"type": "error", "message": f"Classic pipeline setup failed: {type(exc).__name__}: {exc}"},
        )
        await websocket.close()
        return

    stream_format = speechsdk.audio.AudioStreamFormat(
        samples_per_second=UC3_SAMPLE_RATE, bits_per_sample=16, channels=1
    )
    push_stream = speechsdk.audio.PushAudioInputStream(stream_format=stream_format)
    audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
    auto_lang_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
        languages=settings.speech_languages
    )
    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config,
        auto_detect_source_language_config=auto_lang_config,
    )

    history: list[tuple[str, str]] = []
    turn_lock = asyncio.Lock()

    async def _classic_turn(text: str) -> None:
        async with turn_lock:
            session.user_turns += 1
            await _safe_ws_send(
                websocket,
                {"type": "user_transcript", "text": text, "user_turns": session.user_turns},
            )
            await _safe_ws_send(websocket, {"type": "speech_stopped"})
            history.append(("user", text))
            reply = await _run_classic_llm(agent, history)
            history.append(("assistant", reply))
            session.assistant_turns += 1
            await _safe_ws_send(
                websocket,
                {"type": "assistant_transcript", "text": reply, "assistant_turns": session.assistant_turns},
            )
            pcm = await asyncio.to_thread(_synthesize_controlled, reply, voice)
            await _classic_stream_pcm(websocket, pcm, recorder)
            await _safe_ws_send(
                websocket, {"type": "status", "message": "Connected. Continue speaking any time."}
            )

    def _on_recognized(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        result = evt.result
        if result.reason != speechsdk.ResultReason.RecognizedSpeech:
            return
        text = (result.text or "").strip()
        if not text:
            return
        asyncio.run_coroutine_threadsafe(_classic_turn(text), loop)

    def _on_canceled(evt: speechsdk.SpeechRecognitionCanceledEventArgs) -> None:
        asyncio.run_coroutine_threadsafe(
            _safe_ws_send(websocket, {"type": "status", "message": f"STT canceled: {evt}"}),
            loop,
        )

    recognizer.recognized.connect(_on_recognized)
    recognizer.canceled.connect(_on_canceled)

    try:
        await asyncio.to_thread(lambda: recognizer.start_continuous_recognition_async().get())

        await _safe_ws_send(
            websocket,
            {
                "type": "ready",
                "session_id": session.session_id,
                "pipeline": "classic",
                "model": _classic_llm_model(),
                "voice": voice,
                "transcription_model": "azure-speech",
                "transcription_language": _resolve_transcription_language(),
                "tts": "azure-speech (controlled)",
                "sample_rate": UC3_SAMPLE_RATE,
                "expert_agent_configured": False,
                "billing_agent_configured": False,
                "it_agent_configured": False,
            },
        )

        # Greet the caller (synthesized via Azure Speech TTS).
        welcome = _resolve_welcome()
        session.assistant_turns += 1
        await _safe_ws_send(
            websocket,
            {"type": "assistant_transcript", "text": welcome, "assistant_turns": session.assistant_turns},
        )
        history.append(("assistant", welcome))
        welcome_pcm = await asyncio.to_thread(_synthesize_controlled, welcome, voice)
        await _classic_stream_pcm(websocket, welcome_pcm, recorder)

        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            audio_bytes = message.get("bytes")
            if audio_bytes:
                push_stream.write(audio_bytes)
                recorder.add(audio_bytes, "user")
                continue

            text_message = message.get("text")
            if not text_message:
                continue
            try:
                control = json.loads(text_message)
            except json.JSONDecodeError:
                continue
            action = str(control.get("type") or control.get("action") or "").strip().lower()
            if action == "start_recording":
                recorder.start()
                await _safe_ws_send(websocket, {"type": "recording_started"})
            elif action == "stop_recording":
                await _finish_recording(recorder, websocket)
            elif action in {"end_call", "hangup", "stop"}:
                if recorder.active:
                    await _finish_recording(recorder, websocket)
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - surface pipeline errors to the UI
        await _safe_ws_send(
            websocket,
            {"type": "error", "message": f"Classic pipeline error: {type(exc).__name__}: {exc}"},
        )
    finally:
        with contextlib.suppress(Exception):
            if recorder.active:
                await _finish_recording(recorder, None)
        with contextlib.suppress(Exception):
            push_stream.close()
        with contextlib.suppress(Exception):
            await asyncio.to_thread(lambda: recognizer.stop_continuous_recognition_async().get())
        with contextlib.suppress(Exception):
            await websocket.close()


async def _pump_browser_to_voicelive(
    websocket: WebSocket, connection: Any, recorder: ConversationRecorder
) -> None:
    """Relay microphone audio (and control messages) from the browser to Voice Live."""
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect()

        audio_bytes = message.get("bytes")
        if audio_bytes:
            recorder.add(audio_bytes, "user")
            encoded = base64.b64encode(audio_bytes).decode("ascii")
            await connection.input_audio_buffer.append(audio=encoded)
            continue

        text_message = message.get("text")
        if not text_message:
            continue

        try:
            control = json.loads(text_message)
        except json.JSONDecodeError:
            continue
        action = str(control.get("type") or control.get("action") or "").strip().lower()
        if action == "start_recording":
            recorder.start()
            await _safe_ws_send(websocket, {"type": "recording_started"})
            continue
        if action == "stop_recording":
            await _finish_recording(recorder, websocket)
            continue
        if action in {"end_call", "hangup", "stop"}:
            if recorder.active:
                await _finish_recording(recorder, websocket)
            raise WebSocketDisconnect()
        if action == "clear_audio":
            with contextlib.suppress(Exception):
                await connection.input_audio_buffer.clear()


async def _pump_voicelive_to_browser(
    websocket: WebSocket,
    connection: Any,
    session: VoiceCallSession,
    expert_agent: Any,
    billing_agent: Any,
    it_agent: Any,
    recorder: ConversationRecorder,
    external_tts: bool = False,
    voice: str = "",
) -> None:
    """Relay model audio/transcripts from Voice Live to the browser + run tool calls.

    In external-TTS mode Voice Live emits text only (no ``response.audio.delta``); the
    final ``response.text.done`` text is synthesized by our Azure Speech TTS with
    pronunciation control and streamed back as PCM.
    """
    text_buffer: list[str] = []
    async for event in connection:
        event_type = str(getattr(event, "type", ""))

        if event_type == "response.audio.delta":
            delta = getattr(event, "delta", None)
            if delta:
                pcm = base64.b64decode(delta) if isinstance(delta, str) else bytes(delta)
                recorder.add(pcm, "agent")
                audio_b64 = delta if isinstance(delta, str) else base64.b64encode(pcm).decode("ascii")
                await _safe_ws_send(websocket, {"type": "audio", "audio": audio_b64})

        elif event_type == "response.audio_transcript.delta":
            text = str(getattr(event, "delta", "") or "")
            if text:
                await _safe_ws_send(
                    websocket, {"type": "assistant_transcript_delta", "text": text}
                )

        elif event_type == "response.audio_transcript.done":
            text = str(getattr(event, "transcript", "") or "")
            session.assistant_turns += 1
            await _safe_ws_send(
                websocket,
                {"type": "assistant_transcript", "text": text, "assistant_turns": session.assistant_turns},
            )

        elif event_type == "response.text.delta":
            # Text-only (external-TTS) mode: stream the partial text for live display.
            if external_tts:
                text = str(getattr(event, "delta", "") or "")
                if text:
                    text_buffer.append(text)
                    await _safe_ws_send(
                        websocket, {"type": "assistant_transcript_delta", "text": text}
                    )

        elif event_type == "response.text.done":
            # Text-only (external-TTS) mode: finalize + synthesize with our TTS.
            if external_tts:
                text = str(getattr(event, "text", "") or "").strip() or "".join(text_buffer).strip()
                text_buffer = []
                session.assistant_turns += 1
                await _safe_ws_send(
                    websocket,
                    {"type": "assistant_transcript", "text": text, "assistant_turns": session.assistant_turns},
                )
                if text:
                    pcm = await asyncio.to_thread(_synthesize_controlled, text, voice)
                    await _classic_stream_pcm(websocket, pcm, recorder)

        elif event_type == "conversation.item.input_audio_transcription.completed":
            text = str(getattr(event, "transcript", "") or "")
            session.user_turns += 1
            await _safe_ws_send(
                websocket,
                {"type": "user_transcript", "text": text, "user_turns": session.user_turns},
            )

        elif event_type == "input_audio_buffer.speech_started":
            await _safe_ws_send(websocket, {"type": "speech_started"})

        elif event_type == "input_audio_buffer.speech_stopped":
            await _safe_ws_send(websocket, {"type": "speech_stopped"})

        elif event_type == "response.function_call_arguments.done":
            await _handle_function_call(
                websocket, connection, session, expert_agent, billing_agent, it_agent,
                event, external_tts,
            )

        elif event_type == "error":
            error_message = str(getattr(event, "error", "") or "unknown error")
            await _safe_ws_send(websocket, {"type": "error", "message": error_message})


async def _handle_function_call(
    websocket: WebSocket,
    connection: Any,
    session: VoiceCallSession,
    expert_agent: Any,
    billing_agent: Any,
    it_agent: Any,
    event: Any,
    external_tts: bool = False,
) -> None:
    from azure.ai.voicelive.models import (
        FunctionCallOutputItem,
        Modality,
        ResponseCreateParams,
    )

    call_id = str(getattr(event, "call_id", "") or "")
    name = str(getattr(event, "name", "") or "")
    raw_args = str(getattr(event, "arguments", "") or "{}")
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError:
        args = {}

    def _total_handoffs() -> int:
        return session.expert_handoffs + session.billing_handoffs + session.it_handoffs

    async def _speak_answer(answer: str, agent_label: str, topic: str) -> None:
        await _safe_ws_send(
            websocket,
            {"type": "expert_answer", "agent": agent_label, "topic": topic, "text": answer},
        )
        await connection.conversation.item.create(
            item=FunctionCallOutputItem(call_id=call_id, output=answer)
        )
        # In external-TTS mode the follow-up response is text-only; the resulting
        # response.text.done is synthesized by our Azure Speech TTS (with control).
        await connection.response.create(
            response=ResponseCreateParams(
                modalities=[Modality.TEXT] if external_tts else [Modality.AUDIO, Modality.TEXT]
            )
        )

    if name == BILLING_TOOL_NAME:
        question = str(args.get("question") or "").strip()
        account_ref = str(args.get("account_ref") or "").strip()
        session.billing_handoffs += 1
        await _safe_ws_send(
            websocket,
            {
                "type": "expert_handoff",
                "agent": "billing agent",
                "topic": "billing",
                "question": question,
                "expert_handoffs": _total_handoffs(),
            },
        )
        answer = await _run_billing(billing_agent, question, account_ref)
        await _speak_answer(answer, "billing agent", "billing")
        return

    if name == IT_TOOL_NAME:
        question = str(args.get("question") or "").strip()
        category = str(args.get("category") or "").strip()
        session.it_handoffs += 1
        await _safe_ws_send(
            websocket,
            {
                "type": "expert_handoff",
                "agent": "IT agent",
                "topic": category or "IT",
                "question": question,
                "expert_handoffs": _total_handoffs(),
            },
        )
        answer = await _run_it(it_agent, question, category)
        await _speak_answer(answer, "IT agent", category or "IT")
        return

    if name != EXPERT_TOOL_NAME:
        return

    question = str(args.get("question") or "").strip()
    topic = str(args.get("topic") or "").strip()

    session.expert_handoffs += 1
    await _safe_ws_send(
        websocket,
        {
            "type": "expert_handoff",
            "agent": "expert agent",
            "topic": topic,
            "question": question,
            "expert_handoffs": _total_handoffs(),
        },
    )

    answer = await _run_expert(expert_agent, question, topic)
    await _speak_answer(answer, "expert agent", topic)


def main() -> None:
    load_dotenv(override=False)
    # Quiet the benign INFO logs from the Azure credential chain (e.g.
    # "No environment configuration found" from EnvironmentCredential and the IMDS
    # managed-identity probe). These are normal fallback steps before AzureCliCredential
    # succeeds, but they look like errors in the console.
    for _cred_logger in ("azure.identity", "azure.identity.aio"):
        logging.getLogger(_cred_logger).setLevel(logging.WARNING)
    create_app().run()


if __name__ == "__main__":
    main()
