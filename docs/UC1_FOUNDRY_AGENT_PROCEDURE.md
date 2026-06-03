# UC1 Foundry Agent Build Procedure

Use this runbook to create or refresh the UC1 Foundry portal agent and wire UC1 runtime to it.

## 1. Prerequisites

- Azure login is ready:

```powershell
az login
```

- Python venv is activated:

```powershell
.\.venv\Scripts\Activate.ps1
```

- Required settings exist in `.env` (or process env):
  - `FOUNDRY_PROJECT_ENDPOINT`
  - `FOUNDRY_MODEL_DEPLOYMENT_NAME` (or `AOAI_DEPLOYMENT` fallback)
  - `UC1_PROMPT_PATH` (optional, defaults to `assets/uc1_prompt.txt`)

## 2. Create/Update Foundry UC1 Agent Version

Run the reusable script:

```powershell
$env:PYTHONPATH = "src"
python scripts/build_uc1_foundry_agent.py
```

What it does:
- Reads the UC1 prompt file (`assets/uc1_prompt.txt` by default)
- Calls Foundry `agents.create_version(...)`
- Prints `agent_name`, `agent_version`, and status

Every run creates a new immutable agent version for the same agent name.

## 3. Pin Runtime to the New Portal Agent Version

Update `.env` with the output values:

```env
FOUNDRY_PROJECT_ENDPOINT=https://<your-resource>.services.ai.azure.com/api/projects/<project-name>
FOUNDRY_AGENT_NAME=voicecall-uc1-judge
FOUNDRY_AGENT_VERSION=<new-version>
```

UC1 runtime now prefers this portal-agent path.

## 4. Verify End-to-End

```powershell
.\start_uc1.ps1
```

Expected:
- UC1 completes successfully
- `reports/001.metrics.json` has non-zero `token_usage`
- Foundry portal shows activity for the configured agent/version

## 5. Optional: Override Defaults

```powershell
python scripts/build_uc1_foundry_agent.py `
  --project-endpoint "https://<resource>.services.ai.azure.com/api/projects/<project>" `
  --agent-name "voicecall-uc1-judge" `
  --model "gpt-5.4" `
  --prompt-file "assets/uc1_prompt.txt" `
  --description "VoiceCall Verify UC1 rubric judge" `
  --temperature 0
```
