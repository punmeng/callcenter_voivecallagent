# UC2 Foundry Agent Build Procedure

Use this runbook to create or refresh the UC2 Foundry portal agent and pin UC2 runtime to a specific version.

## 1. Prerequisites

- Azure login:

```powershell
az login
```

- Python venv activated:

```powershell
.\.venv\Scripts\Activate.ps1
```

- Required settings in .env or process env:
  - FOUNDRY_PROJECT_ENDPOINT (or VOICE_ASSIST_PROJECT_ENDPOINT)
  - VOICE_ASSIST_MODEL_DEPLOYMENT_NAME (or FOUNDRY_MODEL_DEPLOYMENT_NAME)
  - VOICE_ASSIST_PROMPT_PATH (optional, defaults to assets/uc2_agent_prompt.txt)

## 2. Create/Update UC2 Prompt Agent Version

```powershell
$env:PYTHONPATH = "src"
python scripts/build_uc2_foundry_agent.py
```

This creates a new immutable version under the same UC2 agent name.

## 3. Pin UC2 Runtime to Portal Agent

Update .env with script output:

```env
FOUNDRY_PROJECT_ENDPOINT=https://<your-resource>.services.ai.azure.com/api/projects/<project-name>
VOICE_ASSIST_AGENT_NAME=voicecall-uc2-assistant
VOICE_ASSIST_AGENT_VERSION=<new-version>
```

If VOICE_ASSIST_AGENT_NAME is set, UC2 runtime uses Foundry portal-agent mode.

## 4. Run UC2

```powershell
.\start_uc2.ps1
```

Expected:
- UC2 server starts on 127.0.0.1:8080
- Portal agent activity is visible in Foundry for the configured agent/version

## 5. Optional Overrides

```powershell
python scripts/build_uc2_foundry_agent.py `
  --project-endpoint "https://<resource>.services.ai.azure.com/api/projects/<project>" `
  --agent-name "voicecall-uc2-assistant" `
  --model "gpt-5.4" `
  --prompt-file "assets/uc2_agent_prompt.txt" `
  --description "VoiceCall Verify UC2 real-time assistant" `
  --temperature 0
```
