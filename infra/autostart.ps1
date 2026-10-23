# Switch LMS between "autostart" and "normal" mode, laptop and Pi together.
#   .\infra\autostart.ps1          toggle (on -> off, off -> on)
#   .\infra\autostart.ps1 on       autostart: at Windows login the backend + dashboard start hidden
#                                  (http://localhost:8000, ~30 s after login) and the Pi starts its
#                                  rover server at boot
#   .\infra\autostart.ps1 off      normal: nothing starts by itself (use run_all.ps1 / lms-pi.sh)
#   .\infra\autostart.ps1 status
# Only changes what happens at the NEXT login/boot; whatever runs now keeps running
# (stop it with infra\stop_all.ps1 and `lms-pi.sh stop rover`).
param([ValidateSet("toggle", "on", "off", "status")][string]$Mode = "toggle")

$Root = Split-Path -Parent $PSScriptRoot
$Link = Join-Path ([Environment]::GetFolderPath("Startup")) "LMS backend.lnk"

# Pi address = host part of ROVER_URL in .env
$RoverUrl = (Select-String -Path (Join-Path $Root ".env") -Pattern '^ROVER_URL=(.*)$').Matches.Groups[1].Value.Trim()
$PiHost = ([Uri]$RoverUrl).Host
$PiCtl = "~/lms-rover/infra/pi/lms-pi.sh"

function Invoke-Pi([string]$cmd) {
    $out = ssh -o BatchMode=yes -o ConnectTimeout=6 "pi@$PiHost" $cmd 2>$null
    if ($LASTEXITCODE -ne 0 -and -not $out) { return $null }
    return ($out -join " ").Trim()
}

function Show-Status {
    $laptop = if (Test-Path $Link) { "ON" } else { "off" }
    $pi = Invoke-Pi "systemctl is-enabled lms-rover"
    if ($null -eq $pi) { $pi = "unreachable ($PiHost)" } elseif ($pi -eq "enabled") { $pi = "ON" } else { $pi = "off" }
    Write-Host "laptop autostart: $laptop"
    Write-Host "pi rover at boot: $pi"
}

if ($Mode -eq "status") { Show-Status; return }
if ($Mode -eq "toggle") { $Mode = if (Test-Path $Link) { "off" } else { "on" } }

if ($Mode -eq "on") {
    $Shell = New-Object -ComObject WScript.Shell
    $Sc = $Shell.CreateShortcut($Link)
    $Sc.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $Sc.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'run_all.ps1')`""
    $Sc.WorkingDirectory = $Root
    $Sc.WindowStyle = 7  # minimized
    $Sc.Description = "LMS: WSL services, workers and dashboard on http://localhost:8000"
    $Sc.Save()
    if ($null -eq (Invoke-Pi "$PiCtl enable rover")) {
        Write-Host "WARNING: Pi not reachable at $PiHost - its autostart is unchanged. Run again when it is on."
    }
} else {
    Remove-Item $Link -ErrorAction SilentlyContinue
    if ($null -eq (Invoke-Pi "$PiCtl disable rover")) {
        Write-Host "WARNING: Pi not reachable at $PiHost - its autostart is unchanged. Run again when it is on."
    }
}
Write-Host "mode: $Mode"
Show-Status
