-- LMS database schema (PostgreSQL 16 + TimescaleDB). Idempotent: safe to run again.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------- registry ----------
CREATE TABLE IF NOT EXISTS animals (
    animal_id   text PRIMARY KEY,
    name        text,
    breed       text,
    sex         text CHECK (sex IN ('F', 'M')),
    birth_date  date,
    notes       text,
    first_seen  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz
);

CREATE TABLE IF NOT EXISTS stations (
    station_id  text PRIMARY KEY,
    name        text,
    location    text,
    first_seen  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz
);

-- ---------- time series ----------
CREATE TABLE IF NOT EXISTS vitals (
    ts          timestamptz NOT NULL,
    animal_id   text        NOT NULL,
    hr          real,
    spo2        real,
    body_temp   real,
    activity    real,
    steps       integer,
    battery     real,
    rssi        integer
);
SELECT create_hypertable('vitals', 'ts', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');
CREATE INDEX IF NOT EXISTS vitals_animal_ts ON vitals (animal_id, ts DESC);

CREATE TABLE IF NOT EXISTS env_readings (
    ts          timestamptz NOT NULL,
    station_id  text        NOT NULL,
    temp        real,
    humidity    real,
    pressure    real,
    thi         real
);
SELECT create_hypertable('env_readings', 'ts', if_not_exists => TRUE, chunk_time_interval => INTERVAL '7 days');
CREATE INDEX IF NOT EXISTS env_station_ts ON env_readings (station_id, ts DESC);

CREATE TABLE IF NOT EXISTS rover_status (
    ts          timestamptz NOT NULL,
    rover_id    text        NOT NULL,
    mode        text,
    battery     real,
    distance_cm real,
    blocked     boolean,
    left_dps    real,
    right_dps   real
);
SELECT create_hypertable('rover_status', 'ts', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');

CREATE TABLE IF NOT EXISTS detections (
    ts          timestamptz NOT NULL,
    rover_id    text        NOT NULL,
    label       text        NOT NULL,
    confidence  real,
    x1 real, y1 real, x2 real, y2 real,
    track_id    integer
);
SELECT create_hypertable('detections', 'ts', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');

-- ---------- alerts ----------
CREATE TABLE IF NOT EXISTS alerts (
    id          bigserial PRIMARY KEY,
    ts          timestamptz NOT NULL,
    kind        text        NOT NULL,
    severity    text        NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    message     text        NOT NULL,
    animal_id   text,
    station_id  text,
    value       real,
    source      text        NOT NULL DEFAULT 'rule',
    acked_at    timestamptz,
    acked_by    text
);
CREATE INDEX IF NOT EXISTS alerts_ts ON alerts (ts DESC);
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS resolved_at timestamptz;  -- condition cleared by itself
DROP INDEX IF EXISTS alerts_open;
CREATE INDEX alerts_open ON alerts (animal_id, kind) WHERE acked_at IS NULL AND resolved_at IS NULL;

-- ---------- rollups for charts ----------
CREATE MATERIALIZED VIEW IF NOT EXISTS vitals_1m
WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '1 minute', ts) AS bucket, animal_id,
       avg(hr) AS hr, avg(spo2) AS spo2, avg(body_temp) AS body_temp,
       avg(activity) AS activity, sum(steps) AS steps, count(*) AS n
FROM vitals GROUP BY bucket, animal_id
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS vitals_1h
WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '1 hour', ts) AS bucket, animal_id,
       avg(hr) AS hr, min(hr) AS hr_min, max(hr) AS hr_max,
       avg(body_temp) AS body_temp, max(body_temp) AS body_temp_max,
       avg(activity) AS activity, sum(steps) AS steps, count(*) AS n
FROM vitals GROUP BY bucket, animal_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('vitals_1m', start_offset => INTERVAL '2 hours',
       end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('vitals_1h', start_offset => INTERVAL '3 days',
       end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '30 minutes', if_not_exists => TRUE);

-- keep raw readings 90 days; rollups stay
SELECT add_retention_policy('vitals', INTERVAL '90 days', if_not_exists => TRUE);
SELECT add_retention_policy('rover_status', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('detections', INTERVAL '30 days', if_not_exists => TRUE);
