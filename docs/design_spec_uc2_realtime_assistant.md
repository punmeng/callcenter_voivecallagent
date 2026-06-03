# Software Design Spec — UC2: Real-time Call Assistant

> Version 0.2 · 2026-06-04 · Author: Alex Pun
> Use Case 2 (Call Assistant, real-time streaming). **Input:** live audio stream or live transcript stream per active call line. **Output:** on-screen guidance to the agent during the call (plus an optional post-call Markdown summary).
> This document describes the **target hybrid architecture**. Current repo implementation is UC2 Foundry WebSocket mode (`voiceqa.uc2_main`) and can evolve toward this target.

---

## 1. Purpose

Help the call-center agent **live, during the call** — surface next-best-action prompts, compliance reminders, and answer lookups in near real time, driven by a rolling transcript of the conversation.

## 2. Scope

**In scope**
- Ingest live audio per active call line.
- Stream transcription (zh-TW + en-US code-switching) with partial results.
- Generate live-assist suggestions on a controlled cadence.
- Render guidance to the agent's screen during the call.
- (Optional) emit a post-call Markdown summary, reusing the UC1 report format.

**Out of scope**
- Offline batch QA scoring (that is UC1).
- Auto-actioning anything in CRM without agent confirmation.
- Customer-facing automation / IVR replacement.

## 3. High-level architecture (hybrid)

The core principle: **keep the orchestration loop off the sub-second hot path.**

```
 Telephony / call line                 HOT PATH (sub-second)                Agent screen
 ┌──────────────────┐   audio    ┌────────────────────────────────┐  guidance  ┌────────────┐
 │ active line N     │ ────────▶ │ Azure Voice Live API           │ ─────────▶ │ Assist UI  │
 │ (streaming)       │           │  (integrated speech + LLM)     │            │            │
 └──────────────────┘           └───────────────┬────────────────┘            └────────────┘
                                  rolling transcript │ (async, ≤1–2s tolerated)
                                                     ▼
                                       ┌────────────────────────────┐
                                       │ Hosted Agent (async assist)│
                                       │ • KB / CRM retrieval        │
                                       │ • compliance checks         │
                                       │ • next-best-action          │
                                       └────────────────────────────┘
```

- **Hot path → Azure Voice Live API:** integrated low-latency speech + LLM for the time-critical turn-by-turn interaction.
- **Async assist → hosted/managed agent:** the heavier work (retrieval, compliance, next-best-action) that tolerates 1–2s and benefits from managed tools, state, and observability — deliberately kept off the latency-critical path.

This split is the recommendation already captured in `architecture.md` § Hosting & deployment.

## 4. Components

### 4.1 Audio Ingest (per line)
- One streaming session per active call line; designed for 10 concurrent lines.
- Continuous recognition, partial (interim) results enabled.
- **Auth:** Managed Identity preferred.

### 4.2 Real-time STT (Azure AI Speech, streaming)
- **Mode:** real-time ($1.00/audio-hr) + **Continuous LID** add-on ($0.30/hr) for live code-switching.
- **Reuses UC1 assets:** the same Phrase List and `corrections.json` tuning, applied to streaming results.
- **Diarization:** only if the assist logic needs to distinguish speakers (+$0.30/hr) — off by default.
- **Output:** a rolling, speaker-aware transcript window.

### 4.3 Live-Assist Engine
- **Cadence (the main cost/latency driver):** generate a suggestion roughly once per conversation turn — design point is **1 assist / 5 min of talk** (≈ 2,500 in / 200 out tokens per turn). Trigger-based invocation (only on key phrases/intents) can cut this further.
- **Inputs:** rolling transcript window + retrieved context from the hosted agent.
- **Outputs:** structured assist cards — `{ type: next_best_action | compliance | answer, text, source }`.

### 4.4 Hosted Agent (async assist)
- Managed-agent runtime providing tools, state, and observability.
- **Tools:** KB / CRM retrieval, compliance rule checks, next-best-action ranking.
- **Latency budget:** ≤ 1–2s; never blocks the hot path.

### 4.5 Assist UI
- Renders assist cards to the agent's screen in real time.
- Non-intrusive: suggestions are advisory; the agent decides.

### 4.6 (Optional) Post-call Summarizer
- After call end, run the rolling transcript through the **UC1 rubric/judge** and emit a Markdown report — one shared report format across both use cases.

## 5. Data flow & interfaces

| Stage | Input | Output | Latency target |
|---|---|---|---|
| Audio Ingest | line audio stream | audio frames | continuous |
| Real-time STT | audio frames | rolling transcript | sub-second |
| Live-Assist Engine | transcript window + context | assist cards | sub-second (hot path) |
| Hosted Agent | transcript window | retrieved context | ≤ 1–2s (async) |
| Assist UI | assist cards | on-screen guidance | sub-second |
| Post-call Summarizer | full transcript + rubric | `.md` report | offline |

## 6. Configuration

| Setting | Purpose |
|---|---|
| `VOICE_LIVE_ENDPOINT` | Azure Voice Live API (hot path) |
| `SPEECH_ENDPOINT` / MI | real-time STT + Continuous LID |
| `AGENT_ENDPOINT` | hosted agent for async assist |
| `ASSIST_CADENCE` | turn interval or trigger mode |
| `MAX_CONCURRENT_LINES` | default 10 |
| `ENABLE_DIARIZATION` | off by default (+cost) |
| `ENABLE_POSTCALL_SUMMARY` | run UC1 judge after call end |

## 7. Error handling & resilience

- **STT stream drop:** auto-reconnect; buffer audio briefly; degrade to "assist paused" rather than failing the call.
- **Agent retrieval timeout:** return last-known context or a graceful "no suggestion" — never stall the hot path waiting on async assist.
- **Voice Live unavailable:** fall back to STT + a separate LLM call (higher latency, flagged in the UI as degraded mode).
- **Backpressure at 10 lines:** prioritize hot-path STT/assist; shed/queue async retrieval first.
- All assist is advisory — a component failure reduces help but never blocks the human agent.

## 8. Non-functional notes

- **Latency:** sub-second on the hot path is the hard requirement; async assist ≤ 1–2s.
- **Cost (per the cost estimate):** at 2,400 audio-hr/mo —
  - STT: PAYG ≈ $3,120, or commitment tier ≈ $2,480 (saves ≈ $640/mo).
  - Live-assist LLM: ≈ $38/mo (GPT-4.1-mini) to ≈ $533/mo (GPT-5.5).
  - **Monthly total ≈ $2,518–3,653** depending on STT plan + model.
- **Scaling:** one streaming session per line; horizontal across lines.
- **Security:** Managed Identity for all Azure services; no PII persisted beyond the call unless the post-call summary is enabled (then governed by retention policy).

## 9. UC1 vs UC2 at a glance

| | UC1 — Quality Check | UC2 — Call Assistant |
|---|---|---|
| Timing | After call (batch) | During call (real-time) |
| STT mode | Batch ($0.18/hr) | Real-time ($1.00/hr) + LID |
| Input | Audio blob | Live audio stream |
| Output | Markdown report | On-screen guidance (+ optional MD summary) |
| Runtime | Serverless batch job | Hybrid: Voice Live hot path + hosted agent |
| Latency | Minutes–hours OK | Sub-second |
| Cost/mo | ≈ $33–335 | ≈ $2,518–3,653 |
| Status | Implemented | Implemented baseline (Foundry WebSocket), hybrid design in planning |

## 10. Open questions

1. **Assist cadence** — fixed turn interval vs trigger-based (key-phrase/intent) invocation?
2. **Retrieval scope** — which KB/CRM systems, and how is freshness handled?
3. **Voice Live API** — confirm it meets the sub-second target for zh-TW + en-US at 10 concurrent lines.
4. **Post-call summary** — enable the shared UC1 Markdown report by default, or opt-in per deployment?
5. **Model choice** — GPT-5.5 vs GPT-4.1-mini for live assist, per the cost tradeoff.
