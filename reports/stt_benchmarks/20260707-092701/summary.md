# STT Benchmark Summary

| Provider | Samples | Avg WER | Avg CER | Avg Keyword Recall | Avg Confidence | Avg Latency (ms) | Est. Cost (USD) | Decision Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| azure-speech-stt-fast-phrase-list | 6 | 0.0208 | 0.0093 | 1.0000 | 0.9874 | 4752.58 | 0.0075 | 1.0000 |
| azure-speech-stt | 6 | 0.0208 | 0.0093 | 1.0000 | 0.9874 | 6446.26 | 0.0075 | 0.8890 |
| mai-transcribe-1.5 | 6 | 0.1250 | 0.0556 | 1.0000 | 0.9243 | 7102.38 | 0.0075 | 0.8013 |
| voice-live-api-gpt-realtime (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW) | 6 | 1.1250 | 0.6667 | 1.0000 | 0.2604 | 5404.25 | 0.0097 | 0.3419 |
| voice-live-api (session=gpt-realtime, transcription=azure-speech, lang=zh-TW) | 6 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 7804.13 | 0.0097 | 0.0000 |

Lower WER/CER, latency, and cost are better; higher keyword recall, confidence, and decision score are better.
Raw transcript metrics drive the recommendation. Corrected transcript metrics are reported separately so post-processing does not bias provider ranking.

## Recommendation

- Recommended default: `azure-speech-stt-fast-phrase-list`. It has the best weighted decision score in this run based on raw accuracy, latency, and estimated cost.
- Best Voice Live option in this run: `voice-live-api-gpt-realtime (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW)`. Use it only if you specifically want Voice Live behavior and can accept its current quality tradeoffs.
- Voice Live is not suitable for this environment yet: the live runs failed to produce usable transcripts, so Azure Speech STT is the safer choice for now.
- If you want the safest quality choice for production-style transcription on this dataset, stay with Azure Speech STT.

## Corrected Transcript View

| Provider | Avg Corrected WER | Avg Corrected CER | Avg Corrected Keyword Recall | Avg Corrected Confidence |
|---|---:|---:|---:|---:|
| azure-speech-stt-fast-phrase-list | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| azure-speech-stt | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| mai-transcribe-1.5 | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| voice-live-api-gpt-realtime (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW) | 1.1250 | 0.6667 | 1.0000 | 0.2604 |
| voice-live-api (session=gpt-realtime, transcription=azure-speech, lang=zh-TW) | 1.0000 | 1.0000 | 1.0000 | 0.0000 |

## Voice Model Benchmark

This section maps benchmark outputs to a table-aligned decision approach:
- STT quality sector: choose the provider with the best WER/CER and stable keyword recall from the table above.
- Voice service sector (managed realtime): current Voice Live default path is `voice-live-api-gpt-realtime (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW)`. Use this when you need realtime conversation/tool-calling style workflows, not only raw STT.
- STT-only production sector: prefer Azure Speech STT or MAI-Transcribe based on quality/cost targets; use Voice Live primarily when you also need conversational voice capabilities.
## Cost Estimate (Audio)

| Provider | Estimated Cost (USD) |
|---|---:|
| azure-speech-stt | 0.0075 |
| azure-speech-stt-fast-phrase-list | 0.0075 |
| mai-transcribe-1.5 | 0.0075 |
| voice-live-api | 0.0097 |
| voice-live-api-gpt-realtime | 0.0097 |
