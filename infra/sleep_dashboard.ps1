# Stop the dashboard side on this laptop (API + workers + anything run_all started) but keep the
# Pi watcher running, so switching the rover on again brings everything back (infra/pi_watch.py).
# Run by the dashboard's "Stop rover & dashboard" button; the WSL services (DB, MQTT) stay up.
#   .\infra\sleep_dashboard.ps1 [-DelaySeconds 3]
param([int]$DelaySeconds = 0)
Start-Sleep -Seconds $DelaySeconds
$patterns = "backend\.supervise|backend\.workers\.|backend\.api\.main|simulator\.run|rover\.server|barn\.serial_bridge"
$keep = "piwatch|pi_watch"
# supervisors first (so they do not restart the children), then the children
foreach ($pass in 1, 2) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match $patterns -and $_.CommandLine -notmatch $keep -and
            ($pass -eq 2 -or $_.CommandLine -match "backend\.supervise") } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
