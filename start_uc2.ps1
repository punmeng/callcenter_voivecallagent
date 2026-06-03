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
    $env:PORT = '8080'
}
# AgentServerHost reads FOUNDRY_AGENT_NAME / FOUNDRY_AGENT_VERSION to register
# this process in the Foundry control plane. Override them to the UC2 identity
# so UC2 appears as a separate agent entry in the portal, not as UC1.
$env:FOUNDRY_AGENT_NAME    = 'voicecall-uc2-assistant'
$env:FOUNDRY_AGENT_VERSION = '1'
& $python -m voiceqa.uc2_main
