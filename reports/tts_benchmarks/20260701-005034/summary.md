# TTS Benchmark Summary

Text-to-speech latency/performance comparison. Generated audio is kept under each provider folder in this run for manual / MOS listening review.

| Provider | Samples | Success | Avg Chars | Avg Time-to-First-Audio (ms) | Avg Total Synthesis (ms) | Avg Audio Duration (ms) | Avg Real-Time Factor |
|---|---:|---:|---:|---:|---:|---:|---:|
| voice-live-api (model=gpt-realtime, voice=alloy) | 3 | 0/3 | 42.7 | 0.00 | 0.00 | 0.00 | 0.0000 |

Lower time-to-first-audio, total synthesis time, and real-time factor are better; higher success rate is better. Real-time factor < 1.0 means faster than realtime.

## Recommendation

- No provider produced audio in this run. Check credentials/endpoints (`AZURE_VOICELIVE_ENDPOINT`, `SPEECH_ENDPOINT`/`SPEECH_KEY`) and voice names.