# Development Notes

This note describes what each important file in the current codebase does.

## Root files

- `python -m voiceqa.uc1_main` - UC1 batch launcher.
- `python -m voiceqa.uc2_main` - UC2 hosted-agent launcher.
- [../src/voiceqa/uc1_main.py](../src/voiceqa/uc1_main.py) - UC1 batch orchestration.
- [../src/voiceqa/uc2_main.py](../src/voiceqa/uc2_main.py) - UC2 hosted-agent entrypoint.
- [../.env.example](../.env.example) - sample environment variables for local development.
- [../requirements.txt](../requirements.txt) - Python dependencies used by both UC1 and UC2.
- [../Dockerfile](../Dockerfile) - container image definition for the hosted agent.
- [../agent.yaml](../agent.yaml) - Foundry hosted-agent metadata and environment variables for UC2.
- [P1_README.md](P1_README.md) - top-level overview of the current codebase.
- [P7_README_UC1.md](P7_README_UC1.md) - UC1-specific usage and environment notes.
- [P8_README_UC2.md](P8_README_UC2.md) - UC2-specific usage and environment notes.
- [P2_scope.md](P2_scope.md) - business scope and case comparison.
- [P4_architecture.md](P4_architecture.md) - current architecture and deployment rationale.
- [P5_design_spec_uc1_blob_to_md.md](P5_design_spec_uc1_blob_to_md.md) - UC1 design spec.
- [P6_design_spec_uc2_realtime_assistant.md](P6_design_spec_uc2_realtime_assistant.md) - UC2 design spec.

## Assets

- [../assets/phrase_list.txt](../assets/phrase_list.txt) - speech phrase boosting terms.
- [../assets/corrections.json](../assets/corrections.json) - deterministic post-STT text corrections.
- [../assets/rubric.json](../assets/rubric.json) - local rubric source used when present.
- [../assets/rubric.check_items.json](../assets/rubric.check_items.json) - rubric check-item seed data.
- [../assets/check_items_rules.json](../assets/check_items_rules.json) - rule mapping used for scoring artifacts.
- [../assets/uc1_prompt.txt](../assets/uc1_prompt.txt) - UC1 judge prompt text.
- [../assets/uc2_agent_prompt.txt](../assets/uc2_agent_prompt.txt) - UC2 live-assistant prompt text.

## Reports

- [../reports/002_azure-speech-stt_20260615_141244.md](../reports/002_azure-speech-stt_20260615_141244.md) - example UC1 Markdown report.
- [../reports/002.scoring.json](../reports/002.scoring.json) - example scoring details output.
- [../reports/002.metrics.json](../reports/002.metrics.json) - example metrics output.
- [../reports/scoring_rules.json](../reports/scoring_rules.json) - generated rule summary for scoring.

## Source package

### `src/voiceqa/config.py`

Loads environment variables into the `Settings` dataclass used by UC1. It also handles boolean parsing and path defaults.

### `src/voiceqa/models.py`

Defines the shared data structures for transcripts, rubric items, judgment results, report metadata, and metrics.

### `src/voiceqa/corrections.py`

Loads the correction dictionary and applies deterministic phrase replacements to STT text.

### `src/voiceqa/uc1_blob_reader.py`

Handles Blob Storage and local file input/output for audio, rubric JSON, and report uploads.

### `src/voiceqa/uc1_stt_agent.py`

Runs Azure AI Speech transcription, applies language detection, phrase list tuning, and post-STT corrections.

### `src/voiceqa/uc1_qa_judge.py`

Runs the UC1 rubric judge with Microsoft Agent Framework, one LLM call per rubric item.

### `src/voiceqa/uc1_markdown_writer.py`

Renders the QA report Markdown and writes the JSON artifact files.

### `src/voiceqa/agent_runtime.py`

Builds the shared Microsoft Agent Framework clients used by both UC1 and UC2.

### `src/voiceqa/uc2_live_assistant.py`

Implements the UC2 live-assist logic and the Foundry hosted-agent handlers.

### `src/voiceqa/uc1_main.py`

Orchestrates the UC1 pipeline end to end: load settings, read audio, transcribe, judge, and write reports.

### `src/voiceqa/__init__.py`

Marks the package and provides the package docstring.
