"""Listen for the Pis' beacons (infra/pi/lms_beacon.py) and keep the laptop pointed at them.

    .venv/Scripts/python infra/pi_watch.py            print each Pi when it appears or its address changes
    .venv/Scripts/python infra/pi_watch.py --update   ...and update .env + the Pi's MQTT_HOST (run_all does this)

The Pis broadcast every 10 s on UDP 50505. Windows Firewall must let that in once:
infra/firewall_mqtt.ps1 (admin) adds the rule. After ROVER_URL changes, restart the API
(stop_all / run_all) so the dashboard's Rover page follows.
"""

import argparse
import json
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import find_pi  # noqa: E402  (sibling script: .env helpers and the update logic)

PORT = 50505


def my_ip_towards(addr: str) -> str | None:
    """This laptop's address on the network that reaches `addr` (no packet is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((addr, PORT))
            return s.getsockname()[0]
    except OSError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--update", action="store_true", help="update .env and the Pis when an address changes")
    args = ap.parse_args()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", PORT))
    print(f"listening for Pi beacons on UDP {PORT}", flush=True)
    seen: dict[str, tuple] = {}  # user -> (pi address, laptop address)
    while True:
        data, (addr, _) = sock.recvfrom(2048)
        try:
            msg = json.loads(data)
        except ValueError:
            continue
        if not isinstance(msg, dict) or msg.get("lms") != "pi" or msg.get("user") not in find_pi.ROLE:
            continue
        user = msg["user"]
        mine = my_ip_towards(addr)
        state = (addr, mine)
        if seen.get(user) == state:
            continue
        seen[user] = state
        role = find_pi.ROLE[user]
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
