# UC2 — Real-time Call Assistant

UC2 *assists a human agent live during the call*: it ingests a rolling transcript, generates compact assist cards (next-best-action / compliance / answer), and can emit an optional post-call Markdown summary reusing the UC1 report format. Built on Microsoft Agent Framework + Foundry runtime.

## Contents
1. [Design](#1-design)
2. [Run](#2-run)
3. [Environment variables & runtime modes](#3-environment-variables--runtime-modes)
4. [UI metrics & message shape](#4-ui-metrics--message-shape)
5. [Foundry agent procedure](#5-foundry-agent-procedure)

---

## 1. Design

### Target hybrid architecture

Core principle: **keep the orchestration loop off the sub-second hot path.**

```
 call line          HOT PATH (sub-second)              Agent screen
 ┌─────────┐ audio ┌──────────────────────────┐ guidance ┌──────────┐
 │ line N   │ ────▶│ Azure Voice Live API     │ ───────▶ │ Assist UI│
 └─────────┘       │  (integrated speech+LLM) │          └──────────┘
                   └───────────┬──────────────┘
        rolling transcript     │ (async, ≤1–2s tolerated)
                               ▼
                    ┌────────────────────────────┐
                    │ Hosted Agent (async assist) │
                    │ KB/CRM · compliance · NBA   │
                    └────────────────────────────┘
```

- **Hot path → Azure Voice Live API** for the time-critical turn-by-turn interaction.
- **Async assist → hosted/managed agent** (retrieval, compliance, next-best-action), ≤1–2s, never blocks the hot path.
- Current repo baseline is Foundry WebSocket mode (`voiceqa.uc2_main`); it can evolve toward this hybrid.

### Components
- **Audio ingest** — one streaming session per line (designed for 10 concurrent), continuous recognition with interim results.
- **Real-time STT** — real-time ($1.00/audio-hr) + Continuous LID ($0.30/hr); reuses UC1's Phrase List + `corrections.json`; diarization optional (+$0.30/hr, off by default).
- **Live-assist engine** — cadence ≈ 1 assist / 5 min of talk (~2,500 in / 200 out tokens per turn); trigger-based invocation can cut it further. Outputs `{ type: next_best_action | compliance | answer, text, source }`.
- **Hosted agent** — tools for KB/CRM retrieval, compliance, NBA; latency budget ≤1–2s.
- **Assist UI** — renders advisory cards; the agent decides.
- **(Optional) post-call summarizer** — runs the transcript through the UC1 rubric/judge → shared Markdown report.

### Voice optimization skills (implemented in [../src/voiceqa/uc2_live_assistant.py](../src/voiceqa/uc2_live_assistant.py))

| Skill | What it does | Where to configure |
|---|---|---|
| Real-time speaker diarization | Browser streams PCM over `/audio_ws`; server runs `ConversationTranscriber` and labels segments by speaker. | Automatic on Start Mic. |
| Auto agent/customer mapping | First speaker → Agent, second → Customer, stable for the call. | Automatic; Swap if reversed. |
| Continuous Language ID | `AutoDetectSourceLanguageConfig` detects zh-TW vs en-US per utterance. | `SPEECH_LANGUAGES`. |
| PCM audio streaming | Mic downsampled in-browser to 16 kHz/16-bit/mono, streamed frame-by-frame. | Automatic. |
| Rolling transcript window | Keeps the most recent N turns as assist context. | `VOICE_ASSIST_WINDOW_TURNS` (default 12). |
| Shared Speech auth ladder | Reuses UC1 auth (endpoint+key, keyless Entra ID, key+region) + optional Custom Speech. | `SPEECH_ENDPOINT`/`SPEECH_KEY`/`SPEECH_REGION`, `SPEECH_CUSTOM_ENDPOINT_ID`. |
| STT provider label | STT service name shown in metrics UI. | `[uc2].provider` or `VOICE_ASSIST_STT_SERVICE`. |

### Resilience
STT stream drop → auto-reconnect, degrade to "assist paused". Agent retrieval timeout → return last-known context / graceful "no suggestion", never stall the hot path. All assist is advisory — a component failure reduces help but never blocks the human agent. For the **target hybrid architecture**, the same principle applies: keep any orchestration dependency off the latency-critical speech path.

### Screenshots
![UC2 live call console](images/04_uc2_live-console.png)
![UC2 live call console in call](images/05_uc2_live-console_incall.png)
![UC2 call summary](images/06_uc2_live-console_callsummary.png)

---

## 2. Run

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt; az login
$env:PYTHONPATH = "src"
python -m voiceqa.uc2_main      # or: .\start_uc2.ps1
```

Server defaults: HTTP UI `http://127.0.0.1:8080/`, WebSocket `ws://127.0.0.1:8080/invocations_ws`.

From the consolidated dashboard: `.\start_voice_ui.ps1`, then open `/uc2/live`. If `PORT` is unset the script picks a free port. The header has a language switch (English/繁體中文) and STT method label.

**Startup checklist:** `az login` OK · `.env` has valid `VOICE_ASSIST_*` · server on 8080 · browser opens the UI · Connect shows `Connected`.

---

## 3. Environment variables & runtime modes

Two runtime modes:
1. **Portal agent mode (recommended)** — set `VOICE_ASSIST_AGENT_NAME` + `VOICE_ASSIST_AGENT_VERSION`.
2. **Model deployment mode** — set `VOICE_ASSIST_MODEL_DEPLOYMENT_NAME` (or fallback deployment vars).

Required: `VOICE_ASSIST_PROJECT_ENDPOINT` plus either the portal-agent values or the deployment value. Compatibility aliases: `FOUNDRY_VOICE_ASSIST_AGENT_NAME`, `FOUNDRY_VOICE_ASSIST_AGENT_VERSION`.

---

## 4. UI metrics & message shape

**Runtime Models panel:** STT mode label, LLM/Foundry model label.
**Token Metrics panel:** STT mode, LLM mode, cumulative audio duration (s), LLM request count, session total tokens, last-request tokens.

**STT mode resolution order:** (1) per-message `stt_service` in payload → (2) `VOICE_ASSIST_STT_SERVICE` → (3) shared `SPEECH_ENDPOINT` (same endpoint UC1 uses).

Transcript message:
```json
{ "type": "transcript", "call_id": "001", "speaker": "agent", "text": "...", "partial": false }
```
Response includes `status`, `cards`, optional `summary_markdown`, plus runtime/token metric fields.

### Method selection and optimization code map

| What you want to adjust | Code entry point |
|---|---|
| Audio WS diarization path (`/audio_ws`) and control events (`swap_speakers`, `reset`, `end_call`) | [../src/voiceqa/uc2_live_assistant.py](../src/voiceqa/uc2_live_assistant.py) (`_handle_audio_ws`) |
| Invocation WS/HTTP assist path (`/invocations_ws` and invoke handler) | [../src/voiceqa/uc2_live_assistant.py](../src/voiceqa/uc2_live_assistant.py) (`create_app`, `@app.ws_handler`, `@app.invoke_handler`) |
| Browser client WS routing (invocation vs audio stream) | [../assets/uc2_call_center_ui.html](../assets/uc2_call_center_ui.html) (`wsUrl()`, `audioWsUrl()`) |
| STT method/provider label resolution in UI metrics | [../src/voiceqa/uc2_live_assistant.py](../src/voiceqa/uc2_live_assistant.py) (`_resolve_speech_model_label`) |
| Rolling context and card count tuning | [../src/voiceqa/uc2_live_assistant.py](../src/voiceqa/uc2_live_assistant.py) (`VOICE_ASSIST_WINDOW_TURNS`, `VOICE_ASSIST_MAX_CARDS`) |
| Speaker role mapping and manual swap behavior | [../src/voiceqa/uc2_live_assistant.py](../src/voiceqa/uc2_live_assistant.py) (`_assign_speaker_role`, `_swap_speaker_roles`) |
| LLM runtime mode (Foundry agent vs model deployment) | [../src/voiceqa/uc2_live_assistant.py](../src/voiceqa/uc2_live_assistant.py) (`_resolve_agent_name`, `_resolve_model_deployment`, `build_agent`) |

---

## 5. Foundry agent procedure

**Prerequisites:** `az login`; venv active; `.env` has `FOUNDRY_PROJECT_ENDPOINT` (or `VOICE_ASSIST_PROJECT_ENDPOINT`), `VOICE_ASSIST_MODEL_DEPLOYMENT_NAME` (or `FOUNDRY_MODEL_DEPLOYMENT_NAME`), optional `VOICE_ASSIST_PROMPT_PATH` (default `assets/uc2_agent_prompt.txt`).

**Create/update the agent version:**
```powershell
$env:PYTHONPATH = "src"
python scripts/build_uc2_foundry_agent.py
```
Creates a new immutable version under the UC2 agent name.

**Pin runtime** (`.env`):
```env
FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
VOICE_ASSIST_AGENT_NAME=voicecall-uc2-assistant
VOICE_ASSIST_AGENT_VERSION=<new-version>
# aliases also accepted:
FOUNDRY_VOICE_ASSIST_AGENT_NAME=voicecall-uc2-assistant
FOUNDRY_VOICE_ASSIST_AGENT_VERSION=<new-version>
```
If `VOICE_ASSIST_AGENT_NAME` is set, UC2 uses portal-agent mode.

**Verify:** `.\start_uc2.ps1` → server on 127.0.0.1:8080, portal shows agent activity.

**Optional overrides:**
```powershell
python scripts/build_uc2_foundry_agent.py `
  --project-endpoint "https://<resource>.services.ai.azure.com/api/projects/<project>" `
  --agent-name "voicecall-uc2-assistant" --model "gpt-5.4" `
  --prompt-file "assets/uc2_agent_prompt.txt" --description "UC2 real-time assistant" --temperature 0
```
</content>
