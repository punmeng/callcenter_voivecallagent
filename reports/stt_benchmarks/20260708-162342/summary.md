# STT Benchmark Summary

| Provider | Samples | Avg WER | Avg CER | Avg Keyword Recall | Avg Confidence | Avg Latency (ms) | Est. Cost (USD) | Decision Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on) | 6 | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 5438.18 | N/A | 0.9978 |
| voice-live-realtime-gpt4o-transcribe (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW) | 5 | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 5582.84 | N/A | 0.9698 |
| azure-speech-stt-fast-phrase-list | 6 | 0.0208 | 0.0093 | 1.0000 | 0.9874 | 5426.66 | 0.0076 | 0.3000 |
| azure-speech-stt | 6 | 0.0208 | 0.0093 | 1.0000 | 0.9874 | 6575.59 | 0.0076 | 0.1000 |

Lower WER/CER, latency, and cost are better; higher keyword recall, confidence, and decision score are better.
Raw transcript metrics drive the recommendation. Corrected transcript metrics are reported separately so post-processing does not bias provider ranking.

## Recommendation

- Recommended default: `voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on)`. It has the best weighted decision score in this run based on raw accuracy, latency, and estimated cost.
- If cost matters more than quality, compare `voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on)` against the lowest-cost candidate in your own dataset before deciding.

## Corrected Transcript View

| Provider | Avg Corrected WER | Avg Corrected CER | Avg Corrected Keyword Recall | Avg Corrected Confidence |
|---|---:|---:|---:|---:|
| voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on) | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| voice-live-realtime-gpt4o-transcribe (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW) | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| azure-speech-stt-fast-phrase-list | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| azure-speech-stt | 0.0000 | 0.0000 | 1.0000 | 1.0000 |

## Voice Model Benchmark

This section maps benchmark outputs to a table-aligned decision approach:
- STT quality sector: choose the provider with the best WER/CER and stable keyword recall from the table above.
- STT-only production sector: prefer Azure Speech STT or MAI-Transcribe based on quality/cost targets; use Voice Live primarily when you also need conversational voice capabilities.
## Cost Estimate (Audio)

| Provider | Estimated Cost (USD) |
|---|---:|
| azure-speech-stt | 0.0076 |
| azure-speech-stt-fast-phrase-list | 0.0076 |
| voice-live-realtime-azure-speech-phrase-list | N/A (set pricing model) |
| voice-live-realtime-gpt4o-transcribe | N/A (set pricing model) |
