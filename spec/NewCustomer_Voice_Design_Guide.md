# Voice Design Guide — Conversational Voice Agent (Voice Live + TTS)

**Companion to:** `NewCustomer_VoiceLive_TTS_Benchmark_Plan.md` (UC3)
**Audience:** engineers building the speak-back voice agent · **Scope:** best practices, not a project plan
**Foundation:** Microsoft Agent Framework (`agent_framework`) + Azure voice engineering

> This guide captures *how to build it well*. It is deliberately opinionated and reusable across customers. Where it states a number, that number is a labeled reference — re-measure on the customer's own zh-TW + en-US gold set.

---

## 1. First principles for a bot that speaks

1. **Latency is a feature, not a metric.** In a spoken conversation, anything over ~1 second of silence reads as "it's broken." Design the whole loop around **time-to-first-audio**, not total tokens. Everything else is negotiable; this is not.
2. **The hot path is sacred.** Only recognition → reasoning → speech belongs on it. CRM lookups, logging, policy checks, and analytics go **async**. If it doesn't shape the next spoken word, get it off the critical path.
3. **Speakable ≠ readable.** Text tuned for a screen sounds terrible aloud. Short sentences, one idea per turn, no bullet lists read verbatim, numbers grouped the way humans say them.
4. **Barge-in is normal.** Callers interrupt. Treat clean interruption handling as a core requirement, not an edge case.
5. **Measure before you tune, re-measure after.** Never ship a voice/SSML/lexicon change without re-scoring the gold set. Voice quality regressions are silent until a customer hears them.

---

## 2. Native speech-to-speech vs. cascaded — how to choose

| Choose **Voice Live native S2S** when… | Choose **cascaded (STT → LLM → TTS)** when… |
|---|---|
| Conversational latency and natural turn-taking dominate | Voice identity / brand voice must be tightly controlled |
| Flows are open-ended, chit-chatty, dynamic | Pronunciation of specific terms must be guaranteed via lexicon |
| You want the fewest moving parts | You need to swap the voice independently of the reasoning model |

**Pragmatic default:** native S2S for the conversation, with the option to route the *audio* through an Azure TTS / Custom Voice for brand control — Voice Live supports using Azure TTS voices for output, so you don't have to pick one philosophy for everything.

---

## 3. Microsoft Agent Framework patterns

### 3.1 One runtime module, one client factory
Centralize all client construction in a single `agent_runtime` module. Every tier/voice/model swap during the benchmark happens in one place — the rest of the code never hard-codes a deployment.

```
agent_runtime/
  __init__.py        # build_chat_client(), build_foundry_agent(), build_voice_session()
  config.py          # tier, voice, model, endpoints — env-driven, no literals in call sites
```

- `FoundryAgent` → a portal/hosted agent (managed, good for the async retrieval/compliance agent).
- `FoundryChatClient` / `OpenAIChatClient` → a raw model deployment (good for the reasoning leg).
- Voice Live session → the real-time WebSocket loop.

### 3.2 Split the agent in two
- **Hot-path voice agent** — owns the Voice Live session: turn detection, barge-in, speaking. Stateful, long-lived.
- **Async work agent** — hosted agent that does tool calls (CRM, booking), retrieval, and compliance/PII checks. Called *from* the hot path but never blocks the next utterance; results are folded in on the following turn or via a brief "let me check that" filler.

### 3.3 Statefulness & hosting
UC3 is **stateful and real-time** — the opposite of UC1's scale-to-zero batch job. Host the voice runtime where a persistent WebSocket and low, predictable latency are first-class (a stateful container/app service near the telephony edge), and keep the async agent independently scalable.

---

## 4. TTS / voice engineering best practices

### 4.1 The speak-back tuning ladder (cheapest first)
1. **Voice selection** — pick the strongest zh-TW multilingual Neural voice; use **Neural HD Flash** where latency matters, **Neural HD 2.5** where expressiveness matters. No training, immediate.
2. **SSML** — the workhorse:
   - `<lang xml:lang="en-US">…</lang>` around English spans inside Chinese sentences — this is the single highest-leverage fix for Taiwan code-switching.
   - `<say-as interpret-as="…">` for digits, phone numbers, dates, currency, account IDs (say "零九…" naturally, not digit soup).
   - `<prosody rate="…" pitch="…">` to slow slightly for clarity; `<break>` for human pauses.
3. **Custom lexicon** — a maintained pronunciation dictionary for brand names, SKUs, and English acronyms. This is the TTS analog of UC1's `corrections.json`: deterministic, versioned, grown from benchmark findings. Cheaper and safer than a custom voice.
4. **Streaming synthesis** — start playback on the first synthesized sentence; never wait for the full response. Biggest perceived-latency win after voice choice.
5. **Custom Neural Voice** — only when brand identity truly requires it. Limited-access, needs studio recordings and lead time. Last resort, not first move.

### 4.2 Code-switching is the Taiwan reality
Assume every sentence can mix languages. The failure mode is *not* Chinese quality and *not* English quality in isolation — it's the **boundary** (an English product name mid-Chinese-sentence mispronounced or in the wrong accent). Benchmark boundaries explicitly; fix with `<lang>` tags + lexicon first.

### 4.3 Make responses speakable
- One idea per turn; target short sentences.
- No lists read aloud — offer "the top three are… want the rest?"
- Confirm slot values back to the caller ("booking for Thursday the 5th, correct?").
- Have a graceful "I didn't catch that" and a clean human hand-off path.

### 4.4 zh-TW locale & Taiwan digit handling (lessons from no-go testing)

Native speech-to-speech gives you too little control over locale and pronunciation. Three failures show up repeatedly in Taiwan contact centers — treat them as first-class design requirements, not edge cases:

- **Taiwan digit reading.** The model/voice may read "1" as **"幺" (yāo)** — a Mainland phone convention. Taiwan says **"一" (yī)**. Fix by using a **zh-TW voice**, controlling digits with SSML (`<say-as interpret-as="digits">`, `<sub alias="一">1</sub>`, or `<phoneme>`), and a **custom lexicon**. All of this requires an **Azure TTS leg** — native S2S has no SSML, so route number read-back through cascaded TTS.
- **China-locale vocabulary.** The base model defaults to zh-CN words (運單, 視頻, 質量, 信息, 軟件, 打印…) and **system-prompt + few-shot steering does not reliably override it** — especially in the fused S2S path where you can't see or patch the text. Fix with a **deterministic zh-CN→zh-TW locale correction map** applied to generated text before TTS, and by serving answers from a **Taiwan-authored KB via retrieval/templates** instead of free generation. Prompting is a soft control; deterministic replacement and templating are hard controls.
- **The general rule:** prompts persuade, layers guarantee. For anything that must be right (a number, an ID, a domain term), put a deterministic layer in the pipeline — which means keeping a **text stage you can inspect** (cascaded), not free S2S.

### 4.5 Correction & re-grounding (never let a bad value stick)

A misheard number that survives the caller's corrections is a trust-killer. Design the loop so **every correction is authoritative**:

- **Confirm critical values by read-back**, digit by digit ("您說的是 0-9-1-2，對嗎？").
- On "錯了 / 不對": **clear the slot**, and on the retry **do not re-offer the top-1 hypothesis** — take the next-best (N-best) alternate or switch to a constrained digit grammar / spell mode.
- **Don't let recognition biasing lock in.** If you feed a previously recognized value back as phrase-list/context bias, it reinforces the same error — rebuild or clear the recognition context each correction turn.
- **Offer a DTMF keypad fallback** for order/account numbers — the single most reliable path for critical digits.
- Reduce the base error rate with a **Phrase List** for Taiwan digit pronunciations, escalating to **Custom Speech** trained on Taiwan digit audio only if needed.

---

## 5. Latency budget (design target, re-measure per environment)

Aim for **< 1.0 s** caller-stops-speaking → first agent audio. A workable budget:

| Stage | Budget (proxy) | Notes |
|---|---|---|
| End-of-speech detection (VAD) | ~150–250 ms | Tune turn detection; too eager cuts callers off |
| Recognition + reasoning first token | ~300–500 ms | Native S2S fuses these; keep prompts tight |
| First audio byte (TTS/native) | ~150–300 ms | Streaming + HD Flash; start on sentence 1 |
| **Total to first audio** | **~< 1.0 s** | Everything else async |

If you're over budget: shorten the system prompt, drop a Voice Live tier only if quality holds, stream earlier, and move any synchronous tool call off the hot path.

---

## 6. Barge-in & turn-taking

- Enable and **tune** Voice Live turn detection (VAD sensitivity) — the single biggest driver of "feels natural."
- On caller interruption: stop synthesis immediately, discard the queued audio, re-open the mic. Target **≥ 95% clean interrupts** on the gold set.
- Avoid long monologues — they invite interruptions and raise the cost of getting barge-in wrong.

---

## 7. Reliability, safety, and observability

- **Graceful degradation:** if the async agent (CRM/tool) is slow or down, the bot still talks — acknowledge, offer a fallback, or hand off to a human. Never dead-air.
- **PII & compliance:** run redaction and policy checks on the async path; keep transcripts per the customer's retention policy. (Full compliance sign-off is a separate workstream — flag it.)
- **Observability:** log per-turn latency (TTFB, total), tier/voice in use, barge-in events, task success, and escalations. These are exactly the benchmark KPIs — instrument once, use for both benchmark and production.
- **Config as data:** tier, voice, lexicon, and prompts are configuration, not code. You will tune them for the life of the product.

---

## 8. What carries over from UC1/UC2

- The **gold-set + rubric** discipline (measure, don't guess) — same harness shape, different KPIs (latency/MOS/pronunciation instead of QA verdict agreement).
- The **`corrections.json` → custom lexicon** pattern for domain terms.
- The shared **`agent_runtime`** client factory and the **hot-path/async split**.
- zh-TW + en-US **code-switching as a first-class requirement**, never an English-only shortcut.

---
*Reference figures (Azure Neural HD MOS ≈ 3.99/3.94; sub-second Voice Live latency; TTS $16–$22/1M chars) are Microsoft-published or public list values as of 2026-07-01 — treat as directional and re-measure on the customer's own content.*
