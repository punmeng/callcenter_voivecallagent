# UC1 — Blob Audio → Markdown QA Report

UC1 is the **offline batch QA pipeline**: one audio file in (from Azure Blob or local), one Markdown QA report out. It transcribes with Azure AI Speech, judges each rubric item with a Microsoft Agent Framework LLM (exception-first logic), and writes a `.md` report — not Excel.

## Contents
1. [Design](#1-design)
2. [Run](#2-run)
3. [Environment variables](#3-environment-variables)
4. [Rubric & output](#4-rubric--output)
5. [Foundry agent procedure](#5-foundry-agent-procedure)

---

## 1. Design

### Architecture (stateless batch)

```
 Azure Blob Storage                Pipeline (stateless batch)              Output
 ┌─────────────────┐    audio    ┌──────────────────────────────┐   .md   ┌──────────────┐
 │ container/*.wav  │ ─────────▶ │ 1. Blob Reader               │ ──────▶ │ Blob (out)   │
 │ rubric.json      │ ─────────▶ │ 2. STT (Azure AI Speech)     │         │  or reports/ │
 └─────────────────┘            │ 3. QA Judge (Agent Framework)│         └──────────────┘
                                 │ 4. Markdown Writer           │
                                 └──────────────────────────────┘
```

No conversation, no cross-call memory. Recommended runtime: a serverless batch job (Azure Functions or Container Apps job), Blob- or schedule-triggered, scaling to zero.

### Components
- **Blob Reader** — pulls a single blob or a prefix batch; loads rubric JSON; `call_id` = blob name without extension. Managed Identity preferred; connection string fallback for local dev.
- **STT (Azure AI Speech, batch)** — batch transcription ($0.18/audio-hr, LID + diarization included). Tuning ladder below. Output: diarized transcript.
- **QA Judge (Agent Framework)** — one LLM call per rubric item, bounded concurrency (semaphore 4), temperature 0. Verdict per item `{verdict, reason, evidence_quote}`; items 1–3 use `{summary}` (≤20 字).
- **Markdown Writer** — renders one `.md` per call; writes to output Blob container or local `reports/quality_checks/`.

### Voice optimization skills (implemented in [../src/voiceqa/uc1_stt_agent.py](../src/voiceqa/uc1_stt_agent.py))

| Skill | What it does | Where to configure |
|---|---|---|
| Continuous Language ID | Auto-detects zh-TW vs en-US per utterance (`AutoDetectSourceLanguageConfig`). | `SPEECH_LANGUAGES` or `[uc1].languages` in `config/stt_config.toml`. |
| Speaker diarization | `ConversationTranscriber` tags each turn by speaker. | Provider `azure-speech-stt` in `[uc1]`. |
| Phrase list boosting | Biases recognition toward domain terms/product names. | `assets/phrase_list.txt` (`PHRASE_LIST_PATH`); `[uc1].phrase_list`. |
| Detailed output + word timestamps | Richer scoring evidence. | Always on. |
| N-best capture | Stores top-3 alternatives per segment. | Always on. |
| Post-STT corrections | Regex canonicalization of known mis-hearings. | `assets/corrections.json` (`CORRECTIONS_PATH`). |
| Custom Speech model | Routes to a fine-tuned endpoint. | `SPEECH_CUSTOM_ENDPOINT_ID`. |
| Pluggable STT provider | Swap the engine without code changes. | `[uc1].provider` in `config/stt_config.toml`. |

### Verdict logic (exception-first)
1. Exception clause hit → apply exception result.
2. Match clause hit → `符合`.
3. Otherwise → `不符合` + reason.

### Error handling
- Blob not found → fail that call, log, continue the batch.
- STT failure / empty transcript → mark `STT_FAILED`, skip judging.
- Judge error → retry once; on second failure mark that item `判定錯誤` (don't fail the whole report).
- Idempotent: re-running a blob overwrites its report deterministically (temperature 0).

### Screenshots
![UC1 quality check page](images/02_uc1_qualitycheck.png)
![UC1 quality check report](images/03_uc1_qualitycheck_report.png)

---

## 2. Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = "src"
python -m voiceqa.uc1_main      # or: .\start_uc1.ps1
```

Local audio examples:

```powershell
# single local file
$env:INPUT_SOURCE = "local"; $env:LOCAL_AUDIO_PATH = "C:\recordings\call_001.wav"
$env:PYTHONPATH = "src"; python -m voiceqa.uc1_main

# fully local (no blob for rubric/output)
$env:INPUT_SOURCE = "local"; $env:LOCAL_AUDIO_PATH = "C:\temp\001.wav"
$env:RUBRIC_LOCAL_PATH = "assets\rubric.json"; $env:OUTPUT_TO_BLOB = "false"
$env:PYTHONPATH = "src"; python -m voiceqa.uc1_main

# local folder batch
$env:INPUT_SOURCE = "local"; $env:LOCAL_AUDIO_DIR = "C:\recordings\daily"
$env:PYTHONPATH = "src"; python -m voiceqa.uc1_main
```

From the consolidated dashboard (`start_voice_ui.ps1`), UC1 supports source-audio preview with inline playback and in-modal report viewing.

---

## 3. Environment variables

Required:
- `BLOB_ACCOUNT_URL`, `BLOB_CONTAINER_IN`, `BLOB_CONTAINER_OUT`
- Speech auth (one of): `SPEECH_KEY` + `SPEECH_REGION`, or `SPEECH_KEY` + `SPEECH_ENDPOINT`, or `SPEECH_ENDPOINT` only (Entra ID / `az login`)
- LLM runtime (one path):
  - Foundry path: `FOUNDRY_PROJECT_ENDPOINT` + (`FOUNDRY_AGENT_NAME` or `FOUNDRY_MODEL_DEPLOYMENT_NAME`), or
  - Azure OpenAI fallback path: `AOAI_ENDPOINT` + `AOAI_DEPLOYMENT` (+ `AOAI_API_KEY` unless using Entra ID)

`AOAI_ENDPOINT` accepts classic (`https://<resource>.openai.azure.com`) or new v1 (`.../openai/v1`). For keyless Azure OpenAI: `az login`, set `AOAI_USE_ENTRA_ID=true`, keep `AOAI_ENDPOINT`/`AOAI_DEPLOYMENT`/`AOAI_API_VERSION`, leave `AOAI_API_KEY` empty.

Optional: `INPUT_SOURCE` (`blob`|`local`), `INPUT_BLOB_NAME`, `INPUT_PREFIX`, `LOCAL_AUDIO_PATH`, `LOCAL_AUDIO_DIR`, `RUBRIC_LOCAL_PATH`, `OUTPUT_TO_BLOB`, `INCLUDE_TRANSCRIPT`, `JUDGE_CONCURRENCY` (default 4), `PHRASE_LIST_PATH`, `CORRECTIONS_PATH`, `SPEECH_CUSTOM_ENDPOINT_ID`.

### Method selection and optimization code map

| What you want to adjust | Code entry point |
|---|---|
| UC1 STT provider selection (`azure-speech-stt`, REST/fast/custom, MAI, Voice Live variants) | [../config/stt_config.toml](../config/stt_config.toml) (`[uc1].provider`), [../src/voiceqa/stt_config.py](../src/voiceqa/stt_config.py) (`build_uc1_stt`) |
| Speech auth path (key/endpoint/region/Entra ID) | [../src/voiceqa/uc1_stt_agent.py](../src/voiceqa/uc1_stt_agent.py) (`build_speech_config`) |
| Phrase list boost and correction rules | [../assets/phrase_list.txt](../assets/phrase_list.txt), [../assets/corrections.json](../assets/corrections.json), [../src/voiceqa/uc1_stt_agent.py](../src/voiceqa/uc1_stt_agent.py) |
| UC1 pipeline orchestration (source -> STT -> judge -> report) | [../src/voiceqa/uc1_main.py](../src/voiceqa/uc1_main.py) (`run_uc1`) |
| Judge runtime selection (Foundry agent/model or AOAI fallback) | [../src/voiceqa/uc1_qa_judge.py](../src/voiceqa/uc1_qa_judge.py) (`QaJudge._build_agent`) |
| Report rendering/output artifacts | [../src/voiceqa/uc1_markdown_writer.py](../src/voiceqa/uc1_markdown_writer.py) |

---

## 4. Rubric & output

Rubric JSON (`RUBRIC_BLOB_PATH` or `RUBRIC_LOCAL_PATH`):

```json
{
  "items": [
    {"id": "1", "type": "summary", "criteria": "開場白摘要"},
    {"id": "A1", "type": "verdict", "criteria": "...", "exception": "..."}
  ]
}
```

Output: local `reports/quality_checks/<call_id>.md`; blob `<call_id>.md`; batch mode also emits `reports/quality_checks/index.md` (+ `index.md` in the output container). Report layout: header table (音檔, 時長, 判定結果 符合/不符合 tally), 摘要 (items 1–3), 評分明細 table (判定/原因/佐證 with ❌ on `不符合`), and an optional 逐字稿 section.

---

## 5. Foundry agent procedure

UC1 prefers a **Foundry portal agent** when `FOUNDRY_AGENT_NAME` is set; otherwise it falls back to a Foundry model-deployment client or the Azure OpenAI path.

**Prerequisites:** `az login`; venv active; `.env` has `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL_DEPLOYMENT_NAME` (or `AOAI_DEPLOYMENT`), optional `UC1_PROMPT_PATH` (default `assets/uc1_prompt.txt`).

**Create/update the agent version:**
```powershell
$env:PYTHONPATH = "src"
python scripts/build_uc1_foundry_agent.py
```
Reads the prompt, calls `agents.create_version(...)`, prints `agent_name`/`agent_version`/status. Each run creates a new immutable version.

**Pin runtime to the version** (`.env`):
```env
FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
FOUNDRY_AGENT_NAME=voicecall-uc1-judge
FOUNDRY_AGENT_VERSION=<new-version>
# UC1-specific aliases also accepted:
UC1_FOUNDRY_AGENT_NAME=voicecall-uc1-judge
UC1_FOUNDRY_AGENT_VERSION=<new-version>
```

**Verify:** `.\start_uc1.ps1` → UC1 completes, `reports/002.metrics.json` shows non-zero `token_usage`, portal shows agent activity.

**Optional overrides:**
```powershell
python scripts/build_uc1_foundry_agent.py `
  --project-endpoint "https://<resource>.services.ai.azure.com/api/projects/<project>" `
  --agent-name "voicecall-uc1-judge" --model "gpt-5.4" `
  --prompt-file "assets/uc1_prompt.txt" --description "UC1 rubric judge" --temperature 0
```
</content>
