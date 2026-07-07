param(
    [string]$Dataset = 'data/stt_benchmark.template.jsonl',
    [string]$OutputDir = 'reports/stt_benchmarks',
    [switch]$IncludeCustomSpeech,
    [switch]$IncludeVoiceLive,
    [switch]$IncludeGptTranscribe,
    [switch]$IncludeRestTranscribe,
    [switch]$Parallel,
    [switch]$UseConfigDefaults,
    [string]$CustomEndpointId = ''
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
    $env:AZURE_VOICELIVE_MODEL = 'gpt-5.4'
}
if (-not $env:AZURE_VOICELIVE_API_VERSION) {
    $env:AZURE_VOICELIVE_API_VERSION = '2026-06-01-preview'
}
if (-not $env:VOICE_LIVE_CALL_TIMEOUT_SECONDS) {
    $env:VOICE_LIVE_CALL_TIMEOUT_SECONDS = '60'
}
if (-not $env:VOICE_LIVE_MAI_TIMEOUT_SECONDS) {
    $env:VOICE_LIVE_MAI_TIMEOUT_SECONDS = '90'
}
if (-not $env:VOICE_LIVE_MAI_TRANSCRIBE_MODEL) {
    $env:VOICE_LIVE_MAI_TRANSCRIBE_MODEL = 'gpt-realtime'
}
if (-not $env:VOICE_LIVE_AZ_CLI_TIMEOUT_SECONDS) {
    $env:VOICE_LIVE_AZ_CLI_TIMEOUT_SECONDS = '60'
}
if (-not $env:VOICE_LIVE_TRANSCRIPTION_LANGUAGE) {
    $env:VOICE_LIVE_TRANSCRIPTION_LANGUAGE = 'zh-TW'
}
if (-not $env:AZURE_SPEECH_ENDPOINT) {
    $env:AZURE_SPEECH_ENDPOINT = 'https://ai-speech-alexpun-resource.cognitiveservices.azure.com/'
}

$providers = @(
    'azure-speech-stt',
    'azure-speech-stt-fast',
    'azure-speech-stt-fast-phrase-list',
    'mai-transcribe-1.5'
)

if ($IncludeRestTranscribe) {
    $providers += 'azure-speech-stt-rest'
}

if ($IncludeVoiceLive) {
    $providers += 'voice-live-realtime-azure-speech'
    $providers += 'voice-live-realtime-azure-speech-phrase-list'
    $providers += 'voice-live-realtime-gpt4o-transcribe'
    $providers += 'voice-live-realtime-gpt4o-transcribe-phrase-list'
}

if ($IncludeGptTranscribe) {
    if (-not $env:AOAI_ENDPOINT) {
        throw 'IncludeGptTranscribe is set, but AOAI_ENDPOINT is empty. Set the env var or add it to .env.'
    }
    $providers += 'gpt-audio-transcribe'
}

if ($IncludeCustomSpeech) {
    if ($CustomEndpointId) {
        $env:AZURE_SPEECH_CUSTOM_ENDPOINT_ID = $CustomEndpointId
    }

    if (-not $env:AZURE_SPEECH_CUSTOM_ENDPOINT_ID) {
        throw 'IncludeCustomSpeech is set, but AZURE_SPEECH_CUSTOM_ENDPOINT_ID is empty. Provide -CustomEndpointId or set env var.'
    }

    $providers += 'azure-speech-stt-custom'
}

$benchmarkArgs = @(
    'scripts/eval_stt_quality.py',
    '--dataset', $Dataset,
    '--output-dir', $OutputDir
)

# When -UseConfigDefaults is set, omit --providers so Python reads benchmark.default_providers
# from config/stt_config.toml.  Otherwise build the provider list from switches.
if (-not $UseConfigDefaults) {
    $benchmarkArgs += '--providers'
    $benchmarkArgs += $providers
}

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
