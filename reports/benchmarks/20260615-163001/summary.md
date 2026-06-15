# STT Benchmark Summary

| Provider | Samples | Avg WER | Avg CER | Avg Keyword Recall | Avg Confidence | Avg Latency (ms) | Est. Cost (USD) | Decision Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| mai-transcribe-1.5 | 2 | 0.6806 | 0.6806 | 1.0000 | 0.4556 | 6728.60 | 0.0027 | 0.8907 |
| azure-speech-stt | 2 | 0.7639 | 1.0417 | 1.0000 | 0.2917 | 11139.99 | 0.0027 | 0.5673 |
| voice-live-api (session=gpt-5.4, transcription=azure-speech, lang=zh-TW) | 2 | 0.8750 | 0.8750 | 1.0000 | 0.2000 | 12317.37 | 0.0035 | 0.4069 |
| gpt-audio-transcribe | 2 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.00 | 0.1947 | 0.2000 |

Lower WER/CER, latency, and cost are better; higher keyword recall, confidence, and decision score are better.
Raw transcript metrics drive the recommendation. Corrected transcript metrics are reported separately so post-processing does not bias provider ranking.

## Recommendation

- Recommended default: `mai-transcribe-1.5`. It has the best weighted decision score in this run based on raw accuracy, latency, and estimated cost.
- Best Voice Live option in this run: `voice-live-api (session=gpt-5.4, transcription=azure-speech, lang=zh-TW)`. Use it only if you specifically want Voice Live behavior and can accept its current quality tradeoffs.
- If cost matters more than quality, compare `mai-transcribe-1.5` against the lowest-cost candidate in your own dataset before deciding.

## Corrected Transcript View

| Provider | Avg Corrected WER | Avg Corrected CER | Avg Corrected Keyword Recall | Avg Corrected Confidence |
|---|---:|---:|---:|---:|
| mai-transcribe-1.5 | 0.6806 | 0.6806 | 1.0000 | 0.4556 |
| azure-speech-stt | 0.7639 | 1.0417 | 1.0000 | 0.2917 |
| voice-live-api (session=gpt-5.4, transcription=azure-speech, lang=zh-TW) | 0.8750 | 0.8750 | 1.0000 | 0.2000 |
| gpt-audio-transcribe | 1.0000 | 1.0000 | 1.0000 | 0.0000 |

## Voice Model Benchmark

This section maps benchmark outputs to a table-aligned decision approach:
- STT quality sector: choose the provider with the best WER/CER and stable keyword recall from the table above.
- Voice service sector (managed realtime): current Voice Live default path is `voice-live-api (session=gpt-5.4, transcription=azure-speech, lang=zh-TW)`. Use this when you need realtime conversation/tool-calling style workflows, not only raw STT.
- STT-only production sector: prefer Azure Speech STT or MAI-Transcribe based on quality/cost targets; use Voice Live primarily when you also need conversational voice capabilities.
## Cost Estimate (Audio)

| Provider | Estimated Cost (USD) |
|---|---:|
| azure-speech-stt | 0.0027 |
| mai-transcribe-1.5 | 0.0027 |
| gpt-audio-transcribe | 0.1947 |
| voice-live-api | 0.0035 |
