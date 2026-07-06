# Cost Estimate — VoiceQA Agent

> Last updated: 2026-06-02 · All figures **USD/month**, pay-as-you-go, before tax & infra overhead.
> Rates verified 2026-06-02 from Azure public pricing pages (see §Sources). **Estimates only** —
> actual cost varies by region, agreement (EA/CSP), commitment tier, and real token usage.

---

## Verified unit rates (2026-06-02)

| Service | Item | Rate |
|---|---|---|
| Azure AI Speech | STT — Standard **Batch** | **$0.18** / audio-hour (LID + diarization included) |
| Azure AI Speech | STT — Standard **Real-time** | **$1.00** / audio-hour |
| Azure AI Speech | Real-time enhanced add-on (Continuous LID, Diarization) | **$0.30** / hour **per feature** |
| Azure AI Speech | Custom Speech training | $10 / compute-hour |
| Azure AI Speech | Custom model endpoint hosting | $0.0538 / model / hour |
| Azure OpenAI | GPT-5.5 | $5.00 in / $30.00 out per 1M tokens (cached in $0.50) |
| Azure OpenAI | GPT-4.1-mini | $0.40 in / $1.60 out per 1M tokens |

Free tier (F0): 5 STT audio-hours/month shared Standard+Custom. Batch not covered by free tier.

---

## Case 1 — Quality Check (offline batch QA)

**Volume:** 600 calls/month × 5 min = **50 audio-hours/month**.

### Speech-to-Text
| Mode | Calc | Cost |
|---|---|---|
| **Batch (recommended)** | 50 hr × $0.18 | **$9.00** |
| Real-time (alternative) | 50 hr × $1.00 (+ $0.30/hr per add-on) | $50.00+ |

Batch is the right fit for offline QA: ~5.5× cheaper and diarization + language ID are
included at no extra charge.

### LLM judging (Azure OpenAI)
Assumptions: **30 rubric items/call**, one model call per item.
~2,900 input tokens/item (judge prompt + ~5-min transcript + item standard) and ~120 output tokens.

| | Per call | Per month (×600) |
|---|---|---|
| Input tokens | 87,000 | 52.2M |
| Output tokens | 3,600 | 2.16M |

| Model | Monthly judging cost |
|---|---|
| GPT-5.5 | **$325.80** |
| GPT-4.1-mini | **$24.34** |

### Case 1 total
| Configuration | STT | LLM | **Total / month** |
|---|---|---|---|
| Batch + **GPT-5.5** | $9 | $326 | **≈ $335** |
| Batch + **GPT-4.1-mini** | $9 | $24 | **≈ $33** |

> Per-call cost: **$0.56** (GPT-5.5) or **$0.06** (GPT-4.1-mini).
> **Lever:** prompt-caching the repeated transcript across 30 items can cut input cost
> ~40–50% (GPT-5.5 cached input $0.50/1M). Start on GPT-5.5 for verdict quality; drop to
> GPT-4.1-mini if accuracy holds.

---

## Case 2 — Call Assistant (real-time streaming)

**Volume:** 10 concurrent lines × 8 hr/day × **30 days/month** (call center runs daily)
→ **2,400 audio-hours/month**.

### Speech-to-Text (real-time, required)
| Item | Calc | Cost |
|---|---|---|
| Real-time STT | 2,400 hr × $1.00 | $2,400 |
| Continuous LID add-on | 2,400 hr × $0.30 | $720 |
| **STT subtotal (PAYG)** | | **$3,120** |
| **STT via commitment tier** | $1,600 + 400 hr × $0.80 (STT) + $480 + 400 hr × $0.20 (add-on) | **$2,480** |

> At 2,400 hr/month you exceed the 2,000-hour commitment tier; the tier + overage
> (**$2,480**) still beats PAYG (**$3,120**) — a ~$640/mo saving. Diarization (+$0.30/hr)
> only if the assist logic needs speaker separation.

### Live-assist LLM
Assumption: **one assist turn every 5 minutes** of talk time. A 5-min window holds more
context than a short interval, so ~2,500 in / 200 out tokens/turn → **28,800 turns/month**
(72M in / 5.76M out).

| Model | Monthly assist cost |
|---|---|
| GPT-5.5 | **≈ $533** |
| GPT-4.1-mini | ≈ $38 |

> The 5-min cadence is ~11× fewer calls than a 20-sec cadence, so GPT-5.5 is now
> affordable for live assist. Trigger-based invocation (only on key phrases) would cut it
> further. Adjust the per-turn token size if the assist reviews more/less context.

### Case 2 total
| Configuration | STT | LLM assist | **Total / month** |
|---|---|---|---|
| Commitment STT + **GPT-5.5** | $2,480 | $533 | **≈ $3,013** |
| Commitment STT + GPT-4.1-mini | $2,480 | $38 | ≈ $2,518 |
| PAYG STT + GPT-5.5 | $3,120 | $533 | ≈ $3,653 |
| PAYG STT + GPT-4.1-mini | $3,120 | $38 | ≈ $3,158 |

---

## Case 3 — Automated voice agent (UC3, real-time speech-to-speech)

> **Rates below are structural, not verified dollar figures.** Voice Live / `gpt-realtime`
> bills audio input/output **tokens** (plus any function-call LLM turns), which move faster
> than the STT/LLM split used for Cases 1–2. Confirm current `gpt-realtime` audio-token and
> Voice Live per-minute rates on the Azure pricing page before quoting a number.

UC3's cost is dominated by the **realtime model** on the default pipeline. The three
selectable pipelines are the primary cost/latency/control lever:

| Pipeline | Cost drivers | Relative cost | Latency | When to pick for cost |
|---|---|---|---|---|
| `voicelive` | `gpt-realtime` audio-in + audio-out tokens (STT+LLM+TTS bundled) | **Highest** | Lowest | Demos, best UX, low volume. |
| `voicelive-tts` | `gpt-realtime` audio-in + **text-out** tokens + Azure Speech TTS ($/char) | **Medium** | Low–medium | Text-out tokens are cheaper than audio-out; Azure neural TTS is inexpensive and controllable. |
| `classic` | Azure Speech STT ($/hr) + Foundry **chat** model tokens + Azure Speech TTS | **Lowest** | Medium | High volume, cost-sensitive, no realtime model needed. |

**Optimization levers for UC3**
- **Switch pipeline by scenario:** default to `voicelive` for quality; move steady-state
  traffic to `voicelive-tts` (drop audio-out tokens) or `classic` (drop the realtime model
  entirely) to cut cost.
- **Neural TTS instead of realtime TTS:** `voicelive-tts`/`classic` replace realtime audio-out
  with Azure Speech neural TTS (per-character, much cheaper) — and gain SSML pronunciation control.
- **Foundry agent turns:** billing/IT/expert handoffs add a standard chat-model call per
  escalation; keep those prompts short and cache shared instructions.
- **Reuse the STT commitment tier** from Case 2 for `classic` (Azure Speech real-time hours).



| | Case 1 (QA, batch) | Case 2 (Assistant, real-time) |
|---|---|---|
| Audio hours/month | 50 | 2,400 |
| STT mode | Batch ($0.18/hr) | Real-time ($1.00/hr) + LID |
| STT cost | ~$9 | ~$2,480–3,120 |
| LLM cost | $24–326 | $38–533 |
| **Monthly total** | **~$33–335** | **~$2,518–3,653** |

---

## What is NOT in these figures

- Azure support plan ($100–1,000+/mo), networking, storage, monitoring (add ~20–40% for production).
- Custom Speech training ($10/compute-hr) and endpoint hosting ($0.0538/model/hr) — only if a
  custom model is needed.
- Telephony / call-recording infrastructure.
- Taxes and any EA/CSP discounts (which would *lower* the above).

## Sources
- Azure AI Speech pricing — https://azure.microsoft.com/en-us/pricing/details/speech/ (fetched 2026-06-02)
- Azure OpenAI pricing — https://azure.microsoft.com/en-us/pricing/details/azure-openai/ (fetched 2026-06-02)

## Confirm before finalizing
1. **Per-turn token size** for Case 2 assist (used 2,500 in / 200 out per call).
2. **Model choice** per case (GPT-5.5 vs GPT-4.1-mini).
3. Whether **diarization** is needed in Case 2 (+$0.30/hr).

> Case 2 now uses confirmed inputs: **30 working days/month** and **assist every 5 minutes**.
