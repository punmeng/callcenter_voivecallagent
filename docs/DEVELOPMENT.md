# Development

Repository organization + module map for contributors.

## Repository layout

| Path | Role |
|---|---|
| `src/voiceqa/` | Implementation code. |
| `scripts/` + `start_*.ps1` | Execution wrappers / build scripts. |
| `docs/` | Architecture, use-case guides, benchmarks, cost, changelog. |
| `catalog/` | Planning/control plane (see below). |
| `reports/` | Generated outputs only. |
| `data/` | Benchmark / test datasets. |
| `assets/` | Prompts, phrase list, corrections, rubric, UC2/UC3 HTML UIs. |

## Catalog (expansion control plane)

- `catalog/voice_catalogs.yaml` — cross-model/service/platform capabilities.
- `catalog/use_cases/*.yaml` — use-case definitions.
- `catalog/methods/*.yaml` — benchmark/runtime method definitions.
- `catalog/templates/*.yaml` — templates for new use cases.

### Adding a new use case
1. Add `catalog/use_cases/<id>.yaml` from the template.
2. Add/extend code in `src/voiceqa/`.
3. Add `start_<id>.ps1` if a new runtime path is needed.
4. Add a doc `docs/UC<n>.md` (design + run + procedure).
5. Add or reuse a benchmark method in `catalog/methods/`; update [BENCHMARKS.md](BENCHMARKS.md).
6. Add a cost section in [COST.md](COST.md).

### Naming conventions
- Use-case IDs: `uc<number>-<short-name>`.
- Method IDs: `<domain>-benchmark-v<major>`.
- Cost: keep one canonical [COST.md](COST.md) with a dedicated per-use-case section and explicit assumptions.
- Docs: consolidated descriptive names (`UC1.md`, `UC2.md`, `UC3.md`, `ARCHITECTURE.md`, …); zh-TW kept only for the top-level README.

## Module map (`src/voiceqa/`)

| Module | Responsibility |
|---|---|
| `config.py` | Loads env vars into the `Settings` dataclass (bool parsing, path defaults). |
| `models.py` | Shared data structures: transcripts, rubric items, judgments, report metadata, metrics. |
| `corrections.py` | Loads the correction dictionary; applies deterministic phrase replacements to STT text. |
| `agent_runtime.py` | Builds the shared Microsoft Agent Framework clients used by UC1/UC2/UC3 (`build_azure_openai_agent`, `build_foundry_agent`). |
| `uc1_blob_reader.py` | Blob Storage + local I/O for audio, rubric JSON, report uploads. |
| `uc1_stt_agent.py` | Azure AI Speech transcription: LID, phrase-list, corrections, `build_speech_config`. |
| `uc1_qa_judge.py` | UC1 rubric judge (one LLM call per item). |
| `uc1_markdown_writer.py` | Renders the QA report Markdown + JSON artifacts. |
| `uc1_main.py` | Orchestrates UC1 end to end. |
| `uc2_live_assistant.py` | UC2 live-assist logic + Foundry hosted-agent handlers. |
| `uc2_main.py` | UC2 entrypoint. |
| `uc3_voice_agent.py` | UC3 dispatcher, Voice Live relay, classic pipeline, agent handoffs, TTS control, recording. |
| `uc3_main.py` | UC3 entrypoint. |
| `stt_benchmark.py` / `tts_benchmark.py` | Benchmark providers + runners. |
| `web_ui.py` | Consolidated UC1/UC2/UC3 + benchmark dashboard. |

## Root files

- `python -m voiceqa.uc1_main` / `uc2_main` / `uc3_main` — launchers (also `start_uc1.ps1` / `start_uc2.ps1` / `start_uc3.ps1`).
- [../.env.example](../.env.example) — sample environment variables.
- [../requirements.txt](../requirements.txt) — Python dependencies.
- [../Dockerfile](../Dockerfile) — container image for the hosted agent.
- [../agent.yaml](../agent.yaml) — Foundry hosted-agent metadata (UC2).
- [../VERSION](../VERSION) — build version.

## Assets

- `assets/phrase_list.txt` — speech phrase boosting terms.
- `assets/corrections.json` — deterministic post-STT text corrections.
- `assets/rubric.json`, `rubric.check_items.json`, `check_items_rules.json` — rubric / scoring seed data.
- `assets/uc1_prompt.txt`, `uc2_agent_prompt.txt`, `uc3_agent_prompt.txt`, `uc3_billing_agent_prompt.txt`, `uc3_it_agent_prompt.txt` — prompts.
- `assets/uc2_call_center_ui.html`, `uc3_voice_call_ui.html` — browser UIs.

## Validation checklist

Run these quick checks after modifying runtime or benchmark code:

```powershell
$env:PYTHONPATH = "src"
python -m voiceqa.uc1_main --help
python -m voiceqa.uc2_main --help
python -m voiceqa.uc3_main --help
python scripts/eval_stt_quality.py --help
python scripts/eval_tts_quality.py --help
```

Then run one smoke flow per touched path (UC1/UC2/UC3 or benchmark) and verify outputs under `reports/`.
</content>
