# TTS Benchmark Summary

Text-to-speech latency/performance comparison. Generated audio is kept under each provider folder in this run for manual / MOS listening review.

| Provider | Samples | Success | Avg Chars | Avg Time-to-First-Audio (ms) | Avg Total Synthesis (ms) | Avg Audio Duration (ms) | Avg Real-Time Factor |
|---|---:|---:|---:|---:|---:|---:|---:|
| voice-live-api (model=gpt-realtime, voice=zh-TW-HsiaoChenNeural) | 3 | 3/3 | 42.7 | 503.65 | 5952.37 | 6050.00 | 1.0284 |

Lower time-to-first-audio, total synthesis time, and real-time factor are better; higher success rate is better. Real-time factor < 1.0 means faster than realtime.

## Recommendation

- Most responsive in this run: `voice-live-api (model=gpt-realtime, voice=zh-TW-HsiaoChenNeural)` (time-to-first-audio 504 ms, real-time factor 1.03).
- Latency numbers only capture responsiveness. Listen to the saved WAV files before standardizing on a voice, since naturalness and pronunciation are not scored here.