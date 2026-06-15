# Scope & Method — VoiceQA Agent

> Status: draft for alignment · Owner: Alex Pun · Last updated: 2026-06-02

This document clarifies **what the system does**, **how it does it**, and **where the
two business cases differ**. It is the shared reference before coding/estimation sign-off.

---

## 1. Problem statement

Call-center calls are conducted in **mixed Traditional Chinese (zh-TW) + English**.
Two distinct needs exist:

| | Case 1 — Quality Check | Case 2 — Call Assistant |
|---|---|---|
| **When** | After the call (offline / batch) | During the call (real-time) |
| **Goal** | Score agent behavior against a fixed rubric | Help the agent live (suggestions, lookups) |
| **Output** | Markdown QA report per call + roll-up | Live on-screen guidance to the agent |
| **Latency** | Minutes–hours is fine | Sub-second matters |
| **Volume (stated)** | 600 calls/month × 5 min = 50 audio-hr/mo | 10 lines × 8 hr/day × 30 days = 2,400 audio-hr/mo |
| **Build status** | **Implemented** (this repo) | **Implemented (Foundry WebSocket mode)** |

Both cases share the **same STT foundation**; they diverge on transcription mode
(batch vs. streaming) and on the downstream consumer (rubric judge vs. live assist).

---

## 2. In scope

- **STT** of zh-TW + en-US code-switched audio via **Azure AI Speech**.
- **Phrase List** boosting for brand names, product codes, and domain jargon.
- **Post-STT correction** (`corrections.json`) and N-best harvesting to grow rules over time.
- **Behavioral QA judging** (Case 1): one LLM verdict per rubric item, driven entirely
  by the customer's rubric workbook (`input/sample.xlsx`).
- **Markdown report generation** — one `.md` QA report per call, with a pass/fail tally,
  項目 1–3 summaries, and a per-item 判定結果/判定原因 table (`不符合` rows flagged).
- **Cost model** for both cases (see `P12_cost_estimate.md`).

## 3. Out of scope (for now)

- WER/CER accuracy benchmarking against gold reference transcripts
  *(this was an early misread — the QA here is behavioral, not transcription-accuracy scoring).*
- Real-time agent-assist UI, CRM/knowledge-base retrieval integration (Case 2 front-end).
- Speaker identity beyond role separation (客服 / 客戶).
- Sentiment/emotion analytics, supervisor dashboards, BI reporting.
- Telephony/SIP integration and call recording infrastructure.

---

## 4. Method — shared STT pipeline

The STT tuning ladder (applied in order, cheapest/safest first):

1. **Continuous Language ID** — `zh-TW` + `en-US`, always on, to handle
   intra-sentence code-switching.
2. **Phrase List grammar** — boost known brand/product/jargon terms (no training needed).
3. **Detailed output + N-best capture** — surfaces alternates and feeds the corrector.
4. **`corrections.json`** — deterministic post-STT string replacement for recurring errors.
5. **Custom Speech model** — last resort; requires labeled audio. zh-TW is supported.

Modules: `uc1_stt_agent.py` (recognition), `corrections.py` (post-processor).

---

## 5. Method — Case 1 (Quality Check) judging

- Rubric and judge instructions are read **from the customer's workbook** — the rubric
  sheet (檢核項目 / 必需行為標準) and the `Prompt` sheet. No rules are hard-coded.
- **One LLM call per rubric item**, parallelized (`asyncio.Semaphore(4)`), temperature 0.
- **Exception-first verdict priority**, enforced per item:
  1. Exception clause hit → apply exception result
  2. Match clause hit → `符合`
  3. Otherwise → `不符合` + reason
- Summary items (1–3) use a separate ≤20-字 schema.
- `markdown_writer.py` renders one `.md` report per call: a header table (案例編號,
  音檔, 時長, 判定結果 符合/不符合 tally), a 摘要 section for items 1–3, and a 評分明細
  table (判定結果 + 判定原因 + 佐證) where `不符合` rows are flagged with ❌. The full
  逐字稿 is appended (optional via config). A batch run also emits an `index.md` roll-up.

Modules: `uc1_qa_judge.py`, `uc1_markdown_writer.py`, orchestrated by `voiceqa.uc1_main`.

**Transcription mode:** **Batch** (offline) — lowest cost, diarization + LID included.

---

## 6. Method — Case 2 (Call Assistant) — implemented baseline

UC2 is implemented in this repo as a real-time assistant over a WebSocket stream with Foundry Agent Framework.

- **Streaming transcript ingestion** per active session over `/invocations_ws`.
- Rolling transcript window with live assist generation (next-best-action, compliance, answer cards).
- Optional post-call summary output.
- Runtime and token metrics surfaced to the built-in call-center UI.
- STT mode labels and routing support shared `SPEECH_ENDPOINT` fallback, aligned with UC1 endpoint configuration.

**Next design questions** (future iteration):
- How often does the assistant call the model (per turn? per N seconds? on trigger phrases)?
- Does it need retrieval (knowledge base / CRM) — adds latency + cost?
- Confirm whether to move to the recommended **hybrid** design (Azure **Voice Live API** on the
  sub-second hot path + hosted agent for async retrieval/compliance/next-best-action) at 10
  concurrent lines — see `P6_design_spec_uc2_realtime_assistant.md`.

---

## 7. Assumptions

- Audio is reasonably clean, single channel per speaker role where possible.
- Rubric structure stays consistent with `input/sample.xlsx`.
- Azure AI Speech + Azure OpenAI are the approved platforms (no third-party STT/LLM).
- Case 2 volumes (10 lines, 8 hr/day) are **steady-state concurrency**, not peak.

## 8. Success criteria

- **Case 1:** every rubric item gets a defensible verdict with evidence; report matches
  the required Markdown report format (header tally, 摘要, 評分明細 with ❌-flagged 不符合
  rows); per-call cost stays within the §Case 1 estimate.
- **Case 2:** real-time transcript available with acceptable latency; assist cost stays
  within an agreed per-line budget.

## 9. Deliverables

- This repo (Case 1 pipeline) + `P4_architecture.md`.
- `P2_scope.md` (this file), `P12_cost_estimate.md`, and `P12_cost_estimate.zh-TW.md`.
- `P5_design_spec_uc1_blob_to_md.md` and `P6_design_spec_uc2_realtime_assistant.md`.
- `VoiceQA_Scope_and_Cost.pptx` (scope & cost deck).
- Phrase list + corrections seed files; optional Custom Speech training plan.
