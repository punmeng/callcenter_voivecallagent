# STT Benchmark Summary

| Provider | Samples | Avg WER | Avg CER | Avg Keyword Recall | Avg Confidence | Avg Latency (ms) | Est. Cost (USD) | Decision Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| azure-speech-stt-fast-phrase-list | 6 | 0.0208 | 0.0093 | 1.0000 | 0.9874 | 4556.42 | 0.0075 | 1.0000 |
| azure-speech-stt | 6 | 0.0208 | 0.0093 | 1.0000 | 0.9874 | 6905.25 | 0.0075 | 0.9504 |
| voice-live-realtime-gpt4o-transcribe (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW) | 6 | 0.0208 | 0.0093 | 1.0000 | 0.9874 | 14026.58 | N/A | 0.7778 |
| mai-transcribe-1.5 | 6 | 0.1250 | 0.0556 | 1.0000 | 0.9243 | 7435.80 | 0.0075 | 0.2392 |
| voice-live-realtime-azure-speech (session=gpt-realtime, transcription=azure-speech, lang=zh-TW) | 6 | 0.1250 | 0.0556 | 1.0000 | 0.9243 | 5409.60 | N/A | 0.2022 |

Lower WER/CER, latency, and cost are better; higher keyword recall, confidence, and decision score are better.
Raw transcript metrics drive the recommendation. Corrected transcript metrics are reported separately so post-processing does not bias provider ranking.

## Recommendation

- Recommended default: `azure-speech-stt-fast-phrase-list`. It has the best weighted decision score in this run based on raw accuracy, latency, and estimated cost.
- If you want the safest quality choice for production-style transcription on this dataset, stay with Azure Speech STT.

## Corrected Transcript View

| Provider | Avg Corrected WER | Avg Corrected CER | Avg Corrected Keyword Recall | Avg Corrected Confidence |
|---|---:|---:|---:|---:|
| azure-speech-stt-fast-phrase-list | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| azure-speech-stt | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| voice-live-realtime-gpt4o-transcribe (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW) | 0.0208 | 0.0093 | 1.0000 | 0.9874 |
| mai-transcribe-1.5 | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| voice-live-realtime-azure-speech (session=gpt-realtime, transcription=azure-speech, lang=zh-TW) | 0.0000 | 0.0000 | 1.0000 | 1.0000 |

## Voice Model Benchmark

This section maps benchmark outputs to a table-aligned decision approach:
- STT quality sector: choose the provider with the best WER/CER and stable keyword recall from the table above.
- STT-only production sector: prefer Azure Speech STT or MAI-Transcribe based on quality/cost targets; use Voice Live primarily when you also need conversational voice capabilities.
## Cost Estimate (Audio)

| Provider | Estimated Cost (USD) |
|---|---:|
| azure-speech-stt | 0.0075 |
| azure-speech-stt-fast-phrase-list | 0.0075 |
| mai-transcribe-1.5 | 0.0075 |
| voice-live-realtime-azure-speech | N/A (set pricing model) |
| voice-live-realtime-gpt4o-transcribe | N/A (set pricing model) |
