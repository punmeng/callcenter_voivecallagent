# Test Cases

This file provides a practical, execution-ready test suite for validating the repository end to end.

## 1. Test Scope

- UC1 batch QA pipeline
- UC2 real-time assistant
- UC3 voice agent (all pipelines)
- STT benchmark flow
- TTS benchmark flow
- Dashboard routing and integration
- Basic failure handling and regression checks

## 2. Test Environment

Prerequisites:
- Windows PowerShell
- Python virtual environment created and dependencies installed
- Valid .env configured for your target path(s)
- Azure login available when using keyless auth

Recommended startup:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
az login
```

## 3. Smoke Tests

### TC-SMOKE-001 Dashboard starts

Purpose:
- Verify the consolidated web UI boots.

Steps:
1. Run:

```powershell
.\start_voice_ui.ps1
```

2. Open the shown local URL.

Expected:
- Home page loads.
- UC1, UC2, UC3, STT Benchmark, and TTS Benchmark entries are visible.

### TC-SMOKE-002 Entrypoints import successfully

Purpose:
- Confirm entry modules are runnable.

Steps:
1. Run:

```powershell
$env:PYTHONPATH = "src"
python -m voiceqa.uc1_main --help
python -m voiceqa.uc2_main --help
python -m voiceqa.uc3_main --help
python scripts/eval_stt_quality.py --help
python scripts/eval_tts_quality.py --help
```

Expected:
- Commands return usage/help without import errors.

## 4. UC1 Test Cases

### TC-UC1-001 Local single-file run

Purpose:
- Validate UC1 with local audio input.

Steps:
1. Set env and run:

```powershell
$env:INPUT_SOURCE = "local"
$env:LOCAL_AUDIO_PATH = "data/benchmark_audio/001.wav"
$env:RUBRIC_LOCAL_PATH = "assets/rubric.json"
$env:OUTPUT_TO_BLOB = "false"
$env:PYTHONPATH = "src"
python -m voiceqa.uc1_main
```

Expected:
- UC1 exits successfully.
- Report files appear in reports.
- Generated markdown contains summary + verdict sections.

### TC-UC1-002 Local folder batch

Purpose:
- Validate batch iteration and index generation.

Steps:
1. Run:

```powershell
$env:INPUT_SOURCE = "local"
$env:LOCAL_AUDIO_DIR = "data/benchmark_audio"
$env:RUBRIC_LOCAL_PATH = "assets/rubric.json"
$env:OUTPUT_TO_BLOB = "false"
$env:PYTHONPATH = "src"
python -m voiceqa.uc1_main
```

Expected:
- Multiple per-call markdown files created.
- Index file created when multiple calls are processed.

### TC-UC1-003 Missing local input failure

Purpose:
- Verify clear error path for missing local files.

Steps:
1. Run with a nonexistent file:

```powershell
$env:INPUT_SOURCE = "local"
$env:LOCAL_AUDIO_PATH = "data/benchmark_audio/not_found.wav"
$env:RUBRIC_LOCAL_PATH = "assets/rubric.json"
$env:OUTPUT_TO_BLOB = "false"
$env:PYTHONPATH = "src"
python -m voiceqa.uc1_main
```

Expected:
- Process returns non-zero or clear failure message.
- Error indicates input file not found / no local audio.

### TC-UC1-004 Provider override via config

Purpose:
- Ensure UC1 provider selection from config works.

Steps:
1. In config/stt_config.toml, set [uc1].provider to azure-speech-stt-fast.
2. Re-run TC-UC1-001.

Expected:
- Console logs show selected provider.
- Run completes with expected output artifacts.

## 5. UC2 Test Cases

### TC-UC2-001 Server and UI startup

Purpose:
- Verify UC2 service and UI are reachable.

Steps:
1. Run:

```powershell
.\start_uc2.ps1
```

2. Open UC2 UI page.

Expected:
- UI loads with transcript area and controls.
- Connection can be established.

### TC-UC2-002 Audio websocket path

Purpose:
- Validate audio diarization path.

Steps:
1. Start UC2 UI.
2. Start microphone capture.
3. Speak at least 2 turns.

Expected:
- Transcript events appear.
- Speaker roles are assigned.
- Assist cards are produced.

### TC-UC2-003 Swap speakers action

Purpose:
- Verify speaker role swap control works.

Steps:
1. During an active UC2 session, trigger swap speakers from UI.
2. Speak again.

Expected:
- Subsequent labels reflect swapped agent/customer mapping.

### TC-UC2-004 End call summary

Purpose:
- Validate post-call summary path.

Steps:
1. Run a short call.
2. Trigger end/summary action.

Expected:
- Response contains summary markdown field when summary mode is requested.

### TC-UC2-005 Missing model/agent config

Purpose:
- Ensure startup fails clearly when Foundry config is missing.

Steps:
1. Temporarily unset Foundry project/model or agent env vars used by UC2.
2. Start UC2.

Expected:
- Clear configuration error referencing required endpoint/model/agent settings.

## 6. UC3 Test Cases

### TC-UC3-001 UI and health sync

Purpose:
- Verify method selectors sync from server defaults.

Steps:
1. Run:

```powershell
.\start_uc3.ps1
```

2. Open UC3 page.
3. Observe selector values after load.

Expected:
- Listen/Think/Speak selectors reflect server health defaults.

### TC-UC3-002 Pipeline: voicelive

Purpose:
- Validate all-in-one Voice Live path.

Steps:
1. Set Pipeline to voicelive.
2. Start call and speak.

Expected:
- Audio response returns.
- Transcript messages for user and assistant appear.

### TC-UC3-003 Pipeline: voicelive-tts

Purpose:
- Validate Voice Live listen+think with external Azure TTS.

Steps:
1. Set Pipeline to voicelive-tts.
2. Ask the agent to read a numeric token like 101.

Expected:
- Assistant response is synthesized via controlled Azure TTS.
- Digit pronunciation rule is applied (digit-by-digit default behavior).

### TC-UC3-004 Pipeline: classic

Purpose:
- Validate Azure STT -> Foundry LLM -> Azure TTS path.

Steps:
1. Set Pipeline to classic.
2. Start call and speak.

Expected:
- Conversation works without Voice Live session dependency.
- Listen/Think selectors are disabled in UI for classic.

### TC-UC3-005 Recording controls

Purpose:
- Verify recording lifecycle and output file creation.

Steps:
1. Start a UC3 call.
2. Click Record, speak for 10-20 seconds, click Stop recording.

Expected:
- UI reports recording saved.
- WAV file named uc3_call_<timestamp>.wav appears in configured recording directory.

### TC-UC3-006 Tool handoff events

Purpose:
- Validate billing/IT/expert handoff event flow.

Steps:
1. In voicelive or voicelive-tts, ask:
   - billing amount question
   - IT support question
   - expert escalation style question
2. Observe UI event stream.

Expected:
- Handoff events shown with agent label.
- Assistant returns follow-up spoken answer.

## 7. STT Benchmark Test Cases

### TC-STT-001 Default matrix run

Purpose:
- Verify matrix script runs with default dataset path.

Steps:
1. Run:

```powershell
.\start_stt_benchmark_matrix.ps1
```

Expected:
- Run folder created under reports/stt_benchmarks.
- summary.md generated.
- No dataset not found error.

### TC-STT-002 Include Voice Live

Purpose:
- Validate optional provider inclusion.

Steps:
1. Run:

```powershell
.\start_stt_benchmark_matrix.ps1 -IncludeVoiceLive
```

Expected:
- Summary includes voice-live-realtime-* rows.

### TC-STT-003 Direct CLI variants

Purpose:
- Validate provider choices include Voice Live variants.

Steps:
1. Run:

```powershell
python scripts/eval_stt_quality.py --dataset data/stt_benchmark.template.jsonl --providers voice-live-api-gpt-4o-transcribe
python scripts/eval_stt_quality.py --dataset data/stt_benchmark.template.jsonl --providers voice-live-api-mai-transcribe-1
```

Expected:
- CLI accepts providers.
- Benchmark output files generated.

## 8. TTS Benchmark Test Cases

### TC-TTS-001 Default matrix run

Purpose:
- Verify matrix script runs with default dataset path.

Steps:
1. Run:

```powershell
.\start_tts_benchmark_matrix.ps1
```

Expected:
- Run folder created under reports/tts_benchmarks.
- summary.md generated.
- WAV artifacts saved per provider/sample.

### TC-TTS-002 Include optional providers

Purpose:
- Validate gpt-realtime and mai-voice provider paths.

Steps:
1. Run:

```powershell
.\start_tts_benchmark_matrix.ps1 -IncludeGptRealtime -IncludeMaiVoice
```

Expected:
- Summary includes gpt-realtime and mai-voice entries.

### TC-TTS-003 Voice override behavior

Purpose:
- Verify voice override env plumbing.

Steps:
1. Run:

```powershell
.\start_tts_benchmark_matrix.ps1 -VoiceLiveVoice zh-TW-HsiaoChenNeural -AzureSpeechVoice zh-TW-HsiaoChenNeural
```

Expected:
- Output metadata/behavior reflects requested voices.

## 9. Dashboard Integration Cases

### TC-UI-001 UC routes

Purpose:
- Confirm dashboard routes map correctly.

Steps:
1. Start dashboard.
2. Open UC1, UC2, UC3 pages from nav.

Expected:
- Each page opens correctly.
- No dead links or 404 on UC tabs.

### TC-UI-002 Benchmark pages

Purpose:
- Verify STT and TTS benchmark pages both render and trigger runs.

Steps:
1. Open STT Benchmark page and launch one run.
2. Open TTS Benchmark page and launch one run.

Expected:
- Both pages execute and render run history.

## 10. Regression Checklist

Run after any core changes:

1. TC-SMOKE-001
2. TC-SMOKE-002
3. TC-UC1-001
4. TC-UC2-002
5. TC-UC3-002
6. TC-STT-001
7. TC-TTS-001
8. TC-UI-001

If all 8 pass, core flows are healthy.

## 11. Test Log Template

Use this format while testing one-by-one:

| Case ID | Result (Pass/Fail) | Notes | Evidence (file/run id) |
|---|---|---|---|
| TC-UC1-001 |  |  |  |
| TC-UC2-002 |  |  |  |
| TC-UC3-003 |  |  |  |
| TC-STT-001 |  |  |  |
| TC-TTS-001 |  |  |  |
