# Switch LMS between "autostart" and "normal" mode, laptop and both Pis together.
#   .\infra\autostart.ps1          toggle (on -> off, off -> on)
#   .\infra\autostart.ps1 on       autostart: at Windows login the backend + dashboard start hidden
#                                  (http://localhost:8000, ~30 s after login), the rover Pi starts its
#                                  rover server at boot and the barn Pi its Sense HAT publisher
#   .\infra\autostart.ps1 off      normal: nothing starts by itself (use run_all.ps1 / lms-pi.sh / lms-barn.sh)
#   .\infra\autostart.ps1 status
# Only changes what happens at the NEXT login/boot for the laptop and rover Pi; whatever runs now keeps
# running (stop it with infra\stop_all.ps1 and `lms-pi.sh stop rover`). The barn Pi switches right away.
# Rover Pi = host of ROVER_URL in .env; barn Pi = BARN_PI in .env (user@ip), skipped when empty.
param([ValidateSet("toggle", "on", "off", "status")][string]$Mode = "toggle")

$Root = Split-Path -Parent $PSScriptRoot
$Link = Join-Path ([Environment]::GetFolderPath("Startup")) "LMS backend.lnk"

function Get-EnvValue([string]$key) {
    $m = Select-String -Path (Join-Path $Root ".env") -Pattern "^$key=(.*)$"
    if ($m) { return $m.Matches.Groups[1].Value.Trim() } else { return "" }
}

$Rover = "pi@" + ([Uri](Get-EnvValue "ROVER_URL")).Host
$RoverCtl = "~/lms-rover/infra/pi/lms-pi.sh"
$Barn = Get-EnvValue "BARN_PI"
$BarnCtl = "bash ~/lms/infra/pi/lms-barn.sh"

function Invoke-Pi([string]$target, [string]$cmd) {
    $out = ssh -o BatchMode=yes -o ConnectTimeout=6 $target $cmd 2>$null
    if ($LASTEXITCODE -ne 0 -and -not $out) { return $null }
    return ($out -join " ").Trim()
}

function Pi-State([string]$target, [string]$cmd) {
    $s = Invoke-Pi $target $cmd
    if ($null -eq $s) { return "unreachable ($target)" }
    if ($s -eq "enabled") { return "ON" } else { return "off" }
}

function Show-Status {
    $laptop = if (Test-Path $Link) { "ON" } else { "off" }
    Write-Host "laptop autostart:    $laptop"
    Write-Host "rover pi at boot:    $(Pi-State $Rover 'systemctl is-enabled lms-rover')"
    if ($Barn) { Write-Host "barn pi (Sense HAT): $(Pi-State $Barn "$BarnCtl is-enabled")" }
}

function Set-Pi([string]$name, [string]$target, [string]$cmd) {
    if ($null -eq (Invoke-Pi $target $cmd)) {
        Write-Host "WARNING: $name not reachable at $target - its autostart is unchanged. Run again when it is on."
    }
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
    Set-Pi "rover Pi" $Rover "$RoverCtl enable rover"
    if ($Barn) { Set-Pi "barn Pi" $Barn "$BarnCtl on" }
} else {
    Remove-Item $Link -ErrorAction SilentlyContinue
    Set-Pi "rover Pi" $Rover "$RoverCtl disable rover"
    if ($Barn) { Set-Pi "barn Pi" $Barn "$BarnCtl off" }
}
Write-Host "mode: $Mode"
Show-Status
