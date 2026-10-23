"""Listen for the Pis' beacons (infra/pi/lms_beacon.py) and keep the laptop pointed at them.

    .venv/Scripts/python infra/pi_watch.py            print each Pi when it appears or its address changes
    .venv/Scripts/python infra/pi_watch.py --update   ...and update .env + the Pi's MQTT_HOST (run_all does this)

The Pis broadcast every 10 s on UDP 50505. Windows Firewall must let that in once:
infra/firewall_mqtt.ps1 (admin) adds the rule. After ROVER_URL changes, restart the API
(stop_all / run_all) so the dashboard's Rover page follows.

Wake-up: the dashboard's "Stop rover & dashboard" button powers the rover off, writes
logs/dashboard_sleep.json with the rover's boot id and stops everything on the laptop except
this watcher. When the rover beacons again from a *new* boot (switched on again), the watcher
deletes that file and runs infra/run_all.ps1, so the dashboard comes back and its link goes to
Telegram. The latest boot id per Pi is kept in logs/pi_state.json for the API to read.
"""

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import find_pi  # noqa: E402  (sibling script: .env helpers and the update logic)

PORT = 50505
ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "logs" / "pi_state.json"
SLEEP = ROOT / "logs" / "dashboard_sleep.json"


def my_ip_towards(addr: str) -> str | None:
    """This laptop's address on the network that reaches `addr` (no packet is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((addr, PORT))
            return s.getsockname()[0]
    except OSError:
        return None


def save_state(state: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def wake_if_rover_restarted(boot: str | None) -> None:
    """Dashboard asleep and the rover is up from a new boot: start the laptop side again."""
    if not boot or not SLEEP.exists():
        return
    try:
        slept = json.loads(SLEEP.read_text(encoding="utf-8"))
    except ValueError:
        slept = {}
    if boot == slept.get("rover_boot"):
        return  # still the boot that was shut down (its last beacons before power-off)
    if slept.get("rover_boot") is None and time.time() - slept.get("since", 0) < 90:
        return  # boot of the stopped rover unknown: ignore beacons sent while it was shutting down
    SLEEP.unlink(missing_ok=True)
    print(f"{time.strftime('%H:%M:%S')} rover switched on again: starting the dashboard", flush=True)
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "infra" / "run_all.ps1"),
        ],
        cwd=ROOT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--update", action="store_true", help="update .env and the Pis when an address changes")
    args = ap.parse_args()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", PORT))
    print(f"listening for Pi beacons on UDP {PORT}", flush=True)
    seen: dict[str, tuple] = {}  # user -> (pi address, laptop address)
    state: dict[str, dict] = {}  # user -> {"addr", "boot", "host", "ts"} (logs/pi_state.json)
    while True:
        data, (addr, _) = sock.recvfrom(2048)
        try:
            msg = json.loads(data)
        except ValueError:
            continue
        if not isinstance(msg, dict) or msg.get("lms") != "pi" or msg.get("user") not in find_pi.ROLE:
            continue
        user = msg["user"]
        role = find_pi.ROLE[user]
        boot = msg.get("boot")
        if state.get(user, {}).get("boot") != boot or state.get(user, {}).get("addr") != addr:
            state[user] = {"addr": addr, "boot": boot, "host": msg.get("host"), "ts": time.time()}
            save_state(state)
        if role == "rover":
            wake_if_rover_restarted(boot)
        mine = my_ip_towards(addr)
        if seen.get(user) == (addr, mine):
            continue
        seen[user] = (addr, mine)
        print(
            f"{time.strftime('%H:%M:%S')} {role} Pi '{msg.get('host')}' at {addr} on Wi-Fi "
            f"'{msg.get('ssid') or '?'}' (laptop {mine}): ssh {user}@{addr}",
            flush=True,
        )
        if args.update:
            try:
                find_pi.update(user, addr, mine)
            except Exception as e:  # an unreachable Pi must not stop the watcher
                print(f"  update failed: {e}", flush=True)
                seen.pop(user, None)  # try again on its next beacon


if __name__ == "__main__":
    main()
