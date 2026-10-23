# LMS (Livestock Monitoring System) — Briefing for Claude Code

## ⏸ PAUSED HERE — 2026-10-09 (hardware), software phase in progress
**Hardware status:** Phase 0–2 done, motors + ultrasonic + Pixy2 camera tested (see checklist). Lab closed, so components (Pi, BrickPi, motors, sensors, Pixy) are NOT with the user right now. Pi is off — don't try to SSH until the user says hardware is back.

**Last hardware step in progress:** Pixy2 lens focus (image totally blurry even at 60 cm; user to rotate the lens while watching `http://localhost:8000`).

**When hardware is back, do in this order:**
1. Same Wi-Fi ("Siddhant Vashisth 11"), boot Pi, check IP (`hostname -I`), SSH test, update IP below if changed.
2. Finish Pixy2 focus (`~/lms-tools/pixy_stream_ctl.sh start` + tunnel `ssh -N -L 8000:localhost:8000 pi@<ip>`).
3. Sense HAT test (needs BrickPi removed or a GPIO splitter) → then `barn/sensehat_pub.py` from the new monorepo.
4. Ask MAX30102 board type (DFRobot SEN0344 vs generic) → flash UNO sketch → serial→MQTT bridge → dashboard.
5. Deploy new `rover/` server to the Pi, run with real motors/ultrasonic (⚠️ lift tracks first), benchmark YOLO NCNN on Pi.
6. Reassemble rover → follow mode test.

**Software phase (meanwhile):** plan at `C:\Users\siddh\.claude\plans\done-by-uh-make-async-cherny.md` — monorepo in `d:\Project\LMS` (common/ rover/ backend/ ml/ simulator/ firmware/ barn/ web/ infra/ docs/). Decisions: backend on laptop in WSL Ubuntu 24.04 **without Docker**; DB = PostgreSQL + TimescaleDB (replaces MongoDB); MQTT Mosquitto + Redis Streams; React+Vite dashboard kept; hosted from laptop + Cloudflare Tunnel; new repo on user's own GitHub. Laptop has RTX 3050 4 GB for YOLO training.

## Who you're working with and how to talk
- The user won 1st place at Hack NITR 7.0 with this project and is now rebuilding it as a complete, working system.
- **Reply in Hinglish** (Hindi + English, Roman script). Keep messages short. One step at a time.
- The user is a hands-on builder. Whenever a step needs something physical (plug a cable, attach a motor, power on), **stop and ask them to do it, then wait for "done"** before continuing.

## Setup you are working in
- **You run on the user's laptop** (Windows 11). The **Raspberry Pi 4B** sits next to it with its own monitor, keyboard and mouse. Raspberry Pi OS is already installed.
- Both are on the **same Wi-Fi**. You control the Pi **over SSH** from the laptop. You do not run on the Pi.
- The rover has been **fully disassembled**. Every component is tested alone on the table first, then reassembled.
- Repo: https://github.com/RISHABH12005/FOSSEE-OSHW-Hackathon

## Hardware inventory
| Part | Used for | Notes from the code |
|---|---|---|
| Raspberry Pi 4B | Rover brain | |
| BrickPi3 (Dexter Industries) | Drives LEGO motors, reads EV3 sensors | Talks to Pi over SPI |
| 2× LEGO EV3 large motors | Tracks | Left = **PORT_D**, right = **PORT_C** |
| EV3 ultrasonic sensor | Obstacle detection | BrickPi **PORT_2** |
| Pi Camera 5MP | Video + tracking | Used via Picamera2 |
| Sense HAT | Temp / humidity / pressure (barn environment) | |
| Arduino UNO | Wearable sensor reader | Prints JSON over serial at 115200 |
| MAX30102 | Heart rate + SpO₂ | Code uses **DFRobot_BloodOxygen_S** lib (only works with DFRobot Gravity SEN0344 module, I2C 0x57). Generic breakout → needs SparkFun MAX3010x lib. Ask the user which board they have. |
| MPU6050 | Motion / steps | |

## Phase 0 — Connect to the Pi (do this first, every session)
1. Try to reach the Pi: `ping -n 2 raspberrypi.local` (Windows). If that fails, ask the user to run `hostname -I` in the Pi's terminal and tell you the IP and the Pi username.
2. Check passwordless SSH: `ssh -o BatchMode=yes -o ConnectTimeout=5 <user>@<ip> "echo ok"`.
3. If that fails, SSH keys aren't set up. **You can't type the Pi password yourself**, so ask the user to run once in their own laptop terminal:
   - `ssh-keygen -t ed25519` (Enter for all prompts) — skip if a key already exists
   - Windows has no `ssh-copy-id`; use: `type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh <user>@<ip> "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"`
   - If SSH is refused, enable it on the Pi: `sudo raspi-config` → Interface Options → SSH → Enable.
4. Save the working IP/username under "Session notes" at the bottom.
5. Run every Pi command as `ssh -o BatchMode=yes <user>@<ip> "<command>"`.

**GUI windows:** scripts that open OpenCV windows (`cv2.imshow`) must show on the Pi's monitor. Run them with `DISPLAY=:0` in front, e.g. `ssh ... "cd ~/lms && DISPLAY=:0 python3 Rover/check/cam.py"`. For long-running scripts, tell the user to watch the Pi monitor and stop them with Ctrl+C there, or run them in the Pi's own terminal.

## Phase 1 — Prepare the Pi
1. Check the OS: `cat /etc/os-release` and `uname -m`. Most likely Bookworm, 64-bit.
2. Update: `sudo apt update && sudo apt full-upgrade -y`. Tell the user this takes a while.
3. Install basics: `sudo apt install -y git python3-pip python3-venv python3-opencv python3-picamera2 python3-sense-hat python3-serial i2c-tools`
4. Enable interfaces: `sudo raspi-config nonint do_spi 0`, `sudo raspi-config nonint do_i2c 0`, `sudo raspi-config nonint do_vnc 0`. Reboot only after telling the user.
5. Clone the repo: `git clone https://github.com/RISHABH12005/FOSSEE-OSHW-Hackathon.git ~/lms`
6. Python env: Bookworm blocks system-wide `pip install`. Create `python3 -m venv --system-site-packages ~/lms-venv`. Use `~/lms-venv/bin/python` for all scripts and `~/lms-venv/bin/pip` for installs.

## Phase 2 — BrickPi3 drivers
- Ask the user to mount the BrickPi3 on the Pi and connect its battery pack (BrickPi needs its own 9V-12V supply to drive motors).
- Read the **official DexterInd/BrickPi3 GitHub README** for the current install method before running anything; the old one-line install script may not work cleanly on Bookworm. Install the Python package into `~/lms-venv`.
- Verify: `Rover/check/i2c-spi.py`, then `Rover/check/power.py`. Expected: SPI detected, battery voltage reported (well above 9V is healthy).

## Phase 3 — Test each component alone (in this order)
Before each test, ask the user to connect **only** that part. Report the result in one or two lines.

1. **Motors** — `Rover/check/moter.py`. ⚠️ Motors will spin: tell the user to lift the tracks first. Check each port moves and the encoder changes.
2. **Ultrasonic** — `Rover/check/sensor.py`, then `Rover/ultrasonic.py`. Ask the user to move a hand in front of it; distances should change.
3. **Camera** — `Rover/check/cam.py` with `DISPLAY=:0`. Live video window should appear on the Pi monitor.
4. **Sense HAT** — `Rover/sensehat.py`. Should print temperature/humidity/pressure JSON. (Sense HAT and BrickPi both use the GPIO header; test separately unless stacked.)
5. **Arduino sensors** — compile/flash with Arduino IDE on the laptop. Serial Monitor at 115200 → JSON lines. Then plug into the Pi and read with pyserial on `/dev/ttyACM0`.

When everything passes: reassemble, then run `Rover/picam_motor_Auto&manual-move.py` with `DISPLAY=:0`. It tracks a **green object** (HSV hue 35-90); W/A/S/D/X drive it manually.

## Known issues in the repo
- `Web/p.py` imports `cam` (missing file) and calls `move()` (commented out). Won't run as-is.
- Frontend posts rover commands to `/control`, but `p.py` defines `POST /`.
- No server exposes `/sensor` for the Sense HAT page; `sensehat.py` only prints.
- Autonomous script and `p.py` both open the camera. Only one process can own it.
- Ultrasonic sensor isn't used for stopping the rover.
- `AIML/main.py` uses `COM4`/`COM5` (Linux: `/dev/ttyACM0`, `/dev/ttyACM1`) and **alters sensor readings** (subtracts 25 from HR above 100, substitutes 98/97 for zeros). Remove for the real build.
- A Roboflow API key is committed in `Web/src/pages/FeedPage.tsx`. Don't reuse it; user should get their own and keep it in an env variable.
- "Animal detection" today = green colour tracking + Roboflow **person** model. Real cow detection is a future phase.
- `Rover/ip-static.sh` edits `/etc/dhcpcd.conf`, which Bookworm no longer uses. **Don't run it.** Use `nmcli` or router DHCP reservation.

## Rules
- Never run anything that spins motors without warning the user first.
- Tell the user before `sudo reboot`, `apt full-upgrade`, or anything long.
- Don't edit network config, delete files outside `~/lms`, or `rm -rf` anything on the Pi without asking.
- On an error: read it, explain the cause in one line of Hinglish, propose the fix, then run it.
- Track progress in the checklist below.

## Roadmap after hardware works (don't start unless asked)
1. Unified rover server: one FastAPI app owns the camera, streams video, accepts `/control`, runs autonomous mode, uses ultrasonic for safety.
2. Real cow detection: YOLO (COCO has `cow`/`sheep`) exported to NCNN on the Pi, replacing green tracking in the PD controller.
3. ESP32 collar (MAX30102 + MPU6050 + body-temp sensor) publishing over MQTT.
4. Pipeline: Mosquitto → Redis queue → workers (rules + per-animal anomaly detection) → MongoDB → dashboard, plus Telegram alerts. Simulator for ~50 virtual animals.

## Progress checklist
- [x] Phase 0: SSH from laptop to Pi works without password
- [x] Phase 1: Pi updated, packages installed, repo cloned, venv ready (2026-10-09; also installed python3-spidev; SPI/I2C/VNC enabled)
- [x] Phase 2: BrickPi3 detected, battery OK (2026-10-09: brickpi3 4.0.9 in venv from DexterInd repo; HW 3.2.1, FW 1.4.3; battery 11.37V, 5V rail 4.99V, throttled=0x0. Pi powered only via BrickPi barrel jack. Repo's power.py prints nothing and only checks Pi throttling — use bp.get_voltage_battery())
- [x] Motors tested (2026-10-09: moter.py, 40% for 2s → PORT_C 1578°, PORT_D 1449°; A/B empty as expected)
- [x] Ultrasonic tested (2026-10-09: S2 works; needs ~3.4s after set_sensor_type before first valid read — repo's check/sensor.py waits only 1s so it falsely reports failure. ultrasonic.py live: 5.8–75 cm tracked hand; 255 = no echo/out of range, also seen when object is very close → safety code must not treat 255 as "clear" blindly)
- [x] Camera tested — **temporarily using Pixy2** (no Pi Camera yet; final build will use the Pi Camera). 2026-10-09: live stream works.
- [ ] Sense HAT tested
- [ ] Arduino sensors tested
- [ ] Rover reassembled and driving

## Software phase progress (plan steps S0–S13)
- [x] S0 progress saved · [x] S1 monorepo (`legacy/` = old code, Roboflow key stripped) · [x] S2 WSL services · [x] S3 `common/` schemas+topics
- [x] S4 `simulator/` (offline datasets + live MQTT, `--demo`, use `--backfill-hours 48`)
- [x] S5 `backend/workers/` ingest (batched, persistent session) → processor (TimescaleDB + detector + alerts, auto-resolve) → notifier (Telegram; token not set yet)
- [x] S6 `backend/api/` FastAPI (JWT login, herd/animal/alerts/env/disease, rover proxy, WS /ws/live, serves web/dist)
- [x] S7a `ml/disease/` BernoulliNB+symptom dropout: 2–3 symptoms → top-3 97.8% (old DecisionTree 51%)
- [x] S7b `ml/anomaly/` detector — eval (21 d, 50 cows): fever recall 98%, lameness 95%, estrus 91%, dropout 100%, precision 77–80%, 6–7 false/100 cow-days; reports in simulator/out/eval_*/report.json
- [x] S10 `web/` dashboard (Herd, Animal, Alerts, Barn, Rover, Disease; screenshots verified with Playwright)
- [x] S8 `rover/` server: mock + real drivers, cameras (webcam/video/synthetic/picamera2/pixy2), green + YOLO-ONNX detectors, IoU tracker, PD follow, safety (obstacle/255-after-close/battery/watchdog). `turn_sign` needs hardware calibration.
- [ ] S7c YOLO cow detection · [ ] S9 firmware · [ ] S11 hosting (Cloudflare Tunnel) · [ ] S12 CI/docs · [ ] git commit + GitHub push (ask user)
- Dev stack: `infra\start_services.ps1`, then `python -m backend.workers.ingest|processor|notifier`, `uvicorn backend.api.main:app --port 8000`, `python -m simulator.run live --backfill-hours 48 --demo`, `python -m rover.server --mock --camera synthetic --port 8080`. `.env` ROVER_URL currently points to the laptop mock (change back to the Pi IP for hardware).
- From Git Bash, call WSL scripts with `MSYS_NO_PATHCONV=1` or Git Bash rewrites `/mnt/d/...` paths.

## ⚠️ Disk rule: everything on D:
C: has only ~10 GB free. Code, venvs, datasets, model runs, caches → D: only. WSL disk is `D:\Ubuntu WSL\ext4.vhdx` (WSL /root is on D:). User env vars: `PIP_CACHE_DIR=D:\DevCache\pip`, `PLATFORMIO_CORE_DIR=D:\DevCache\platformio`, `PLAYWRIGHT_BROWSERS_PATH=D:\DevCache\ms-playwright`, npm cache `D:\DevCache\npm-cache`. Shells/tools started before these were set don't see them — pass them explicitly.

## Software phase notes (laptop)
- Backend services live in WSL Ubuntu-24.04 (root user, systemd). Start: `powershell -ExecutionPolicy Bypass -File infra\start_services.ps1` (also starts a hidden `wsl --exec sleep infinity` keepalive — without it WSL stops the idle distro and the services die). Stop: `infra\stop_services.ps1`. Health check: `.venv/Scripts/python infra/check_services.py`.
- One-time: `infra/wsl_install.sh` then `infra/setup.sh` (reads `.env`, idempotent). `.wslconfig` has `networkingMode=mirrored` so Windows `localhost` reaches WSL services; LAN devices (Pi/ESP32) will additionally need a Windows/Hyper-V firewall rule for 1883 (admin) — not done yet.
- Mosquitto 2.0.18: password file must be `root:mosquitto 640`; config `listener 1883` (both IPv4/IPv6 — `localhost` resolves to ::1 first on Windows).
- Python venv: `.venv` (3.13) at repo root; `requirements.txt` (laptop), tests in `tests/` (`.venv/Scripts/python -m pytest`), lint `ruff`.
- `.env` (gitignored) has generated random passwords; `.env.example` is the template.

## Session notes
- Laptop: Windows 11. SSH key `~/.ssh/id_ed25519` (comment `lms-laptop`), installed on Pi via Imager (2026-10-09).
- OS: fresh Raspberry Pi OS 64-bit desktop, **Debian 13 Trixie** (not Bookworm), aarch64. 16 GB SD (~7.9 GB free at start). Pi 4B Rev 1.1, 4 GB RAM.
- Pi hostname: `lmspi` — but `lmspi.local` does NOT resolve from the laptop; use the IP.
- Wi-Fi: both on "Siddhant Vashisth 11" (10.77.218.x). Laptop sometimes joins "Galaxy A16 5G 9365" instead → Pi unreachable; check laptop Wi-Fi first.
- Pi IP: 10.77.218.209 (DHCP, may change — re-check with `hostname -I` on the Pi)
- Pi username: pi
- SSH: `ssh -o BatchMode=yes pi@10.77.218.209 "<cmd>"` works without password. Passwordless sudo set via `/etc/sudoers.d/010_pi-nopasswd`.
- From Windows, prefer the Bash tool for ssh commands containing `$` (PowerShell mangles the quoting).
- Trixie desktop runs Wayland (labwc); `DISPLAY=:0` should go via XWayland — if cv2.imshow fails, try `WAYLAND_DISPLAY=wayland-0` or `QT_QPA_PLATFORM=xcb`.
- MAX30102 board type: _(fill in)_
- Hardware count: final project needs Sense HAT → plan is 2 Pis (rover Pi with BrickPi3, barn Pi with Sense HAT) or 1 Pi + GPIO splitter. BrickPi3 header covers only pins 1-26.

### Pixy2 camera (temporary)
- Board says "CMUcam5" but it is a **Pixy2** (firmware 3.0.18, USB b1ac:f000). The old `charmedlabs/pixy` (Pixy1) lib does NOT work with it — use `charmedlabs/pixy2`.
- Source on Pi: `~/pixy2-src`. Build script (local copy in scratchpad was `build_pixy2.sh`): patches `swig.dat` distutils→setuptools, adds `video_stop/video_resume/video_get_raw_frame` to `python_demos/pixy_python_interface.cpp` + `pixy.i`, builds, copies `_pixy*.so` + `pixy.py` into `~/lms-venv` site-packages. udev rule `/etc/udev/rules.d/pixy.rules` installed (non-root USB).
- Raw frame: 316×208 Bayer, ~60 fps grab; correct demosaic is `cv2.COLOR_BayerRG2BGR`. Must call `video_stop()` before raw frames; CCC block tracking needs `video_resume()`.
- Streamer: `pi-tools/pixy_stream.py` (repo-local) → deployed to `~/lms-tools/pixy_stream.py`, MJPEG on port 8000. View at `http://10.77.218.209:8000` or via tunnel `ssh -N -L 8000:localhost:8000 pi@10.77.218.209` → `http://localhost:8000`.
- Control it ONLY via `~/lms-tools/pixy_stream_ctl.sh start|stop|restart|status` (source in `pi-tools/`). Never put `pkill -f pixy_stream…` or `pgrep -f "lms-venv/bin/python -u"` in an ssh command line — the pattern matches the ssh shell itself and kills it (exit 255).
- Image pipeline (2026-10-09): brightness 90 (default was 148 → blown highlights), EA demosaic, 3-frame temporal average, grey-world WB, auto-levels LUT, unsharp at native size, 2× cubic upscale, JPEG 85 → ~24 fps. CLAHE/Lanczos were too slow on the Pi. SWIG calls hold the GIL, so grab+process must stay in one thread (a separate grab thread starved processing to ~1 fps).
- Pixy2 can't open while the streamer runs (USB claimed); after killing it, `init()` may return -7 for a few seconds — retry.
- Old Pixy1 attempt left in `~/pixy-src` (unused).
