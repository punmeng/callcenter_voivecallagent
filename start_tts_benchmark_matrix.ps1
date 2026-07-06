param(
    [string]$Dataset = 'data/tts_benchmark.template.jsonl',
    [string]$OutputDir = 'reports/tts_benchmarks',
    [switch]$IncludeAzureSpeech,
    [switch]$IncludeGptRealtime,
    [switch]$IncludeMaiVoice,
    [switch]$VoiceLiveOnly,
    [switch]$Parallel,
    [string]$VoiceLiveVoice = '',
    [string]$GptRealtimeVoice = '',
    [string]$MaiVoiceName = '',
    [string]$AzureSpeechVoice = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = 'python'
}

$env:PYTHONPATH = 'src'

# Use defaults only when the caller did not set them in the current shell.
if (-not $env:AZURE_VOICELIVE_ENDPOINT) {
    $env:AZURE_VOICELIVE_ENDPOINT = 'https://ai-speech-alexpun-resource.services.ai.azure.com/'
}
if (-not $env:AZURE_VOICELIVE_MODEL) {
    $env:AZURE_VOICELIVE_MODEL = 'gpt-realtime'
}
if (-not $env:AZURE_VOICELIVE_API_VERSION) {
    $env:AZURE_VOICELIVE_API_VERSION = '2026-06-01-preview'
}
if (-not $env:VOICE_LIVE_TTS_CALL_TIMEOUT_SECONDS) {
    $env:VOICE_LIVE_TTS_CALL_TIMEOUT_SECONDS = '60'
}
# Default Voice Live TTS voice. Azure neural voices (e.g. zh-TW-HsiaoChenNeural)
# synthesize the exact input text verbatim; OpenAI voices (e.g. alloy) fall back
# to an instructions-driven read that is not guaranteed verbatim.
if (-not $env:AZURE_VOICELIVE_TTS_VOICE) {
    $env:AZURE_VOICELIVE_TTS_VOICE = 'zh-TW-HsiaoChenNeural'
}
if (-not $env:AZURE_SPEECH_ENDPOINT) {
    $env:AZURE_SPEECH_ENDPOINT = 'https://ai-speech-alexpun-resource.cognitiveservices.azure.com/'
}

if ($VoiceLiveVoice) {
    $env:AZURE_VOICELIVE_TTS_VOICE = $VoiceLiveVoice
}
if ($GptRealtimeVoice) {
    $env:GPT_REALTIME_TTS_VOICE = $GptRealtimeVoice
}
if ($MaiVoiceName) {
    $env:MAI_VOICE_NAME = $MaiVoiceName
}
if ($AzureSpeechVoice) {
    $env:AZURE_SPEECH_TTS_VOICE = $AzureSpeechVoice
}

# Voice Live is always benchmarked (primary). gpt-realtime (OpenAI voice, model-
# driven), MAI-Voice-2 (multilingual neural TTS), and Azure Speech TTS (SDK
# baseline) are optional comparison scenarios.
$providers = @('voice-live-api')

if ($IncludeGptRealtime) {
    $providers += 'gpt-realtime'
}

if ($IncludeMaiVoice) {
    $providers += 'mai-voice'
}

if (-not $VoiceLiveOnly) {
    $providers += 'azure-speech-tts'
}
elseif ($IncludeAzureSpeech) {
    $providers += 'azure-speech-tts'
}

$benchmarkArgs = @(
    'scripts/eval_tts_quality.py',
    '--dataset', $Dataset,
    '--output-dir', $OutputDir,
    '--providers'
)
$benchmarkArgs += $providers

if ($Parallel) {
    $benchmarkArgs += '--parallel'
}

& $python @benchmarkArgs

$latest = Get-ChildItem $OutputDir -Directory | Sort-Object Name -Descending | Select-Object -First 1
if (-not $latest) {
    throw "No benchmark run folder found under $OutputDir"
}

$summaryPath = Join-Path $latest.FullName 'summary.md'
Write-Output "RUN=$($latest.Name)"
Get-Content $summaryPath
