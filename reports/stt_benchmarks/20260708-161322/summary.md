# STT Benchmark Summary

| Provider | Samples | Avg WER | Avg CER | Avg Keyword Recall | Avg Confidence | Avg Latency (ms) | Est. Cost (USD) | Decision Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on) | 7 | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 5984.32 | N/A | 0.9653 |
| azure-speech-stt-fast-phrase-list | 7 | 0.0179 | 0.0079 | 1.0000 | 0.9892 | 4671.56 | 0.0088 | 0.8833 |
| azure-speech-stt | 7 | 0.0179 | 0.0079 | 1.0000 | 0.9892 | 6440.94 | 0.0088 | 0.8413 |
| voice-live-realtime-gpt4o-transcribe (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW) | 6 | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 13081.23 | N/A | 0.7778 |
| mai-transcribe-1.5 | 7 | 0.1071 | 0.0476 | 1.0000 | 0.9351 | 7668.18 | 0.0088 | 0.2287 |

Lower WER/CER, latency, and cost are better; higher keyword recall, confidence, and decision score are better.
Raw transcript metrics drive the recommendation. Corrected transcript metrics are reported separately so post-processing does not bias provider ranking.

## Recommendation

- Recommended default: `voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on)`. It has the best weighted decision score in this run based on raw accuracy, latency, and estimated cost.
- If cost matters more than quality, compare `voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on)` against the lowest-cost candidate in your own dataset before deciding.

## Corrected Transcript View

| Provider | Avg Corrected WER | Avg Corrected CER | Avg Corrected Keyword Recall | Avg Corrected Confidence |
|---|---:|---:|---:|---:|
| voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on) | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| azure-speech-stt-fast-phrase-list | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| azure-speech-stt | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| voice-live-realtime-gpt4o-transcribe (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW) | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| mai-transcribe-1.5 | 0.0000 | 0.0000 | 1.0000 | 1.0000 |

## Voice Model Benchmark

This section maps benchmark outputs to a table-aligned decision approach:
- STT quality sector: choose the provider with the best WER/CER and stable keyword recall from the table above.
- STT-only production sector: prefer Azure Speech STT or MAI-Transcribe based on quality/cost targets; use Voice Live primarily when you also need conversational voice capabilities.
## Cost Estimate (Audio)

| Provider | Estimated Cost (USD) |
|---|---:|
| azure-speech-stt | 0.0088 |
| azure-speech-stt-fast-phrase-list | 0.0088 |
| mai-transcribe-1.5 | 0.0088 |
| voice-live-realtime-azure-speech-phrase-list | N/A (set pricing model) |
| voice-live-realtime-gpt4o-transcribe | N/A (set pricing model) |
