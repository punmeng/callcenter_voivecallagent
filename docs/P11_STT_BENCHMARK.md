# STT Benchmark Guide

This benchmark scaffold compares transcript quality across:

- `azure-speech-stt`
- `azure-speech-stt-fast`
- `azure-speech-stt-fast-phrase-list`
- `azure-speech-stt-rest`
- `azure-speech-stt-custom`
- `voice-live-api`
- `mai-transcribe-1.5`
- `gpt-audio-transcribe`

It evaluates each provider with the same dataset and reports:

- WER (word error rate)
- CER (character error rate)
- keyword recall
- average latency
- weighted decision score using raw accuracy, latency, and estimated cost

It also appends an audio cost estimate section in `summary.md`.

## Benchmark sectors

- STT benchmark sector: quality and latency for transcript output.
- Voice model benchmark sector: table-aligned recommendation for when to use managed realtime voice service (`voice-live-api`) versus STT-focused engines.

## Table-aligned STT approach

- STT-only path (Azure Speech API / MAI-Transcribe style): prioritize WER/CER and keyword recall; use latency and cost as tie-breakers.
- Managed realtime voice path (Voice Live API): use when you need realtime dialog/tool-calling behavior in the same service, not only raw transcript quality.
- Keep comparison fair: run the same audio set across all providers, then use `summary.md` recommendations to pick default method for your scenario.

## Traditional Chinese evaluation matrix

For zh-TW call-center comparison, treat the benchmark as a decision matrix instead of a single WER table.

- Primary decision axis: raw transcript accuracy. The default weighted decision score uses `70%` raw accuracy, `20%` latency, and `10%` estimated cost.
- Secondary view: corrected transcript accuracy. The benchmark reports corrected metrics separately so repo-specific correction rules do not bias provider ranking.
- Text normalization: metrics normalize Unicode with `NFKC`, ignore punctuation, collapse whitespace, and compare lower-cased Latin text so mixed zh-TW + English transcripts are judged more consistently.
- Keyword coverage: populate `keywords` with business terms that matter for downstream QA, such as product names, addresses, cancel/reschedule intents, policy phrases, or account-verification terms.
- Sample coverage: include short calls, noisy calls, mixed zh-TW/English calls, agent-heavy calls, customer-heavy calls, and calls with named entities.
- Decision threshold: do not standardize on one provider unless it stays near the top across all scenario buckets, not just the overall average.

Recommended scenario buckets for your dataset:

- greeting and identity verification
- appointment or order changes
- billing or payment questions
- complaint or escalation handling
- addresses, names, dates, phone numbers, and codes
- mixed Mandarin, Taiwanese-accented Mandarin, and English terminology

## Dataset format (JSONL)

Each line is one call sample:

```json
{"call_id":"001","audio_path":"C:/temp/001.wav","reference_text":"您好我要取消租屋","keywords":["取消","租屋"],"audio_duration_seconds":4.49,"voice_live_hypothesis":"您好我要取消租屋","mai_transcribe_hypothesis":"您好 我要 取消 租屋"}
```

Required fields:

- `call_id`
- `audio_path`
- `reference_text`

Recommended fields:

- `keywords` (array)
- `audio_duration_seconds` (for cost estimate)
- `voice_live_hypothesis` (fallback hypothesis field for Voice Live adapters)
- `mai_transcribe_hypothesis` (used by `mai-transcribe-1.5` adapter scaffold)

Recommendation for `keywords` in zh-TW evaluation:

- include 2 to 8 intent or entity terms per sample when possible
- prefer domain terms that must survive ASR errors
- include English loanwords or acronyms when agents actually say them in calls

## Run

> The repo ships `data/stt_benchmark.template.jsonl`. Copy it to `data/stt_benchmark.jsonl` and fill in your own samples before running.

```powershell
$env:PYTHONPATH = "src"
python scripts/eval_stt_quality.py --dataset data/stt_benchmark.jsonl --providers azure-speech-stt voice-live-api mai-transcribe-1.5

# suggested matrix for your current plan
python scripts/eval_stt_quality.py --dataset data/stt_benchmark.jsonl --providers \
	azure-speech-stt \
	azure-speech-stt-fast \
	azure-speech-stt-fast-phrase-list \
	azure-speech-stt-rest \
	mai-transcribe-1.5

# include Voice Live API only when needed (currently unstable in some environments)
python scripts/eval_stt_quality.py --dataset data/stt_benchmark.jsonl --providers \
	azure-speech-stt \
	azure-speech-stt-fast \
	voice-live-api \
	mai-transcribe-1.5

# optional custom speech endpoint benchmark (when custom model is ready)
python scripts/eval_stt_quality.py --dataset data/stt_benchmark.jsonl --providers azure-speech-stt-custom
```

Output files are written to:

- `reports/benchmarks/<run-id>/summary.md`
- `reports/benchmarks/<run-id>/<provider>.results.jsonl`

`summary.md` now contains:

- a raw transcript ranking table used for provider recommendation
- a corrected transcript view for post-processing comparison
- a cost section for estimated audio cost

## Current adapter status

- `azure-speech-stt`: live adapter implemented using existing `SttAgent`
- `azure-speech-stt-fast`: live adapter implemented (fixed locale)
- `azure-speech-stt-fast-phrase-list`: fast adapter with phrase list enabled
- `azure-speech-stt-rest`: live REST adapter implemented
- `azure-speech-stt-custom`: live adapter using custom speech endpoint ID
- `voice-live-api`: Voice Live default model path (recommended managed-service baseline)
- `mai-transcribe-1.5`: live REST adapter implemented (`/speechtotext/transcriptions:transcribe`)
- `gpt-audio-transcribe`: Azure OpenAI audio transcription adapter

Voice Live environment variables:

- `AZURE_VOICELIVE_ENDPOINT`
- optional `AZURE_VOICELIVE_API_KEY` (if not set, benchmark uses Azure CLI credential)
- optional `AZURE_VOICELIVE_API_VERSION` (default: `2026-06-01-preview`)
- optional `AZURE_VOICELIVE_MODEL` (default: `gpt-realtime`)
- optional `VOICE_LIVE_TRANSCRIPTION_MODEL` (default: `azure-speech`; overridden by provider-specific variants)
- optional `VOICE_LIVE_TRANSCRIPTION_LANGUAGE` (default: `zh-TW`)
- optional `VOICE_LIVE_CALL_TIMEOUT_SECONDS` (default: `25`; matrix script sets `45`)
- optional `VOICE_LIVE_AZ_CLI_TIMEOUT_SECONDS` (default: `60` when API key is not set)

Voice Live WAV input requirements for live mode:

- mono channel
- PCM16
- 24kHz

Runtime behavior on unstable Voice Live transport:

- If a Voice Live provider hits a transport-layer failure (for example `Cannot write to closing transport` or WebSocket connection reset), the benchmark marks that provider as unavailable for the current run and skips the remaining samples for that provider.

When endpoint is missing or transcript parsing returns empty text, Voice Live adapter falls back to dataset field `voice_live_hypothesis`.

When a live call completes without transcript text, the benchmark now includes compact Voice Live event diagnostics in the error field so you can see which event types arrived and whether transcription completion was observed.

MAI-Transcribe environment variables:

- `AZURE_SPEECH_ENDPOINT` (or fallback `SPEECH_ENDPOINT`)
- `AZURE_SPEECH_KEY` (or fallback `SPEECH_KEY`)
- optional `MAI_TRANSCRIBE_API_VERSION` (default: `2025-10-15`)

Azure Speech custom benchmark environment variables:

- `AZURE_SPEECH_CUSTOM_ENDPOINT_ID` (or `SPEECH_CUSTOM_ENDPOINT_ID`) for `azure-speech-stt-custom`

When endpoint/key is missing, MAI adapter falls back to dataset hypothesis fields for local smoke testing.

Cost model environment variables (optional overrides):

- `AZURE_SPEECH_STT_REALTIME_HOURLY_USD` (default: `1.0`)
- `AZURE_SPEECH_STT_REST_HOURLY_USD` (default: `0.33`)
- `VOICE_LIVE_AUDIO_HOURLY_USD` (default: `1.3`)
- `MAI_TRANSCRIBE_AUDIO_HOURLY_USD` (default: `1.0`)
- `GPT_AUDIO_TRANSCRIBE_HOURLY_USD` (default: `72.0`)

Decision score weight overrides:

- `BENCHMARK_ACCURACY_WEIGHT` (default: `0.7`)
- `BENCHMARK_LATENCY_WEIGHT` (default: `0.2`)
- `BENCHMARK_COST_WEIGHT` (default: `0.1`)

Notes:

- Defaults are placeholders/proxies for quick benchmarking.
- Replace with your actual regional/contracted rates for decision-grade cost comparison.

Recommended compare set for your current decision:

- `voice-live-api` (default model path)
- `azure-speech-stt`
- `mai-transcribe-1.5`

Backward compatibility:

- CLI still accepts `mai-voice` as an alias.
- Dataset fallback also accepts `mai_voice_hypothesis` if `mai_transcribe_hypothesis` is absent.