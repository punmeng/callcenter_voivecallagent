# TTS Benchmark Summary

Text-to-speech latency/performance comparison. Generated audio is kept under each provider folder in this run for manual / MOS listening review.

| Provider | Samples | Success | Avg Chars | Avg Time-to-First-Audio (ms) | Avg Total Synthesis (ms) | Avg Audio Duration (ms) | Avg Real-Time Factor |
|---|---:|---:|---:|---:|---:|---:|---:|
| voice-live-api (model=gpt-5.4, voice=zh-TW-HsiaoChenNeural) | 5 | 5/5 | 36.4 | 668.24 | 5828.24 | 6072.50 | 0.9642 |
| azure-speech-tts (voice=zh-TW-HsiaoYuNeural) | 5 | 5/5 | 36.4 | 3290.17 | 4138.15 | 7374.60 | 0.5966 |

Lower time-to-first-audio, total synthesis time, and real-time factor are better; higher success rate is better. Real-time factor < 1.0 means faster than realtime.

## Recommendation

- Most responsive in this run: `voice-live-api (model=gpt-5.4, voice=zh-TW-HsiaoChenNeural)` (time-to-first-audio 668 ms, real-time factor 0.96).
- Latency numbers only capture responsiveness. Listen to the saved WAV files before standardizing on a voice, since naturalness and pronunciation are not scored here.