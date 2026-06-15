from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_framework import Agent
from azure.ai.agentserver.invocations import InvocationAgentServerHost
from dotenv import load_dotenv
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route
from starlette.websockets import WebSocket

from .agent_runtime import build_foundry_agent


_UI_HTML_PATH = Path("assets/uc2_call_center_ui.html")


@dataclass
class AssistMessage:
    speaker: str
    text: str
    kind: str = "transcript"


@dataclass
class LiveAssistSession:
    session_id: str
    call_id: str | None = None
    messages: list[AssistMessage] = field(default_factory=list)
    last_response: dict[str, Any] | None = None
    llm_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    llm_latency_total_ms: float = 0.0
    audio_duration_seconds: float = 0.0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def add_message(self, speaker: str, text: str, kind: str = "transcript") -> None:
        cleaned_text = text.strip()
        if not cleaned_text:
            return

        self.messages.append(AssistMessage(speaker=speaker.strip() or "unknown", text=cleaned_text, kind=kind))
        self.updated_at = datetime.now(timezone.utc)

    def render_window(self, max_messages: int) -> str:
        window = self.messages[-max_messages:]
        if not window:
            return "(no transcript yet)"

        lines: list[str] = []
        for message in window:
            lines.append(f"{message.speaker}: {message.text}")
        return "\n".join(lines)


def build_agent() -> Agent:
    project_endpoint = _resolve_project_endpoint()
    agent_name = _resolve_agent_name()
    agent_version = _resolve_agent_version()
    model_deployment = _resolve_model_deployment()
    return build_foundry_agent(
        name="VoiceCallAssistant",
        instructions=_load_prompt(),
        project_endpoint=project_endpoint,
        agent_name=agent_name,
        agent_version=agent_version,
        model=model_deployment,
    )


def create_app() -> InvocationAgentServerHost:
    app = InvocationAgentServerHost(routes=[Route("/", _serve_ui, methods=["GET"], name="uc2_ui")])
    agent = build_agent()
    sessions: dict[str, LiveAssistSession] = {}

    @app.invoke_handler
    async def invoke(request: Request) -> JSONResponse | Response:
        payload = await request.json()
        session_id = _resolve_session_id(request, payload)
        response = await _run_assist(agent, sessions, session_id, payload)
        return JSONResponse(response)

    @app.ws_handler
    async def ws(websocket: WebSocket) -> None:
        session_id = _resolve_ws_session_id(websocket)
        async for raw_message in websocket.iter_text():
            payload = _safe_json_loads(raw_message)
            response = await _run_assist(agent, sessions, session_id, payload)
            await websocket.send_text(json.dumps(response, ensure_ascii=False))

    return app


async def _serve_ui(_: Request) -> HTMLResponse:
    if _UI_HTML_PATH.exists() and _UI_HTML_PATH.is_file():
        return HTMLResponse(_UI_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>UC2 UI not found</h1><p>Expected assets/uc2_call_center_ui.html</p>", status_code=500)


def main() -> None:
    load_dotenv(override=False)
    create_app().run()


async def _run_assist(
    agent: Agent,
    sessions: dict[str, LiveAssistSession],
    session_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    session = sessions.setdefault(session_id, LiveAssistSession(session_id=session_id))

    event_type = str(payload.get("event") or payload.get("type") or "transcript").strip().lower()
    call_id = str(payload.get("call_id") or session.call_id or session_id).strip()
    if call_id:
        session.call_id = call_id

    if event_type == "reset":
        session.messages.clear()
        session.last_response = None
        session.llm_requests = 0
        session.input_tokens = 0
        session.output_tokens = 0
        session.total_tokens = 0
        session.llm_latency_total_ms = 0.0
        session.audio_duration_seconds = 0.0
        session.updated_at = datetime.now(timezone.utc)
        return {
            "session_id": session.session_id,
            "call_id": session.call_id,
            "status": "reset",
            "cards": [],
            "summary_markdown": None,
            "runtime": {
                "speech_model": _resolve_speech_model_label(payload),
                "llm_model": _resolve_llm_model_label(),
            },
            "token_metrics": _build_token_metrics(payload, session, 0, 0, 0, 0.0, "reset"),
        }

    speaker = str(payload.get("speaker") or payload.get("role") or "transcript").strip() or "transcript"
    text = str(payload.get("text") or payload.get("transcript") or "").strip()
    if text:
        session.add_message(speaker=speaker, text=text, kind=event_type)
    
    # Track audio duration from payload
    audio_duration = _coerce_float(payload.get("audio_duration_seconds"))
    if audio_duration > 0:
        session.audio_duration_seconds += audio_duration

    window_size = _resolve_int_env("VOICE_ASSIST_WINDOW_TURNS", 12)
    max_cards = _resolve_int_env("VOICE_ASSIST_MAX_CARDS", 3)
    transcript_window = session.render_window(window_size)
    summary_mode = event_type in {"end_call", "summary", "post_call"}
    should_invoke, skip_status = _should_invoke_assistant(payload, text=text, summary_mode=summary_mode)

    if not should_invoke:
        response = _build_passthrough_response(session, payload, status=skip_status)
        session.updated_at = datetime.now(timezone.utc)
        return response

    prompt = _build_prompt(
        session=session,
        payload=payload,
        transcript_window=transcript_window,
        max_cards=max_cards,
        summary_mode=summary_mode,
    )
    started = time.perf_counter()
    result = await agent.run(prompt)
    llm_latency_ms = (time.perf_counter() - started) * 1000
    parsed = _safe_json_loads(result.text or "")
    last_input_tokens, last_output_tokens, last_total_tokens = _extract_usage_from_response(result)
    session.llm_requests += 1
    session.input_tokens += last_input_tokens
    session.output_tokens += last_output_tokens
    session.total_tokens += last_total_tokens
    session.llm_latency_total_ms += llm_latency_ms

    response = _normalize_response(parsed, session, max_cards=max_cards, summary_mode=summary_mode)
    response["runtime"] = {
        "speech_model": _resolve_speech_model_label(payload),
        "llm_model": _resolve_llm_model_label(),
    }
    response["token_metrics"] = _build_token_metrics(
        payload,
        session,
        last_input_tokens,
        last_output_tokens,
        last_total_tokens,
        llm_latency_ms,
        "executed",
    )

    session.last_response = response
    session.updated_at = datetime.now(timezone.utc)
    return response


def _should_invoke_assistant(payload: dict[str, Any], *, text: str, summary_mode: bool) -> tuple[bool, str]:
    if summary_mode:
        return True, "summary"

    if _coerce_bool(payload.get("partial")):
        return False, "partial_transcript"

    if not text.strip():
        return False, "waiting_for_transcript"

    return True, "executed"


def _build_passthrough_response(
    session: LiveAssistSession,
    payload: dict[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    previous = session.last_response or {}
    response = {
        "session_id": session.session_id,
        "call_id": session.call_id or session.session_id,
        "status": status,
        "cards": previous.get("cards") if isinstance(previous.get("cards"), list) else [],
        "summary_markdown": previous.get("summary_markdown") if isinstance(previous.get("summary_markdown"), str) else None,
        "runtime": {
            "speech_model": _resolve_speech_model_label(payload),
            "llm_model": _resolve_llm_model_label(),
        },
        "token_metrics": _build_token_metrics(payload, session, 0, 0, 0, 0.0, status),
    }
    return response


def _build_token_metrics(
    payload: dict[str, Any],
    session: LiveAssistSession,
    last_input_tokens: int,
    last_output_tokens: int,
    last_total_tokens: int,
    last_latency_ms: float,
    last_request_status: str,
) -> dict[str, Any]:
    avg_latency_ms = session.llm_latency_total_ms / session.llm_requests if session.llm_requests else 0.0
    return {
        "llm_requests": session.llm_requests,
        "audio_duration_seconds": round(session.audio_duration_seconds, 2),
        "speech_model": _resolve_speech_model_label(payload),
        "llm_model": _resolve_llm_model_label(),
        "avg_llm_latency_ms": round(avg_latency_ms, 2),
        "last_request": {
            "status": last_request_status,
            "input_tokens": last_input_tokens,
            "output_tokens": last_output_tokens,
            "total_tokens": last_total_tokens,
            "latency_ms": round(last_latency_ms, 2),
        },
        "session_total": {
            "input_tokens": session.input_tokens,
            "output_tokens": session.output_tokens,
            "total_tokens": session.total_tokens,
        },
    }


def _build_prompt(
    session: LiveAssistSession,
    payload: dict[str, Any],
    transcript_window: str,
    max_cards: int,
    summary_mode: bool,
) -> str:
    task = "post-call summary" if summary_mode else "real-time assist"
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        "You are VoiceCall Assistant, a real-time call-center copilot.\n"
        "Help the human agent, do not speak to the customer, and keep guidance concise.\n"
        "Output strict JSON only with these keys: session_id, call_id, status, cards, summary_markdown.\n"
        "cards must be an array of 0 to "
        f"{max_cards} objects with keys type, text, source.\n"
        "Allowed card types are next_best_action, compliance, answer.\n"
        "If the task is post-call summary, summary_markdown may contain a short Traditional Chinese Markdown recap.\n"
        "Otherwise summary_markdown must be null.\n\n"
        f"Task: {task}\n"
        f"Session ID: {session.session_id}\n"
        f"Call ID: {session.call_id or ''}\n\n"
        f"Latest payload:\n{payload_json}\n\n"
        f"Rolling transcript window:\n{transcript_window}\n"
    )


def _normalize_response(
    parsed: dict[str, Any],
    session: LiveAssistSession,
    *,
    max_cards: int,
    summary_mode: bool,
) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    raw_cards = parsed.get("cards")
    if isinstance(raw_cards, list):
        for raw_card in raw_cards[:max_cards]:
            if not isinstance(raw_card, dict):
                continue
            card_type = str(raw_card.get("type") or "next_best_action").strip() or "next_best_action"
            text = str(raw_card.get("text") or "").strip()
            source = str(raw_card.get("source") or "voice-call-assistant").strip() or "voice-call-assistant"
            if text:
                cards.append({"type": card_type, "text": text, "source": source})

    summary_markdown = parsed.get("summary_markdown") if summary_mode else None
    if not isinstance(summary_markdown, str):
        summary_markdown = None
    else:
        summary_markdown = summary_markdown.strip() or None

    status = str(parsed.get("status") or ("summary" if summary_mode else "ok")).strip() or "ok"

    response = {
        "session_id": str(parsed.get("session_id") or session.session_id),
        "call_id": str(parsed.get("call_id") or session.call_id or session.session_id),
        "status": status,
        "cards": cards,
        "summary_markdown": summary_markdown,
    }

    if not response["cards"] and not summary_markdown:
        response["cards"] = [
            {
                "type": "next_best_action",
                "text": "等待更多逐字稿後再提供下一步建議。",
                "source": "fallback",
            }
        ]
        response["status"] = "needs_more_context"

    return response


def _resolve_session_id(request: Request, payload: dict[str, Any]) -> str:
    explicit = str(payload.get("session_id") or payload.get("agent_session_id") or "").strip()
    if explicit:
        return explicit
    session_id = request.headers.get("x-agent-session-id")
    if session_id:
        return session_id
    return str(getattr(request.state, "session_id", "http-session"))


def _resolve_ws_session_id(websocket: WebSocket) -> str:
    explicit = str(websocket.query_params.get("agent_session_id") or "").strip()
    if explicit:
        return explicit

    env_session_id = os.getenv("FOUNDRY_AGENT_SESSION_ID")
    if env_session_id:
        return env_session_id

    return str(websocket.headers.get("x-agent-session-id") or "ws-session")


def _load_prompt() -> str:
    prompt_path = Path(os.getenv("VOICE_ASSIST_PROMPT_PATH", "assets/uc2_agent_prompt.txt"))
    if prompt_path.exists() and prompt_path.is_file():
        return prompt_path.read_text(encoding="utf-8").strip()
    return (
        "You are a concise call-center copilot for live agent assistance. "
        "Prioritize compliance, next-best-action, and customer empathy."
    )


def _resolve_project_endpoint() -> str:
    value = (
        os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        or os.getenv("VOICE_ASSIST_PROJECT_ENDPOINT")
        or os.getenv("AZURE_AI_PROJECT_ENDPOINT")
        or os.getenv("AZURE_AIPROJECT_ENDPOINT")
        or ""
    ).strip()
    if not value:
        raise ValueError(
            "Set FOUNDRY_PROJECT_ENDPOINT or VOICE_ASSIST_PROJECT_ENDPOINT to create the Foundry chat client."
        )
    return value


def _resolve_model_deployment() -> str:
    value = (
        os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME")
        or os.getenv("VOICE_ASSIST_MODEL_DEPLOYMENT_NAME")
        or os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
        or os.getenv("AZURE_AI_DEPLOYMENT_NAME")
        or ""
    ).strip()
    if not value:
        if _resolve_agent_name():
            return ""
        raise ValueError(
            "Set FOUNDRY_MODEL_DEPLOYMENT_NAME or VOICE_ASSIST_MODEL_DEPLOYMENT_NAME for the model deployment."
        )
    return value


def _resolve_agent_name() -> str | None:
    value = (
        os.getenv("VOICE_ASSIST_AGENT_NAME")
        or os.getenv("FOUNDRY_VOICE_ASSIST_AGENT_NAME")
        or ""
    ).strip()
    return value or None


def _resolve_agent_version() -> str | None:
    value = (
        os.getenv("VOICE_ASSIST_AGENT_VERSION")
        or os.getenv("FOUNDRY_VOICE_ASSIST_AGENT_VERSION")
        or ""
    ).strip()
    return value or None


def _resolve_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return max(1, int(raw_value))
    except ValueError:
        return default


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _extract_usage(payload: Any) -> tuple[int, int, int] | None:
    if not isinstance(payload, dict):
        return None

    input_tokens = 0
    output_tokens = 0
    total_tokens = 0

    for key in ("input_token_count", "input_tokens", "prompt_tokens", "inputTokenCount", "promptTokenCount"):
        if key in payload:
            input_tokens = _coerce_int(payload.get(key))
            break

    for key in ("output_token_count", "output_tokens", "completion_tokens", "outputTokenCount", "completionTokenCount"):
        if key in payload:
            output_tokens = _coerce_int(payload.get(key))
            break

    for key in ("total_token_count", "total_tokens", "totalTokenCount"):
        if key in payload:
            total_tokens = _coerce_int(payload.get(key))
            break

    if total_tokens <= 0 and (input_tokens > 0 or output_tokens > 0):
        total_tokens = input_tokens + output_tokens

    if input_tokens <= 0 and output_tokens <= 0 and total_tokens <= 0:
        return None

    return input_tokens, output_tokens, total_tokens


def _extract_usage_from_response(response: Any) -> tuple[int, int, int]:
    candidates: list[dict[str, Any]] = []

    usage_details = getattr(response, "usage_details", None)
    if isinstance(usage_details, dict):
        candidates.append(usage_details)

    usage = getattr(response, "usage", None)
    if isinstance(usage, dict):
        candidates.append(usage)
    elif usage is not None:
        candidates.append(
            {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0),
                "total_tokens": getattr(usage, "total_tokens", 0),
            }
        )

    metadata = getattr(response, "metadata", None)
    if isinstance(metadata, dict):
        for key in ("usage", "usage_details", "model_usage", "modelUsage", "token_usage", "tokenUsage"):
            nested = metadata.get(key)
            if isinstance(nested, dict):
                candidates.append(nested)

    for payload in candidates:
        parsed = _extract_usage(payload)
        if parsed:
            return parsed

    return 0, 0, 0


def _resolve_speech_model_label(payload: dict[str, Any]) -> str:
    # Check if using Azure Speech Service
    # Priority: payload → VOICE_ASSIST_STT_SERVICE → SPEECH_ENDPOINT (shared with UC1) → stt_config.toml
    stt_service = (
        str(payload.get("stt_service") or "").strip().lower()
        or str(os.getenv("VOICE_ASSIST_STT_SERVICE") or "").strip().lower()
        or str(os.getenv("SPEECH_ENDPOINT") or "").strip().lower()
    )
    if stt_service and "azure" in stt_service:
        stt_model = str(payload.get("stt_model") or os.getenv("VOICE_ASSIST_STT_MODEL") or "Azure Speech - Text to Speech").strip()
        return f"Azure Speech Service ({stt_model})"

    payload_label = str(payload.get("speech_model") or "").strip()
    if payload_label:
        return payload_label

    speech_language = str(payload.get("speech_language") or "").strip()
    if speech_language:
        return f"Browser Web Speech API ({speech_language})"

    # Fall back to stt_config.toml [uc2].provider so the UI label matches the config.
    try:
        from .stt_config import load_stt_config, provider_to_display_label
        cfg = load_stt_config()
        return provider_to_display_label(cfg.uc2.provider)
    except Exception:
        pass

    return "Browser Web Speech API"


def _resolve_llm_model_label() -> str:
    agent_name = _resolve_agent_name()
    agent_version = _resolve_agent_version() or "latest"
    if agent_name:
        return f"Foundry Agent: {agent_name} (v{agent_version})"

    model = _resolve_model_deployment()
    if model:
        # Try to extract model name from deployment
        # Common patterns: gpt-4, gpt-4-turbo, gpt-5.4, etc.
        model_name = model.lower().strip()
        if "gpt" in model_name or "claude" in model_name or "llama" in model_name:
            return f"Foundry Deployment: {model_name}"
        return f"Foundry Model: {model}"

    return "Unknown"


def _safe_json_loads(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    if not cleaned:
        return {}

    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}