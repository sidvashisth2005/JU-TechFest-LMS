# Architecture

```
 ESP32 collars ──┐
 UNO + serial ───┤  MQTT (Mosquitto, auth)          Redis Stream lms:in
 Sense HAT ──────┼──────────────────────► ingest ─────────────────────► processor ──► TimescaleDB
 Simulator ──────┤   lms/collar/<id>/vitals   validates with           batches writes,
 Rover ──────────┘   lms/barn/<id>/env        common/schemas.py        runs ml/anomaly detector,
                     lms/rover/<id>/...       bad msgs -> lms:dead     stores + resolves alerts
                                                                              │
                                              Redis pub/sub lms:live ◄────────┤
                                              Redis pub/sub lms:alerts ◄──────┘
                                                   │            │
                         React dashboard ◄── FastAPI API     notifier ──► Telegram
                         (web/)   WebSocket /ws/live, REST /api/*, rover proxy
                                       │
                                       └──► rover server on the Pi (HTTP :8080)
```

## Why these pieces

| Choice | Reason |
|---|---|
| MQTT | Light enough for an ESP32, keeps queued messages for a restarting subscriber (ingest uses a persistent session, QoS 1). |
| Redis Streams between ingest and processor | Decouples receiving from processing; a slow database never makes the broker drop messages; unacknowledged batches are retried after a crash. |
| TimescaleDB (PostgreSQL) | Sensor data is time series: hypertables, `time_bucket` for charts, retention policies. Runs in WSL and on a Pi 4 (MongoDB 5+ does not run on a Pi 4 CPU). |
| One shared schema module (`common/`) | Firmware, simulator, edge publishers and backend agree on one message format; a missing sensor is `null`, never a substitute value. |
| API as the only public entry point | One login; the rover and the database are never exposed directly. The rover video and controls go through `/api/rover/*`. |

## Detection logic (ml/anomaly/detector.py)

1. Median filter over the last 5 readings: one bad sample never alarms.
2. Temperature and heart rate compared with the herd median at the same moment: heat waves move the whole herd and do not look like fever.
3. Activity compared with each animal's own normal for that hour of day, then divided by the herd's current ratio: lameness lowers one cow, heat lowers everyone.
4. Conditions must persist (fever 20 min, tachycardia 30 min) and alerts are not repeated within a cooldown; when a condition clears, the alert is marked resolved.
5. Collar offline = silent for 10 min while the rest of the herd keeps reporting (a whole-herd gap is a gateway problem, not 50 broken collars).
6. Barn heat stress from the temperature-humidity index (THI 72 / 79 / 89), with hysteresis.

## Rover (rover/)

Control loop at 15 Hz: camera frame → detector (green marker or YOLO cow model) → IoU tracker → controller (manual with 0.5 s watchdog, or PD follow) → safety filter (obstacle < 20 cm (ROVER_STOP_CM) blocks forward motion; "no echo" right after a close reading counts as blocked; battery < 9 V stops) → BrickPi3 motors. Every part has a mock so the full loop runs on a laptop.
