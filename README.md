# LMS — Livestock Monitoring System

An autonomous rover and wearable sensor collars that watch over a herd, plus a data pipeline, ML models and a live dashboard. Rebuilt from the Hack NITR 7.0 winning prototype (original code in [`legacy/`](legacy/)).

## Architecture

```
 ESP32 collars ─┐                       ┌─► processor workers ─► TimescaleDB ─► FastAPI ─► React dashboard
 Barn station ──┼─► Mosquitto (MQTT) ─► ingest ─► Redis Streams  (rules + anomaly ML)     │    (WebSocket live)
 Simulator ─────┘                                     │                                   └─► Cloudflare Tunnel
                                                      └─► alerts ─► Telegram
 Rover (Pi 4 + BrickPi3): camera ─► YOLO cow detection ─► PD follow controller ─► motors, ultrasonic safety
```

## Layout

| Folder | What |
|---|---|
| `common/` | Shared message schemas and MQTT topic names |
| `rover/` | Rover server for the Pi: drivers (real + mock), controller, safety |
| `backend/` | API, MQTT ingest, workers, alert notifier |
| `ml/` | Cow detection (YOLO), disease predictor, vitals anomaly detection |
| `simulator/` | Virtual herd and barn station publishing to MQTT |
| `firmware/` | ESP32 collar and Arduino UNO sketches |
| `barn/` | Sense HAT and serial bridge publishers (Pi) |
| `web/` | React + Vite dashboard |
| `infra/` | Service install/start scripts (WSL, no Docker), DB schema |
| `pi-tools/` | Pixy2 camera tools for the Pi |
| `legacy/` | Original hackathon code, kept for reference |

Setup instructions live in [`docs/`](docs/) as each part lands.
