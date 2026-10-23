"""Redis Stream -> TimescaleDB, plus anomaly detection and alerts.

    python -m backend.workers.processor [--name p1]

Reads validated messages from `lms:in` as part of the `processor` consumer group, writes
them in batches, runs the streaming detector, stores alerts, and publishes live updates
on Redis pub/sub for the API's WebSocket. Barn stations get their open-alert count back over
MQTT (retained `lms/barn/{id}/state`) for their LED, and a joystick "ack" event from a station
acknowledges that station's open alerts.

Run more than one (`--name p2`) only if you shard by animal; the detector keeps per-animal
state in memory, so two processors on the same stream would each see half the herd.
On start it replays the last 48 h from the database to rebuild baselines (no alerts emitted).
"""

import argparse
import json
import logging
import os
import signal
import time
from collections import defaultdict
from datetime import UTC, datetime

import paho.mqtt.client as mqtt
import psycopg
import redis

from backend.config import CHANNEL_ALERTS, CHANNEL_LIVE, STREAM_GROUP, STREAM_IN, settings
from common import topics
from common.schemas import (
    AlertMsg,
    DetectionsMsg,
    EnvMsg,
    RoverStatusMsg,
    StationEventMsg,
    StationStateMsg,
    VitalsMsg,
    thi,
)
from ml.anomaly.detector import Detector
from ml.anomaly.multivariate import load_scorer

log = logging.getLogger("processor")
BATCH = 1000
BLOCK_MS = 1000
TICK_S = 60
MODELS = {
    "vitals": VitalsMsg,
    "env": EnvMsg,
    "event": StationEventMsg,
    "rover_status": RoverStatusMsg,
    "detections": DetectionsMsg,
}


def dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, UTC)


class Processor:
    def __init__(self, name: str):
        self.name = name
        self.r = redis.from_url(settings.redis_url)
        self.db = self._connect()
        # Layer 3 (IsolationForest) is opt-in: on simulated herds it found nothing the rules missed
        # and added ~4 false info alerts per 100 cow-days (ml/anomaly/models/iforest_report.json)
        scorer = load_scorer() if os.environ.get("LMS_IFOREST") == "1" else None
        self.detector = Detector(scorer=scorer)
        log.info("multivariate model %s", "on" if scorer else "off (set LMS_IFOREST=1 to enable)")
        self.stop = False
        self.mqtt = self._mqtt()
        try:
            self.r.xgroup_create(STREAM_IN, STREAM_GROUP, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    @staticmethod
    def _connect():
        """Connect to the database, retrying with backoff (it may still be starting)."""
        delay = 1.0
        while True:
            try:
                return psycopg.connect(settings.database_url, autocommit=False, connect_timeout=10)
            except psycopg.OperationalError as e:
                log.warning("database not reachable (%s); retrying in %.0fs", e, delay)
                time.sleep(delay)
                delay = min(delay * 2, 30)

    @staticmethod
    def _mqtt():
        """Publisher for station state; connects in the background and keeps retrying."""
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"lms-processor-{os.getpid()}")
        c.username_pw_set(settings.mqtt_user, settings.mqtt_password)
        c.reconnect_delay_set(1, 30)
        c.connect_async(settings.mqtt_host, settings.mqtt_port)
        c.loop_start()
        return c

    def _recover_db(self) -> None:
        """After a failed write: roll back, or reconnect if the connection itself is gone."""
        try:
            self.db.rollback()
        except psycopg.Error:
            pass
        if self.db.closed or self.db.broken:
            log.warning("database connection lost; reconnecting")
            try:
                self.db.close()
            except psycopg.Error:
                pass
            self.db = self._connect()

    # ---------- startup ----------
    def warmup(self, hours: float = 48) -> None:
        t0 = time.time()
        with self.db.cursor() as cur:
            cur.execute(
                "SELECT extract(epoch FROM ts), animal_id, hr, spo2, body_temp, activity, steps, battery "
                "FROM vitals WHERE ts > now() - make_interval(hours => %s) ORDER BY ts",
                (hours,),
            )
            n = 0
            for ts, aid, hr, spo2, temp, act, steps, batt in cur:
                self.detector.on_vitals(
                    VitalsMsg(
                        animal_id=aid,
                        ts=float(ts),
                        hr=hr,
                        spo2=spo2,
                        body_temp=temp,
                        activity=act,
                        steps=steps,
                        battery=batt,
                    )
                )
                n += 1
        self.db.rollback()
        # alerts that are still open in the DB stay open in the detector, so they aren't raised twice
        with self.db.cursor() as cur:
            cur.execute(
                "SELECT coalesce(animal_id, station_id), kind, extract(epoch FROM ts) FROM alerts "
                "WHERE acked_at IS NULL AND resolved_at IS NULL AND ts > now() - interval '2 days'"
            )
            for subject, kind, ts in cur:
                self.detector.open[(subject, kind)] = float(ts)
        self.db.rollback()
        log.info("warm-up: replayed %d readings in %.1fs", n, time.time() - t0)

    # ---------- main loop ----------
    def run(self) -> None:
        self.warmup()
        next_tick = time.time() + TICK_S
        # first deliver anything this consumer read before a crash but never acknowledged
        cursor = "0"
        while not self.stop:
            resp = self.r.xreadgroup(STREAM_GROUP, self.name, {STREAM_IN: cursor}, count=BATCH, block=BLOCK_MS)
            entries = resp[0][1] if resp else []
            if cursor == "0" and not entries:
                cursor = ">"
                continue
            if entries and not self.handle(entries):
                cursor = "0"  # re-read our pending (unacknowledged) entries on the next pass
            if time.time() >= next_tick:
                next_tick = time.time() + TICK_S
                try:
                    saved = self.insert_alerts(self.detector.tick(time.time()))
                    resolved = self.resolve_alerts()
                    self.db.commit()
                except psycopg.Error:
                    log.exception("alert tick failed")
                    self._recover_db()
                    continue
                self.publish_alerts(saved, resolved)
                self.publish_station_state()  # also picks up acks made on the dashboard

    def handle(self, entries) -> bool:
        """Process a batch; False if it could not be stored (left pending for a retry)."""
        groups = defaultdict(list)
        ids = []
        for entry_id, fields in entries:
            ids.append(entry_id)
            kind = fields[b"type"].decode()
            model = MODELS.get(kind)
            if model is None:
                continue
            groups[kind].append(model.model_validate_json(fields[b"data"]))

        alerts: list[AlertMsg] = []
        live = []
        # environment first so heat state is current when vitals of the same tick arrive
        for e in sorted(groups["env"], key=lambda m: m.ts):
            alerts += self.detector.on_env(e)
            live.append({"type": "env", **e.model_dump(), "thi": e.thi})
        for v in sorted(groups["vitals"], key=lambda m: m.ts):
            alerts += self.detector.on_vitals(v)
            live.append({"type": "vitals", **v.model_dump(exclude_none=True)})
        for ev in sorted(groups["event"], key=lambda m: m.ts):
            alerts += self.detector.on_station_event(ev)
            live.append({"type": "station_event", **ev.model_dump()})
        for s in groups["rover_status"]:
            live.append({"type": "rover_status", **s.model_dump()})

        try:
            self.write(groups)
            saved = self.insert_alerts(alerts)
            resolved = self.resolve_alerts()
            acked = sum(self.ack_station(ev) for ev in groups["event"] if ev.kind == "ack")
            self.db.commit()
        except Exception:
            self._recover_db()
            log.exception("DB write failed; batch left unacknowledged for retry")
            time.sleep(2)
            return False
        self.r.xack(STREAM_IN, STREAM_GROUP, *ids)
        pipe = self.r.pipeline()
        for item in live:
            pipe.publish(CHANNEL_LIVE, json.dumps(item))
        pipe.execute()
        self.publish_alerts(saved, resolved + acked)
        if groups["env"] or groups["event"] or any(a.station_id for a in alerts):
            self.publish_station_state()
        return True

    def write(self, groups) -> None:
        with self.db.cursor() as cur:
            vitals = groups["vitals"]
            if vitals:
                with cur.copy(
                    "COPY vitals (ts, animal_id, hr, spo2, body_temp, activity, steps, battery, rssi) FROM STDIN"
                ) as cp:
                    for v in vitals:
                        cp.write_row(
                            (
                                dt(v.ts),
                                v.animal_id,
                                v.hr,
                                v.spo2,
                                v.body_temp,
                                v.activity,
                                v.steps,
                                v.battery,
                                v.rssi,
                            )
                        )
                last = {}
                for v in vitals:
                    last[v.animal_id] = max(last.get(v.animal_id, 0), v.ts)
                cur.executemany(
                    "INSERT INTO animals (animal_id, last_seen) VALUES (%s, %s) "
                    "ON CONFLICT (animal_id) DO UPDATE "
                    "SET last_seen = GREATEST(animals.last_seen, EXCLUDED.last_seen)",
                    [(a, dt(t)) for a, t in last.items()],
                )
            env = groups["env"]
            if env:
                cur.executemany(
                    "INSERT INTO env_readings "
                    "(ts, station_id, temp, humidity, pressure, thi, tilt, vibration, heading, magnetic) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        (
                            dt(e.ts),
                            e.station_id,
                            e.temp,
                            e.humidity,
                            e.pressure,
                            thi(e.temp, e.humidity),
                            e.tilt,
                            e.vibration,
                            e.heading,
                            e.magnetic,
                        )
                        for e in env
                    ],
                )
                last = {}
                for e in env:
                    last[e.station_id] = max(last.get(e.station_id, 0), e.ts)
                cur.executemany(
                    "INSERT INTO stations (station_id, last_seen) VALUES (%s, %s) "
                    "ON CONFLICT (station_id) DO UPDATE "
                    "SET last_seen = GREATEST(stations.last_seen, EXCLUDED.last_seen)",
                    [(s, dt(t)) for s, t in last.items()],
                )
            if groups["event"]:
                cur.executemany(
                    "INSERT INTO station_events (ts, station_id, kind, value, detail) VALUES (%s, %s, %s, %s, %s)",
                    [(dt(ev.ts), ev.station_id, ev.kind, ev.value, ev.detail) for ev in groups["event"]],
                )
            for s in groups["rover_status"]:
                cur.execute(
                    "INSERT INTO rover_status "
                    "(ts, rover_id, mode, battery, distance_cm, blocked, left_dps, right_dps) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        dt(s.ts),
                        s.rover_id,
                        s.mode,
                        s.battery,
                        s.distance_cm,
                        s.blocked,
                        s.left_dps,
                        s.right_dps,
                    ),
                )
            rows = [
                (dt(d.ts), d.rover_id, x.label, x.confidence, *x.box, x.track_id)
                for d in groups["detections"]
                for x in d.detections
            ]
            if rows:
                cur.executemany(
                    "INSERT INTO detections (ts, rover_id, label, confidence, x1, y1, x2, y2, track_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    rows,
                )

    def insert_alerts(self, alerts: list[AlertMsg]) -> list[dict]:
        """Insert alerts in the current transaction; returns them with their DB ids."""
        saved = []
        with self.db.cursor() as cur:
            for a in alerts:
                cur.execute(
                    "INSERT INTO alerts (ts, kind, severity, message, animal_id, station_id, value, source) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (dt(a.ts), a.kind, a.severity, a.message, a.animal_id, a.station_id, a.value, a.source),
                )
                saved.append({"id": cur.fetchone()[0], **a.model_dump()})
        return saved

    def resolve_alerts(self) -> int:
        """Close DB alerts whose condition the detector saw clear (in the current transaction)."""
        done, self.detector.resolved = self.detector.resolved, []
        n = 0
        with self.db.cursor() as cur:
            for subject, kind, ts in done:
                cur.execute(
                    "UPDATE alerts SET resolved_at = %s WHERE kind = %s AND coalesce(animal_id, station_id) = %s "
                    "AND acked_at IS NULL AND resolved_at IS NULL",
                    (dt(ts), kind, subject),
                )
                n += cur.rowcount
        return n

    def ack_station(self, ev: StationEventMsg) -> int:
        """Joystick ack on a station: acknowledge its open alerts (current transaction)."""
        with self.db.cursor() as cur:
            cur.execute(
                "UPDATE alerts SET acked_at = %s, acked_by = %s "
                "WHERE station_id = %s AND acked_at IS NULL AND resolved_at IS NULL",
                (dt(ev.ts), f"{ev.station_id} joystick", ev.station_id),
            )
            if cur.rowcount:
                log.info("station %s acknowledged %d alert(s) from its joystick", ev.station_id, cur.rowcount)
            return cur.rowcount

    def publish_station_state(self) -> None:
        """Retained open-alert count per station, for the station's LED."""
        try:
            with self.db.cursor() as cur:
                cur.execute(
                    """SELECT s.station_id, count(a.id),
                              max(CASE a.severity WHEN 'critical' THEN 3 WHEN 'warning' THEN 2
                                  WHEN 'info' THEN 1 END)
                       FROM stations s LEFT JOIN alerts a ON a.station_id = s.station_id
                            AND a.acked_at IS NULL AND a.resolved_at IS NULL
                       GROUP BY s.station_id"""
                )
                rows = cur.fetchall()
            self.db.rollback()
        except psycopg.Error:
            log.exception("station state query failed")
            self._recover_db()
            return
        worst = {1: "info", 2: "warning", 3: "critical"}
        for sid, n, rank in rows:
            msg = StationStateMsg(open_alerts=n, worst=worst.get(rank))
            self.mqtt.publish(topics.barn_state(sid), msg.model_dump_json(), qos=1, retain=True)

    def publish_alerts(self, saved: list[dict], resolved: int = 0) -> None:
        """Announce alert changes after they are committed."""
        if resolved:
            self.r.publish(CHANNEL_LIVE, json.dumps({"type": "alert", "resolved": resolved}))
        if not saved:
            return
        pipe = self.r.pipeline()
        for item in saved:
            pipe.publish(CHANNEL_LIVE, json.dumps({"type": "alert", **item}))
            pipe.publish(CHANNEL_ALERTS, json.dumps(item))
        pipe.execute()
        for a in saved:
            log.info(
                "ALERT %s %s %s: %s",
                a["severity"],
                a["animal_id"] or a["station_id"],
                a["kind"],
                a["message"],
            )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="p1")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    p = Processor(args.name)

    def _stop(*_):
        p.stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    p.run()


if __name__ == "__main__":
    main()
