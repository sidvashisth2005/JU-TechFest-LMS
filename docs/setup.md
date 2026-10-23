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

## 5. Raspberry Pi (rover)

Raspberry Pi OS 64-bit (Trixie). Packages: `python3-opencv python3-picamera2 python3-sense-hat python3-serial python3-spidev i2c-tools`; SPI and I2C enabled; venv with `--system-site-packages`; BrickPi3 from the DexterInd repo. Details and the Pixy2 build are in `CLAUDE.md`.

```bash
~/lms-venv/bin/pip install -r rover/requirements.txt
~/lms-venv/bin/python -m rover.server --camera picamera2 --detector yolo:ml/detection/models/cow.onnx --mqtt <laptop-ip>
```

Then set `ROVER_URL=http://<pi-ip>:8080` in the laptop's `.env`. For devices on the LAN to reach the laptop's MQTT broker, allow inbound TCP 1883 in Windows Firewall (and Hyper-V firewall for WSL).

First drive on hardware: lift the tracks, try Manual forward/left/right. If left/right are swapped run with `--turn-sign -1`; if forward goes backward, set `drive_sign = -1` in `rover/config.py`.

## 6. Collars

- ESP32 collar: `firmware/collar_esp32` — copy `include/lms_config.example.h` to `include/lms_config.h`, fill in Wi-Fi/MQTT/animal id, `pio run -t upload`.
- UNO prototype: `firmware/uno_bridge` (`pio run -t upload`), then on the Pi `python -m barn.serial_bridge --port /dev/ttyACM0`.
- Sense HAT barn station: `python -m barn.sensehat_pub --station barn1`.
