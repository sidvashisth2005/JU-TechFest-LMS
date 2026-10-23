# Setup

Everything runs on one Windows laptop with WSL (no Docker), plus the Raspberry Pi on the rover. Keep all of it on the D: drive.

## 1. Laptop: backend services (once)

```powershell
# from the repo root, in PowerShell
copy .env.example .env            # then set real passwords in .env
wsl -d Ubuntu-24.04 -u root -e bash /mnt/d/Project/LMS/infra/wsl_install.sh   # Mosquitto, Redis, PostgreSQL 16, TimescaleDB
wsl -d Ubuntu-24.04 -u root -e bash /mnt/d/Project/LMS/infra/setup.sh         # DB user + schema, MQTT login (safe to rerun)
```

`%USERPROFILE%\.wslconfig` must contain `networkingMode=mirrored` under `[wsl2]` so Windows `localhost` reaches the WSL services.

## 2. Laptop: Python and the dashboard (once)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt -r ml\requirements.txt
.venv\Scripts\python -m ml.disease.train          # writes ml/disease/artifacts/
cd web; npm ci; npm run build; cd ..
```

## 3. Run

```powershell
.\infra\run_all.ps1 -Simulator -MockRover   # everything, with 50 virtual cows and a laptop rover
.\infra\stop_all.ps1
```

Open http://localhost:8000 and sign in with `API_ADMIN_USER` / `API_ADMIN_PASSWORD` from `.env`. Health check: `.venv\Scripts\python infra\check_services.py`. Logs: `logs\*.log`.

For dashboard development with hot reload: `cd web; npm run dev` (http://localhost:5173, proxies the API).

## 4. Telegram alerts

Create a bot with @BotFather, put the token in `.env` as `TELEGRAM_BOT_TOKEN`, message the bot once, and set `TELEGRAM_CHAT_ID` (the chat id is in `https://api.telegram.org/bot<TOKEN>/getUpdates`). Warning and critical alerts are sent; each animal+kind at most once per 3 hours.

## 5. Raspberry Pi (rover + barn sensors)

Raspberry Pi OS 64-bit (Trixie). Packages: `python3-opencv python3-picamera2 python3-sense-hat python3-serial python3-spidev i2c-tools`. SPI and I2C must be enabled. Make the venv with `python3 -m venv --system-site-packages ~/lms-venv` and install BrickPi3 from the DexterInd repo. Details and the Pixy2 build are in `CLAUDE.md`.

Deploy from the laptop (Git Bash, repo root). This copies the committed code, installs the Python packages, creates `~/lms-rover/.env` the first time (MQTT and rover token taken from the laptop `.env`), and installs the systemd services:

```bash
bash infra/pi/deploy.sh                       # PI=pi@<ip> bash infra/pi/deploy.sh if the IP changed
ssh pi@<pi-ip> "~/lms-rover/infra/pi/lms-pi.sh start rover"      # rover | sensehat | uno | pixy | all
ssh pi@<pi-ip> "~/lms-rover/infra/pi/lms-pi.sh status"
ssh pi@<pi-ip> "~/lms-rover/infra/pi/lms-pi.sh enable all"       # start at every boot
```

| Service | What it runs | Settings in `~/lms-rover/.env` |
|---|---|---|
| `lms-rover` | `rover.server` on :8080 (camera, detector, motors, ultrasonic, safety) | `ROVER_CAMERA`, `ROVER_DETECTOR`, `ROVER_TOKEN`, `ROVER_TURN_SIGN`, `ROVER_DRIVE_SIGN` |
| `lms-sensehat` | `barn.sensehat_pub` (temperature, humidity, pressure → MQTT) | `BARN_STATION`, `BARN_INTERVAL` |
| `lms-uno-bridge` | `barn.serial_bridge` (collar or ESP-NOW gateway on USB serial → MQTT; `UNO_PORT=auto` finds the board) | `UNO_PORT`, `UNO_ANIMAL` |
| `lms-pixy-stream` | `pi-tools/pixy_stream.py` on :8000 (camera test page; cannot run with the rover) | — |

The laptop's `.env` needs `ROVER_URL=http://<pi-ip>:8080` and the same `ROVER_TOKEN` as the Pi. For the Pi and the collars to reach the laptop's MQTT broker, allow inbound TCP 1883 in Windows Firewall, and in the Hyper-V firewall for WSL (admin PowerShell):

```powershell
New-NetFirewallRule -DisplayName "LMS MQTT" -Direction Inbound -Protocol TCP -LocalPort 1883 -Action Allow
Set-NetFirewallHyperVVMSetting -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -DefaultInboundAction Allow
```

The first drive on hardware must be done with the tracks lifted. Try Manual forward/left/right from the dashboard Rover page. If left and right are swapped, set `ROVER_TURN_SIGN=-1`. If forward drives backward, set `ROVER_DRIVE_SIGN=-1`. Restart the rover after either change.

YOLO on the Pi: `ROVER_DETECTOR=yolo:ml/detection/models/coco_yolo11n.onnx` (OpenCV, ~8 fps measured), or `ncnn:ml/detection/models/coco_yolo11n_ncnn_model` (needs `pip install ncnn`; usually faster on ARM, so benchmark both).

## 6. Collars

Step-by-step for the hackathon day (wiring, flashing, serial setup, backups): **[docs/collar.md](collar.md)**.

- **ESP32 collar** (`firmware/collar_esp32`, main). It works with any of 4 pulse sensors: MAX30102, MAX30100 and DFRobot SEN0344 are auto-detected on I2C, and an analog pulse sensor is set with `ppg analog`. Any MPU6050-family accelerometer works, plus an optional DS18B20. Flash with `pio run -e wifi -t upload`, then set Wi-Fi, MQTT and the animal id over serial (`pio device monitor`, type `help`). No reflash is needed when the network changes. Modes:
  - `wifi` / `wifi_c3`: always on, a reading every 5 s. Use this for demos.
  - `wifi_sleep`: wakes every 60 s, measures for 6 s, sends over Wi-Fi, then deep sleeps.
  - `espnow` / `espnow_c3`: same as `wifi_sleep`, but sends over ESP-NOW to the gateway. Longest battery life and no router needed.

  Every reading is also printed on USB serial, so a collar on a cable works without Wi-Fi.
- **ESP-NOW gateway** (`firmware/gateway_espnow`, any ESP32 on the Pi's USB): `pio run -t upload`. Then start the `uno` service on the Pi; it forwards every collar.
- **UNO backup** (`firmware/uno_bridge`): one env per pulse sensor, `uno` / `uno_max30100` / `uno_dfrobot` / `uno_analog`. Plug it into the laptop and run `.\infra\run_all.ps1 -Collar auto`, or plug it into the Pi and use the `uno` service.
- **Sense HAT barn station**: the `sensehat` service (`python -m barn.sensehat_pub --station barn1`).

## 7. Tests

```powershell
.venv\Scripts\python -m pytest            # unit + API tests; DB tests skip when services are down
$env:LMS_E2E=1; .venv\Scripts\python -m pytest tests\test_e2e.py -v   # with run_all.ps1 running: MQTT -> DB -> API
.venv\Scripts\ruff check .
```
