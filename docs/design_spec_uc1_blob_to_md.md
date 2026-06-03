# Software Design Spec — UC1: Blob Audio → Markdown QA Report

> Version 0.1 · 2026-06-03 · Author: Alex Pun
> Use Case 1 (Quality Check, offline batch). **Input:** audio file from Azure Blob Storage. **Output:** a Markdown (`.md`) QA report — not Excel.
> This is a clean design spec. It does not assume or reference any existing code.

---

## 1. Purpose

Score a recorded call-center conversation against a fixed QA rubric, fully offline, and emit a human-readable Markdown report. One audio file in (from Blob), one Markdown report out.

## 2. Scope

**In scope**
- Pull a single audio blob (or a batch under a prefix) from Azure Blob Storage.
- Transcribe with Azure AI Speech (zh-TW + en-US code-switching).
- Judge each rubric item with an LLM (exception-first verdict logic).
- Write one Markdown QA report per call.

**Out of scope**
- Excel output (explicitly replaced by Markdown).
- Real-time / live-assist (that is UC2).
- WER/CER accuracy scoring, sentiment, dashboards, UI.

## 3. High-level architecture

```
 Azure Blob Storage                Pipeline (stateless batch)              Output
 ┌─────────────────┐    audio    ┌──────────────────────────────┐   .md   ┌──────────────┐
 │ container/       │ ─────────▶ │ 1. Blob Reader               │ ──────▶ │ Blob (out)   │
 │   calls/*.wav    │            │ 2. STT (Azure AI Speech)     │         │  or local    │
 │ rubric.json      │ ─────────▶ │ 3. QA Judge (Azure OpenAI)   │         │  reports/    │
 └─────────────────┘            │ 4. Markdown Writer           │         └──────────────┘
                                 └──────────────────────────────┘
```

Four components, each with a single responsibility. The pipeline is stateless: no conversation, no cross-call memory. Recommended runtime is a serverless batch job (Azure Functions or Container Apps job), Blob-trigger or schedule-trigger, scaling to zero between runs.

## 4. Components

### 4.1 Blob Reader
- **Input:** container name + blob name (single) or prefix (batch); rubric blob path.
- **Auth:** Managed Identity preferred (`DefaultAzureCredential`); connection string as fallback for local dev.
- **Behavior:** stream the audio blob to a temp path; load the rubric JSON; emit `(call_id, audio_path, rubric)`.
- **`call_id`:** derived from the blob name (without extension).

### 4.2 STT Module (Azure AI Speech — batch transcription)
- **Mode:** batch transcription ($0.18/audio-hr, language ID + diarization included). No real-time needed for offline QA.
- **Tuning ladder** (apply in order, only as far as accuracy requires):
  1. Continuous Language ID for `zh-TW` + `en-US`.
  2. Phrase List — boost brand names, product codes, jargon.
  3. Detailed output + N-best capture.
  4. `corrections.json` — deterministic post-STT string replacement.
  5. Custom Speech model — last resort, needs labeled audio.
- **Output:** a diarized transcript (speaker-tagged turns with timestamps).

### 4.3 QA Judge (Azure OpenAI)
- **Granularity:** one LLM call per rubric item, run in parallel (bounded concurrency, e.g. semaphore of 4), temperature 0.
- **Verdict logic (exception-first):**
  1. Exception clause hit → apply exception result.
  2. Match clause hit → `符合`.
  3. Otherwise → `不符合` + reason.
- **Structured output per item:** `{ verdict, reason, evidence_quote }`.
- **Items 1–3 special schema:** `{ summary }` (≤ 20 字) instead of a verdict.

### 4.4 Markdown Writer (replaces the Excel writer)
- Renders one `.md` file per call from the judge results. See §6 for the layout.
- Writes to an output Blob container (or local `reports/`).

## 5. Data flow & interfaces

| Stage | Input | Output |
|---|---|---|
| Blob Reader | container/blob path, rubric path | local audio path, rubric object |
| STT | audio path | diarized transcript |
| QA Judge | transcript + rubric | list of `{item, verdict, reason, evidence}` |
| MD Writer | judge results + call metadata | `<call_id>.md` |

**Rubric schema (input JSON):**
```json
{
  "items": [
    { "id": "1",  "type": "summary",  "criteria": "開場白摘要" },
    { "id": "A1", "type": "verdict",  "criteria": "...", "exception": "..." }
  ]
}
```

## 6. Markdown output structure (the key new requirement)

One report per call. Suggested template:

```markdown
# 語音質檢報告 — {call_id}

| 欄位 | 值 |
|---|---|
| 音檔 | {blob_name} |
| 時長 | {duration} |
| 處理時間 | {processed_at} |
| 判定結果 | 符合 {pass} / 不符合 {fail} |

## 摘要（項目 1–3）
- **項目 1：** {summary_1}
- **項目 2：** {summary_2}
- **項目 3：** {summary_3}

## 評分明細
| 項目 | 判定 | 原因 | 佐證 |
|---|---|---|---|
| A1 | ✅ 符合 | … | "…逐字稿引用…" |
| A2 | ❌ 不符合 | … | "…逐字稿引用…" |

## 逐字稿
> [00:00] 客服：…
> [00:05] 客戶：…
```

**Formatting rules**
- `不符合` rows flagged with ❌ (the Markdown analogue of the Excel light-red fill).
- A pass/fail tally in the header table.
- Transcript appended at the end (or omitted via a config flag for shorter reports).
- For a batch run, optionally also emit an `index.md` linking each per-call report.

## 7. Configuration

| Setting | Purpose |
|---|---|
| `BLOB_ACCOUNT_URL` / `BLOB_CONTAINER_IN` | source audio location |
| `BLOB_CONTAINER_OUT` (or `OUTPUT_DIR`) | where reports land |
| `RUBRIC_BLOB_PATH` | rubric JSON location |
| `SPEECH_ENDPOINT` / `SPEECH_KEY` (or MI) | Azure AI Speech |
| `AOAI_ENDPOINT` / `AOAI_DEPLOYMENT` | Azure OpenAI model |
| `JUDGE_CONCURRENCY` | parallel judge calls (default 4) |
| `INCLUDE_TRANSCRIPT` | include/omit transcript section |

## 8. Error handling

- **Blob not found / unreadable:** fail that call, log, continue the batch.
- **STT failure or empty transcript:** mark the report as `STT_FAILED`, skip judging.
- **Judge call error:** retry once; on second failure mark that item `判定錯誤` rather than failing the whole report.
- **Output write failure:** retry once; surface a non-zero exit for the batch.
- Idempotent: re-running the same blob overwrites its report deterministically (temperature 0).

## 9. Non-functional notes

- **Cost (per the cost estimate):** at 50 audio-hr/mo, batch STT ≈ $9; LLM judging ≈ $24 (GPT-4.1-mini) to ≈ $326 (GPT-5.5) per month. Markdown output adds no incremental cost vs Excel.
- **Latency:** minutes–hours is acceptable (offline).
- **Scaling:** stateless; parallelize across calls and across rubric items within a call.
- **Security:** Managed Identity for Blob + Speech + OpenAI; no secrets in reports; audio temp files deleted after processing.

## 10. Open questions

1. Single-blob trigger vs prefix/batch sweep as the primary entry mode?
2. Should `index.md` roll-up be generated for batch runs?
3. Transcript included by default, or opt-in only?
4. Model choice per the cost tradeoff — start on GPT-5.5, drop to GPT-4.1-mini if accuracy holds?
