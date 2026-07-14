# STT Benchmark Summary

| Provider | Samples | Avg WER | Avg CER | Avg Keyword Recall | Avg Confidence | Avg Latency (ms) | Est. Cost (USD) | Decision Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| azure-speech-stt-fast-phrase-list | 3 | 0.3704 | 0.5263 | 0.4444 | 0.5380 | 4658.20 | 0.0037 | 1.0000 |
| azure-speech-stt | 3 | 0.3704 | 0.5263 | 0.4444 | 0.5380 | 6300.09 | 0.0037 | 0.9216 |
| mai-transcribe-1.5 | 3 | 0.4444 | 0.5965 | 0.2222 | 0.4357 | 8846.27 | 0.0037 | 0.5322 |
| voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on) | 3 | 0.6667 | 0.7193 | 0.1111 | 0.2705 | 5787.93 | N/A | 0.1623 |

Lower WER/CER, latency, and cost are better; higher keyword recall, confidence, and decision score are better.
Raw transcript metrics drive the recommendation. Corrected transcript metrics are reported separately so post-processing does not bias provider ranking.

## Recommendation

- Recommended default: `azure-speech-stt-fast-phrase-list`. It has the best weighted decision score in this run based on raw accuracy, latency, and estimated cost.
- If you want the safest quality choice for production-style transcription on this dataset, stay with Azure Speech STT.

## Corrected Transcript View

| Provider | Avg Corrected WER | Avg Corrected CER | Avg Corrected Keyword Recall | Avg Corrected Confidence |
|---|---:|---:|---:|---:|
| azure-speech-stt-fast-phrase-list | 0.1111 | 0.2105 | 0.7778 | 0.8319 |
| azure-speech-stt | 0.1111 | 0.2105 | 0.7778 | 0.8319 |
| mai-transcribe-1.5 | 0.2593 | 0.4211 | 0.4444 | 0.6249 |
| voice-live-realtime-azure-speech-phrase-list (session=gpt-realtime, transcription=azure-speech, lang=zh-TW, phrase_list=on) | 0.4815 | 0.5439 | 0.3333 | 0.4596 |

## Voice Model Benchmark

This section maps benchmark outputs to a table-aligned decision approach:
- STT quality sector: choose the provider with the best WER/CER and stable keyword recall from the table above.
- STT-only production sector: prefer Azure Speech STT or MAI-Transcribe based on quality/cost targets; use Voice Live primarily when you also need conversational voice capabilities.
## Cost Estimate (Audio)

| Provider | Estimated Cost (USD) |
|---|---:|
| azure-speech-stt | 0.0037 |
| azure-speech-stt-fast-phrase-list | 0.0037 |
| mai-transcribe-1.5 | 0.0037 |
| voice-live-realtime-azure-speech-phrase-list | N/A (set pricing model) |
