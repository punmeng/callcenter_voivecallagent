# Changelog

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
