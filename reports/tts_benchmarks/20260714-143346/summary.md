# TTS Benchmark Summary

Text-to-speech latency/performance comparison. Generated audio is kept under each provider folder in this run for manual / MOS listening review.

| Provider | Samples | Success | Avg Chars | Avg Time-to-First-Audio (ms) | Avg Total Synthesis (ms) | Avg Audio Duration (ms) | Avg Real-Time Factor |
|---|---:|---:|---:|---:|---:|---:|---:|
| voice-live-api (model=gpt-5.4, voice=en-US-AvaMultilingualNeural) | 5 | 5/5 | 36.4 | 485.74 | 4037.74 | 5805.00 | 0.7137 |
| azure-speech-tts (voice=zh-CN-XiaoxiaoNeural) | 5 | 5/5 | 36.4 | 2965.77 | 3866.73 | 5679.60 | 0.7134 |

Lower time-to-first-audio, total synthesis time, and real-time factor are better; higher success rate is better. Real-time factor < 1.0 means faster than realtime.

## Recommendation

- Most responsive in this run: `voice-live-api (model=gpt-5.4, voice=en-US-AvaMultilingualNeural)` (time-to-first-audio 486 ms, real-time factor 0.71).
- Latency numbers only capture responsiveness. Listen to the saved WAV files before standardizing on a voice, since naturalness and pronunciation are not scored here.