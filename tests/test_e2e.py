"""End to end: a reading published over MQTT must come out of the API.

    LMS_E2E=1 .venv/Scripts/python -m pytest tests/test_e2e.py -v

Needs the full stack running (infra/run_all.ps1: services + ingest + processor + API).
Skipped otherwise, including in CI. Uses a dedicated test animal id (E2E001) and removes
its rows afterwards.
"""

import json
import os
import time
import urllib.request

import psycopg
import pytest

from backend.config import settings
from common import topics
from common.schemas import VitalsMsg

pytestmark = pytest.mark.skipif(os.environ.get("LMS_E2E") != "1", reason="set LMS_E2E=1 with the stack running")
ANIMAL = "E2E001"
API = os.environ.get("LMS_API", "http://127.0.0.1:8000")


def api(path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def test_mqtt_reading_reaches_the_api():
    import paho.mqtt.client as mqtt

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="lms-e2e-test")
    c.username_pw_set(settings.mqtt_user, settings.mqtt_password)
    c.connect(settings.mqtt_host, settings.mqtt_port)
    c.loop_start()
    sent_at = time.time()
    msg = VitalsMsg(animal_id=ANIMAL, ts=sent_at, hr=71, spo2=97, body_temp=38.7, activity=0.05, steps=4)
    c.publish(topics.collar_vitals(ANIMAL), msg.model_dump_json(), qos=1).wait_for_publish(5)
    c.loop_stop()
    c.disconnect()

    token = api("/api/auth/login", body={"username": settings.admin_user, "password": settings.admin_password})["token"]
    try:
        deadline = time.time() + 20
        latest = None
        while time.time() < deadline:
            latest = api(f"/api/animals/{ANIMAL}", token).get("latest") if _exists(token) else None
            if latest and abs(latest["ts"] - sent_at) < 1:
                break
            time.sleep(1)
        assert latest is not None, "reading never reached the database/API"
        assert latest["hr"] == 71 and latest["body_temp"] == pytest.approx(38.7)
    finally:
        with psycopg.connect(settings.database_url) as db:
            db.execute("DELETE FROM vitals WHERE animal_id = %s", (ANIMAL,))
            db.execute("DELETE FROM alerts WHERE animal_id = %s", (ANIMAL,))
            db.execute("DELETE FROM animals WHERE animal_id = %s", (ANIMAL,))


def _exists(token: str) -> bool:
    try:
        api(f"/api/animals/{ANIMAL}", token)
        return True
    except urllib.error.HTTPError:
        return False
