# Changelog

## v1.3.0 - 2026-07-14

TTS benchmark voice selection + custom SSML, and continuous language ID for UC1.

### Added

- **TTS benchmark per-provider voice selection** on the dashboard — a **Voice** dropdown next to each provider (`_TTS_PROVIDER_VOICES`) whose choice is passed through `build_tts_provider(name, voice=...)`, so voices can be compared without editing env vars.
- **Custom SSML for TTS benchmark** — an SSML box (with `{{text}}` per-sample placeholder) plus a **Generate welcome script** helper that builds a call-center greeting matched to the selected voice. SSML runs are limited to a single provider; `azure-speech-tts` / `mai-voice` synthesize SSML directly via `speak_ssml_async`, while the Voice Live text path speaks the SSML's extracted plain text. Added `ssml` field to `TtsSample`.

### Changed

- **UC1 continuous language identification** — the batch STT agent now sets `SpeechServiceConnection_LanguageIdMode=Continuous`, so language is re-detected/switched per utterance (zh-TW ↔ en-US) instead of only once at the start.
- Trimmed `data/tts_benchmark.template.jsonl` to 5 representative rows (zh-TW / en-US).

## v1.2.0 - 2026-07-07

STT benchmark method alignment with UC3, phrase-list/normalization improvements, and Voice Live fixes.

### Added

- **Voice Live STT benchmark methods aligned to UC3** (all use a `gpt-realtime` session): `voice-live-realtime-azure-speech` (UC3 pipeline 1, with a `-phrase-list` variant that passes domain hints via Voice Live `AudioInputTranscriptionOptions.phrase_list`) and `voice-live-realtime-gpt4o-transcribe` (UC3 pipeline 2). `gpt-4o-transcribe` does not support phrase lists, so it has no `-phrase-list` variant. Legacy `voice-live-api` / `voice-live-api-gpt-realtime` IDs kept as aliases.
- **Dashboard STT benchmark**: WAV multi-select (choose which clips to compare), best = green / worst = red per-metric coloring across the compared methods, cleaner two-line method labels with a phrase-list pill, and a **Delete old reports** button that clears `reports/stt_benchmarks`.
- **UC3 MAI-Voice-2 voices**: `en-US-Harper:MAI-Voice-2` and `zh-CN-Mei:MAI-Voice-2` (Simplified-Mandarin) in the Speaker dropdown — available on the `voicelive-tts` and `classic` pipelines; classic Listen is now selectable (azure-speech).
- **Simplified→Traditional normalization** (OpenCC `s2t`, `opencc-python-reimplemented`) applied to reference + hypothesis so engines that emit Simplified (e.g. `gpt-4o-transcribe`) aren't penalized against zh-TW references. Disable with `STT_BENCHMARK_ZH_TO_TRADITIONAL=0`.

### Changed

- STT benchmark output folder `reports/benchmarks` → `reports/stt_benchmarks`.
- **`reports/` reorganized into category folders**: UC1 quality-check reports now live under `reports/quality_checks/` (new `OUTPUT_DIR` default) alongside `stt_benchmarks/`, `tts_benchmarks/`, and `screenshots/`. Removed duplicate `spec/` architecture images (kept `VoiceQA_Architecture-v1.png` + `Voice_Method_Selection.png`).
- UC3 status-bar badges now reflect the current selection before a call; MAI voices are hidden on the all-in-one `voicelive` pipeline.
- Quieted noisy `azure.identity` credential-chain INFO logs on UC3 startup.

### Fixed

- Voice Live STT now uses `AzureSemanticVad` when the transcription model is `azure-speech` (Voice Live rejects `ServerVad` in that case).
- Voice Live STT captures only the final `input_audio_transcription.completed` transcript — no more duplicated "partial + final" output for streaming models like `gpt-4o-transcribe`.
- `mai-transcribe-1.5` auto-falls-back to standard fast transcription when the resource rejects enhanced mode, instead of returning an empty result.
- Removed the invalid `voice-live-realtime-gpt4o-transcribe-phrase-list` method (Voice Live rejects `phrase_list` for `gpt-4o-transcribe`, so it always returned empty results).
- Dashboard "Details" now opens for Voice Live methods — the per-sample lookup matches the bare provider name instead of the verbose `summary.md` display label.

## v1.1.0 - 2026-07-06

Adds the automated voice agent (UC3), the TTS benchmark, and selectable voice pipelines.

### Added

- **UC3 — automated AI voice agent** (speech-to-speech) via Azure AI Voice Live `gpt-realtime`, mounted at `/uc3/live` plus standalone `start_uc3.ps1`.
- **Three selectable UC3 pipelines** (chosen per call from the UI): `voicelive` (STT+LLM+TTS bundled), `voicelive-tts` (Voice Live STT+LLM → Azure Speech TTS with SSML pronunciation control, e.g. "101" → "1-0-1"), and `classic` (Azure Speech STT → Foundry chat LLM → Azure Speech TTS, no Voice Live).
- **UC3 agent handoffs** via function tools: `query_billing`, `query_it_support`, `escalate_to_expert`, each routed to a dedicated Foundry agent with knowledge grounding (`allow_preview=True`).
- **UC3 method selectors + badges** in the UI (Listen / Speaker+language / Think), pipeline dropdown, `/health`-synced defaults, and validated per-call overrides.
- **UC3 recording** — mixes mic + agent audio into a WAV saved to UC1's source folder for quality-checking.
- **TTS benchmark** (mirrors the STT benchmark): providers `voice-live-api`, `azure-speech-tts`, `gpt-realtime`, `mai-voice`; latency/perf metrics + kept WAV artifacts; dashboard tab and `start_tts_benchmark_matrix.ps1`.
- Dashboard nav split into STT Benchmark and TTS Benchmark; real `/uc3` tab.
- Catalog-driven organization layer (`catalog/` use_cases, methods, templates).

### Docs

- Updated docs for UC3: architecture ([ARCHITECTURE.md](ARCHITECTURE.md)) added Case 3 / UC3, cost ([COST.md](COST.md)) added the UC3 pipeline cost & optimization table, and [UC3.md](UC3.md) covers the three pipelines + handoffs. Added the TTS benchmark to [BENCHMARKS.md](BENCHMARKS.md).
- **Consolidated the `docs/` set from 23 files (P1–P19 + zh-TW mirrors) down to 10**: [README.md](README.md) (+ [README.zh-TW.md](README.zh-TW.md)), [ARCHITECTURE.md](ARCHITECTURE.md), [UC1.md](UC1.md), [UC2.md](UC2.md), [UC3.md](UC3.md), [BENCHMARKS.md](BENCHMARKS.md), [COST.md](COST.md), [DEVELOPMENT.md](DEVELOPMENT.md), [CHANGELOG.md](CHANGELOG.md). Per-use-case design spec + README + Foundry procedure merged into one guide each; STT + TTS benchmarks merged; zh-TW kept only for the top-level README.
- Fact-checked consolidated docs against runtime behavior and added direct code-reference maps for UC3 method selection and voice optimization in [UC3.md](UC3.md) and [BENCHMARKS.md](BENCHMARKS.md).
- Extended fact-check to UC1/UC2 guides: corrected UC1 LLM runtime requirements (Foundry path vs AOAI fallback), corrected UC2 resilience wording to match current baseline, and added direct method-selection/voice-optimization code maps in [UC1.md](UC1.md) and [UC2.md](UC2.md).

### Changed

- UC3 `classic` pipeline now uses the same SSML-controlled Azure Speech TTS path as `voicelive-tts` (`_synthesize_controlled`), so pronunciation controls are consistent across both Azure-TTS pipelines.
- Fixed UC2 STT runtime label default text from "Text to Speech" to "Speech to Text" in the live assistant model label resolver.
- Benchmark runners now default to existing dataset templates (`data/stt_benchmark.template.jsonl`, `data/tts_benchmark.template.jsonl`) and STT CLI now runs directly without requiring external `PYTHONPATH` setup.
- STT benchmark CLI provider choices now include Voice Live variant IDs (`voice-live-api-gpt-4o-transcribe`, `voice-live-api-mai-transcribe-1`).

## v1.0.0 - 2026-06-16

Initial baseline release for the consolidated VoiceCall Verify experience.

### Included

- UC1 batch QA pipeline with STT, rubric scoring, markdown/json report output.
- UC2 realtime call assistant flow with live guidance and runtime metrics.
- Consolidated dashboard for Home, UC1, UC2, and Benchmark pages.
- STT benchmark matrix flow with provider comparison and run history rendering.
- Bilingual dashboard header support (English and Traditional Chinese).
- Audio preview endpoint and inline player on UC1/Benchmark source tables.

### Cleanup in this release

- Removed obsolete dashboard config-page handlers and routes.
- Removed unused imports from dashboard server module.
- Updated key docs to match current runtime behavior and launch flow.
