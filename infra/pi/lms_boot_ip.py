#!/usr/bin/env python3
"""Make a headless Pi findable after boot. Runs as root at every boot (lms-boot-ip.service).

1. Waits up to 90 s for a Wi-Fi/Ethernet IPv4 address.
2. Got one: writes it to /boot/firmware/lms-ip.txt (open the SD card on any PC), prints it on the
   console, and scrolls "IP x.x.x.x" 3 times on a Sense HAT if one is fitted (skipped when the
   barn service is enabled: it shows the IP itself when it starts).
3. No address (no known Wi-Fi in range): starts its own Wi-Fi hotspot "LMS-<hostname>" (password
   in /etc/lms/ap.conf), reachable at 10.42.0.1, so you can SSH in and add a network. It stays up
   10 min, longer while someone is connected, then the Pi tries its known networks again.

On the laptop, `python infra/find_pi.py` finds the Pis on the same Wi-Fi or over a direct cable.
Standard library only: runs with the system python3.
"""

import glob
import socket
import subprocess
import time
from pathlib import Path

AP_CONF = Path("/etc/lms/ap.conf")
AP_CON = "LMS-setup"
AP_IP = "10.42.0.1"
BOOT_TXT = Path("/boot/firmware/lms-ip.txt")
WAIT_S = 90
AP_MIN_S = 600


def run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def addresses() -> list[tuple[str, str]]:
    """(interface, IPv4) for every global address except our own hotspot's."""
    out = []
    for line in run("ip", "-4", "-o", "addr", "show", "scope", "global").splitlines():
        parts = line.split()
        if len(parts) > 3 and parts[2] == "inet":
            ip = parts[3].split("/")[0]
            if ip != AP_IP:
                out.append((parts[1], ip))
    return out


def wait_for_address(seconds: float) -> list[tuple[str, str]]:
    end = time.time() + seconds
    while time.time() < end:
        found = addresses()
        if found:
            return found
        time.sleep(3)
    return []


def has_sense_hat() -> bool:
    try:
        return Path("/proc/device-tree/hat/product").read_text().strip("\0\n ").startswith("Sense HAT")
    except OSError:
        return False


def barn_service_enabled() -> bool:
    return bool(glob.glob("/home/*/.config/systemd/user/default.target.wants/lms-sensehat.service"))


def scroll(text: str, times: int = 3) -> None:
    if not has_sense_hat():
        return
    try:
        from sense_hat import SenseHat

        s = SenseHat()
        s.low_light = False
        for _ in range(times):
            s.show_message(text, scroll_speed=0.1, text_colour=(0, 200, 255))
            time.sleep(0.5)
        s.clear()
    except Exception as e:  # LED is a bonus; never fail the boot service over it
        print(f"sense hat: {e}", flush=True)


def announce(lines: list[str]) -> None:
    text = "\n".join(lines)
    print(text, flush=True)  # journal: journalctl -u lms-boot-ip
    try:
        BOOT_TXT.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {socket.gethostname()}\n{text}\n")
    except OSError as e:
        print(f"could not write {BOOT_TXT}: {e}", flush=True)
    try:
        with open("/dev/tty1", "w") as tty:
            tty.write(f"\n*** LMS {socket.gethostname()}: {text} ***\n")
    except OSError:
        pass


def ap_password() -> str | None:
    try:
        for line in AP_CONF.read_text().splitlines():
            if line.startswith("password="):
                pw = line.split("=", 1)[1].strip()
                return pw if len(pw) >= 8 else None
    except OSError:
        pass
    return None


def someone_connected() -> bool:
    ssh = run("ss", "-Htn", "state", "established", "( sport = :22 )").strip()
    stations = run("iw", "dev", "wlan0", "station", "dump").strip()
    return bool(ssh or stations)


def hotspot(host: str, password: str) -> None:
    ssid = f"LMS-{host}"[:32]
    run("nmcli", "connection", "delete", AP_CON)
    run("nmcli", "device", "wifi", "hotspot", "ifname", "wlan0", "con-name", AP_CON, "ssid", ssid, "password", password)
    run("nmcli", "connection", "modify", AP_CON, "connection.autoconnect", "no")
    announce([f"no known Wi-Fi: hotspot {ssid} is on", f"connect to it, then: ssh <user>@{AP_IP}"])
    shown = 0.0
    end = time.time() + AP_MIN_S
    while time.time() < end or someone_connected():
        if not barn_service_enabled() and time.time() - shown > 60:
            scroll(f"WIFI {ssid} IP {AP_IP}", times=1)
            shown = time.time()
        time.sleep(10)
    run("nmcli", "connection", "down", AP_CON)  # NetworkManager goes back to the known networks


def main() -> None:
    host = socket.gethostname()
    found = wait_for_address(WAIT_S)
    while not found:
        password = ap_password()
        if password is None:
            print(f"no address yet and no hotspot password in {AP_CONF}; waiting", flush=True)
            found = wait_for_address(300)
            continue
        hotspot(host, password)
        found = wait_for_address(WAIT_S)
    announce([f"{ifname} {ip}" for ifname, ip in found])
    if not barn_service_enabled():
        scroll("IP " + " ".join(ip for _, ip in found))


if __name__ == "__main__":
    main()
