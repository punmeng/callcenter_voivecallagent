# Readable Results — voice-live-realtime-gpt4o-transcribe (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW)

- **Files counted toward performance:** 2
- **Files timed out (skipped):** 1
- **Total audio files:** 3

---

## HWRD_HQRD_錯_HWRD1 — ⚠️ Error

- **Reference:** 我要延長 Hardware RD Job 時間
- **Hypothesis:** _(empty response)_
- **WER:** 1.0000 · **CER:** 1.0000 · **Keyword Recall:** 0.0000 · **Confidence:** 0.0000
- **Latency:** 52742.80 ms
- **Error:** Live call failed: RuntimeError: Voice Live server error: {'message': 'Error committing input audio buffer: buffer too small. Expected at least 100ms of audio, but buffer only has 0.00ms of audio.', 'type': 'invalid_request_error', 'code': 'input_audio_buffer_commit_empty', 'param': None, 'event_id': None}

## HWRD_HQRD_錯_HWRD2 — ✅ OK

- **Reference:** 我要延長 Hardware RD Job 時間
- **Hypothesis:** 我要延長號位RDjob的時間。
- **Corrected:** 我要延長Hardware RDJob。
- **WER:** 0.4444 · **CER:** 0.4737 · **Keyword Recall:** 0.6667 · **Confidence:** 0.5675
- **Latency:** 4748.42 ms

## HWRD_HQRD_錯_HWRD3 — ⏱️ Timeout (skipped — not counted)

- **Reference:** 我要延長 Hardware RD Job 時間
- **Hypothesis:** _(empty response)_
- **Latency:** 92023.50 ms
- **Error:** Live call failed: TimeoutError: 
