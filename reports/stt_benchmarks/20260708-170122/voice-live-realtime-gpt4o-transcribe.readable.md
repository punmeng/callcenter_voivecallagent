# Readable Results — voice-live-realtime-gpt4o-transcribe (session=gpt-realtime, transcription=gpt-4o-transcribe, lang=zh-TW)

- **Files counted toward performance:** 2
- **Files timed out (skipped):** 1
- **Total audio files:** 3

---

## HWRD_HQRD_錯_HWRD1 — ⚠️ Error

- **Reference:** 我要延長 Hardware RD Job 時間
- **Hypothesis:** _(empty response)_
- **WER:** 1.0000 · **CER:** 1.0000 · **Keyword Recall:** 0.0000 · **Confidence:** 0.0000
- **Latency:** 12177.38 ms
- **Error:** Live call failed: RuntimeError: Voice Live server error: {'message': 'Error committing input audio buffer: buffer too small. Expected at least 100ms of audio, but buffer only has 0.00ms of audio.', 'type': 'invalid_request_error', 'code': 'input_audio_buffer_commit_empty', 'param': None, 'event_id': None}

## HWRD_HQRD_錯_HWRD2 — ✅ OK

- **Reference:** 我要延長 Hardware RD Job 時間
- **Hypothesis:** 我要延長後衛阿弟trouble時間。
- **WER:** 0.5556 · **CER:** 0.6316 · **Keyword Recall:** 0.0000 · **Confidence:** 0.3289
- **Latency:** 5370.22 ms

## HWRD_HQRD_錯_HWRD3 — ⏱️ Timeout (skipped — not counted)

- **Reference:** 我要延長 Hardware RD Job 時間
- **Hypothesis:** _(empty response)_
- **Latency:** 92026.59 ms
- **Error:** Live call failed: TimeoutError: 
