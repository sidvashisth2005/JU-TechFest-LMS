# LMS — Livestock Monitoring System

An autonomous rover and wearable sensor collars that watch over a herd, plus a data pipeline, ML models and a live dashboard. Rebuilt from the Hack NITR 7.0 winning prototype (original code in [`legacy/`](legacy/)).

```
 ESP32 collars ─┐                       ┌─► processor (TimescaleDB, anomaly detection, alerts) ─► FastAPI ─► React dashboard
 Barn station ──┼─► Mosquitto (MQTT) ─► ingest ─► Redis Streams                                        │   (live WebSocket)
 Simulator ─────┘                                     └─► Telegram alerts                               └─► Cloudflare Tunnel
 Rover (Pi 4 + BrickPi3): camera ─► cow detection ─► PD follow controller ─► motors, with ultrasonic safety
```

## Results so far

- **Health alerts** (simulated herd, 50 cows × 21 days): fever caught 98% (median 1.5 h), lameness 95%, estrus 91%, offline collars 100%; zero false fever alarms and zero alarms from sensor glitches. [Details](docs/ml.md)
- **Disease suggestions** with only 2–3 symptoms ticked: right disease in the top 3 for 97.8% of cases (hackathon model: 51%).
- **Rover**: follow mode and obstacle stop verified end to end with simulated hardware; hardware tests of motors, ultrasonic and camera passed on the Pi.

## Run it

```powershell
.\infra\run_all.ps1 -Simulator -MockRover    # then open http://localhost:8000
```

Full setup: [docs/setup.md](docs/setup.md) · Design: [docs/architecture.md](docs/architecture.md) · ML: [docs/ml.md](docs/ml.md) · Hosting: [docs/hosting.md](docs/hosting.md)

## Layout

| Folder | What |
|---|---|
| `common/` | Shared message schemas and MQTT topic names |
| `backend/` | MQTT ingest, processor, Telegram notifier, FastAPI API |
| `ml/` | Disease model, anomaly detector + evaluation, YOLO cow detector |
| `simulator/` | Virtual herd and barn station publishing to MQTT, labelled datasets |
| `rover/` | Rover server for the Pi: drivers (real + mock), vision, safety, controller |
| `web/` | React + Vite dashboard |
| `firmware/` | ESP32 collar and Arduino UNO sketches (PlatformIO) |
| `barn/` | Sense HAT and UNO serial publishers for the Pi |
| `infra/` | WSL service install/start, DB schema, run/stop/tunnel scripts |
| `pi-tools/` | Pixy2 camera streaming for the Pi |
| `tests/` | pytest suite (`.venv\Scripts\python -m pytest`) |
| `legacy/` | Original hackathon code, kept for reference |
