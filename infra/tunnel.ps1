# Public https link to the dashboard with a Cloudflare quick tunnel (free, no account,
# no router settings). The link changes every time; for a fixed name use a named tunnel
# on a domain you own (see docs/hosting.md).
#
# The dashboard requires login, but anyone with the link sees the login page and the
# rover can be driven after login - keep API_ADMIN_PASSWORD strong.
$Bin = "D:\DevCache\bin"
$Exe = Join-Path $Bin "cloudflared.exe"
if (-not (Test-Path $Exe)) {
    New-Item -ItemType Directory -Force $Bin | Out-Null
    Write-Host "downloading cloudflared to $Exe"
    # curl.exe, not Invoke-WebRequest: the PowerShell 5 progress bar makes a 55 MB download crawl
    curl.exe -sSL -o $Exe "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
}
$Root = Split-Path -Parent $PSScriptRoot
$Log = Join-Path $Root "logs\tunnel.log"
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Process -WindowStyle Hidden -FilePath $Exe -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://localhost:8000" `
    -RedirectStandardError $Log
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep 1
    $m = Select-String -Path $Log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($m) { Write-Host "Public dashboard: $($m.Matches[0].Value)"; return }
}
Write-Host "tunnel did not report a URL yet - see $Log"
