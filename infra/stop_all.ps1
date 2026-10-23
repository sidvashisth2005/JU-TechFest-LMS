# Stop everything started by run_all.ps1, then the WSL services.
$patterns = "backend\.workers\.|backend\.api\.main|simulator\.run|rover\.server"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match $patterns } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host "stopped $($_.ProcessId)" }
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
& (Join-Path $PSScriptRoot "stop_services.ps1")
