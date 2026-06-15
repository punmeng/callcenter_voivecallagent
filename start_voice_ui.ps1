Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = 'python'
}

$env:PYTHONPATH = 'src'
if (-not $env:PORT) {
    $candidatePorts = @(8088, 8090, 8091, 8092, 8100, 8181, 8501)
    foreach ($candidatePort in $candidatePorts) {
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidatePort)
            $listener.Start()
            $listener.Stop()
            $env:PORT = [string]$candidatePort
            break
        } catch {
            continue
        }
    }
    if (-not $env:PORT) {
        throw 'Unable to find a free local port for the dashboard.'
    }
}

& $python -m uvicorn voiceqa.web_ui:create_app --factory --host 127.0.0.1 --port $env:PORT
