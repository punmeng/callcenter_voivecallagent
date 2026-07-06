# VoiceCall Verify: Voice Method Selection and Best Practices

A practical playbook for **mixed Traditional Chinese (zh-TW) + English** call-center voice AI: choose the right STT/LLM/TTS method per scenario, benchmark tradeoffs, and run production-style UC pipelines. Build version: see [../VERSION](../VERSION).

> UC1 = offline QA scoring · UC2 = live coaching for a human agent · **UC3 = the AI *is* the agent**.

Method-first focus:
- Select voice methods by scenario (batch QA, live assist, automated voice agent).
- Optimize quality/latency/cost with STT + TTS benchmark evidence.
- Apply pipeline-level controls (Voice Live all-in-one, Voice Live + controlled TTS, classic STT->LLM->TTS).

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
az login
```

Copy [../.env.example](../.env.example) to `.env` and fill in values. Launch the consolidated dashboard:

```powershell
.\start_voice_ui.ps1   # auto-selects a local port if PORT is unset
```

![Consolidated dashboard home page](images/01_indexpage.png)

## Visual diagrams

- Voice method selection: [../spec/Voice_Method_Selection.png](../spec/Voice_Method_Selection.png)
- End-to-end architecture: [../spec/VoiceQA_Architecture.png](../spec/VoiceQA_Architecture.png)

## The three use cases

| | UC1 — Quality Check | UC2 — Call Assistant | UC3 — Voice Agent |
|---|---|---|---|
| **When** | After the call (batch) | During the call (real-time) | During the call (real-time) |
| **Role** | Scores the agent | Assists a human agent | **Is** the agent |
| **Input** | Audio blob / local file | Live transcript / mic | Live caller mic |
| **Output** | Markdown QA report | On-screen assist cards | Synthesized voice reply |
| **Entrypoint** | `python -m voiceqa.uc1_main` / `start_uc1.ps1` | `python -m voiceqa.uc2_main` / `start_uc2.ps1` | `start_uc3.ps1` (or `/uc3/live`) |
| **Guide** | [UC1.md](UC1.md) | [UC2.md](UC2.md) | [UC3.md](UC3.md) |

All three share a common **Azure speech stack + Agent Framework runtime** foundation. The exact STT/TTS path differs by pipeline (for example, UC3 can run Voice Live STT or Azure Speech STT depending on selection).

## Scope

**In scope**
- STT of zh-TW + en-US code-switched audio via Azure AI Speech (LID, phrase-list, corrections, N-best).
- Behavioral QA judging (UC1) — one LLM verdict per rubric item, driven by the customer's rubric.
- Markdown QA reports (one per call, pass/fail tally, ❌-flagged `不符合` rows).
- Real-time assist (UC2) and a fully automated voice agent (UC3) with billing/IT/expert handoffs.
- STT + TTS benchmarks and a cost model for all cases.

**Out of scope (for now)**
- WER/CER accuracy benchmarking against gold transcripts (UC1 QA is *behavioral*, not transcription-accuracy scoring).
- Sentiment/emotion analytics, supervisor dashboards, BI reporting.
- Telephony/SIP/ACS integration and call-recording infrastructure (the browser mic is the call source in this build).

## Documentation index

| Doc | Purpose |
|---|---|
| [README.md](README.md) · [README.zh-TW.md](README.zh-TW.md) | This overview (English / 繁體中文). |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Design concept (voice-tech 3 layers), per-case architecture, working process. |
| [UC1.md](UC1.md) | UC1 — batch QA: design, run, Foundry agent procedure. |
| [UC2.md](UC2.md) | UC2 — live assistant: design, run, Foundry agent procedure. |
| [UC3.md](UC3.md) | UC3 — voice agent: three pipelines, handoffs, run. |
| [BENCHMARKS.md](BENCHMARKS.md) | STT + TTS benchmark guides. |
| [COST.md](COST.md) | Monthly cost estimate + optimization for all cases. |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Repo/catalog organization + module map. |
| [CHANGELOG.md](CHANGELOG.md) | Version history. |

## Key files

- [../src/voiceqa/uc1_main.py](../src/voiceqa/uc1_main.py) — UC1 orchestration
- [../src/voiceqa/uc1_stt_agent.py](../src/voiceqa/uc1_stt_agent.py) — Azure Speech transcription
- [../src/voiceqa/uc1_qa_judge.py](../src/voiceqa/uc1_qa_judge.py) — Agent Framework rubric judge
- [../src/voiceqa/uc2_live_assistant.py](../src/voiceqa/uc2_live_assistant.py) — UC2 live assistant
- [../src/voiceqa/uc3_voice_agent.py](../src/voiceqa/uc3_voice_agent.py) — UC3 voice agent (3 pipelines + handoffs)
- [../src/voiceqa/web_ui.py](../src/voiceqa/web_ui.py) — consolidated dashboard
- [../src/voiceqa/agent_runtime.py](../src/voiceqa/agent_runtime.py) — shared Agent Framework client setup
- [../catalog/voice_catalogs.yaml](../catalog/voice_catalogs.yaml) — capability matrix / expansion control plane
</content>
</invoke>
