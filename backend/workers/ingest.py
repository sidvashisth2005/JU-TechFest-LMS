"""MQTT -> Redis Stream. Validates every device message and queues it for the processor.

    python -m backend.workers.ingest

Bad messages are counted and kept in the `lms:dead` stream for debugging instead of being
dropped silently.
"""

import json
import logging
import signal
import threading
import time

import paho.mqtt.client as mqtt
import redis
from pydantic import ValidationError

from backend.config import STREAM_IN, settings
from common import topics
from common.schemas import DetectionsMsg, EnvMsg, RoverStatusMsg, VitalsMsg

log = logging.getLogger("ingest")

# subscription -> (message type name, model, id field filled from the topic)
ROUTES = {
    topics.COLLAR_VITALS_SUB: ("vitals", VitalsMsg, "animal_id"),
    topics.BARN_ENV_SUB: ("env", EnvMsg, "station_id"),
    topics.ROVER_STATUS_SUB: ("rover_status", RoverStatusMsg, "rover_id"),
    topics.ROVER_DETECTIONS_SUB: ("detections", DetectionsMsg, "rover_id"),
}
STREAM_MAXLEN = 2_000_000
DEAD_MAXLEN = 10_000


def route(topic: str):
    parts = topic.split("/")
    for sub, r in ROUTES.items():
        s = sub.split("/")
        if len(s) == len(parts) and all(a in ("+", b) for a, b in zip(s, parts, strict=True)):
            return r
    return None


def parse(topic: str, payload: bytes):
    """Return (type name, validated model) or raise ValueError."""
    r = route(topic)
    if r is None:
        raise ValueError(f"unknown topic {topic}")
    name, model, id_field = r
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("payload is not a JSON object")
    # the topic is the source of truth for the device id
    data[id_field] = topics.device_id(topic)
    data.setdefault("ts", time.time())
    return name, model.model_validate(data)


class Ingest:
    def __init__(self):
        self.r = redis.from_url(settings.redis_url)
        self.ok = 0
        self.bad = 0
        # messages are buffered and written to Redis in pipelined batches (one round trip each)
        self.buf: list[tuple[str, dict]] = []
        self.lock = threading.Lock()
        # persistent session: the broker keeps queued messages while ingest is restarting
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="lms-ingest", clean_session=False)
        self.client.username_pw_set(settings.mqtt_user, settings.mqtt_password)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(1, 30)

    def on_connect(self, client, _userdata, _flags, reason, _props):
        if reason.is_failure:
            log.error("MQTT connect failed: %s", reason)
            return
        for sub in ROUTES:
            client.subscribe(sub, qos=1)
        log.info("connected, subscribed to %d topics", len(ROUTES))

    def on_message(self, _client, _userdata, msg):
        try:
            name, model = parse(msg.topic, msg.payload)
        except (ValueError, ValidationError) as e:
            item = ("lms:dead", {"topic": msg.topic, "payload": msg.payload[:2000], "error": str(e)[:500]})
            with self.lock:
                self.bad += 1
                self.buf.append(item)
            return
        with self.lock:
            self.ok += 1
            self.buf.append((STREAM_IN, {"type": name, "data": model.model_dump_json()}))

    def flush(self) -> None:
        with self.lock:
            batch, self.buf = self.buf, []
        if not batch:
            return
        pipe = self.r.pipeline(transaction=False)
        for stream, fields in batch:
            maxlen = DEAD_MAXLEN if stream == "lms:dead" else STREAM_MAXLEN
            pipe.xadd(stream, fields, maxlen=maxlen, approximate=True)
        try:
            pipe.execute()
        except redis.RedisError:
            with self.lock:  # keep the batch for the next attempt
                self.buf = batch + self.buf
            raise

    def run(self):
        self.client.connect(settings.mqtt_host, settings.mqtt_port)
        self.client.loop_start()
        stop = []
        signal.signal(signal.SIGINT, lambda *_: stop.append(1))
        signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
        last = time.time()
        while not stop:
            time.sleep(0.05)
            try:
                self.flush()
            except redis.RedisError as e:
                log.error("redis write failed, retrying: %s", e)
                time.sleep(1)
            if time.time() - last >= 30:
                log.info("queued %d, rejected %d", self.ok, self.bad)
                last = time.time()
        self.client.loop_stop()
        self.flush()
        self.client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    Ingest().run()
