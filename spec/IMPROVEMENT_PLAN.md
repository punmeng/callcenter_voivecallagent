# P17 · Improvement Plan — UC1 · UC2 · UC3 · STT Benchmark · TTS Benchmark

Grounded in the repo's own docs (`P4_architecture`, `P11_STT_BENCHMARK`, `P5/P6` design specs) and the customer no-go findings (NG-1 digit「幺」, NG-2 China-locale terms, NG-3 sticky misheard numbers). Priorities: **P0 = do next**, **P1 = soon**, **P2 = later**. Every item has a success metric so progress is measurable, not vibes.

Suggested filename in repo: `docs/P17_IMPROVEMENT_PLAN.md`. New benchmark doc suggested: `docs/P18_TTS_BENCHMARK.md`.

---

## UC1 — Offline Quality Check (batch)

**Current (from P4/P5):** mature pipeline — `blob_reader → stt_agent` (Continuous LID, PhraseList, Detailed+N-best, `corrections.py`, optional Custom Speech) `→ qa_judge` (rubric, per-item async `Semaphore(4)`, exception-first verdict) `→ markdown_writer` (per-call `.md`, 符合/不符合 tally, `index.md`). Well-structured and already testable.

| # | Improvement | Pri | Success metric |
|---|---|---|---|
| 1 | **Judge–human agreement eval.** Build a small human-labeled gold set; measure verdict agreement per rubric item. Today the judge's *correctness* isn't quantified — this is the real QA KPI (not WER). | P0 | ≥90% verdict agreement vs human; per-item breakdown |
| 2 | **Corrections harvest loop.** Turn N-best alternates into a periodic job that proposes new `corrections.py` entries; track hit-rate. | P0 | correction hit-rate tracked; monthly harvest run |
| 3 | **Borderline reliability.** Dual-judge or self-consistency vote on low-confidence items (keep temp 0). Cut false 不符合. | P1 | false-不符合 rate ↓; disagreement flagged for review |
| 4 | **Rubric versioning + regression.** Version the rubric sheet; snapshot judge outputs and diff when the rubric changes. | P1 | zero silent regressions on rubric edits |
| 5 | **Custom Speech (conditional).** Only if the STT benchmark shows STT is the bottleneck: train on labeled audio, measure delta vs PhraseList baseline. | P1 | CER ↓ vs PhraseList on gold set |
| 6 | **Cost/throughput.** Confirm serverless batch (Functions / Container Apps job) scales to zero; tune `Semaphore` vs model rate limits; per-run cost telemetry. | P2 | cost/call logged; within the $33–335/mo model |
| 7 | **Trend dashboard.** Roll-up pass-rate by rubric item and by agent over time. | P2 | dashboard live |

---

## UC2 — Real-time Call Assistant

**Current (from P4/P6):** Foundry WebSocket real-time baseline (`uc2_main`) + Agent/Customer diarization + live notes/translation/summary. P4 flags the **hybrid** (Voice Live hot path + hosted agent for async) as the recommended next step and P2_scope §6 as the open question.

| # | Improvement | Pri | Success metric |
|---|---|---|---|
| 1 | **Execute the hybrid migration.** Move the speech hot path to **Voice Live API**; keep a hosted agent for async KB/CRM/compliance/next-best-action. Resolves the P2 §6 open question. | P0 | hot path on Voice Live; async off the critical path |
| 2 | **Latency instrumentation.** Measure end-to-end + assist TTFB per turn; enforce a sub-second hot-path budget. | P0 | p50 hot-path < 1.0 s; dashboarded |
| 3 | **Diarization accuracy (DER).** The feature is new — quantify it on a labeled set and tune. | P1 | DER measured; target set with customer |
| 4 | **zh-TW localization of assist output.** Apply `localize_tw()` to generated notes/summaries — NG-2 applies to agent-facing text too. | P1 | 0 China-locale terms on glossary |
| 5 | **Async assist quality.** Grounded KB/CRM retrieval + next-best-action; add observability (traces, tool-call logs). | P1 | agent-rated usefulness; retrieval grounded |
| 6 | **Transport resilience.** Voice Live transport instability is already noted in P11 — add retry/backoff + keep-alive so live sessions don't drop. | P2 | dropped-session rate ↓ |

---

## UC3 — Conversational Voice Agent (NEW)

**Current:** scoped only (this project). No `uc3_*` modules yet. Build on the shared runtime.

| # | Improvement | Pri | Success metric |
|---|---|---|---|
| 1 | **Scaffold modules.** `uc3_voice_session.py` (Voice Live WS), `uc3_dialog.py` (confirm/re-capture + N-best + DTMF → NG-3), `ssml.py` (SSML builder); extend `config.VOICE_PROFILES` and `agent_runtime.build_voice_session()`. | P0 | modules run an end-to-end call |
| 2 | **Wire NG-1/2/3 gates.** zh-TW voice; tool-verbatim number reads (`digits_to_tw`); `localize_tw` before TTS; DTMF fallback for critical numbers. | P0 | NG-1/2/3 pass on the gold set |
| 3 | **Native-vs-cascaded toggle.** Per-flow method selection via `VOICE_PROFILES` (see `Voice_Method_Selection.md`). | P1 | flows switch method by config, no code change |
| 4 | **Hosting.** Stateful real-time runtime near the telephony edge; hot-path/async split. | P1 | persistent session; async isolated |
| 5 | **KB / templated responses.** Serve answers from a Taiwan-authored KB to minimize free-generation drift. | P2 | free-generated share ↓; drift ↓ |

---

## STT Benchmark

**Current (from P11):** strong scaffold — `scripts/eval_stt_quality.py`, 8 providers (azure-speech-stt / -fast / -fast-phrase-list / -rest / -custom, voice-live-api, mai-transcribe-1.5, gpt-audio-transcribe). Metrics: WER, CER, keyword recall, latency, weighted score (70% accuracy / 20% latency / 10% cost). zh-TW decision matrix, raw vs corrected views, NFKC normalization, scenario buckets, JSONL dataset.

| # | Improvement | Pri | Success metric |
|---|---|---|---|
| 1 | **Digit / ID field accuracy sub-metric.** Score numeric spans separately — directly measures the NG-3 root cause; keyword recall doesn't isolate digits. | P0 | per-sample digit-sequence accuracy reported |
| 2 | **Code-switch boundary accuracy.** Measure error specifically at zh↔en boundaries, not just overall CER. | P0 | boundary error rate in `summary.md` |
| 3 | **Diarization accuracy sector (DER).** Add a benchmark sector for UC2's Agent/Customer split. | P1 | DER per provider/config |
| 4 | **Stabilize Voice Live in-harness.** Retry/backoff + keep-alive so voice-live-api is comparable instead of skipped on transport failure. | P1 | voice-live-api completes full runs |
| 5 | **Contracted cost rates.** Replace the placeholder hourly proxies with real regional/EA rates for decision-grade cost. | P1 | cost section uses contracted rates |
| 6 | **Auto corrections-harvest.** Emit a proposed `corrections.py` diff from N-best alternates each run. | P1 | proposed-diff artifact per run |
| 7 | **Bucket enforcement.** Require min N samples per scenario bucket; enforce the "top across all buckets" rule programmatically. | P2 | ranking gated on all buckets |

---

## TTS Benchmark (NEW — mirror the STT scaffold)

**Current:** does not exist. UC3 speaks, so it needs its own benchmark — and behavioral voice quality, **not** WER, is the KPI. Build `scripts/eval_tts_quality.py` in the same shape as `eval_stt_quality.py` and document as `P18_TTS_BENCHMARK.md`.

| # | Improvement | Pri | Success metric |
|---|---|---|---|
| 1 | **Provider/voice matrix.** zh-TW Neural, Neural HD, HD Flash, Custom Voice × {native S2S, cascaded TTS}. | P0 | matrix runs on one dataset |
| 2 | **Core metrics.** TTFB latency; **MOS** (human 5-pt); **pronunciation accuracy** (Taiwan digits NG-1, code-switch, brand terms); intelligibility round-trip (synthesize → re-transcribe → CER); barge-in; cost per min/char. | P0 | metrics in `summary.md`, zh-TW/en-US split |
| 3 | **NG gates + output split.** NG-1/2/3 as hard pass/fail; report **tool-verbatim vs free-generated** separately. | P0 | configs that fail any gate are rejected |
| 4 | **Dataset + MOS harness.** JSONL (text · expected pronunciation · optional reference audio) + a lightweight human-rating collector. | P1 | ≥2 raters/item; agreement tracked |
| 5 | **Decision score.** Weighted (e.g. 50% quality [MOS+pron] / 30% latency / 20% cost), tunable via env like the STT harness. | P1 | single comparable score per config |

---

## Sequenced roadmap (do-next first)

| Wave | Items |
|---|---|
| **Wave 1 (P0)** | UC1 judge–human eval + corrections harvest · UC2 hybrid migration + latency instrumentation · UC3 scaffold + NG gates · STT digit & code-switch metrics · **create TTS benchmark** |
| **Wave 2 (P1)** | UC1 borderline reliability + rubric versioning · UC2 DER + localization + async quality · UC3 method toggle + hosting · STT DER + Voice Live stability + contracted cost · TTS MOS harness + decision score |
| **Wave 3 (P2)** | UC1 cost/dashboard · UC2 transport resilience · UC3 KB/templated · STT bucket enforcement |

**North-star metrics:** UC1 judge–human agreement · UC2 sub-second hot-path latency · UC3 NG-1/2/3 gate pass + task success · STT digit/code-switch accuracy · TTS MOS ≥ 4.0 with NG gates green.
