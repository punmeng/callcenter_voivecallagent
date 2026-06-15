# Changelog

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
