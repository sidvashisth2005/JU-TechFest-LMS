# Stop LMS backend services and release WSL.  Usage:  .\infra\stop_services.ps1
$Distro = "Ubuntu-24.04"
wsl -d $Distro -u root -e bash /mnt/d/Project/LMS/infra/stop.sh
Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" |
    Where-Object { $_.CommandLine -like "*--exec sleep infinity*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "WSL keepalive stopped" }
