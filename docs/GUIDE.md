# LMS — Poora project aasaan bhasha mein (A se Z)

Ye guide un sab ke liye hai jo project ko samajhna chahte hain: aap, aapki team, ya koi naya banda. Isme koi heavy jargon nahi hai. Jahan technical shabd aaya hai, wahin uska matlab bhi likha hai. (Har topic ko gehraai se seekhna ho to `docs/LEARN.md` padho.)

---

## 1. Project ek line mein

**Gaay ke gale mein ek collar hai jo uski dhadkan, oxygen, body temperature aur chalna-phirna naapta hai. Barn mein ek station hai jo garmi aur nami naapta hai. Ek chhota robot (rover) camera se gaay ko dhoondh kar uske peeche chalta hai. Ye saara data laptop/server pe aata hai. Wahan program check karta hai ki koi gaay beemar to nahi, aur gadbad dikhe to dashboard aur Telegram pe alert bhejta hai.**

Example: gaay C017 ka temperature herd se 1°C zyada hai aur 20 minute se zyada waisa hi bana hua hai. Dashboard pe C017 laal ho jaati hai aur phone pe Telegram aata hai: *"Fever: 40.1 C (+1.3 vs herd)"*.

---

## 2. Building blocks: kaun sa part kya karta hai

| Part | Kya hai | Project mein kaam |
|---|---|---|
| **Raspberry Pi 4B** | Chhota computer (Linux chalta hai) | Rover ka dimaag: camera, AI, motors. Doosra Pi barn station ban sakta hai. |
| **BrickPi3** | Pi ke upar lagne wala board | LEGO motors aur sensors ko Pi se jodta hai. Iski apni battery (9–12 V) hai, aur Pi ko bhi wahi power deti hai. |
| **2× LEGO EV3 motor** | Encoder wali motors (kitna ghoomi, ye bata deti hain) | Rover ke tracks. Left = PORT_D, Right = PORT_C. |
| **EV3 ultrasonic** | Awaaz ki goonj se doori naapta hai | Aage koi cheez 25 cm se paas ho to rover ruk jaata hai. PORT_2. |
| **Pixy2 camera** (abhi) / **Pi Camera** (final) | Camera | Video + gaay dhoondhna. Pixy2 pan-tilt servo pe laga hai. |
| **Sense HAT** | Pi ke upar lagne wala sensor board | Barn ka temperature, humidity, pressure. |
| **MAX30102** | Ungli/skin pe laal + infrared roshni daalkar naapta hai | Heart rate (BPM) aur SpO₂ (khoon mein oxygen %). |
| **MPU6050** | Accelerometer (hilna-dulna naapta hai) | Activity aur steps. |
| **DS18B20** | Waterproof temperature probe | Body temperature (sirf ESP32 collar mein). |
| **Arduino UNO** | Microcontroller (chhota chip computer) | **Backup** collar: sensors padhkar JSON USB cable pe bhejta hai (radio nahi hai). |
| **ESP32** | Wi-Fi + Bluetooth wala microcontroller | Final collar: khud Wi-Fi/ESP-NOW se data bhejta hai, aur sone (deep sleep) se battery bachata hai. |
| **Laptop** | Server | Database, data pipeline, AI, website: sab yahin chalta hai (demo ke liye). |

**Kitne Pi?** BrickPi3 aur Sense HAT dono Pi ke GPIO header (pins) pe lagte hain, isliye ek Pi pe dono saath nahi lag sakte. Final mein do Pi chahiye: ek **rover Pi** (BrickPi) aur ek **barn Pi** (Sense HAT). Ya ek Pi + GPIO splitter.

---

## 3. Bade concepts, ek-ek line mein

- **SSH**: laptop se Pi ka terminal chalana, network ke through. `ssh pi@10.77.218.209 "hostname"` likha → command Pi pe chali → jawab laptop pe aaya.
- **MQTT**: ek "post office" jaisa system. Sensor ek *topic* (address) pe message bhejta hai, jaise `lms/collar/C001/vitals`, aur jo bhi us topic ko sun raha hai, use mil jaata hai. Ye post office program **Mosquitto** hai (port 1883).
- **JSON**: data likhne ka simple format: `{"animal_id":"C001","hr":68,"spo2":97}`.
- **Redis Stream**: ek line (queue). Messages isme lagte hain aur worker ek-ek karke uthata hai. Worker band ho jaaye to messages khote nahi, line mein pade rehte hain.
- **PostgreSQL + TimescaleDB**: database. TimescaleDB time wale data (har minute ki reading) ko tez aur chhota rakhta hai.
- **FastAPI**: Python ka web server. Ye website ko data deta hai (API).
- **React dashboard**: browser mein dikhne wali website.
- **WebSocket**: website aur server ke beech khula rehne wala connection. Naya data aate hi page khud update ho jaata hai, refresh nahi karna padta.
- **JWT token**: login ke baad milne wala "pass". Har request ke saath jaata hai, taaki server ko pata ho ki aap logged in ho.
- **YOLO**: AI model jo photo mein cheezein dhoondhta hai aur unke charon taraf box banata hai (gaay, insaan).
- **ONNX / NCNN**: trained model ko save karne ke formats, jinse model Pi pe tez chal sake.
- **systemd service**: Linux ka tareeka program ko "service" banane ka. Pi boot ho to apne aap chalu ho, aur crash ho to dobara chalu ho jaaye.
- **WSL**: Windows ke andar asli Ubuntu Linux. Hamare database/MQTT/Redis isi mein chalte hain.
- **Cloudflare Tunnel**: laptop pe chal rahi website ka ek public `https://...trycloudflare.com` link bana deta hai, bina router settings chhede.

---

## 4. Data kahan se aata hai aur kahan jaata hai (har sensor ka safar)

### 4.1 Collar → dashboard (sabse important raasta)

```
MAX30102 + MPU6050 (+ DS18B20)
      │  I2C wires (SDA/SCL) / 1-wire
      ▼
UNO ya ESP32  ── banata hai JSON: {"animal_id":"C001","hr":71,"spo2":97,"activity":0.041,"steps":3}
      │
      ├─(UNO)   USB cable → Pi → barn/serial_bridge.py ──┐
      ├─(ESP32 wifi)  Wi-Fi → seedha MQTT ───────────────┤
      └─(ESP32 espnow) radio → gateway ESP32 → USB → Pi → serial_bridge.py ─┤
                                                          ▼
                                       Mosquitto (laptop, port 1883)  topic lms/collar/C001/vitals
                                                          ▼
                     backend/workers/ingest.py   (check karta hai ki message sahi hai: common/schemas.py)
                                                          ▼
                                     Redis Stream "lms:in"   (line mein lag gaya)
                                                          ▼
                    backend/workers/processor.py
                       ├─ TimescaleDB table "vitals" mein save
                       ├─ ml/anomaly/detector.py se check: fever? dhadkan tez? kam chal rahi?
                       ├─ alert bana to table "alerts" + Redis "lms:alerts"
                       └─ Redis "lms:live" pe live update
                                ▼                                   ▼
            backend/api (WebSocket /ws/live)          backend/workers/notifier.py
                                ▼                                   ▼
                   Dashboard (Herd / Animal page)             Telegram message
```

**Example ke saath:** aapne UNO wale MAX30102 pe ungli rakhi.
1. UNO har ~4 second mein ek JSON line USB pe print karta hai.
2. Pi pe `serial_bridge.py` us line ko padhta hai aur MQTT pe `lms/collar/C001/vitals` bhejta hai.
3. Laptop pe ingest usse Redis mein daalta hai, aur processor database mein save karta hai.
4. Dashboard pe C001 ka graph 1–2 second mein update ho jaata hai.

Ungli hata di to `hr` = `null` jaayega. Hum kabhi nakli value nahi bharte, purane code mein ye galti thi aur use hata diya gaya.

### 4.2 Sense HAT → Barn page
`barn/sensehat_pub.py` har 30 s mein temperature, humidity aur pressure padhta hai. Pi ka CPU Sense HAT ko garam karta hai, isliye ek formula se correction hota hai. Phir ye MQTT topic `lms/barn/barn1/env` pe bhejta hai. Processor isse **THI** (temperature-humidity index) nikalta hai: 72 se upar = mild heat stress, 79 = moderate, 89 = severe. Sense HAT ki LED matrix pe bhi rang dikhta hai (hara/peela/narangi/laal).

### 4.3 Rover camera + motors + ultrasonic
```
Camera (Pixy2/Pi Cam) ─► rover/drivers/camera.py ─► rover/vision.py (YOLO: "cow 0.91" box)
                                                        ▼
                     rover/controller.py (PD: gaay frame ke beech mein rahe, sahi doori pe)
                                                        ▼
         rover/safety.py (ultrasonic <25 cm? insaan bahut paas? battery <9 V? 0.5 s se command nahi?)
                                                        ▼
                         rover/drivers/brickpi.py ─► BrickPi3 ─► motors C/D
```
Rover ka apna web server (`rover/server.py`, port 8080) video stream, status aur control deta hai. Dashboard ka Rover page laptop API se baat karta hai, aur laptop API rover se (`backend/api/rover.py`, secret `ROVER_TOKEN` header ke saath). Rover apna status aur detections MQTT pe bhi bhejta hai.

### 4.4 Simulator (jab asli gaay nahi hain)
`simulator/` 50 nakli gaay banata hai. Har gaay ki apni normal dhadkan, temperature aur din-raat ka routine hota hai. Beech-beech mein ye "bimari" daalta hai (fever, lameness, estrus, sensor band) aur unka record (label) rakhta hai. Ye data bhi wahi MQTT raasta leta hai jo asli collar leta hai, isliye dashboard ko fark nahi padta. Labels se hum naap sakte hain ki detector kitna sahi hai.

---

## 5. Har folder aur file: kya hai, chalane pe kya hota hai

### `common/` (sabki common bhasha)
| File | Kaam | Example |
|---|---|---|
| `schemas.py` | Har message ka format (VitalsMsg, EnvMsg, AlertMsg…) + `thi()` formula | Galat format ka message ingest pe hi reject ho jaata hai |
| `topics.py` | MQTT topic names ek jagah | `collar_vitals("C001")` → `lms/collar/C001/vitals` |

### `simulator/`
| File | Chalao | Kya hoga |
|---|---|---|
| `run.py` | `python -m simulator.run live --backfill-hours 48 --demo` | 50 gaay ka pichhle 48 ghante ka data turant bhejega, phir har minute live. `--demo` thodi der mein dikhne wali bimariyan daalta hai. |
| | `python -m simulator.run offline --days 21 --out simulator/out/x` | MQTT nahi. CSV files + labels banata hai, evaluation ke liye. |
| `model.py` | (import hota hai) | Gaay ka "physics": baseline, routine, bimari ka asar |

### `backend/`
| File | Chalao | Kya hoga |
|---|---|---|
| `config.py` | — | `.env` se settings padhta hai (passwords, URLs) |
| `workers/ingest.py` | `python -m backend.workers.ingest` | MQTT sunega, sahi messages Redis stream mein daalega |
| `workers/processor.py` | `python -m backend.workers.processor` | Stream → database + detector → alerts. DB band ho jaaye to dobara judne ki koshish karta hai. |
| `workers/notifier.py` | `python -m backend.workers.notifier` | Warning/critical alert → Telegram (ek gaay+kism ka alert 3 ghante mein ek hi baar) |
| `api/main.py` | `uvicorn backend.api.main:app --port 8000` | Website + API + WebSocket chalu. Logs se token chhupata hai. |
| `api/auth.py` | — | Login, JWT token |
| `api/routes.py` | — | `/api/animals`, `/api/alerts`, `/api/env`, `/api/disease/predict`… |
| `api/rover.py` | — | Rover tak pul (proxy): `/api/rover/status`, `/control`, `/mode`, `/stream.mjpg` |
| `api/db.py` | — | Database connections ka pool |
| `supervise.py` | `python -m backend.supervise ingest -- -m backend.workers.ingest` | Program crash ho to 2 s, 4 s… baad dobara chalata hai, aur log `logs/ingest.log` mein likhta hai |

### `ml/` (AI/ML)
| File | Chalao | Kya hoga |
|---|---|---|
| `anomaly/detector.py` | (processor use karta hai) | Bimari pakadne ka dimaag: glitch filter, herd se tulna, har gaay ka apna normal, "kitni der se" check |
| `anomaly/evaluate.py` | `python -m ml.anomaly.evaluate simulator/out/eval_mild` | Detector ka report card (recall, precision) |
| `anomaly/multivariate.py` | `python -m ml.anomaly.multivariate train simulator/out/run1` | IsolationForest (Layer 3). Test kiya, kuch extra nahi mila, isliye default band hai (`LMS_IFOREST=1` se chalu) |
| `disease/train.py` | `python -m ml.disease.train` | Symptoms → bimari wala model train karke `artifacts/` mein save |
| `disease/predict.py` | (API use karta hai) | 3 symptoms do → top-3 bimariyan + % |
| `detection/run_pipeline.sh` | WSL: `bash ml/detection/run_pipeline.sh` | Cow dataset download → YOLO11n training (GPU) → ONNX/NCNN export |
| `detection/models/` | — | `coco_yolo11n.onnx` (rover abhi yahi use karta hai: gaay + insaan), `cow.onnx` (sirf gaay, behtar), NCNN folders |

### `rover/` (Pi pe chalta hai; laptop pe `--mock` se)
| File | Kaam |
|---|---|
| `server.py` | `python -m rover.server --mock --camera synthetic` → laptop pe nakli rover. Pi pe service chalati hai. Endpoints: `/status`, `/control`, `/mode`, `/stream.mjpg`, `/snapshot.jpg`. |
| `config.py` | Saari settings: speed, 25 cm stop, battery 9 V, turn_sign… |
| `drivers/brickpi.py` | Asli motors/ultrasonic (BrickPi3), aur testing ke liye Mock version |
| `drivers/camera.py` | Camera chunna: `picamera2`, `pixy2`, `webcam`, `video:file.mp4`, `synthetic` (nakli chalti gaay) |
| `vision.py` | Detector: `green` (purana hara marker), `yolo:…onnx`, `ncnn:…folder` + tracker (har gaay ko ID) |
| `controller.py` | Modes: `idle`, `manual` (aap chalao), `follow` (gaay ke peeche) |
| `safety.py` | Brake ka dimaag: obstacle, insaan paas, battery kam, command band |

### `barn/` (Pi pe)
| File | Chalao (Pi pe) | Kaam |
|---|---|---|
| `sensehat_pub.py` | `python -m barn.sensehat_pub --station barn1` | Sense HAT → MQTT |
| `serial_bridge.py` | `python -m barn.serial_bridge --port auto` (laptop: `run_all.ps1 -Collar auto`) | USB pe laga koi bhi collar/gateway → MQTT. `auto` khud board dhoondhta hai |
| `mqtt.py` | — | Dono ke liye MQTT connection (`.env` se host/password) |

### `firmware/` (chips ke liye C++ code, PlatformIO se)
| Folder | Kaam | Flash kaise |
|---|---|---|
| `collar_esp32/` | **Main** ESP32 collar. 4 PPG boards chala leta hai (MAX30102/MAX30100/DFRobot khud pehchaanta hai, analog `ppg analog` se). Wi-Fi/MQTT serial se set hota hai, reflash nahi. Modes: `wifi`, `wifi_sleep`, `espnow` (+ C3 boards) | `pio run -e wifi -t upload` |
| `gateway_espnow/` | ESP32 jo collars ke ESP-NOW radio messages sunke USB pe JSON deta hai | `pio run -t upload` |
| `uno_bridge/` | **Backup** UNO collar, har PPG board ka alag env | `pio run -e uno` / `uno_max30100` / `uno_dfrobot` / `uno_analog` |
| `shared/LmsSensors/` | Dono collars ka common code: MPU6050 reader, activity/steps, analog pulse beat detector | — |

ESP32 ki settings (Wi-Fi, MQTT, animal id) serial monitor se set hoti hain (`help` type karo) aur ESP32 ki flash mein save rehti hain. Chaho to defaults `include/lms_config.h` mein bhi daal sakte ho (ye file git mein nahi jaati). Hackathon day ka poora tareeka: `docs/collar.md`.

### `infra/` (sab chalane-band karne ke scripts)
| File | Kahan chalao | Kya hoga |
|---|---|---|
| `wsl_install.sh` | WSL, ek baar | Mosquitto, Redis, PostgreSQL, TimescaleDB install |
| `setup.sh` | WSL, ek baar (dobara chalana safe) | Database, tables (`schema.sql`), MQTT user banata hai |
| `start_services.ps1` / `stop_services.ps1` | Laptop PowerShell | Sirf WSL services start/stop |
| `run_all.ps1` | Laptop | **Sab kuch chalu** (services + workers + API). `-Simulator`, `-MockRover`, `-Tunnel` options |
| `stop_all.ps1` | Laptop | Sab band |
| `tunnel.ps1` | Laptop | Public https link |
| `check_services.py` | Laptop | Har service ka OK/FAIL |
| `pi/deploy.sh` | Laptop Git Bash | Code Pi pe copy + install + services |
| `pi/lms-pi.sh` | Pi pe (ssh se) | Pi ki services: `start rover`, `status`, `logs uno`… |
| `pi/*.service` | — | systemd service files (rover, sensehat, uno-bridge, pixy-stream) |

### Baaki
- `web/`: React dashboard. Pages: Landing, Login, Herd (50 gaay ka grid), Animal (graphs), Alerts, Barn, Rover (video + control pad), Disease.
- `pi-tools/`: Pixy2 camera test page (port 8000 on Pi), pan-tilt buttons/arrow keys, focus score.
- `tests/`: automatic checks (`pytest`). Har badlaav ke baad chalao.
- `legacy/`: hackathon ka purana code, sirf reference ke liye.
- `docs/`: ye guide, setup, architecture, ML results, hosting, demo plan, deployment, LEARN.
- `CLAUDE.md` / `AGENTS.md`: AI assistants (Claude Code / Codex) ke liye instructions aur progress.
- `.env` (git mein nahi): saare passwords/tokens. `.env.example` uska khaali template.

---

## 6. Files aapas mein kaise judi hain

1. **Sab ek hi bhasha bolte hain:** simulator, ingest, processor, barn scripts, rover aur tests, sab `common/schemas.py` import karte hain. Firmware wahi JSON fields bhejta hai. Kisi field ka naam badalna ho to pehle yahan badlo.
2. **Programs ek-doosre ko seedha call nahi karte. Beech mein MQTT aur Redis hain.** Isliye koi bhi ek part band ho jaaye to baaki chalte rehte hain. Example: notifier band hai to bhi alerts database mein aate rahenge.
3. **Settings `.env` se aati hain:** `backend/config.py` laptop ki `.env` padhta hai, Pi pe services `~/lms-rover/.env` padhti hain. Dono mein `ROVER_TOKEN` aur MQTT password same hone chahiye.
4. **Website → API → rover:** browser kabhi rover se seedha baat nahi karta. Laptop API login check karke rover ko request bhejta hai.

---

## 7. GitHub se kaise juda hai

- Code ka ghar: **private repo** https://github.com/sidvashisth2005/lms-rover (sirf aap dekh sakte ho).
- Laptop pe `D:\Project\LMS` us repo ki copy hai. Badlaav save karne ka tareeka:
  ```powershell
  git status                 # kya badla
  git add -A
  git commit -m "kya kiya"   # local save point
  git push                   # GitHub pe bhejo
  ```
- **GitHub Actions (CI):** har push pe GitHub khud tests + lint + website build chalata hai (`.github/workflows/ci.yml`). Laal cross = kuch toota.
- **Pi pe git nahi:** repo private hai, isliye Pi ke paas GitHub ka password nahi. Laptop se `bash infra/pi/deploy.sh` committed code ko SSH ke through Pi pe copy kar deta hai (`git archive | ssh … tar -x`). Isliye **pehle commit, phir deploy**.
- `.gitignore` ki wajah se secrets (`.env`, `lms_config.h`), datasets aur build files GitHub pe nahi jaate.

---

## 8. Pi ko door se (remotely) kaise chalate hain

1. **Same Wi-Fi:** laptop aur Pi dono "Siddhant Vashisth 11" pe hone chahiye. Pi ka IP: Pi pe `hostname -I` (abhi 10.77.218.209; hotspot badla to IP badal sakta hai).
2. **SSH bina password:** laptop ki SSH key Pi pe installed hai, isliye `ssh pi@10.77.218.209 "uptime"` seedha chalta hai.
3. **Services chalana:**
   ```bash
   ssh pi@10.77.218.209 "~/lms-rover/infra/pi/lms-pi.sh start rover"     # rover chalu
   ssh pi@10.77.218.209 "~/lms-rover/infra/pi/lms-pi.sh status"          # kya chal raha hai
   ssh pi@10.77.218.209 "~/lms-rover/infra/pi/lms-pi.sh logs rover"      # live log
   ssh pi@10.77.218.209 "~/lms-rover/infra/pi/lms-pi.sh enable all"      # boot pe auto-start
   ```
4. **Browser se:** dashboard ka Rover page (laptop API ke through). Camera test ke liye `http://10.77.218.209:8000` (pixy service).
5. **Code update:** laptop pe commit → `bash infra/pi/deploy.sh` → `lms-pi.sh restart rover`.
6. **Bahar se (future):** Tailscale lagane se Pi ko ek fixed `100.x.x.x` address milta hai jo kisi bhi network se chalta hai (`docs/deployment.md`).
7. **Pi band karna:** `ssh pi@10.77.218.209 "sudo shutdown -h now"`. Hara LED band ho jaaye, tab hi power hatao.

⚠️ Jo command motors ghuma sakti hai (rover service, follow mode, control pad), use chalane se pehle tracks hawa mein utha do.

---

## 9. Poora system chalana: step by step (demo)

```powershell
# Laptop (PowerShell, D:\Project\LMS)
.\infra\run_all.ps1 -Simulator -Tunnel        # services + workers + API + 50 gaay + public link
.venv\Scripts\python infra\check_services.py   # sab OK?
# Pi
ssh pi@10.77.218.209 "~/lms-rover/infra/pi/lms-pi.sh start all"
# Browser: http://127.0.0.1:8000  ya tunnel link (logs\tunnel.log mein)
# Band karna:
.\infra\stop_all.ps1
```
Kya dikhna chahiye: Herd page pe 50+ gaay, kuch ke alerts, Barn page pe THI, Rover page pe live video + boxes, aur Telegram pe alerts. Poora demo script + "kuch toot jaaye to kya karein": `docs/demo.md`.

Rover hardware nahi hai? `-MockRover` lagao. Laptop pe nakli rover aur nakli camera chal jaayenge.

---

## 10. A se Z: components se codebase tak kaise bana

1. **Hackathon version (purana):** alag-alag scripts thi. Hare rang ka marker follow karna, Arduino ka JSON, ek website. Kuch files toot-phooti thi aur readings badli jaati thi (`legacy/`).
2. **Hardware ek-ek karke test:** Pi OS → SSH → BrickPi3 (battery 11.4 V) → motors (encoder chala) → ultrasonic (3.4 s warm-up, 255 = goonj nahi) → Pixy2 (library khud build ki, focus kiya).
3. **Monorepo banaya:** sab kuch ek repo mein, folder-wise (`common`, `backend`, `rover`…).
4. **Pehle bhasha tay ki** (`common/schemas.py`), phir data banane wala (simulator), phir pipeline (ingest → processor → DB → API), phir dashboard.
5. **ML:** disease model (51% → 97.8% top-3), anomaly detector (precision 0.31 → 0.77–0.80 tuning se), YOLO cow fine-tune (mAP50 0.63 → 0.73), person model try kiya (stock behtar nikla, isliye stock use kiya), IsolationForest try kiya (kuch extra nahi mila, band rakha).
6. **Rover software:** mock pe pehle bana aur test hua. Phir asli Pi + BrickPi + Pixy2 + YOLO pe chalaya (camera ~34 fps, YOLO ~8 fps).
7. **Firmware:** ESP32 collar (3 modes), ESP-NOW gateway, UNO bridge. Sab compile ho chuke hain, flash hardware milne pe hoga.
8. **Pakka banaya:** login, rover token, logs mein token chhupana, crash pe auto-restart, DB reconnect, tests, CI, docs.

---

## 11. Abhi tak kya ho chuka (✅) aur kya baaki (⏳)

✅ Software poora: pipeline, dashboard, alerts + Telegram, simulator, 3 ML models + evaluation, rover server (mock + real), Pi services + deploy, firmware (compile), hosting via tunnel, tests (45+), CI, docs.
✅ Hardware tested: Pi, BrickPi3, motors (alag se), ultrasonic, Pixy2 camera + YOLO on Pi.

⏳ Hardware pe baaki (isi order mein):
1. Motors ko rover server se chalana (tracks utha ke). Dashboard se drive karke `ROVER_TURN_SIGN`/`ROVER_DRIVE_SIGN` set karna.
2. Follow mode: gaay ka khilona/photo rakh ke test. Pi pe ONNX vs NCNN speed naapna.
3. Sense HAT test (doosra Pi ya splitter), phir `sensehat` service.
4. Hackathon day: ESP32 + PPG aayenge → `docs/collar.md` follow karna (flash → `scan` → Wi-Fi set). Backup: USB cable, phir UNO.
5. ESP32 collar + gateway flash karna, battery life naapna.
6. Rover reassemble karna aur poora follow test.

⏳ Aapki taraf se: laptop firewall mein port 1883 kholna (admin, `docs/setup.md`), Telegram token regenerate karna, optional Tailscale.

---

## 12. Future: aage kya aur kaise

| Kya | Kaise |
|---|---|
| Laptop ki jagah hamesha-on server | Cloud VM (Oracle free / VPS) + https + MQTT TLS. Same code chalega (`docs/deployment.md`). |
| Har farm pe ek gateway | Gateway Pi pe Mosquitto bridge. Internet jaane pe data queue mein rukta hai, internet aate hi bhej deta hai. |
| Bade khet (km range) | LoRa collars + LoRa gateway. Gateway ke baad sab same rahega. |
| Lambi battery | ESP-NOW sleep mode (already coded). Real battery life naapni hai. |
| Rover kahin se bhi | Tailscale (fixed IP), token already laga hai. |
| Behtar AI | Asli collar data se thresholds tune karna, IsolationForest dobara test karna, apne farm ki gaay ki photos se YOLO dobara train karna. |
| Pi Camera | `ROVER_CAMERA=picamera2`. Code ready hai. |

---

## 13. Jab kuch kaam na kare (jaldi wale ilaaj)

| Dikkat | Pehle ye check karo |
|---|---|
| Dashboard nahi khul raha | `check_services.py`. `logs\api.log` dekho. |
| Pi nahi mil raha | Laptop sahi Wi-Fi pe hai? Pi pe `hostname -I`, naya IP `.env` + deploy mein daalo. |
| Rover page "unreachable" | `lms-pi.sh status`. `ROVER_URL` sahi IP pe hai? |
| "rover rejected ROVER_TOKEN" | Laptop `.env` aur Pi `~/lms-rover/.env` mein `ROVER_TOKEN` same karo, phir rover restart. |
| Collar data nahi aa raha | `lms-pi.sh logs uno`. Firewall 1883. Ungli sensor pe theek se hai? |
| Rover ulta ghoom raha | Pi `.env` mein `ROVER_TURN_SIGN=-1`, phir restart. |
| Pixy hang | `lms-pi.sh restart rover`. Servo jhatke se mat ghumao. |
| Tests fail | Error ka pehla laal hissa padho. `ruff check .` bhi chalao. |
