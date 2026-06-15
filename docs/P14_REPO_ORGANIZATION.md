# Repository Organization Guide

This guide defines a scalable structure for adding more voice catalogs and use cases.

## Current baseline

- Use case 1: UC1 batch quality check.
- Use case 2: UC2 real-time assistant.
- Benchmark method: STT benchmark v1.
- Design concept: Build 2026 voice design concept.
- Cost model: UC1 + UC2 monthly estimates in a single cost document.

## Source of truth

Use `catalog/` as the planning/control layer.

- `catalog/voice_catalogs.yaml` — cross-model/service/platform capabilities.
- `catalog/use_cases/*.yaml` — use case definitions.
- `catalog/methods/*.yaml` — method definitions.
- `catalog/templates/*.yaml` — templates for new use cases.

## File system roles

- `src/voiceqa/` — implementation code.
- `scripts/` + `start_*.ps1` — execution wrappers.
- `docs/` — architecture, procedures, benchmark, design concept, cost.
- `reports/` — generated outputs only.
- `data/` — benchmark or test datasets.

## Adding a new use case

1. Add `catalog/use_cases/<id>.yaml` using template.
2. Add/extend code in `src/voiceqa/`.
3. Add `start_<id>.ps1` if new runtime path is needed.
4. Add docs in `docs/P<n>_README_<id>.md` (use the next reading-order prefix) + design spec.
5. Add or reuse benchmark method in `catalog/methods/`.
6. Add cost section for the use case in `docs/P12_cost_estimate.md`.

## Naming conventions

- Use case IDs: `uc<number>-<short-name>`.
- Method IDs: `<domain>-benchmark-v<major>`.
- Doc names: `P<n>_README_UC<n>.md`, `P<n>_design_spec_<id>.md` (the `P<n>` prefix follows reading order; zh-TW mirrors reuse the English sibling's number).

## Cost estimation policy

- Keep one canonical file: `docs/P12_cost_estimate.md`.
- Require a dedicated section per use case with explicit assumptions.
- Keep a zh-TW mirror in `docs/P12_cost_estimate.zh-TW.md`.
