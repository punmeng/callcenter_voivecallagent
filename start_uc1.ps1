Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = 'python'
}

$env:PYTHONPATH = 'src'
& $python -m voiceqa.uc1_main
