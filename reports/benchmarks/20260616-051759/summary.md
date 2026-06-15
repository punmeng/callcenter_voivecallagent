# STT Benchmark Summary

| Provider | Samples | Avg WER | Avg CER | Avg Keyword Recall | Avg Confidence | Avg Latency (ms) | Est. Cost (USD) | Decision Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| mai-transcribe-1.5 | 2 | 0.6806 | 0.6806 | 1.0000 | 0.4556 | 5061.92 | 0.0027 | 0.7827 |
| azure-speech-stt-fast | 2 | 0.7639 | 1.0417 | 1.0000 | 0.2917 | 5610.91 | 0.0027 | 0.3029 |
| azure-speech-stt-fast-phrase-list | 2 | 0.7639 | 1.0417 | 1.0000 | 0.2917 | 5659.17 | 0.0027 | 0.3002 |
| azure-speech-stt-rest | 2 | 0.8750 | 0.8750 | 1.0000 | 0.2000 | 2977.49 | 0.0009 | 0.3000 |
| azure-speech-stt | 2 | 0.7639 | 1.0417 | 1.0000 | 0.2917 | 6531.56 | 0.0027 | 0.2511 |

Lower WER/CER, latency, and cost are better; higher keyword recall, confidence, and decision score are better.
Raw transcript metrics drive the recommendation. Corrected transcript metrics are reported separately so post-processing does not bias provider ranking.

## Recommendation

- Recommended default: `mai-transcribe-1.5`. It has the best weighted decision score in this run based on raw accuracy, latency, and estimated cost.
- If cost matters more than quality, compare `mai-transcribe-1.5` against the lowest-cost candidate in your own dataset before deciding.

## Corrected Transcript View

| Provider | Avg Corrected WER | Avg Corrected CER | Avg Corrected Keyword Recall | Avg Corrected Confidence |
|---|---:|---:|---:|---:|
| mai-transcribe-1.5 | 0.6806 | 0.6806 | 1.0000 | 0.4556 |
| azure-speech-stt-fast | 0.7639 | 1.0417 | 1.0000 | 0.2917 |
| azure-speech-stt-fast-phrase-list | 0.7639 | 1.0417 | 1.0000 | 0.2917 |
| azure-speech-stt-rest | 0.8750 | 0.8750 | 1.0000 | 0.2000 |
| azure-speech-stt | 0.7639 | 1.0417 | 1.0000 | 0.2917 |

## Voice Model Benchmark

This section maps benchmark outputs to a table-aligned decision approach:
- STT quality sector: choose the provider with the best WER/CER and stable keyword recall from the table above.
- STT-only production sector: prefer Azure Speech STT or MAI-Transcribe based on quality/cost targets; use Voice Live primarily when you also need conversational voice capabilities.
## Cost Estimate (Audio)

| Provider | Estimated Cost (USD) |
|---|---:|
| azure-speech-stt | 0.0027 |
| azure-speech-stt-fast | 0.0027 |
| azure-speech-stt-fast-phrase-list | 0.0027 |
| azure-speech-stt-rest | 0.0009 |
| mai-transcribe-1.5 | 0.0027 |
