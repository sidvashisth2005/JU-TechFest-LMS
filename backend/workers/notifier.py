"""Send new alerts to Telegram.

    python -m backend.workers.notifier

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env (create a bot with @BotFather, then
message it once and read your chat id from https://api.telegram.org/bot<TOKEN>/getUpdates).
Without them it only logs. `info` alerts are not sent; the same animal+kind is sent at most
once per cooldown.
"""

import json
import logging
import time
import urllib.parse
import urllib.request

import redis

from backend.config import CHANNEL_ALERTS, settings

log = logging.getLogger("notifier")
COOLDOWN_S = 3 * 3600
ICON = {"critical": "🔴", "warning": "🟠", "info": "🔵"}


def format_alert(a: dict) -> str:
    subject = f"Cow {a['animal_id']}" if a.get("animal_id") else f"Barn {a.get('station_id')}"
    when = time.strftime("%d %b %H:%M", time.localtime(a["ts"]))
    return f"{ICON.get(a['severity'], '')} {subject}: {a['message']}\n{a['severity'].upper()} · {when}"


def send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": settings.telegram_chat_id, "text": text}).encode()
    with urllib.request.urlopen(url, data=data, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"telegram HTTP {resp.status}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    enabled = bool(settings.telegram_token and settings.telegram_chat_id)
    if not enabled:
        log.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set: alerts will only be logged")
    r = redis.from_url(settings.redis_url)
    sub = r.pubsub(ignore_subscribe_messages=True)
    sub.subscribe(CHANNEL_ALERTS)
    last_sent: dict[tuple, float] = {}
    for msg in sub.listen():
        a = json.loads(msg["data"])
        if a["severity"] == "info":
            continue
        key = (a.get("animal_id") or a.get("station_id"), a["kind"])
        if time.time() - last_sent.get(key, 0) < COOLDOWN_S:
            continue
        text = format_alert(a)
        if enabled:
            try:
                send_telegram(text)
                last_sent[key] = time.time()
                log.info("sent: %s", text.splitlines()[0])
            except Exception as e:  # network trouble must not kill the notifier
                log.error("telegram send failed: %s", e)
        else:
            last_sent[key] = time.time()
            log.info("(not sent) %s", text.splitlines()[0])


if __name__ == "__main__":
    main()
