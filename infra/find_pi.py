"""Find the LMS Pis from the laptop, without a monitor on the Pi.

    .venv/Scripts/python infra/find_pi.py             list the Pis it can reach
    .venv/Scripts/python infra/find_pi.py --update    ...and point everything at the new addresses
    .venv/Scripts/python infra/find_pi.py --install   ...and install the boot IP announcer on them

Looks on every Wi-Fi/Ethernet network of this laptop (port 22, then `ssh user@ip hostname` with
the users pi and rpi-1), and on a direct Ethernet cable through IPv6 link-local addresses, which
need no DHCP. The Pis must already have this laptop's SSH key.

--update: rover Pi (user pi) -> ROVER_URL in .env, barn Pi (user rpi-1) -> BARN_PI in .env, and
MQTT_HOST on each Pi = this laptop's address on that network (their services are restarted if
running). Restart the laptop API afterwards so it uses the new ROVER_URL.
--install: copies infra/pi to the Pi and installs lms-beacon (IP broadcast every 10 s + Telegram on
change, user service) and lms-boot-ip (setup hotspot, SD-card file; needs passwordless sudo).
The setup-hotspot password comes from PI_SETUP_AP_PASSWORD in .env (created if missing).
"""

import argparse
import io
import ipaddress
import re
import secrets
import socket
import subprocess
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
USERS = ["pi", "rpi-1"]  # rover Pi, barn Pi
ROLE = {"pi": "rover", "rpi-1": "barn"}
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new"]


def sh(cmd: list[str], timeout: float = 20, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=stdin)


def ps(command: str) -> str:
    return sh(["powershell", "-NoProfile", "-Command", command], timeout=30).stdout


def local_networks() -> list[tuple[str, ipaddress.IPv4Network, str]]:
    """(adapter, network, our address) for each IPv4 network this laptop is on (/24 or smaller)."""
    out = ps(
        "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -ne 'WellKnown' } | "
        'ForEach-Object { "$($_.InterfaceAlias)|$($_.IPAddress)|$($_.PrefixLength)" }'
    )
    nets = []
    for line in out.splitlines():
        try:
            alias, ip, prefix = line.strip().split("|")
        except ValueError:
            continue
        if ip.startswith(("127.", "169.254.")) or "vEthernet" in alias or "Loopback" in alias:
            continue
        net = ipaddress.ip_network(f"{ip}/{max(int(prefix), 24)}", strict=False)
        nets.append((alias, net, ip))
    # Wi-Fi first: a scan leaves hundreds of half-open connections that make Windows stall the
    # next scan for a while, and the Pis are almost always on Wi-Fi
    return sorted(nets, key=lambda n: "wi-fi" not in n[0].lower())


def ssh_open(ip: str) -> bool:
    # phone hotspots are slow to resolve a new neighbour, so allow time and one retry
    for timeout in (1.5, 3.0):
        try:
            with socket.create_connection((ip, 22), timeout=timeout):
                return True
        except TimeoutError:
            continue
        except OSError:
            return False
    return False


def identify(addr: str) -> tuple[str, str] | None:
    """(user, hostname) of the first known user that can log in, else None."""
    for user in USERS:
        try:
            r = sh([*SSH, f"{user}@{addr}", "hostname"], timeout=15)
        except subprocess.TimeoutExpired:
            continue
        if r.returncode == 0 and r.stdout.strip():
            return user, r.stdout.strip()
    return None


def cable_neighbours() -> list[str]:
    """IPv6 link-local addresses seen on wired adapters that are up (a Pi on a direct cable)."""
    found = []
    for line in ps(
        "Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' -and $_.MediaType -eq '802.3' } | "
        "ForEach-Object { $_.ifIndex }"
    ).split():
        idx = line.strip()
        sh(["ping", "-6", "-n", "2", f"ff02::1%{idx}"], timeout=15)  # makes neighbours answer
        out = ps(
            f"Get-NetNeighbor -InterfaceIndex {idx} -AddressFamily IPv6 | "
            "Where-Object { $_.IPAddress -like 'fe80*' -and $_.State -ne 'Unreachable' } | "
            "ForEach-Object { $_.IPAddress }"
        )
        found += [f"{a.strip()}%{idx}" for a in out.split() if a.strip()]
    return found


def set_env(key: str, value: str) -> None:
    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    line = f"{key}={value}"
    if re.search(rf"^{re.escape(line)}$", text, flags=re.M):
        return  # already set
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    ENV.write_text(text, encoding="utf-8")


def get_env(key: str) -> str:
    if ENV.exists():
        m = re.search(rf"^{key}=(.*)$", ENV.read_text(encoding="utf-8"), flags=re.M)
        if m:
            return m.group(1).strip()
    return ""


def update(user: str, addr: str, laptop_ip: str | None) -> None:
    role = ROLE[user]
    if role == "rover":
        set_env("ROVER_URL", f"http://{addr}:8080")
        env_file, restart = "~/lms-rover/.env", "systemctl is-active -q lms-rover && sudo systemctl restart lms-rover"
    else:
        set_env("BARN_PI", f"{user}@{addr}")
        env_file, restart = (
            "~/lms/.env",
            ("systemctl --user is-active -q lms-sensehat && bash ~/lms/infra/pi/lms-barn.sh restart"),
        )
    print(f"  .env: {'ROVER_URL' if role == 'rover' else 'BARN_PI'} -> {addr}")
    if laptop_ip:
        # only touch the Pi (and restart its service) when MQTT_HOST really changes
        cmd = (
            f"test -f {env_file} && ! grep -qx 'MQTT_HOST={laptop_ip}' {env_file} && "
            f"sed -i 's/^MQTT_HOST=.*/MQTT_HOST={laptop_ip}/' {env_file} && echo changed && {{ {restart}; true; }}"
        )
        r = sh([*SSH, f"{user}@{addr}", cmd], timeout=60)
        if "changed" in r.stdout:
            print(f"  Pi {env_file}: MQTT_HOST -> {laptop_ip}")


def install(user: str, addr: str) -> None:
    password = get_env("PI_SETUP_AP_PASSWORD")
    if len(password) < 8:
        password = secrets.token_urlsafe(9)
        set_env("PI_SETUP_AP_PASSWORD", password)
        print("  created PI_SETUP_AP_PASSWORD in .env (the setup hotspot's Wi-Fi password)")
    folder = "~/lms-rover" if ROLE[user] == "rover" else "~/lms"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        t.add(ROOT / "infra" / "pi", arcname="infra/pi", filter=lambda i: None if "__pycache__" in i.name else i)
    tar = buf.getvalue()
    # sync: a power cut soon after copying leaves unsynced files empty on the SD card
    sh_files = f"{folder}/infra/pi/*.sh"
    unpack = f"mkdir -p {folder} && tar -x -C {folder} && sed -i 's/\\r$//' {sh_files} && chmod +x {sh_files} && sync"
    subprocess.run([*SSH, f"{user}@{addr}", unpack], input=tar, check=True)
    # beacon: user service, no sudo; Telegram settings go over stdin, never on a command line
    telegram = "".join(f"{k}={get_env(k)}\n" for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if get_env(k))
    r = sh(
        [*SSH, f"{user}@{addr}", f"bash {folder}/infra/pi/install_beacon.sh {ROLE[user]}"],
        timeout=60,
        stdin=telegram,
    )
    print("  " + (r.stdout.strip() or r.stderr.strip()).replace("\n", "\n  "))
    # boot announcer + setup hotspot: needs root
    r = sh(
        [*SSH, f"{user}@{addr}", f"sudo -n bash {folder}/infra/pi/install_boot_ip.sh"],
        timeout=60,
        stdin=password + "\n",
    )
    if r.returncode == 0:
        print("  " + r.stdout.strip().replace("\n", "\n  "))
    else:
        print(
            f"  lms-boot-ip (setup hotspot) needs sudo. On the laptop run once (asks the Pi password):\n"
            f'  ssh -t {user}@{addr} "sudo bash {folder}/infra/pi/install_boot_ip.sh"\n'
            f"  (no hotspot password that way; re-run --install after setting passwordless sudo)"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--update", action="store_true", help="write the addresses into .env and the Pis")
    ap.add_argument("--install", action="store_true", help="install the boot IP announcer on the Pis")
    ap.add_argument("--all", action="store_true", help="scan every network even after finding devices")
    args = ap.parse_args()

    candidates: list[tuple[str, str | None, str]] = []  # (address, laptop ip on that net, where)
    for alias, net, mine in local_networks():
        hosts = [str(h) for h in net.hosts() if str(h) != mine]
        with ThreadPoolExecutor(128) as pool:
            open_ = [h for h, ok in zip(hosts, pool.map(ssh_open, hosts), strict=True) if ok]
        print(f"{alias}: {net} (me {mine}) - {len(open_)} device(s) with SSH")
        candidates += [(h, mine, alias) for h in open_]
        if open_ and not args.all:
            break  # found SSH devices on this network; --all to scan the others too
    for addr in cable_neighbours():
        candidates.append((addr, None, "cable (IPv6 link-local)"))

    found = 0
    for addr, mine, where in candidates:
        who = identify(addr)
        if who is None:
            continue
        user, host = who
        found += 1
        print(f"\nFOUND {ROLE[user]} Pi '{host}': ssh {user}@{addr}   [{where}]")
        if args.update and "%" not in addr:
            update(user, addr, mine)
        if args.install:
            install(user, addr)
    if not found:
        print(
            "\nNo Pi found. Is it on the same Wi-Fi? Waited ~2 min after power-on? Without Wi-Fi it opens\n"
            "its own hotspot LMS-<name> after ~90 s (if lms-boot-ip is installed): join it, then\n"
            "ssh <user>@10.42.0.1. Or read lms-ip.txt on the SD card's boot partition."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
