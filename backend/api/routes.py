"""Herd, alerts and environment endpoints (the disease checker is public: backend/api/public.py)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api import db
from backend.api.auth import require_user
from common.schemas import dew_point

router = APIRouter(prefix="/api", tags=["herd"], dependencies=[Depends(require_user)])
OFFLINE_AFTER = "10 minutes"
SEVERITY_RANK = "CASE severity WHEN 'critical' THEN 3 WHEN 'warning' THEN 2 ELSE 1 END"


def bucket_seconds(hours: float, points: int = 300) -> int:
    """Bucket width so a chart gets about `points` points, at least one minute."""
    return max(60, int(hours * 3600 / points))


@router.get("/summary")
def summary() -> dict:
    herd = db.one(
        f"""SELECT count(*) AS animals,
                   count(*) FILTER (WHERE last_seen > now() - interval '{OFFLINE_AFTER}') AS online
            FROM animals"""
    )
    open_alerts = db.rows(
        "SELECT severity, count(*) AS n FROM alerts WHERE acked_at IS NULL AND resolved_at IS NULL GROUP BY severity"
    )
    env = db.rows(
        """SELECT DISTINCT ON (station_id) station_id, extract(epoch FROM ts) AS ts,
                  temp, humidity, pressure, thi
           FROM env_readings WHERE ts > now() - interval '1 hour' ORDER BY station_id, ts DESC"""
    )
    return {**herd, "open_alerts": {r["severity"]: r["n"] for r in open_alerts}, "environment": env}


@router.get("/animals")
def animals() -> list[dict]:
    return db.rows(
        f"""
        WITH latest AS (
            SELECT DISTINCT ON (animal_id) animal_id, ts, hr, spo2, body_temp, activity, battery
            FROM vitals WHERE ts > now() - interval '6 hours' ORDER BY animal_id, ts DESC
        ), worst AS (
            SELECT animal_id, max({SEVERITY_RANK}) AS rank, count(*) AS open_alerts
            FROM alerts WHERE acked_at IS NULL AND resolved_at IS NULL AND animal_id IS NOT NULL GROUP BY animal_id
        )
        SELECT a.animal_id, a.name, a.breed,
               extract(epoch FROM a.last_seen) AS last_seen,
               a.last_seen > now() - interval '{OFFLINE_AFTER}' AS online,
               l.hr, l.spo2, l.body_temp, l.activity, l.battery,
               CASE w.rank WHEN 3 THEN 'critical' WHEN 2 THEN 'warning' WHEN 1 THEN 'info' ELSE 'ok' END
                   AS status,
               coalesce(w.open_alerts, 0) AS open_alerts
        FROM animals a
        LEFT JOIN latest l USING (animal_id)
        LEFT JOIN worst w USING (animal_id)
        ORDER BY coalesce(w.rank, 0) DESC, a.animal_id
        """
    )


@router.get("/animals/{animal_id}")
def animal(animal_id: str) -> dict:
    info = db.one(
        f"""SELECT animal_id, name, breed, sex, birth_date, notes,
                   extract(epoch FROM first_seen) AS first_seen, extract(epoch FROM last_seen) AS last_seen,
                   last_seen > now() - interval '{OFFLINE_AFTER}' AS online
            FROM animals WHERE animal_id = %s""",
        (animal_id,),
    )
    if info is None:
        raise HTTPException(404, "unknown animal")
    latest = db.one(
        """SELECT extract(epoch FROM ts) AS ts, hr, spo2, body_temp, activity, steps, battery, rssi
           FROM vitals WHERE animal_id = %s ORDER BY ts DESC LIMIT 1""",
        (animal_id,),
    )
    alerts = db.rows(
        """SELECT id, extract(epoch FROM ts) AS ts, kind, severity, message, value, source
           FROM alerts WHERE animal_id = %s AND acked_at IS NULL AND resolved_at IS NULL ORDER BY ts DESC""",
        (animal_id,),
    )
    return {**info, "latest": latest, "open_alerts": alerts}


@router.get("/animals/{animal_id}/history")
def animal_history(animal_id: str, hours: float = Query(24, gt=0, le=24 * 30)) -> dict:
    width = bucket_seconds(hours)
    points = db.rows(
        """SELECT extract(epoch FROM time_bucket(make_interval(secs => %s), ts)) AS ts,
                  avg(hr) AS hr, avg(spo2) AS spo2, avg(body_temp) AS body_temp,
                  avg(activity) AS activity, sum(steps) AS steps
           FROM vitals
           WHERE animal_id = %s AND ts > now() - make_interval(secs => %s)
           GROUP BY 1 ORDER BY 1""",
        (width, animal_id, hours * 3600),
    )
    for p in points:
        for k in ("hr", "spo2", "body_temp", "activity"):
            if p[k] is not None:
                p[k] = round(float(p[k]), 3)
    return {"animal_id": animal_id, "bucket_seconds": width, "points": points}


class AnimalUpdate(BaseModel):
    name: str | None = Field(None, max_length=60)
    breed: str | None = Field(None, max_length=60)
    sex: str | None = Field(None, pattern="^[FM]$")
    notes: str | None = Field(None, max_length=1000)


@router.patch("/animals/{animal_id}")
def update_animal(animal_id: str, body: AnimalUpdate) -> dict:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "nothing to update")
    sets = ", ".join(f"{k} = %({k})s" for k in fields)
    with db.conn() as c:
        cur = c.execute(f"UPDATE animals SET {sets} WHERE animal_id = %(id)s", {**fields, "id": animal_id})
        if cur.rowcount == 0:
            raise HTTPException(404, "unknown animal")
    return animal(animal_id)


@router.get("/alerts")
def alerts(
    open_only: bool = Query(True, alias="open"),
    animal_id: str | None = None,
    severity: str | None = Query(None, pattern="^(info|warning|critical)$"),
    limit: int = Query(200, ge=1, le=2000),
) -> list[dict]:
    where, params = ["true"], []
    if open_only:
        where.append("acked_at IS NULL AND resolved_at IS NULL")
    if animal_id:
        where.append("animal_id = %s")
        params.append(animal_id)
    if severity:
        where.append("severity = %s")
        params.append(severity)
    return db.rows(
        f"""SELECT id, extract(epoch FROM ts) AS ts, kind, severity, message, animal_id, station_id, value,
                   source, extract(epoch FROM acked_at) AS acked_at, acked_by,
                   extract(epoch FROM resolved_at) AS resolved_at
            FROM alerts WHERE {" AND ".join(where)} ORDER BY {SEVERITY_RANK} DESC, ts DESC LIMIT %s""",
        (*params, limit),
    )


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, user: str = Depends(require_user)) -> dict:
    row = db.one(
        """UPDATE alerts SET acked_at = now(), acked_by = %s
           WHERE id = %s AND acked_at IS NULL RETURNING id""",
        (user, alert_id),
    )
    if row is None:
        raise HTTPException(404, "no open alert with that id")
    return {"acked": alert_id}


@router.get("/env")
def environment(station_id: str | None = None, hours: float = Query(24, gt=0, le=24 * 30)) -> dict:
    width = bucket_seconds(hours)
    points = db.rows(
        """SELECT station_id, extract(epoch FROM time_bucket(make_interval(secs => %s), ts)) AS ts,
                  round(avg(temp)::numeric, 2) AS temp, round(avg(humidity)::numeric, 1) AS humidity,
                  round(avg(pressure)::numeric, 1) AS pressure, round(avg(thi)::numeric, 1) AS thi,
                  round(avg(tilt)::numeric, 1) AS tilt, round(max(vibration)::numeric, 3) AS vibration
           FROM env_readings
           WHERE ts > now() - make_interval(secs => %s) AND (%s::text IS NULL OR station_id = %s)
           GROUP BY 1, 2 ORDER BY 2""",
        (width, hours * 3600, station_id, station_id),
    )
    for p in points:
        p["dew_point"] = dew_point(_num(p["temp"]), _num(p["humidity"]))
    return {"bucket_seconds": width, "points": points}


def _num(v) -> float | None:
    return None if v is None else float(v)


@router.get("/stations")
def stations() -> list[dict]:
    """Every barn station with its latest reading, 3 h pressure trend, open alerts and last events."""
    rows = db.rows(
        f"""
        WITH latest AS (
            SELECT DISTINCT ON (station_id) station_id, extract(epoch FROM ts) AS ts, temp, humidity,
                   pressure, thi, tilt, vibration, heading, magnetic
            FROM env_readings WHERE ts > now() - interval '7 days' ORDER BY station_id, ts DESC
        ), past AS (
            SELECT DISTINCT ON (station_id) station_id, pressure AS pressure_3h
            FROM env_readings
            WHERE ts BETWEEN now() - interval '3 hours 15 minutes' AND now() - interval '2 hours 45 minutes'
                  AND pressure IS NOT NULL
            ORDER BY station_id, ts
        ), open_alerts AS (
            SELECT station_id, count(*) AS n FROM alerts
            WHERE station_id IS NOT NULL AND acked_at IS NULL AND resolved_at IS NULL GROUP BY station_id
        ), hello AS (
            SELECT DISTINCT ON (station_id) station_id, detail AS hello
            FROM station_events WHERE kind = 'hello' ORDER BY station_id, ts DESC
        ), gate AS (
            SELECT DISTINCT ON (station_id) station_id, kind AS gate
            FROM station_events WHERE kind IN ('gate_open', 'gate_closed') ORDER BY station_id, ts DESC
        )
        SELECT s.station_id, s.name, extract(epoch FROM s.last_seen) AS last_seen,
               s.last_seen > now() - interval '{OFFLINE_AFTER}' AS online,
               l.ts, l.temp, l.humidity, l.pressure, l.thi, l.tilt, l.vibration, l.heading, l.magnetic,
               round((l.pressure - p.pressure_3h)::numeric, 1) AS pressure_trend_3h,
               coalesce(o.n, 0) AS open_alerts, h.hello, g.gate
        FROM stations s
        LEFT JOIN latest l USING (station_id)
        LEFT JOIN past p USING (station_id)
        LEFT JOIN open_alerts o USING (station_id)
        LEFT JOIN hello h USING (station_id)
        LEFT JOIN gate g USING (station_id)
        ORDER BY s.station_id
        """
    )
    for r in rows:
        r["dew_point"] = dew_point(_num(r["temp"]), _num(r["humidity"]))
        r["pressure_trend_3h"] = _num(r["pressure_trend_3h"])
    return rows


@router.get("/stations/events")
def station_events(
    station_id: str | None = None,
    hours: float = Query(24, gt=0, le=24 * 30),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    return db.rows(
        """SELECT extract(epoch FROM ts) AS ts, station_id, kind, value, detail FROM station_events
           WHERE ts > now() - make_interval(secs => %s) AND (%s::text IS NULL OR station_id = %s)
           ORDER BY ts DESC LIMIT %s""",
        (hours * 3600, station_id, station_id, limit),
    )
