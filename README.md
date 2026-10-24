# JU TechFest — LMS (Livestock Monitoring System)

An autonomous rover, wearable sensor collars and a barn weather station that watch over a herd, backed by a live data pipeline, ML models and a web dashboard. Rebuilt into a full working system from our **Hack NITR 7.0 winning (1st place)** prototype; the original hackathon code is kept in [`legacy/`](legacy/).

```
 Collars (ESP32 / ESP8266 / UNO) ─┐                       ┌─► processor (TimescaleDB, anomaly detection, alerts) ─► FastAPI ─► React dashboard
 Barn station (Pi + Sense HAT) ───┼─► Mosquitto (MQTT) ─► ingest ─► Redis Streams                                        │   (live WebSocket)
 Simulator (virtual herd) ────────┘                                     └─► Telegram alerts                               └─► Cloudflare Tunnel
 Rover (Pi 4 + BrickPi3): Pi Camera ─► YOLO11n detection ─► PD follow controller ─► LEGO EV3 motors, with ultrasonic safety
```

## What it does

- **Smart collars** read heart rate / SpO₂ (MAX30102, MAX30100 or DFRobot SEN0344, auto-detected), motion (MPU6050) and temperature, and publish over Wi-Fi/MQTT, ESP-NOW or USB serial. Wi-Fi and IDs are set over serial — no reflashing.
- **Health monitoring** flags fever, lameness, estrus, low activity and offline collars per animal, and sends alerts to the dashboard and Telegram.
- **Barn station** (Raspberry Pi + Sense HAT): temperature, humidity, pressure, THI, dew point, storm risk, heat stress, plus knock / tilt / gate-open events and an LED + joystick menu on the device.
- **Rover** follows cows (also sheep/horses), stops for obstacles (ultrasonic, 20 cm) and for people close to the camera, streams live video, and can be driven from the dashboard.
- **Disease checker** — free public page, no login: 60 common diseases of cows/buffaloes, goats, sheep, dogs and cats, in **English / Hindi / Hinglish**. Tick 2–3 signs and get the likely diseases, urgency, what to do now and prevention.
- **Dashboard**: herd overview, per-animal charts, alerts, barn environment, rover control + video, disease checker.
- **Zero-setup on the field**: Pis broadcast their IP (and Telegram it), the laptop auto-updates its config, and the dashboard link is sent on Telegram (`/link`).

## Results

- **Health alerts** (simulated herd, 50 cows × 21 days): fever caught 98% (median 1.5 h), lameness 95%, estrus 91%, offline collars 100%; zero false fever alarms and zero alarms from sensor glitches. [Details](docs/ml.md)
- **Disease suggestions** with only 2–3 signs ticked: right disease in the top 3 for 98–100% of cases (hackathon model: 51%).
- **Cow detection** (fine-tuned YOLO11n): mAP50 0.726 vs 0.631 for the stock model; ~10 ms/frame on a laptop CPU, ~121 ms (~8 fps) on the Pi 4 CPU. YOLO11n beat MobileNet-SSD on near cows (AP50 0.80 vs 0.60) and people (0.82 vs 0.61).
- **Rover**: motors, ultrasonic, Pi Camera (30 fps) and BrickPi3 tested on real hardware; dashboard → rover command latency 38 ms median.
- **Barn station** running on a real Pi + Sense HAT, publishing to the dashboard every 30 s.

## Hardware

| Part | Role |
|---|---|
| Raspberry Pi 4B + BrickPi3 | Rover brain, drives 2× LEGO EV3 large motors (tracks) |
| EV3 ultrasonic sensor | Obstacle stop |
| Pi Camera (ov5647) | Video + detection (Pixy2 supported too) |
| Raspberry Pi 4B + Sense HAT | Barn weather station |
| ESP32 / ESP8266 / Arduino UNO | Collar boards |
| MAX30102 / MAX30100, MPU6050, DHT22, OLED | Collar sensors |

3D-printable collar enclosures: [`All_Editable_CAD_Models/`](All_Editable_CAD_Models/). Project report: [`LMS.pdf`](LMS.pdf).

## Tech stack

Python (FastAPI, OpenCV, ONNX / NCNN, scikit-learn, Ultralytics YOLO11) · PostgreSQL + TimescaleDB · Mosquitto MQTT · Redis Streams · React + Vite + TypeScript · PlatformIO (ESP32 / ESP8266 / UNO) · Telegram Bot API · Cloudflare Tunnel

## Run it

```powershell
.\infra\run_all.ps1 -Simulator -MockRover    # then open http://localhost:8000
```

No hardware needed: the simulator publishes a virtual herd and barn, and the mock rover streams a synthetic camera.

Full setup: [docs/setup.md](docs/setup.md) · Design: [docs/architecture.md](docs/architecture.md) · ML: [docs/ml.md](docs/ml.md) · Collar: [docs/collar.md](docs/collar.md) · Barn: [docs/barn.md](docs/barn.md) · Hosting: [docs/hosting.md](docs/hosting.md) · Demo: [docs/demo.md](docs/demo.md) · Real deployment: [docs/deployment.md](docs/deployment.md) · Autostart: [docs/autostart.md](docs/autostart.md) · Plain-language guide (Hinglish): [docs/GUIDE.md](docs/GUIDE.md)

## Layout

| Folder | What |
|---|---|
| `common/` | Shared message schemas and MQTT topic names |
| `backend/` | MQTT ingest, processor, Telegram notifier, FastAPI API |
| `ml/` | Disease model + knowledge base, anomaly detector + evaluation, YOLO detector |
| `simulator/` | Virtual herd and barn station publishing to MQTT, labelled datasets |
| `rover/` | Rover server for the Pi: drivers (real + mock), vision, safety, controller |
| `web/` | React + Vite dashboard |
| `firmware/` | ESP32 / ESP8266 collars, ESP-NOW gateway, Arduino UNO bridge (PlatformIO) |
| `barn/` | Sense HAT station and UNO serial publishers for the Pi |
| `infra/` | WSL services, DB schema, run/stop/tunnel/autostart scripts, Pi installers and finder |
| `pi-tools/` | Drive test and Pixy2 camera streaming for the Pi |
| `tests/` | pytest suite (`.venv\Scripts\python -m pytest`) |
| `legacy/` | Original Hack NITR 7.0 code, kept for reference |
