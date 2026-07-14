# Benchmarks

Two benchmark suites compare voice methods with the same dataset and emit run history under `reports/`. Use the **STT benchmark** to pick a transcription method (accuracy/latency/cost) and the **TTS benchmark** to compare synthesis providers (latency/perf + kept audio for MOS review).

- STT: `python scripts/eval_stt_quality.py` · `start_stt_benchmark_matrix.ps1` → `reports/stt_benchmarks/<run-id>/`
- TTS: `python scripts/eval_tts_quality.py` · `start_tts_benchmark_matrix.ps1` → `reports/tts_benchmarks/<run-id>/`

---

## Part A — STT benchmark

Compares transcript quality/latency/cost across providers:

- `azure-speech-stt`, `azure-speech-stt-fast`, `azure-speech-stt-fast-phrase-list`, `azure-speech-stt-rest`, `azure-speech-stt-custom`
- `mai-transcribe-1.5`
- `gpt-audio-transcribe`
- Voice Live (all use a `gpt-realtime` session — mirror UC3 pipelines 1/2, split by transcription model):
  - `voice-live-realtime-azure-speech` and `voice-live-realtime-azure-speech-phrase-list`
  - `voice-live-realtime-gpt4o-transcribe`

> **Phrase-list support:** Voice Live only accepts `phrase_list` hints for the `azure-speech`, `azure-mrs`, `mai-transcribe`, `mai-transcribe-1.5`, and `azure-fast-transcription` transcription models. `gpt-4o-transcribe` does **not** support phrase lists, so there is no `voice-live-realtime-gpt4o-transcribe-phrase-list` method — only the plain `voice-live-realtime-gpt4o-transcribe` variant is available.

Metrics per provider: WER, CER, keyword recall, average latency, and a **weighted decision score** (default `70%` raw accuracy, `20%` latency, `10%` estimated cost). `summary.md` also appends an audio cost estimate.

### Two sectors
- **STT benchmark sector** — quality and latency for transcript output.
- **Voice model benchmark sector** — table-aligned recommendation for when to use the managed realtime voice service (`voice-live-realtime-*`) vs STT-focused engines.

### Table-aligned approach
- **STT-only path** (Azure Speech / MAI-Transcribe): prioritize WER/CER and keyword recall; latency & cost as tie-breakers.
- **Managed realtime voice path** (Voice Live API): use when you need realtime dialog/tool-calling in the same service, not only raw transcript quality.
- Run the same audio set across all providers, then use `summary.md` to pick the default method per scenario.

### Traditional Chinese decision matrix
Treat the benchmark as a decision matrix, not a single WER table:
- **Primary axis:** raw transcript accuracy (the weighted score). **Secondary:** corrected-transcript accuracy (reported separately so repo correction rules don't bias ranking).
- **Normalization:** NFKC, ignore punctuation, collapse whitespace, lower-case Latin, and **Simplified→Traditional** (OpenCC `s2t`) so engines that emit Simplified Chinese (e.g. `gpt-4o-transcribe`) aren't penalized against Traditional zh-TW references — disable with `STT_BENCHMARK_ZH_TO_TRADITIONAL=0`. Mixed zh-TW + English is judged consistently.
- **Keyword coverage:** populate `keywords` with business terms that matter downstream (product names, addresses, cancel/reschedule intents, policy phrases, account-verification terms).
- **Sample coverage:** short/noisy/mixed/agent-heavy/customer-heavy calls and calls with named entities.
- **Decision threshold:** don't standardize on one provider unless it stays near the top across all scenario buckets, not just the overall average.

Recommended scenario buckets: greeting/identity verification · appointment/order changes · billing/payment · complaint/escalation · addresses/names/dates/phone/codes · mixed Mandarin / Taiwanese-accented Mandarin / English terminology.

### Dataset format (JSONL)
```json
{"call_id":"001","audio_path":"C:/temp/001.wav","reference_text":"您好我要取消租屋","keywords":["取消","租屋"],"audio_duration_seconds":4.49,"voice_live_hypothesis":"...","mai_transcribe_hypothesis":"..."}
```
Required: `call_id`, `audio_path`, `reference_text`. Recommended: `keywords` (2–8 intent/entity terms), `audio_duration_seconds` (cost estimate), `voice_live_hypothesis`, `mai_transcribe_hypothesis`. Include English loanwords/acronyms when agents actually say them.

### Run
```powershell
.\start_stt_benchmark_matrix.ps1                 # default STT-oriented paths
.\start_stt_benchmark_matrix.ps1 -IncludeVoiceLive
```
Outputs: `reports/stt_benchmarks/<run-id>/summary.md`, `reports/stt_benchmarks/<run-id>/<provider>.results.jsonl`. The Voice Live methods pin the session model via `UC3_VOICE_LIVE_MODEL` (default `gpt-realtime`).

---

## Part B — TTS benchmark

Compares synthesis providers on **latency/performance** (not intelligibility/MOS) and keeps generated WAVs for manual/MOS review.

### Providers (`--providers`; default `voice-live-api`, `azure-speech-tts`)
- `voice-live-api` — Voice Live realtime TTS (`gpt-realtime`), Azure standard/neural voice via `pre_generated_assistant_message` (falls back to instruction-driven read).
- `gpt-realtime` — Voice Live realtime TTS pinned to an OpenAI voice (instruction strategy).
- `azure-speech-tts` — Azure Speech SDK neural TTS baseline (`Riff24Khz16BitMonoPcm`).
- `mai-voice` — Azure Speech multilingual neural voice (MAI-Voice-2), e.g. `en-US-Harper:MAI-Voice-2`.

### Metrics (latency/perf only, by design)
`time_to_first_audio_ms`, `total_synthesis_ms`, `audio_duration_ms`, `real_time_factor` (RTF). No WER/intelligibility/cost scoring — judge quality by listening to `reports/tts_benchmarks/<run>/<provider>/<sample>.wav`.

### Run
```powershell
python scripts/eval_tts_quality.py --dataset data/tts_benchmark.template.jsonl `
  --providers voice-live-api azure-speech-tts gpt-realtime mai-voice --parallel

.\start_tts_benchmark_matrix.ps1 -IncludeGptRealtime -GptRealtimeVoice marin `
  -IncludeMaiVoice -MaiVoiceName en-US-Harper:MAI-Voice-2
```

### Dataset format (JSONL)
`{ "sample_id": "...", "text": "...", "language": "zh-TW", "scenario": "zh-TW|en-US|mixed" }`. Required: `sample_id`, `text`. See `data/tts_benchmark.template.jsonl` (5 rows across zh-TW / en-US).

### Voice configuration
- `AZURE_VOICELIVE_TTS_VOICE` (default `zh-TW-HsiaoChenNeural`) — Voice Live path. Names with `Neural` or 2+ dashes → Azure standard voice; otherwise an OpenAI voice string.
- `AZURE_SPEECH_TTS_VOICE` (default `zh-TW-HsiaoChenNeural`) — Azure Speech baseline.
- `GPT_REALTIME_TTS_VOICE` / `GPT_REALTIME_MODEL` — `gpt-realtime` provider.
- `MAI_VOICE_NAME` — MAI-Voice-2 id (`<locale>-<Name>:MAI-Voice-2`).

> Voice Live TTS key learning: audio requires `modalities=[AUDIO]`; verbatim `pre_generated_assistant_message` gives exact synthesis for Azure neural voices, while OpenAI voices need the instruction strategy. Override with `VOICE_LIVE_TTS_STRATEGY`.

### Dashboard: per-provider voice + custom SSML
The TTS benchmark page (`/tts-benchmark`) adds a **Voice** dropdown next to each provider (from `_TTS_PROVIDER_VOICES` in [../src/voiceqa/web_ui.py](../src/voiceqa/web_ui.py)) so you can compare specific voices without editing env vars; the selection is passed through `build_tts_provider(name, voice=...)`. A **Custom speech (SSML)** box lets you supply an SSML document (use `{{text}}` as a per-sample placeholder) to tune prosody, style, and pauses; **Generate welcome script** fills in a call-center greeting matched to the selected voice. When SSML is used only one provider may be selected, and its voice must match the SSML `<voice>`. Providers that cannot consume SSML (the Voice Live text-driven path) fall back to the SSML's extracted plain text; `azure-speech-tts` / `mai-voice` synthesize the SSML directly via `speak_ssml_async`.

---

## Provider-name reference (across subsystems)

The same model families appear under different identifiers in different places — match the identifier to the subsystem:

| Family | STT benchmark (`eval_stt_quality.py`) | UC3 Voice Live in-call (Listen dropdown) | TTS benchmark |
|---|---|---|---|
| Azure Speech | `azure-speech-stt` (+ `-fast`, `-rest`, `-custom`) | `azure-speech` | `azure-speech-tts` |
| GPT transcribe | `gpt-audio-transcribe` | `gpt-4o-transcribe` (+ `-mini`, `-diarize`) | — |
| MAI | `mai-transcribe-1.5` | `mai-transcribe-1` | `mai-voice` (MAI-Voice-2, TTS) |
| Voice Live | `voice-live-realtime-azure-speech` / `-gpt4o-transcribe` (+ `-phrase-list`) | `gpt-realtime` / `gpt-4o-realtime-preview` | `voice-live-api` / `gpt-realtime` |

> Note: `voice-live-api` and `voice-live-api-gpt-realtime` remain as legacy aliases for the two methods above. The `-phrase-list` variants pass domain hints via Voice Live's `AudioInputTranscriptionOptions.phrase_list`. `voice-live-api-mai-transcribe-1` is also available for MAI transcription-model pinning.

---

## Method selection code references

| What you want to adjust | Code location |
|---|---|
| STT provider factory and aliases | [../src/voiceqa/stt_benchmark.py](../src/voiceqa/stt_benchmark.py) (`build_provider`) |
| STT scoring weights (accuracy/latency/cost) | [../src/voiceqa/stt_benchmark.py](../src/voiceqa/stt_benchmark.py) (`load_scoring_profile`) |
| TTS provider factory and defaults | [../src/voiceqa/tts_benchmark.py](../src/voiceqa/tts_benchmark.py) (`build_tts_provider`) |
| TTS Voice Live strategy (`pregenerated` vs `instructions`) | [../src/voiceqa/tts_benchmark.py](../src/voiceqa/tts_benchmark.py) (`VoiceLiveTtsProvider._synthesize_via_voicelive`) |
| Dashboard benchmark provider whitelist/defaults | [../src/voiceqa/web_ui.py](../src/voiceqa/web_ui.py) (`_BENCHMARK_SUPPORTED_PROVIDERS`, `_TTS_SUPPORTED_PROVIDERS`, `_TTS_DEFAULT_PROVIDERS`) |
| STT matrix run presets | [../start_stt_benchmark_matrix.ps1](../start_stt_benchmark_matrix.ps1) |
| TTS matrix run presets | [../start_tts_benchmark_matrix.ps1](../start_tts_benchmark_matrix.ps1) |

## Voice optimization code references

| Optimization target | Code location |
|---|---|
| Improve STT domain terms (phrase list) | [../assets/phrase_list.txt](../assets/phrase_list.txt), [../src/voiceqa/uc1_stt_agent.py](../src/voiceqa/uc1_stt_agent.py) |
| Deterministic correction rules | [../assets/corrections.json](../assets/corrections.json), [../src/voiceqa/corrections.py](../src/voiceqa/corrections.py) |
| Voice Live TTS strategy + voice selection | [../src/voiceqa/tts_benchmark.py](../src/voiceqa/tts_benchmark.py), [../src/voiceqa/uc3_voice_agent.py](../src/voiceqa/uc3_voice_agent.py) |
| UC3 pronunciation/SSML tuning in production call flow | [../src/voiceqa/uc3_voice_agent.py](../src/voiceqa/uc3_voice_agent.py) (`_apply_speech_control`, `_build_ssml`) |
</content>
