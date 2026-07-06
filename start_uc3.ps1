Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = 'python'
}

$env:PYTHONPATH = 'src'
# AgentServerHost uses PORT env var when no explicit port is provided.
if (-not $env:PORT) {
    $env:PORT = '8082'
}
# UC3 registers as its own agent identity in the Foundry control plane so it
# appears separately from UC1 (judge) and UC2 (assistant) in the portal.
$env:FOUNDRY_AGENT_NAME    = 'voicecall-uc3-voice-agent'
$env:FOUNDRY_AGENT_VERSION = '1'
& $python -m voiceqa.uc3_main
