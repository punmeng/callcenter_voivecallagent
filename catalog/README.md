# Voice Catalog Registry

This folder is a lightweight control plane for scaling VoiceCall Verify beyond UC1/UC2.

## Structure

- `use_cases/` — one YAML per business use case.
- `methods/` — one YAML per reusable evaluation or runtime method.
- `templates/` — starter YAML templates for new use cases/methods.
- `voice_catalogs.yaml` — shared capability matrix and technology layers.

## How to add a new use case

1. Copy `templates/use_case.template.yaml` to `use_cases/<new-name>.yaml`.
2. Set `runtime.method_id` to an existing method in `methods/`.
3. Set `capabilities.required` to the minimum required features.
4. Add docs under `docs/` and link from `docs/README.md`.

## Current baseline

- `uc1-quality-check` (batch QA report)
- `uc2-realtime-assistant` (live call assist)
- `stt-benchmark-v1` (cross-provider STT benchmark)
