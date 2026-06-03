# Architecture

```
              ┌──────────────────────────────────────────────────────────────┐
              │               VoiceQA Agent (voiceqa.uc1_main)              │
              │   STT → Judge → Markdown, per call recording                 │
              └────┬───────────────────────┬───────────────────────┬─────────┘
                   ▼                       ▼                       ▼
        ┌───────────────────┐   ┌─────────────────────┐   ┌────────────────────┐
        │   STT Module      │   │   QA Judge Module   │   │  Markdown Writer   │
        │   uc1_stt_agent   │   │   uc1_qa_judge      │   │  uc1_markdown_writer│
        │                   │   │                     │   │                    │
        │ • Continuous LID  │   │ • Loads rubric from │   │ • Renders one .md  │
        │   [zh-TW, en-US]  │   │   sheet 1 col C     │   │   report per call  │
        │ • PhraseList      │   │ • Loads judge       │   │ • Header tally     │
        │   Grammar         │   │   instructions from │   │   符合/不符合       │
        │ • Detailed output │   │   Prompt sheet      │   │ • ❌ flag on 不符合 │
        │   + N-best        │   │ • Per-item async    │   │   rows in 評分明細  │
        │ • corrections.py  │   │   judging           │   │ • 摘要 items 1-3   │
        │   post-processor  │   │ • Exception-first   │   │ • 逐字稿 appended  │
        │ • Custom Speech   │   │   verdict logic     │   │   (optional)       │
        │   endpoint (opt.) │   │ • 20-字 summary     │   │ • index.md roll-up │
        │                   │   │   for items 1-3     │   │   for batch runs   │
        └───────────────────┘   └─────────────────────┘   └────────────────────┘
```

## STT tuning ladder

1. **Continuous LID** for `zh-TW` + `en-US` code-switching (always on)
2. **Phrase List** — boost brand names, product codes, jargon
3. **Detailed output + N-best capture** — feeds the corrector and surfaces alternates
4. **`corrections.json`** — post-STT string replacement
5. **Custom Speech model** — last resort, requires labeled audio

## QA judging strategy

- One LLM call per rubric item, parallelized with `asyncio.Semaphore(4)`
- Structured JSON output: `{verdict, reason, evidence_quote}`
- Items 1-3 use a different schema: `{summary}` (≤20 字)
- Verdict priority enforced in the user message, not the system prompt:
  1. Exception clause hit → apply exception result
  2. Match clause hit → 符合
  3. Otherwise → 不符合 + reason

## Markdown output rules (from the Prompt sheet)

- One `.md` report per call. Header table carries 案例編號, 音檔, 時長, and a
  判定結果 符合/不符合 tally.
- 摘要 section for items 1-3 (≤20-字 each).
- 評分明細 table from item A1 onwards: 判定結果 + 判定原因 + 佐證 columns.
- Rows with `不符合` flagged with ❌ (the Markdown analogue of the Excel light-red fill).
- 逐字稿 appended at the end (optional via config flag).
- Batch runs also emit an `index.md` roll-up linking each per-call report.

## Hosting & deployment

The right runtime differs by case: **Case 1 is a stateless batch pipeline; Case 2
is a stateful, latency-sensitive real-time assistant.** A hosted/managed agent
runtime (threads, tool routing, persistent state, managed retrieval) only earns its
keep in Case 2.

### Case 1 — Quality Check → serverless batch job (no hosted agent)

- Stateless: STT → 30 independent judge calls → Markdown. No conversation, no tool-calling
  loop, no cross-turn memory — none of the features an agent runtime provides.
- **Recommended:** Azure Functions or an Azure Container Apps job, queue- or
  schedule-triggered. Scales to zero between batches.
- Matches the "minutes–hours latency is fine" requirement and keeps cost inside the
  $33–335/mo model. A hosted agent here is unused overhead (more cost, more moving parts).

### Case 2 — Call Assistant → hybrid (Voice Live hot path + hosted agent for async assist)

- Real-time, stateful per call, sub-second latency target.
- A full managed-agent orchestration loop adds round-trip latency that fights the
  sub-second goal — so keep it **off the speech hot path**.
- **Recommended hybrid:**
  - **Real-time speech path → Azure Voice Live API** (integrated speech + LLM, built
    for low latency). This is the open question already flagged in `scope.md` §6.
  - **Hosted agent only for the heavier async assist** — KB/CRM retrieval, compliance
    checks, next-best-action — work that tolerates 1–2s and benefits from managed tools,
    state, and observability.

### Tradeoff

A managed/hosted agent buys **less infra code + built-in state, tools, and
observability**, at the cost of **higher per-call latency, higher cost, and less
control**. For an offline batch (Case 1) that trade is all downside; for a stateful,
tool-using live assistant (Case 2) it's mostly upside — except on the latency-critical
hot path, which belongs on Voice Live.
