# Process Summary

This document summarizes the current working process for VoiceCall Verify across development, execution, evaluation, and expansion.

## 1. Scope baseline

Current baseline includes:

- Use case 1 (UC1): Batch quality check from audio to Markdown report.
- Use case 2 (UC2): Real-time call assistant.
- Benchmark method: STT benchmark with comparable provider outputs.
- Design concept: Build 2026 voice use-case design framework.
- Cost estimation: Case-based monthly estimate for UC1 and UC2.

## 2. End-to-end workflow

1. Define scenario and business outcome.
2. Select use case path (UC1 batch or UC2 realtime).
3. Run implementation entrypoint (`start_uc1.ps1` / `start_uc2.ps1`).
4. Run benchmark (`start_stt_benchmark_matrix.ps1`) for quality/cost comparison.
5. Review generated reports under `reports/` and `reports/benchmarks/<run-id>/`.
6. Update design/cost docs when assumptions or architecture change.

## 3. Runtime process

### UC1 process

- Input: local audio or blob audio.
- STT: Azure Speech transcription with phrase-list and correction pipeline.
- Judge: Agent Framework rubric scoring.
- Output: markdown report + JSON scoring and metrics artifacts.

Primary entrypoint:

```powershell
.\start_uc1.ps1
```

### UC2 process

- Input: live transcript messages from websocket channel.
- Assist: Agent Framework runtime for next-best-action/compliance guidance.
- Metrics: STT mode, LLM mode, token usage, cumulative audio duration.
- Output: live assist cards and optional summary content.

Primary entrypoint:

```powershell
.\start_uc2.ps1
```

## 4. Benchmark process

Default benchmark compares stable STT-oriented paths:

- `azure-speech-stt`
- `azure-speech-stt-fast`
- `azure-speech-stt-fast-phrase-list`
- `azure-speech-stt-rest`
- `mai-transcribe-1.5`

Voice Live can be included only when explicitly requested.

Primary entrypoint:

```powershell
.\start_stt_benchmark_matrix.ps1
```

Optional Voice Live run:

```powershell
.\start_stt_benchmark_matrix.ps1 -IncludeVoiceLive
```

Benchmark outputs:

- `reports/benchmarks/<run-id>/summary.md`
- `reports/benchmarks/<run-id>/<provider>.results.jsonl`

## 5. Design and decision process

Decision principle:

- Do not select technology by model/API name alone.
- Start from customer problem and application scenario.

Use the three-layer view from the design concept:

- Model layer
- Service layer
- Orchestration platform layer

Reference:

- `docs/P3_VOICE_USE_CASES_DESIGN_CONCEPT.zh-TW.md`

## 6. Cost process

Use one canonical cost file with per-use-case sections:

- `docs/P12_cost_estimate.md`

Current sections:

- Case 1: UC1 quality check (batch)
- Case 2: UC2 call assistant (realtime)

## 7. Repository organization process

Use `catalog/` as the control plane for expansion:

- `catalog/voice_catalogs.yaml` for capability matrix and technology layers.
- `catalog/use_cases/*.yaml` for each use case definition.
- `catalog/methods/*.yaml` for benchmark/runtime methods.
- `catalog/templates/` for new use case scaffolding.

When adding a new use case:

1. Add catalog use-case YAML.
2. Add/extend implementation code in `src/voiceqa/`.
3. Add start script if needed.
4. Add docs and design spec.
5. Add benchmark mapping and cost section.

## 8. Validation snapshot (latest)

Validated on 2026-06-04:

- UC1 startup/run: pass.
- UC2 startup smoke test: pass (server boot).
- Benchmark matrix default run: pass.

## 9. Primary references

- `docs/P1_README.md`
- `docs/P7_README_UC1.md`
- `docs/P8_README_UC2.md`
- `docs/P11_STT_BENCHMARK.md`
- `docs/P3_VOICE_USE_CASES_DESIGN_CONCEPT.zh-TW.md`
- `docs/P14_REPO_ORGANIZATION.md`
- `docs/P12_cost_estimate.md`
- `catalog/README.md`
