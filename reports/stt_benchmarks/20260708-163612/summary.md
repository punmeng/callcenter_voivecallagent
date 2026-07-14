# STT Benchmark Summary

| Provider | Samples | Avg WER | Avg CER | Avg Keyword Recall | Avg Confidence | Avg Latency (ms) | Est. Cost (USD) | Decision Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on) | 3 | 0.3333 | 0.4737 | 0.4444 | 0.5731 | 6001.00 | N/A | 0.9936 |
| azure-speech-stt-fast-phrase-list | 3 | 0.3704 | 0.5263 | 0.4444 | 0.5380 | 5322.39 | 0.0037 | 0.9151 |
| azure-speech-stt | 3 | 0.3704 | 0.5263 | 0.4444 | 0.5380 | 9340.75 | 0.0037 | 0.8808 |
| voice-live-realtime-gpt4o-transcribe (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW) | 2 | 0.7222 | 0.7368 | 0.3333 | 0.2838 | 28745.61 | N/A | 0.0000 |

Lower WER/CER, latency, and cost are better; higher keyword recall, confidence, and decision score are better.
Raw transcript metrics drive the recommendation. Corrected transcript metrics are reported separately so post-processing does not bias provider ranking.

## Recommendation

- Recommended default: `voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on)`. It has the best weighted decision score in this run based on raw accuracy, latency, and estimated cost.
- If cost matters more than quality, compare `voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on)` against the lowest-cost candidate in your own dataset before deciding.

## Corrected Transcript View

| Provider | Avg Corrected WER | Avg Corrected CER | Avg Corrected Keyword Recall | Avg Corrected Confidence |
|---|---:|---:|---:|---:|
| voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on) | 0.3704 | 0.5088 | 0.4444 | 0.5442 |
| azure-speech-stt-fast-phrase-list | 0.2222 | 0.2456 | 0.7778 | 0.7696 |
| azure-speech-stt | 0.2222 | 0.2456 | 0.7778 | 0.7696 |
| voice-live-realtime-gpt4o-transcribe (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW) | 0.7222 | 0.5526 | 0.5000 | 0.3816 |

## Voice Model Benchmark

This section maps benchmark outputs to a table-aligned decision approach:
- STT quality sector: choose the provider with the best WER/CER and stable keyword recall from the table above.
- STT-only production sector: prefer Azure Speech STT or MAI-Transcribe based on quality/cost targets; use Voice Live primarily when you also need conversational voice capabilities.
## Cost Estimate (Audio)

| Provider | Estimated Cost (USD) |
|---|---:|
| azure-speech-stt | 0.0037 |
| azure-speech-stt-fast-phrase-list | 0.0037 |
| voice-live-realtime-azure-speech-phrase-list | N/A (set pricing model) |
| voice-live-realtime-gpt4o-transcribe | N/A (set pricing model) |
