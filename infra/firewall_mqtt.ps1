# Allow LAN devices (Pi, ESP collar) to reach Mosquitto on this laptop (TCP 1883), and the Pis'
# IP beacons to reach infra/pi_watch.py (UDP 50505).
# Needs admin. Private profile + local subnet only. Idempotent.
# WSL runs with networkingMode=mirrored, so the Hyper-V firewall needs a rule too.
#Requires -RunAsAdministrator

$port = 1883
$name = "LMS MQTT $port"

Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $port `
    -Action Allow -Profile Private -RemoteAddress LocalSubnet | Out-Null

$beacon = "LMS Pi beacon 50505"
Get-NetFirewallRule -DisplayName $beacon -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $beacon -Direction Inbound -Protocol UDP -LocalPort 50505 `
    -Action Allow -Profile Private -RemoteAddress LocalSubnet | Out-Null

# Hyper-V firewall (WSL VM creator id)
$wsl = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'
if (Get-Command New-NetFirewallHyperVRule -ErrorAction SilentlyContinue) {
    Get-NetFirewallHyperVRule -Name 'LMS-MQTT' -ErrorAction SilentlyContinue | Remove-NetFirewallHyperVRule
    New-NetFirewallHyperVRule -Name 'LMS-MQTT' -DisplayName $name -Direction Inbound `
        -VMCreatorId $wsl -Protocol TCP -LocalPorts $port -Action Allow | Out-Null
}

Get-NetFirewallRule -DisplayName $name, $beacon | Select-Object DisplayName, Enabled, Profile, Action
Get-NetFirewallHyperVRule -Name 'LMS-MQTT' -ErrorAction SilentlyContinue | Select-Object Name, Enabled, Action
