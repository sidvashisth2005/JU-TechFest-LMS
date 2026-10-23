"""Send the dashboard's LAN link to Telegram whenever this laptop's address changes.

    python -m backend.workers.dashlink

Phones on the same Wi-Fi open the dashboard at http://<laptop IP>:8000, and that IP changes
with the hotspot. Checks every 30 s; sends once at start and again on every change. Send the bot
/link (or /dashboard) at any time to get the current link back.
Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env (same as the notifier); only that chat is answered.
"""

import json
import logging
import socket
import subprocess
import time
import urllib.parse
import urllib.request

from backend.config import settings
from backend.workers.notifier import send_telegram

log = logging.getLogger("dashlink")
PORT = 8000
EVERY_S = 30


def lan_ip() -> str | None:
    """The address other devices on the Wi-Fi reach us at (no packet is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith(("127.", "169.254.")) else ip


def wifi_name() -> str:
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in out.stdout.splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "SSID":
            return value.strip()
    return ""


def link_text(ip: str | None) -> str:
    if not ip:
        return "📊 LMS dashboard: this laptop has no Wi-Fi address right now"
    ssid = wifi_name()
    return f"📊 LMS dashboard\nhttp://{ip}:{PORT}\nWi-Fi: {ssid or '?'} (phone must be on the same Wi-Fi)"


def wait_for_commands(offset: int, seconds: int) -> tuple[int, bool]:
    """Long-poll the bot for up to `seconds`; returns (next offset, whether /link was asked).
    The caller starts at offset -1 (= only the newest message) and ignores that first answer,
    so commands sent while the laptop was off are not replayed."""
    q = urllib.parse.urlencode({"offset": offset, "timeout": seconds, "allowed_updates": '["message"]'})
    url = f"https://api.telegram.org/bot{settings.telegram_token}/getUpdates?{q}"
    with urllib.request.urlopen(url, timeout=seconds + 10) as r:
        updates = json.load(r).get("result", [])
    asked = False
    for u in updates:
        offset = max(offset, u["update_id"] + 1)
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip().lower()
        if str(msg.get("chat", {}).get("id")) == str(settings.telegram_chat_id) and text.split("@")[0] in (
            "/link",
            "/dashboard",
            "link",
            "dashboard",
        ):
            asked = True
    return offset, asked


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    enabled = bool(settings.telegram_token and settings.telegram_chat_id)
    if not enabled:
        log.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set: the link is only logged")
    told = None
    offset = -1
    while True:
        ip = lan_ip()
        if ip and ip != told:
            log.info("dashboard at http://%s:%d", ip, PORT)
            if not enabled:
                told = ip
            else:
                try:
                    send_telegram(link_text(ip))
                    told = ip
                except Exception as e:  # no internet yet: retry next round
                    log.error("telegram send failed: %s", e)
        if not enabled:
            time.sleep(EVERY_S)
            continue
        try:
            # waiting on the bot doubles as the 30 s pause between address checks
            first = offset == -1
            offset, asked = wait_for_commands(offset, EVERY_S)
            if asked and not first:  # the first poll only skips past old messages
                send_telegram(link_text(lan_ip()))
                log.info("answered /link")
        except Exception as e:
            log.error("telegram poll failed: %s", e)
            time.sleep(EVERY_S)


if __name__ == "__main__":
    main()
