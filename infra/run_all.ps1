# Start the whole LMS backend on this laptop, each part as a hidden background process.
#   .\infra\run_all.ps1                 services + ingest + processor + notifier + API
#   .\infra\run_all.ps1 -Simulator      ...plus the 50-cow simulator (48 h backfill + demo events)
#   .\infra\run_all.ps1 -MockRover      ...plus a laptop rover (mock motors, synthetic camera)
#   .\infra\run_all.ps1 -Tunnel         ...plus a public https link via Cloudflare quick tunnel
# Stop everything with .\infra\stop_all.ps1. Logs go to logs\*.log.
param([switch]$Simulator, [switch]$MockRover, [switch]$Tunnel)

$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force $Logs | Out-Null

& (Join-Path $PSScriptRoot "start_services.ps1")

# Each part runs under backend.supervise, which restarts it whenever it exits (crash, lost
# connection) and appends its output to logs\<name>.log.
function Start-Part($name, [string[]]$arguments) {
    $running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match "backend\.supervise $name " }
    if ($running) { Write-Host "$name already running"; return }
    $all = @("-m", "backend.supervise", $name, "--") + $arguments
    Start-Process -WindowStyle Hidden -WorkingDirectory $Root -FilePath $Py -ArgumentList $all
    Write-Host "$name started (auto-restart on)"
}

Start-Part "ingest" @("-m", "backend.workers.ingest")
Start-Part "processor" @("-m", "backend.workers.processor")
Start-Part "notifier" @("-m", "backend.workers.notifier")
Start-Part "api" @("-m", "uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000")
if ($Simulator) {
    Start-Part "simulator" @("-m", "simulator.run", "live", "--backfill-hours", "48", "--backfill-interval", "120",
        "--backfill-pause", "0", "--demo", "--interval", "15")
}
if ($MockRover) {
    Start-Part "rover" @("-m", "rover.server", "--mock", "--camera", "synthetic", "--port", "8080", "--mqtt", "127.0.0.1")
}
if ($Tunnel) {
    & (Join-Path $PSScriptRoot "tunnel.ps1")
}
Write-Host "Dashboard: http://localhost:8000   (API docs: http://localhost:8000/docs)"
