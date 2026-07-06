# Call Center Voice AI — Voice Live + TTS Benchmark Plan

**Customer:** `[Add customer name]` (new customer) · **Prepared by:** Alex Pun, Sr Solution Engineer, Microsoft Taiwan · **Date:** 2026-07-01
**Modeled volume:** ~5,000 calls/day · **Languages:** Traditional Chinese (zh-TW) + English (en-US), intra-sentence code-switching

> **Status:** Draft plan. All Azure rates below are **clearly-labeled public list-price proxies** (USD, pay-as-you-go), not a quote. `[bracketed]` items are placeholders to confirm with the customer.
> This is **UC3**, extending the existing VoiceQA program (UC1 offline Quality Check — implemented; UC2 real-time Call Assistant). Where UC1/UC2 *listen*, **UC3 speaks back** — so the primary KPI is voice **latency, naturalness, and pronunciation**, not behavioral QA agreement.

---

## 1. Use Case

**One-paragraph statement.** `[Add customer name]` wants a **conversational voice agent** — an inbound self-service voicebot (and optional outbound reminder/notification bot) that *speaks back* to callers in natural Traditional Chinese with English code-switching for brand and product terms. Before committing to a production build, the customer needs a **rigorous benchmark of the Azure "speak-back" stack — Voice Live API and Text-to-Speech (TTS)** — to decide (a) native speech-to-speech vs. cascaded TTS, (b) which Voice Live tier (Lite / Standard / Pro), and (c) which voice (standard neural vs. Neural HD vs. a future Custom Neural Voice). The benchmark's output is a go/no-go recommendation plus a tuned configuration.

- **Business driver:** deflect routine calls (balance/status queries, FAQs, appointment/booking, simple changes) from human agents; extend service to 24×7 without headcount; keep a consistent, on-brand voice.
- **Who consumes the output:** contact-center operations (deflection & CSAT), the voicebot product owner (config decision), and human agents (warm hand-off on escalation).
- **Success criteria (benchmark):** a signed-off configuration that meets latency, naturalness, pronunciation, and task-success targets on a zh-TW + en-US gold set (targets in §4).
- **In scope:** the speak-back path — Voice Live real-time loop, TTS voice quality, code-switch pronunciation, barge-in, and the benchmark harness that scores them.
- **Out of scope (this UC):** see §2.

### Inline cost estimate — UC3 (recommended config: Voice Live *Standard*, native speech-to-speech)

Basis (labeled proxy assumptions): avg **3-min call, 5 turns**, native speech-to-speech; 5,000 calls/day; 30-day run-rate.

| Granularity | Cost (proxy) | Rate basis |
|---|---|---|
| Per call | **~$0.076** | Voice Live Standard native S2S, scaled from the Azure Voice Live calculator Pro anchor ($0.22/conv) by the official native-audio token-rate ratio (Standard $11+$22 vs Pro $32+$64) |
| Per day | **~$380** | $0.076 × 5,000 |
| Per month | **~$11,400** (30-day) / **~$8,360** (22 business-day) | per-day × 30 / × 22 |

Tier sensitivity at 5,000 calls/day (native S2S, per-month, 30-day run-rate): **Lite ≈ $4,200 · Standard ≈ $11,400 · Pro ≈ $33,000**. Add **~$1,920–$2,640/month** if a cascaded Azure TTS brand voice (Neural std $16/1M → HD $22/1M chars) is layered on top for voice-identity control. One-time benchmark compute is **negligible (~$158 proxy)** — the real benchmark cost is human rubric-labeling time. Full breakdown in §7.

---

## 2. Scope / Out-of-Scope

**In scope**
- Voice Live real-time conversational loop (WebSocket): turn detection, barge-in, native speech-to-speech.
- TTS voice evaluation: standard Neural, Neural HD (incl. HD Flash low-latency), and SSML/lexicon tuning for zh-TW + en-US.
- Benchmark harness: gold-set runner, latency capture, naturalness (MOS) collection, pronunciation scoring, task-success scoring — split by language segment.
- Optimization ladder (voice → SSML → custom lexicon → streaming → Custom Neural Voice).
- Config recommendation + soft design guide (Microsoft Agent Framework hosting pattern).

**Out of scope (note as dependencies, do not design here)**
- Telephony / SIP / SBC / call-recording infrastructure and media-stream bridging into Voice Live.
- CRM/back-office system integration and the business logic the bot calls (tools/APIs) — stubbed for the benchmark.
- Offline batch QA (that is **UC1**) and live human-agent assist (that is **UC2**).
- Custom Neural Voice recording/studio production (flagged as an optional later phase; limited-access feature).
- Production security review, PII redaction policy, and compliance sign-off (separate workstream).

---

## 3. Voice Technology

The speak-back path can be built two ways; the benchmark exists to choose between them per KPI.

| Component | Option A — **Voice Live native speech-to-speech** | Option B — **Cascaded: STT → LLM → Azure TTS** |
|---|---|---|
| Stack | Single Voice Live WebSocket (GPT real-time; STT+reasoning+voice fused) | Streaming STT + LLM + Azure TTS voice, orchestrated |
| Latency | Lowest — sub-second turn latency is the design target | Higher — sum of three hops; mitigated by streaming/chunking |
| Naturalness | Highest — model-native prosody, natural turn-taking, barge-in | Depends on TTS voice; Neural HD 2.5 rated MOS ~3.99 (F)/3.94 (M) |
| Brand-voice control | Via Voice Live's option to use Azure TTS / Custom Voice for audio | Full — pick any Neural/HD/Custom voice + SSML |
| Code-switch handling | Model-native | Controlled via `<lang>` SSML + custom lexicon |
| Best when | Conversational, low-latency self-service | Voice identity & pronunciation must be tightly controlled |

**Recommendation to benchmark:** lead with **Voice Live native S2S** for the conversational hot path, and benchmark **Voice Live + Azure TTS voice (HD Flash)** as the brand-voice/pronunciation-controlled alternative. Keep **classic cascaded** as a baseline only.

> **Update — customer no-go testing (2026-07):** native S2S failed on Taiwan **digit reading (1→"幺" instead of "一")**, **China-locale vocabulary** (e.g. 提單→運單) that survived system-prompt + few-shot steering, and **misheard numbers that "stick"** through user correction. These are controllability gaps inherent to the fused S2S path. **For any flow that reads back numbers, IDs, or domain terms, default to the controllable cascaded path** (streaming zh-TW STT you can bias → a text LLM whose output you can post-process → Azure zh-TW TTS with SSML + custom lexicon). See §4 must-fix gates and §5 fixes.

- **STT:** provided *inside* Voice Live for the native path; streaming STT only if Option B is chosen.
- **TTS:** the heart of this UC — evaluate **standard Neural** vs. **Neural HD** (incl. **HD Flash** for low latency, and **HD 2.5** for expressiveness). Free tier includes 0.5M chars/month for prototyping.
- **Translation:** not required (single-language callers, in-language responses) — note as optional for cross-language hand-off.
- **Multi-modal:** out of scope for v1 (voice-only).
- **Voice Live tiers to benchmark:** **Lite** (cheapest, simple flows) → **Standard** (recommended default) → **Pro** (richest reasoning, highest cost).

---

## 4. Benchmark Plan (zh-TW + en-US — mandatory)

Because UC3 *speaks*, the benchmark measures **voice output quality and responsiveness**, not transcription WER/CER (that is a secondary health check only). Every metric is reported **separately for zh-TW segments and en-US segments**, plus for **code-switch boundaries** (the hardest case: English brand/product terms inside Chinese sentences).

### Gold set
- **`[Add N]` ≈ 100–120 representative call scenarios** covering the top self-service intents, each scripted with **intra-sentence zh-TW ↔ en-US switching** (product names, plan names, English acronyms).
- Human raters (`[Add rater count]`, ≥2 per item for agreement) score each synthesized/played response.

### Primary KPIs and targets (proxy targets — confirm with customer)

| KPI | Definition | Target (proxy) | Why it matters |
|---|---|---|---|
| **Turn latency** | Caller stops speaking → first audio byte from agent (TTFB) and full response | **< 1.0 s** to first audio; smooth thereafter | Sub-second is the Voice Live design promise; > ~1.5 s feels broken |
| **Naturalness (MOS)** | 5-point human Mean Opinion Score | **≥ 4.0** overall, **≥ 3.8** on zh-TW | Reference: Azure Neural HD 2.5 ≈ 3.99 (F)/3.94 (M) |
| **Pronunciation accuracy** | % of brand/product/English terms pronounced correctly | **≥ 95%** at code-switch boundaries | The failure mode Taiwan contact centers actually hit |
| **Task success rate** | % of calls where the bot completes the caller's intent | **≥ 80%** on in-scope intents | The deflection business case |
| **Barge-in handling** | Agent stops promptly when caller interrupts | **≥ 95%** clean interrupts | Callers talk over bots; must feel responsive |

### Secondary / health checks
- **WER/CER of the STT leg** (Option B or Voice Live's inbound recognition) — transcription health only, *not* the pass/fail KPI.
- **Intelligibility round-trip:** synthesize → re-transcribe → compare, to catch garbled output.
- **Cost per successful task** (ties §7 to task success).

### Method
- Run the gold set across the benchmark grid: **{Voice Live Lite, Standard, Pro} × {native S2S, HD Flash voice, standard Neural voice}**.
- Capture latency automatically; collect MOS + pronunciation + task-success from human raters; report zh-TW vs en-US vs code-switch separately.
- Winner = cheapest configuration that clears every primary target.

### Known no-go findings from customer testing (must-fix gates)

These three failures were observed on the **native S2S** path and are now **hard pass/fail gates** — the gold set must include explicit cases for each, and a configuration that fails any of them cannot ship.

| # | Observed failure | Gate |
|---|---|---|
| **NG-1** | Digit **"1" read as "幺" (yāo)** — a Mainland phone convention; Taiwan says **"一" (yī)** | 100% of digit read-backs use Taiwan reading |
| **NG-2** | **China-locale vocabulary** in output (e.g. 提單→運單) that **persisted despite system prompt + few-shot** | 0 China-locale terms on the glossary in synthesized output |
| **NG-3** | A **misheard number "sticks"** — user corrections don't overwrite it | Every correction re-grounds the slot within ≤1 turn |

Root theme: all three are **controllability gaps of native speech-to-speech**. Prompt/few-shot steering is a *soft* control; these require *hard* deterministic layers (SSML, lexicon, text post-processing, dialog re-grounding) that only the **cascaded path** exposes. Fixes in §5.

---

## 5. Optimization Method

Ordered cheapest/safest first — the **speak-back tuning ladder** (analogous to the UC1 STT ladder, adapted for output):

1. **Voice selection (no training).** Choose the best zh-TW multilingual Neural voice; prefer **Neural HD Flash** for latency-sensitive turns. Free, immediate.
2. **SSML tuning.** `<lang xml:lang="en-US">` around English spans for correct code-switch pronunciation; `<prosody>` rate/pitch; `<break>` for natural pauses; `<say-as>` for numbers, dates, phone numbers, account IDs.
3. **Custom lexicon (the TTS analog of Phrase List / `corrections.json`).** A maintained pronunciation dictionary for brand names, product SKUs, and English acronyms — deterministic, no training, grown from benchmark findings over time.
4. **Streaming / chunked synthesis.** Stream TTS and start playback on the first sentence to cut perceived latency; tune Voice Live turn-detection (VAD) sensitivity for clean barge-in.
5. **Tier & prompt tuning.** Drop from Pro → Standard → Lite where quality holds; tighten the system prompt for concise, speakable responses (short sentences synthesize faster and sound better).
6. **Custom Neural Voice (last resort).** A brand voice built from recorded studio audio — highest identity control, but a **limited-access feature** needing recording effort and lead time. Only if steps 1–5 don't meet the voice-identity bar.

**Governance:** every optimization decision is re-scored on the gold set (§4) before it ships — never ship a tuning change unmeasured.

### Fixes for the customer no-go findings (NG-1 / NG-2 / NG-3)

**NG-1 — Taiwan digit reading (1 = 一, not 幺).**
1. Use a **zh-TW voice** (e.g. `zh-TW-HsiaoChenNeural`, `HsiaoYuNeural`, `YunJheNeural`) — never a zh-CN voice; this alone usually flips 幺→一.
2. Control digits in **SSML**: `<say-as interpret-as="digits">`, and where it still says 幺, force the reading with `<sub alias="一">1</sub>` per digit, spell numbers as Chinese characters in the text, or pin with `<phoneme>`.
3. Add a **custom lexicon** entry for the digit reading (a community zh-TW Azure TTS lexicon exists as a starting point).
4. **Requires the cascaded path** — native S2S does not expose SSML, so number read-back must run through an Azure TTS leg.

**NG-2 — China-locale vocabulary (提單, not 運單) that survives prompting.**
1. **Decouple text from voice:** generate with a **text LLM whose output you can inspect and patch**, then TTS — not free S2S.
2. **Locale correction map** (the text analog of UC1's `corrections.json`): a deterministic zh-CN→zh-TW glossary applied to every generated response *before* TTS — e.g. 運單→提單, 視頻→影片, 質量→品質, 信息→資訊, 軟件→軟體, 打印→列印, 螢幕/屏幕→螢幕, 網絡→網路, 默認→預設. Deterministic replacement beats prompting.
3. **Constrain to approved answers:** serve most responses from a **Taiwan-authored KB via retrieval/templates** (select-from-approved) rather than free generation — eliminates drift at the source.
4. System prompt + few-shot are *soft* controls; keep them, but never rely on them as the only guardrail.

**NG-3 — misheard number that "sticks" through correction.**
1. **Confirm-and-recapture dialog:** read critical numbers back ("您說的是 0-9-1-2，對嗎？"); on rejection, **clear the slot** and re-prompt digit-by-digit ("請一位一位地念").
2. **Use N-best on correction:** when the caller says "錯了", do **not** re-offer the top-1 hypothesis — take the next-best alternate or switch to a constrained digit grammar.
3. **Don't let biasing lock in:** if a previously recognized value is fed back as phrase-list/context bias, it reinforces the error — rebuild/clear the recognition context each correction turn; treat the newest correction as authoritative and overwrite state.
4. **DTMF keypad fallback** for order/account numbers — the most reliable path for critical digits in a call center.
5. Reduce the base error with a **Phrase List** for Taiwan digit pronunciations, escalating to a **Custom Speech** model trained on Taiwan digit audio if needed.

### Keeping native speech-to-speech as the primary service (mitigation path)

If the customer wants **Voice Live native S2S as the major service**, that is viable — the strategy is *not* "pure native audio for everything," but **keep native S2S for the ~80% conversational flow and route the accuracy-critical moments (numbers, IDs, locale-sensitive terms) through the controls Voice Live does expose.**

> **Key lever:** Voice Live supports **realtime-model reasoning + Azure TTS voice output** (including custom voice). Setting the output voice to a **zh-TW neural/HD/custom voice** — on the same Voice Live WebSocket, same low latency — recovers most of the NG-1/NG-2 pronunciation control while still meeting the "runs on Voice Live" requirement.

**Four switches to turn on inside Voice Live**

| Switch | Effect | Addresses |
|---|---|---|
| Output **voice = zh-TW** (`zh-TW-HsiaoChenNeural` / custom) | Fixes "幺", restores brand voice | NG-1 |
| **Function calling / tools** | Critical content returned by backend as **pre-localized Taiwan text**; model only reads it **verbatim** | NG-1 / NG-2 |
| **input_audio_transcription** on | Text of the caller's speech for confirmation logic + logging | NG-3 |
| **turn_detection** (server VAD) tuned | Clean barge-in / capture | NG-3 |

**Per-finding mitigation on the native path**
- **NG-1:** don't let the model verbalize digits — a `say_number` tool returns the Taiwan reading string ("一九一二"); instruct "always read tool text verbatim, never re-verbalize numbers." Output via zh-TW voice as a second safety net.
- **NG-2:** serve answers from a **KB tool whose response is run through `localize_tw()` before returning**; the model reads it verbatim. Minimize free-generated speech; keep prompt/few-shot as a soft backup only.
- **NG-3:** pure native audio exposes **no clean N-best** (the model consumes audio directly), so the cascaded "try next candidate" trick is unavailable. Use two nets instead: (1) input transcription + forced read-back confirmation; (2) **DTMF keypad capture for critical numbers** on the telephony gateway — the reliable fallback under native S2S.

**Illustrative `session.update` (verify field names against your API version)**

```jsonc
{
  "type": "session.update",
  "session": {
    "modalities": ["audio", "text"],
    "voice": { "name": "zh-TW-HsiaoChenNeural", "type": "azure-standard" },
    "input_audio_transcription": { "model": "azure-speech", "language": "zh-TW" },
    "turn_detection": { "type": "server_vad", "silence_duration_ms": 300 },
    "instructions": "台灣在地客服語音助理。凡工具回傳文字一律逐字唸；『1』念『一』不念『幺』；關鍵號碼逐位覆誦確認，兩次不成改用電話鍵盤；用台灣用語（提單/影片/品質/資訊/螢幕/列印）。",
    "tools": [
      { "type": "function", "name": "say_number",       "description": "數字轉台灣讀法字串供逐位覆誦" },
      { "type": "function", "name": "get_order_status", "description": "查訂單，回傳已在地化台灣繁體字串（須逐字唸）" }
    ]
  }
}
```
Tool handlers reuse the §5 helpers (`digits_to_tw` for NG-1, `localize_tw` for NG-2).

**Residual risk (state to the customer)**
- Any **free-generated** model speech can still drift in pronunciation/word choice — tool-verbatim reading suppresses most of it, not 100%.
- Therefore the benchmark must **measure "tool-verbatim" vs. "free-generated" output separately**, with NG-1/2/3 as hard gates.
- If only a narrow slice (e.g. number read-back) fails the gate, carve **just that slice** onto Azure TTS voice / cascaded and **keep everything else on native S2S** — the primary service remains Voice Live native S2S.

---

## 6. Agent Framework & Hosting

Standardize on the **Microsoft Agent Framework** (`agent_framework`), consistent with UC1/UC2.

- **Client construction:** centralize in one `agent_runtime` module — `FoundryAgent` for a portal/hosted agent, `FoundryChatClient` / `OpenAIChatClient` for a model deployment. One place to swap tiers/voices during the benchmark.
- **Hosting (UC3 is real-time & stateful):** a **stateful real-time runtime**, not a scale-to-zero batch job. Baseline = **Voice Live WebSocket** on the hot path; a **hosted agent handles async retrieval, tool calls, and compliance checks** off the critical path so the voice loop stays sub-second.
- **Hot path vs. async:** keep only recognition → reasoning → speech on the hot path; push CRM lookups, logging, and policy checks to the async agent.
- **Reuse from UC1/UC2:** the custom-lexicon/corrections discipline, the gold-set harness pattern, and the shared `agent_runtime` client factory carry straight over.

*(Detailed patterns in the companion `NewCustomer_Voice_Design_Guide.md`.)*

---

## 7. Cost Model

**All rates are labeled public list-price proxies (USD, pay-as-you-go), subject to region, tier, and EA/agreement discounts — not a quote.** Volume = 5,000 calls/day; 30-day monthly run-rate; 3-min/5-turn call basis. Computed programmatically; consistent with §1.

### Voice Live — native speech-to-speech (per-tier)

| Tier | Per call | Per day (5,000) | Per month (30-day) |
|---|---|---|---|
| Lite | ~$0.028 | ~$140 | ~$4,200 |
| **Standard (recommended)** | **~$0.076** | **~$380** | **~$11,400** (22-day: ~$8,360) |
| Pro | ~$0.220 | ~$1,100 | ~$33,000 |

Voice Live per-conversation anchor: Azure Voice Live pricing calculator, **Pro ≈ $0.22/conversation** at 3-min/5-turn native S2S. Standard/Lite scaled by the official native-audio token-rate ratio (Pro $32 in/$64 out; Standard $11/$22; Lite ~$4 in — per M tokens).

### Optional cascaded Azure TTS brand voice (add-on, if used for output)

| Voice | Per call | Per day | Per month |
|---|---|---|---|
| Neural standard ($16/1M chars) | ~$0.013 | ~$64 | ~$1,920 |
| Neural HD ($22/1M chars) | ~$0.018 | ~$88 | ~$2,640 |

Basis: ~800 synthesized chars/call × 5,000 calls/day = 4.0M chars/day. (Neural HD dropped from $30→$22/1M in Mar 2026.)

### Consolidated per-UC view (reconciles to §1)

| Line item | Config | Per month (proxy) |
|---|---|---|
| **UC3 core** | Voice Live Standard, native S2S | **~$11,400** |
| UC3 + brand voice (optional) | + Neural HD cascaded TTS | ~$11,400 + ~$2,640 = **~$14,040** |
| One-time benchmark run | 120 gold calls × 6 configs, priced at Pro | **~$158** (compute only) |

> The benchmark's dominant cost is **human rubric-labeling time**, not Azure compute. Budget rater hours accordingly.

---

## 8. Assumptions

- Volume **5,000 calls/day** and **3-min/5-turn** average are **proxies** — confirm with the customer's real ACD/telephony data.
- 30-day run-rate assumes a 24×7 self-service bot; a staffed 22-business-day model lowers monthly figures (~27%).
- All Azure prices are **public list proxies** captured 2026-07-01; final pricing depends on region (e.g., Taiwan/SEA), tier, and agreement.
- Telephony media bridging into Voice Live is assumed to exist (dependency, not designed here).
- Neural HD MOS reference (3.99/3.94) is Microsoft-published for HD 2.5; the customer gold set must re-measure on **their** zh-TW + en-US content.
- Custom Neural Voice, if pursued, is a **limited-access** feature with recording lead time.

---

## 9. Next Steps

1. **Confirm inputs** with the customer: real call volume/mix, top self-service intents, brand/product term list, and KPI targets.
2. **Assemble the gold set** (~100–120 zh-TW + en-US code-switched scenarios) and recruit ≥2 raters/item.
3. **Stand up the benchmark harness** on the shared `agent_runtime` module; wire latency capture + rater collection.
4. **Run the benchmark grid** (3 tiers × 3 voice configs); report zh-TW / en-US / code-switch separately.
5. **Apply the optimization ladder** (voice → SSML → custom lexicon → streaming); re-score.
6. **Recommend a config** (cheapest that clears all targets) and decide native S2S vs. cascaded brand voice.
7. **Go/no-go** for a production pilot; if go, scope telephony integration and compliance as follow-on workstreams.

---
*Companion deliverables: `NewCustomer_VoiceLive_TTS_Benchmark_Plan.pptx` (executive deck) · `NewCustomer_Voice_Design_Guide.md` (soft design guide).*
