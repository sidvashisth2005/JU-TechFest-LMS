#!/usr/bin/env python3
"""Tell the laptop (and your phone) where this Pi is. Runs on both Pis as a user service.

Every 10 s, while the Pi has an address, it broadcasts one small UDP packet on each network it is on
(port 50505): {"lms": "pi", "host", "user", "role", "ips", "ssid"}. The laptop's infra/pi_watch.py
hears it and keeps .env and the Pi's MQTT_HOST pointed at the right addresses.

When the address changes (first connect after boot, another Wi-Fi, a new DHCP lease) it also sends
one Telegram message, if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are in ~/.config/lms/beacon.env,
so you can find the Pi from your phone without the laptop.

Standard library only (system python3). Installed by infra/pi/install_beacon.sh.
"""

import getpass
import json
import os
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

PORT = 50505
EVERY_S = 10
CONF = Path.home() / ".config" / "lms" / "beacon.env"


def load_conf() -> dict:
    conf = {}
    try:
        for line in CONF.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                conf[k.strip()] = v.strip()
    except OSError:
        pass
    return conf


def run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def addresses() -> list[tuple[str, str, str]]:
    """(interface, IPv4, broadcast address) for each global address (not our setup hotspot)."""
    out = []
    for line in run("ip", "-4", "-o", "addr", "show", "scope", "global").splitlines():
        p = line.split()
        if len(p) > 3 and p[2] == "inet":
            ip = p[3].split("/")[0]
            brd = p[p.index("brd") + 1] if "brd" in p else "255.255.255.255"
            if ip != "10.42.0.1":
                out.append((p[1], ip, brd))
    return out


def wifi_name() -> str:
    return run("nmcli", "-t", "-g", "GENERAL.CONNECTION", "device", "show", "wlan0").strip()


def telegram(conf: dict, text: str) -> bool:
    token, chat = conf.get("TELEGRAM_BOT_TOKEN"), conf.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return True  # not configured: nothing to send
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=10) as r:
            return r.status == 200
    except OSError as e:
        print(f"telegram: {e}", flush=True)  # no internet yet; retried next round
        return False


def main() -> None:
    conf = load_conf()
    host, user = socket.gethostname(), getpass.getuser()
    role = conf.get("LMS_ROLE", os.environ.get("LMS_ROLE", ""))
    told: tuple = ()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    while True:
        found = addresses()
        if found:
            ips = [ip for _, ip, _ in found]
            ssid = wifi_name()
            msg = json.dumps({"lms": "pi", "host": host, "user": user, "role": role, "ips": ips, "ssid": ssid})
            for _, _, brd in found:
                try:
                    sock.sendto(msg.encode(), (brd, PORT))
                except OSError as e:
                    print(f"broadcast {brd}: {e}", flush=True)
            if tuple(ips) != told:
                print(f"address now {', '.join(ips)} on {ssid or '?'}", flush=True)
                text = (
                    f"🟢 {host}{f' ({role})' if role else ''} is online\n"
                    f"IP {', '.join(ips)}\nWi-Fi {ssid or '?'}\nssh {user}@{ips[0]}"
                )
                if telegram(conf, text):
                    told = tuple(ips)
        time.sleep(EVERY_S)


if __name__ == "__main__":
    main()
