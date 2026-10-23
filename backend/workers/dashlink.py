"""Send the dashboard's LAN link to Telegram whenever this laptop's address changes.

    python -m backend.workers.dashlink

Phones on the same Wi-Fi open the dashboard at http://<laptop IP>:8000, and that IP changes
with the hotspot. Checks every 30 s; sends once at start and again on every change.
Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env (same as the notifier).
"""

import logging
import socket
import subprocess
import time

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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    enabled = bool(settings.telegram_token and settings.telegram_chat_id)
    if not enabled:
        log.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set: the link is only logged")
    told = None
    while True:
        ip = lan_ip()
        if ip and ip != told:
            ssid = wifi_name()
            text = f"📊 LMS dashboard\nhttp://{ip}:{PORT}\nWi-Fi: {ssid or '?'} (phone must be on the same Wi-Fi)"
            log.info("dashboard at http://%s:%d on %s", ip, PORT, ssid or "?")
            if not enabled:
                told = ip
            else:
                try:
                    send_telegram(text)
                    told = ip
                except Exception as e:  # no internet yet: retry next round
                    log.error("telegram send failed: %s", e)
        time.sleep(EVERY_S)


if __name__ == "__main__":
    main()
