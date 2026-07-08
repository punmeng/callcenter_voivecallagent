# Deployment Guide

How to deploy **VoiceCall Verify** to a new machine (Windows or Linux/Docker), including
prerequisites, Azure resources, environment setup, and how to run each entry point.

---

## 1. Prerequisites

### 1.1 Machine / runtime

| Requirement | Notes |
|---|---|
| **Python 3.12** | The project targets 3.12 (matches `Dockerfile` `python:3.12-slim`). 3.11+ generally works. |
| **pip / venv** | Bundled with Python. |
| **Git** | To clone the repo (or copy the folder over). |
| **PowerShell 7+** (Windows) | For the `start_*.ps1` launchers. Not required on Linux. |
| **Azure CLI** (`az`) | Only if you authenticate with `az login` instead of keys (see §4). |
| **Outbound HTTPS (443)** | To reach Azure Speech / OpenAI / Voice Live / Blob endpoints. |

### 1.2 Linux-only system packages

The Azure Speech SDK (`azure-cognitiveservices-speech`) needs a few shared libraries that
are **not** in `python:3.12-slim` by default:

```bash
apt-get update && apt-get install -y \
    build-essential ca-certificates libssl-dev libasound2 wget
```

(On Windows these are already provided by the OS.)

### 1.3 Azure resources

Provision only what the use cases you plan to run require:

| Resource | Needed for | Key env vars |
|---|---|---|
| **Azure AI Speech** | UC1, UC2, benchmarks, UC3 classic pipeline | `SPEECH_ENDPOINT` (+ `SPEECH_KEY` or `az login`) |
| **Azure OpenAI** | UC1 judge, UC2/UC3 LLM, **Tuning** button, `gpt-audio-transcribe` | `AOAI_ENDPOINT`, `AOAI_DEPLOYMENT` (+ `AOAI_API_KEY` or Entra) |
| **Azure AI Voice Live** | UC2, UC3 (voicelive pipelines), Voice Live STT/TTS benchmarks | `AZURE_VOICELIVE_ENDPOINT` (+ `AZURE_VOICELIVE_API_KEY` or `az login`) |
| **Foundry project + agents** | UC1/UC2/UC3 portal agents, LLM tuning agent | `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL_DEPLOYMENT_NAME`, agent names |
| **Azure Blob Storage** | UC1 blob input/output mode only (optional) | `BLOB_ACCOUNT_URL`, `BLOB_CONTAINER_IN/OUT` |

> You can run UC1 fully offline against local WAVs (`INPUT_SOURCE=local`) without Blob Storage.

---

## 2. Get the code

```powershell
git clone <your-repo-url> "VoiceCall Verify"
cd "VoiceCall Verify"
```

Or copy the project folder to the target machine. Do **not** copy `.venv/` — recreate it (§3).

---

## 3. Install (native)

### Windows (PowerShell)

```powershell
# From the repo root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Linux / macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

The `start_*.ps1` scripts auto-detect `.venv\Scripts\python.exe`; if absent they fall back to
the system `python`.

---

## 4. Configure environment

1. Copy the template and fill in values:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Edit `.env`. Minimum for the **dashboard + STT benchmarks + UC1 (local)**:

   ```dotenv
   # Azure AI Speech
   SPEECH_ENDPOINT=https://<region>.api.cognitive.microsoft.com/
   SPEECH_KEY=<key>                 # or leave empty and use `az login`
   SPEECH_LANGUAGES=zh-TW,en-US     # multi-language auto-detect list

   # Azure OpenAI (judge + Tuning button + gpt-audio-transcribe)
   AOAI_ENDPOINT=https://<resource>.openai.azure.com/openai/v1
   AOAI_DEPLOYMENT=gpt-4.1-mini
   AOAI_API_KEY=<key>               # or AOAI_USE_ENTRA_ID=true

   # UC1 local mode (skip Blob)
   INPUT_SOURCE=local
   LOCAL_AUDIO_DIR=data/benchmark_audio
   OUTPUT_TO_BLOB=false
   OUTPUT_DIR=reports/quality_checks
   ```

3. For **Voice Live** (UC2/UC3/Voice Live benchmarks) add:

   ```dotenv
   AZURE_VOICELIVE_ENDPOINT=https://<resource>.services.ai.azure.com/
   AZURE_VOICELIVE_API_KEY=<key>    # or `az login`
   VOICE_LIVE_TRANSCRIPTION_LANGUAGE=zh-TW,en-US
   ```

4. For **Foundry portal agents** (UC1 judge / UC2 / UC3 / LLM tuning agent) add:

   ```dotenv
   FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
   FOUNDRY_MODEL_DEPLOYMENT_NAME=gpt-4.1-mini
   # Optional dedicated tuning agent (else falls back to the model deployment / AOAI):
   # STT_TUNING_AGENT_NAME=voicecall-stt-tuning
   ```

See [../.env.example](../.env.example) for the full annotated list.

### Authentication: keys vs. `az login`

- **Keys**: set `SPEECH_KEY` / `AZURE_VOICELIVE_API_KEY` / `AOAI_API_KEY`. Simplest for a
  single host.
- **Entra ID (recommended)**: leave the keys empty, set `AOAI_USE_ENTRA_ID=true`, and run
  `az login` on the machine (or attach a Managed Identity). The code uses
  `DefaultAzureCredential`, which tries Environment → Managed Identity → Azure CLI. Grant the
  identity the relevant data-plane roles (e.g. *Cognitive Services User*, *Azure AI Developer*).

---

## 5. Run

All commands assume the repo root and an activated venv (or use the `start_*.ps1` wrappers,
which set `PYTHONPATH=src` for you).

| Target | Windows launcher | Direct command | Port |
|---|---|---|---|
| **Dashboard** (UC1/UC2/UC3 + benchmarks) | `.\start_voice_ui.ps1` | `python -m uvicorn voiceqa.web_ui:create_app --factory --host 127.0.0.1 --port 8088` | auto (8088, 8090…) |
| **UC1** batch QA | `.\start_uc1.ps1` | `python -m voiceqa.uc1_main` | — (batch) |
| **UC2** live assistant | `.\start_uc2.ps1` | `python -m voiceqa.uc2_main` | 8080 |
| **UC3** voice call | `.\start_uc3.ps1` | `python -m voiceqa.uc3_main` | 8082 |
| STT benchmark | — | `python scripts/eval_stt_quality.py --dataset data/stt_benchmark.template.jsonl --providers azure-speech-stt` | — |

The dashboard picks the first free port from a candidate list and prints the URL. To pin it,
set `PORT` before launching:

```powershell
$env:PORT = "8088"; .\start_voice_ui.ps1
```

For a non-loopback deployment (LAN/other machines), bind to all interfaces:

```powershell
$env:PYTHONPATH = "src"
python -m uvicorn voiceqa.web_ui:create_app --factory --host 0.0.0.0 --port 8088
```

> Binding to `0.0.0.0` exposes the app to the network. Put it behind a reverse proxy
> (TLS + auth) before exposing beyond localhost.

---

## 6. Docker (optional)

The included `Dockerfile` defaults to the UC2 entry point. For the dashboard, override the
command and add the Linux Speech libs.

```dockerfile
# Example override on top of the base image
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates libssl-dev libasound2 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
EXPOSE 8088
CMD ["python", "-m", "uvicorn", "voiceqa.web_ui:create_app", "--factory", "--host", "0.0.0.0", "--port", "8088"]
```

Build & run (pass secrets via env file, never bake them into the image):

```bash
docker build -t voicecall-verify .
docker run --rm -p 8088:8088 --env-file .env voicecall-verify
```

For the `az login` path in a container, prefer a **Managed Identity** (on Azure) or mount
credentials; interactive `az login` is not suitable for containers.

---

## 7. Verify the deployment

```powershell
$env:PYTHONPATH = "src"
python -m voiceqa.uc1_main --help
python -m voiceqa.uc2_main --help
python -m voiceqa.uc3_main --help
python scripts/eval_stt_quality.py --help
```

Then a real smoke test:

1. Start the dashboard (`.\start_voice_ui.ps1`) and open the printed URL.
2. Go to **STT Benchmark**, run `azure-speech-stt` against
   `data/stt_benchmark.template.jsonl` (ensure `reference_text` is filled).
3. Confirm a run folder appears under `reports/stt_benchmarks/<timestamp>/` with
   `summary.md` and `report.html`, and that **Details** / **Tuning** buttons work.

---

## 8. Files that must ship with the app

These are read at runtime (paths configurable via env):

- `assets/phrase_list.txt`, `assets/corrections.json` — STT boosting + corrections.
- `assets/*_prompt.txt`, `assets/rubric*.json` — prompts and rubric seed data.
- `assets/uc2_call_center_ui.html`, `assets/uc3_voice_call_ui.html` — browser UIs.
- `data/` — benchmark/test datasets (or point env vars at your own).

Writable at runtime: `reports/` (created automatically).

---

## 9. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `ModuleNotFoundError: voiceqa` | `PYTHONPATH` not set to `src`. Use a `start_*.ps1` script or `export PYTHONPATH=src`. |
| Speech SDK import/load error on Linux | Missing `libssl`/`libasound2` — install packages from §1.2. |
| `... requires SPEECH_KEY or Azure AD token via az login` | No key set and not logged in. Set the key or run `az login`. |
| `AZURE_VOICELIVE_ENDPOINT is not set` | Voice Live features need the endpoint (UC2/UC3/Voice Live benchmarks). |
| Tuning button returns an error | LLM tuning needs `FOUNDRY_PROJECT_ENDPOINT` (+ agent/model) **or** `AOAI_ENDPOINT`. |
| `Enhanced mode is currently not supported yet` (MAI) | Region doesn't support MAI enhanced transcribe; it auto-falls back to standard fast transcription. |
| Dashboard "Unable to find a free local port" | All candidate ports busy — set `$env:PORT` explicitly. |
| Simplified vs Traditional inflating WER | Handled by OpenCC s2t normalization; disable via `STT_BENCHMARK_ZH_TO_TRADITIONAL=0`. |

---

## 10. Security notes

- Keep secrets in `.env` (git-ignored) or a secret store — never commit keys.
- Prefer Entra ID / Managed Identity over keys where possible.
- Do not expose the dashboard directly to the internet without TLS + authentication in front.
