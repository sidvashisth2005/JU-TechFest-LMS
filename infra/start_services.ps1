# Start LMS backend services (WSL Ubuntu) and keep WSL alive in the background.
# WSL stops an idle distro after a few seconds, which would take the services down with it,
# so a hidden `sleep infinity` process holds it open.
# Usage (PowerShell, repo root):  .\infra\start_services.ps1
$Distro = "Ubuntu-24.04"

$keepalive = Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" |
    Where-Object { $_.CommandLine -like "*--exec sleep infinity*" }
if (-not $keepalive) {
    # one pre-quoted argument string: Start-Process joins array arguments without quoting
    Start-Process -WindowStyle Hidden -FilePath "wsl.exe" `
        -ArgumentList "-d $Distro -u root --exec sleep infinity"
    Start-Sleep -Seconds 2
    Write-Host "WSL keepalive started"
} else {
    Write-Host "WSL keepalive already running"
}

wsl -d $Distro -u root -e bash /mnt/d/Project/LMS/infra/start.sh
