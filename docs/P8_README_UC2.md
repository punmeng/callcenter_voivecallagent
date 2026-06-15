# UC2 Real-Time Assistant

UC2 is the live call-assistant path. It uses Microsoft Agent Framework and Foundry runtime settings, while keeping UC1 batch processing unchanged.

## What UC2 does

- Receives live transcript messages over the WebSocket endpoint `/invocations_ws`.
- Generates compact assist cards for agent guidance.
- Supports optional post-call summary generation.
- Reports runtime and usage metrics in the built-in UI.

## Runtime modes

UC2 supports two runtime modes:

1. Portal agent mode (recommended)
	- Set `VOICE_ASSIST_AGENT_NAME` and `VOICE_ASSIST_AGENT_VERSION`.
2. Model deployment mode
	- Set `VOICE_ASSIST_MODEL_DEPLOYMENT_NAME` (or fallback deployment variables).

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
az login
```

Required environment values:

- `VOICE_ASSIST_PROJECT_ENDPOINT`
- Either portal-agent values (`VOICE_ASSIST_AGENT_NAME`, `VOICE_ASSIST_AGENT_VERSION`) or deployment value (`VOICE_ASSIST_MODEL_DEPLOYMENT_NAME`)

Optional compatibility values accepted by runtime:

- `FOUNDRY_VOICE_ASSIST_AGENT_NAME`
- `FOUNDRY_VOICE_ASSIST_AGENT_VERSION`

## Run

```powershell
$env:PYTHONPATH = "src"
python -m voiceqa.uc2_main
```

Server default:

- HTTP UI: `http://127.0.0.1:8080/`
- WebSocket: `ws://127.0.0.1:8080/invocations_ws`

## Run from consolidated dashboard

You can also run UC2 from the shared dashboard:

```powershell
.\start_voice_ui.ps1
```

Then open `http://127.0.0.1:<PORT>/uc2/live` from the dashboard home.

- If `PORT` is not set, the script picks an available local port automatically.
- The dashboard header includes language switch (English/繁體中文) and STT method label.

## Screenshots

Live call console (idle):

![UC2 live call console](images/04_uc2_live-console.png)

During an active call:

![UC2 live call console in call](images/05_uc2_live-console_incall.png)

Post-call summary:

![UC2 live call console call summary](images/06_uc2_live-console_callsummary.png)

## Startup checklist

- `az login` is successful.
- `.env` contains valid `VOICE_ASSIST_*` settings.
- UC2 server is running on port `8080`.
- Browser can open `http://127.0.0.1:8080/`.
- Click Connect in UI and verify connection status is `Connected`.

## Built-in UI metrics

Runtime Models panel:

- STT mode label
- LLM/Foundry model label

Token Metrics panel:

- STT mode
- LLM mode
- Cumulative audio duration (seconds)
- LLM request count
- Session total tokens (input/output/total)
- Last request tokens (input/output/total)

STT mode resolution order in UC2:

1. Per-message `stt_service` in payload
2. `VOICE_ASSIST_STT_SERVICE`
3. Shared `SPEECH_ENDPOINT` (same endpoint UC1 uses)

Reusable build runbook:

- `docs/P10_UC2_FOUNDRY_AGENT_PROCEDURE.md`

## Message shape

Example transcript message:

```json
{
  "type": "transcript",
  "call_id": "001",
  "speaker": "agent",
  "text": "...",
  "partial": false
}
```

Response includes `status`, `cards`, optional `summary_markdown`, plus runtime and token metric fields consumed by the UI.