"""Check that PostgreSQL/TimescaleDB, Redis and Mosquitto are reachable with the .env settings.

Run from the repo root:  .venv/Scripts/python infra/check_services.py
"""

import os
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt
import psycopg
import redis
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
ok = True


def report(name, fn):
    global ok
    try:
        print(f"{name:10} OK   {fn()}")
    except Exception as e:  # noqa: BLE001 - this is a diagnostic script
        ok = False
        print(f"{name:10} FAIL {e}")


def check_db():
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as c:
        ver = c.execute("SELECT extversion FROM pg_extension WHERE extname='timescaledb'").fetchone()[0]
        tables = [r[0] for r in c.execute("SELECT hypertable_name FROM timescaledb_information.hypertables")]
        return f"timescaledb {ver}, hypertables {sorted(tables)}"


def check_redis():
    r = redis.from_url(os.environ["REDIS_URL"], socket_timeout=5)
    return f"ping={r.ping()} version={r.info()['redis_version']}"


def check_mqtt():
    got = []
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    c.username_pw_set(os.environ["MQTT_USER"], os.environ["MQTT_PASSWORD"])
    c.on_message = lambda _c, _u, m: got.append(m.payload.decode())
    c.connect(os.environ.get("MQTT_HOST", "127.0.0.1"), int(os.environ.get("MQTT_PORT", 1883)))
    c.loop_start()
    c.subscribe("lms/selftest")
    time.sleep(0.3)
    c.publish("lms/selftest", "ping")
    deadline = time.time() + 3
    while not got and time.time() < deadline:
        time.sleep(0.05)
    c.loop_stop()
    c.disconnect()
    if not got:
        raise RuntimeError("no message round-trip")

    # anonymous clients must be refused
    reasons = []
    a = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    a.on_connect = lambda _c, _u, _f, reason, _p: reasons.append(reason)
    a.connect(os.environ.get("MQTT_HOST", "127.0.0.1"), int(os.environ.get("MQTT_PORT", 1883)))
    a.loop_start()
    time.sleep(1)
    a.loop_stop()
    if reasons and not reasons[0].is_failure:
        raise RuntimeError("anonymous connection was accepted")
    return f"round-trip ok, anonymous refused ({reasons[0] if reasons else 'no answer'})"


report("postgres", check_db)
report("redis", check_redis)
report("mqtt", check_mqtt)
sys.exit(0 if ok else 1)
