# AGENTS.md — instructions for coding agents (Codex, Claude Code, …)

LMS = Livestock Monitoring System. Includes a rover (Raspberry Pi 4B + BrickPi3 + LEGO EV3 motors + EV3 ultrasonic + Pixy2/Pi camera, YOLO cow following), cattle collars (ESP32/UNO + MAX30102 + MPU6050 + DS18B20), a Sense HAT barn station, an MQTT → Redis → TimescaleDB pipeline with anomaly alerts and Telegram, a FastAPI backend, and a React dashboard. Owner: Siddhant (GitHub `sidvashisth2005`, private repo `lms-rover`). Full history and hardware notes: `CLAUDE.md`. Plain-language walkthrough: `docs/GUIDE.md`.

## How to talk to the user
- Reply in **Hinglish** (Hindi + English, Roman script), short, one step at a time.
- When a step needs a physical action (plug a cable, power on, lift the rover), **stop, ask the user to do it, wait for "done"**.

## Machine and paths
- Windows 11 laptop, repo at `D:\Project\LMS`. Shells available: PowerShell and Git Bash.
- **Everything goes on D:** (C: has ~10 GB free). Caches: `PIP_CACHE_DIR=D:\DevCache\pip`, npm cache `D:\DevCache\npm-cache`, `PLATFORMIO_CORE_DIR=D:\DevCache\platformio`, `PLAYWRIGHT_BROWSERS_PATH=D:\DevCache\ms-playwright`. Never install big things to C:.
- Python venv: `.venv` (Python 3.13) at the repo root. Always use `.venv\Scripts\python`.
- Backend services (Mosquitto, Redis, PostgreSQL 16 + TimescaleDB) run inside **WSL Ubuntu-24.04** as root with systemd, no Docker. WSL disk is on D:. `.wslconfig` uses `networkingMode=mirrored`, so Windows `127.0.0.1` reaches them.
- Use `127.0.0.1`, not `localhost` (`localhost` resolves to IPv6 first on Windows and can stall).
- From Git Bash, calls into WSL need `MSYS_NO_PATHCONV=1`, or `/mnt/d/...` paths get rewritten.

## Run things (laptop)
```powershell
.\infra\start_services.ps1                     # WSL services + keepalive (WSL stops idle distros otherwise)
.\infra\run_all.ps1 -Simulator -MockRover      # services + ingest + processor + notifier + API (+50 sim cows, +laptop rover)
.\infra\run_all.ps1 -Simulator -Tunnel         # demo with real Pi rover and public https link
.\infra\stop_all.ps1                           # stops everything (also WSL services)
.venv\Scripts\python infra\check_services.py   # health check
```
- Dashboard: http://127.0.0.1:8000 (login from `.env`: `API_ADMIN_USER` / `API_ADMIN_PASSWORD`). Logs: `logs\<name>.log`.
- Each part runs under `python -m backend.supervise <name> -- <args>`, which restarts it on crash.
- Single parts by hand: `python -m backend.workers.ingest|processor|notifier`, `uvicorn backend.api.main:app --port 8000`, `python -m simulator.run live --backfill-hours 48 --demo`, `python -m rover.server --mock --camera synthetic --port 8080`.
- Dashboard source: `cd web; npm ci; npm run dev` (hot reload :5173), `npm run build` (served by the API from `web/dist`).

## Test and lint (run before every commit)
```powershell
.venv\Scripts\ruff check . ; .venv\Scripts\ruff format --check .
.venv\Scripts\python -m pytest -q                       # ~45 tests; DB tests skip if services are down
$env:LMS_E2E=1; .venv\Scripts\python -m pytest tests\test_e2e.py -v   # needs run_all.ps1 running
cd firmware\collar_esp32; ..\..\.venv\Scripts\pio run   # all 5 collar envs; also firmware\uno_bridge (4 envs), firmware\gateway_espnow
# pio lives in .venv; set PLATFORMIO_CORE_DIR=D:\DevCache\platformio if the shell doesn't have it
```
CI (`.github/workflows/ci.yml`) runs ruff, pytest (after `python -m ml.disease.train`), and `npm run build`.

## Raspberry Pi (rover + barn sensors)
- SSH: `ssh -o BatchMode=yes pi@10.77.218.209 "<cmd>"`. Key auth and passwordless sudo are set up. The IP is DHCP and may change: if unreachable, ask the user to run `hostname -I` on the Pi, and check the laptop is on Wi-Fi "Siddhant Vashisth 11".
- Pi: Raspberry Pi OS 64-bit **Trixie**, venv `~/lms-venv` (`--system-site-packages`), code in `~/lms-rover` (no git on the Pi; repo is private).
- Deploy (Git Bash, repo root, commits only): `bash infra/pi/deploy.sh` (or `PI=pi@<ip> bash infra/pi/deploy.sh`).
- Services: `ssh pi@<ip> "~/lms-rover/infra/pi/lms-pi.sh start|stop|restart|enable|status|logs <rover|sensehat|uno|pixy|all>"`. `rover` and `pixy` cannot run together (one camera).
- Pi settings: `~/lms-rover/.env` (template `infra/pi/pi.env.example`). `ROVER_TOKEN` must match the laptop `.env`. `ROVER_URL` in the laptop `.env` points to `http://<pi-ip>:8080`.
- Prefer the Bash tool for ssh commands containing `$` (PowerShell mangles quoting).
- **Never** put `pkill -f pixy_stream…` or `pgrep -f "lms-venv/bin/python -u"` inside an ssh command line. The pattern matches the ssh shell itself and kills it. Use `lms-pi.sh` or `~/lms-tools/pixy_stream_ctl.sh`.
- Hardware facts: motors left = BrickPi **PORT_D**, right = **PORT_C**. Ultrasonic = **PORT_2**; it needs ~3.4 s warm-up, and 255 = no echo (also when very close). Battery is healthy above 10 V and the rover stops below 9 V. Pixy2 pan-tilt: S0 = tilt (higher = up), S1 = pan (higher = right), and moves must be ramped (a jump reset the Pixy over USB). `ROVER_TURN_SIGN`/`ROVER_DRIVE_SIGN` are **not calibrated yet**.

## Safety rules (must follow)
- **Never run anything that can spin motors without telling the user first and asking them to lift the tracks.** This includes `rover.server` without `--mock`, `/control`, `/mode follow`, and motor test scripts.
- Tell the user before `sudo reboot`, `apt full-upgrade`, or anything long. Do not edit network config, delete files outside `~/lms-rover`/`~/lms-tools`, or `rm -rf` on the Pi without asking.
- Ask before exposing anything publicly (Cloudflare tunnel, firewall rules, port forwards).
- **Secrets:** `.env` files are gitignored and must never be committed, printed, or echoed into logs. Do not `cat .env` or `source .env` in a shell whose output is shown; read values in Python if needed. The admin password is the user's choice; do not change it.
- The old Roboflow key in the original public repo must never be reused.
- Do not fake sensor data. Missing readings are `null`, never substitute values (the old code did this; it was removed on purpose).
- Do not commit datasets, `*.pt`, `runs/`, `.pio/`, `node_modules`, `simulator/out/`.

## Layout
| Folder | What |
|---|---|
| `common/` | Shared pydantic message schemas (`VitalsMsg`, `EnvMsg`, `AlertMsg`, …) and MQTT topic names. Change a message here first. |
| `simulator/` | 50 virtual cows + barn: `offline` (CSV + labels for evaluation) and `live` (MQTT). |
| `backend/workers/` | `ingest` (MQTT → Redis Stream `lms:in`), `processor` (stream → TimescaleDB + anomaly detector → alerts), `notifier` (alerts → Telegram). |
| `backend/api/` | FastAPI: JWT login, herd/animal/alerts/env/disease routes, rover proxy (adds `X-Rover-Token`), WebSocket `/ws/live`, serves `web/dist`. |
| `backend/supervise.py` | Restart-on-crash wrapper used by `run_all.ps1`. |
| `ml/anomaly/` | Streaming detector (rules + herd comparison + per-cow baselines), `evaluate.py`, optional IsolationForest (`multivariate.py`, off unless `LMS_IFOREST=1`). |
| `ml/disease/` | Symptom → disease (BernoulliNB). `python -m ml.disease.train` writes `artifacts/`. |
| `ml/detection/` | YOLO11n cow fine-tune pipeline (WSL GPU), models in `models/` (`coco_yolo11n.onnx` is used by the rover; `cow.onnx`; NCNN folders). |
| `rover/` | Pi rover server: `drivers/` (BrickPi + mock), `drivers/camera.py` (picamera2/pixy2/webcam/video/synthetic), `vision.py` (green/YOLO ONNX/NCNN + IoU tracker), `controller.py` (PD follow), `safety.py`, `server.py`. |
| `barn/` | Pi publishers: `sensehat_pub.py`, `serial_bridge.py` (any collar/gateway on USB serial → MQTT, `--port auto`; also runs on the laptop via `run_all.ps1 -Collar auto`). |
| `firmware/` | PlatformIO: `collar_esp32` (main collar; envs wifi / wifi_sleep / espnow / wifi_c3 / espnow_c3; PPG auto-detect MAX30102/MAX30100/DFRobot + analog; settings over serial stored in NVS), `uno_bridge` (backup over USB; envs uno / uno_max30100 / uno_dfrobot / uno_analog), `gateway_espnow`, `shared/LmsSensors` (MPU6050-family reader, activity/steps, analog beat detector). Day-of guide: `docs/collar.md`. |
| `infra/` | WSL install/setup scripts, `schema.sql`, `mosquitto.conf`, `run_all/stop_all/tunnel.ps1`, `pi/` (systemd units, `lms-pi.sh`, `deploy.sh`). |
| `pi-tools/` | Pixy2 MJPEG stream + pan-tilt page (camera test tool). |
| `web/` | React + Vite + Tailwind dashboard. |
| `docs/` | setup, architecture, ml (all measured results), hosting, demo, deployment, LEARN (Hinglish), GUIDE (plain language). |
| `legacy/` | The original hackathon code, for reference only. Do not run. |

## Conventions
- Python 3.11+ syntax, ruff (line length 120). Match the surrounding comment style: short docstrings that say *why*.
- New MQTT message or field: update `common/schemas.py`, `infra/schema.sql` (if stored), the processor, and the tests.
- Report results honestly: measured numbers go in `docs/ml.md`, and nothing invented goes on the landing page.
- Commit messages: imperative summary line. Push to `origin main` only when the user asks.
- After meaningful progress, update the checklist in `CLAUDE.md`.

## What is left (as of 2026-10-16)
Hardware, when the user has the parts:
1. Connect the motors and lift the tracks. Drive from the dashboard and calibrate the turn/drive sign.
2. Run follow mode with YOLO, and benchmark ONNX vs NCNN on the Pi.
3. Sense HAT test (BrickPi covers the GPIO header, so it needs a splitter or a second Pi), then the `sensehat` service.
4. Collar: the ESP32 and pulse sensor arrive on the hackathon day. Follow `docs/collar.md`: flash `wifi`, `scan`, then set ssid/pass/mqtt over serial. Backups are USB + `run_all.ps1 -Collar auto`, then the UNO with the env matching the PPG board. None of the collar firmware has run on real hardware yet (compile-only).
5. ESP32 collar and gateway flashing, then reassembly.

User-side:
- Windows firewall + Hyper-V rule for port 1883 (admin, see docs/setup.md).
- Revoke/regenerate the Telegram token.
- Optional Tailscale.
