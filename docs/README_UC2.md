# UC2 Agent Mode

This branch adds a Foundry Agent Framework entrypoint for the real-time call-assistant use case and shares the same Agent Framework runtime helper as UC1.

## What it does

- Accepts live transcript updates over `invocations_ws`
- Uses Microsoft Agent Framework with a Foundry model deployment
- Returns compact assist cards for the agent UI
- Keeps the existing UC1 batch pipeline untouched

## Local setup

```powershell
python -m venv .venv
.
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set the hosted-agent runtime values for local development:

- `VOICE_ASSIST_PROJECT_ENDPOINT`
- `VOICE_ASSIST_MODEL_DEPLOYMENT_NAME`

For portal-agent mode (recommended for Foundry observability), set:

- `VOICE_ASSIST_AGENT_NAME`
- `VOICE_ASSIST_AGENT_VERSION`

If you are running against Azure services locally, sign in first:

```powershell
az login
```

## Run

```powershell
$env:PYTHONPATH = "src"
python -m voiceqa.uc2_main
```

The server listens on `127.0.0.1:8080` by default and exposes `GET /invocations_ws` for the live transcript stream.

Call-center UI is built in:

- Open `http://127.0.0.1:8080/`
- Click Connect
- Start Mic to stream live speaking transcripts
- Click End Call + Summary to request post-call summary
- Runtime Models panel shows STT mode and current LLM/Foundry model
- Token Metrics panel shows STT mode, LLM mode, cumulative audio duration (seconds), request count, and input/output/total tokens (including post-call summary)

STT mode resolution for UC2 is:

1. per-message `stt_service` in payload
2. `VOICE_ASSIST_STT_SERVICE`
3. shared `SPEECH_ENDPOINT` (same endpoint UC1 uses)

Reusable UC2 agent build runbook: `docs/UC2_FOUNDRY_AGENT_PROCEDURE.md`.

## Message shape

Send JSON text frames such as:

```json
{"type":"transcript","call_id":"001","speaker":"agent","text":"...","partial":false}
```

The agent responds with JSON containing `status`, `cards`, optional `summary_markdown`, plus runtime/token metrics fields used by the built-in UI.