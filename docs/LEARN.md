# LMS — Seekhne ki guide (Hinglish)

Is project mein jo kuch bhi bana — hardware se lekar AI tak — uska har topic yahan hai. Har topic mein 4 cheezein:

- **Kya hai** — concept simple shabdon mein
- **Kis kaam aata hai** — real duniya mein iska use
- **Humne kaise use kiya** — is project mein exactly kya kiya, kaunsi file
- **Khud kaise karoge** — manually karna ho to approach aur commands

Padhne ka tarika: upar se neeche order mein padho — har part pichhle pe based hai. Commands copy karke khud chala ke dekhna sabse achha seekhna hai.

---

## Part A — Hardware aur Raspberry Pi

### A1. Raspberry Pi kya hai
- **Kya hai:** Ek chhota computer (credit card size). CPU, RAM, USB, Wi-Fi, aur 40 GPIO pins jinse sensors/motors jud sakte hain. Linux chalta hai.
- **Kis kaam aata hai:** Robots, IoT gateways, cameras, chhote servers — jahan laptop bada/mehenga ho.
- **Humne kaise use kiya:** Pi 4B (4 GB) rover ka dimaag hai — camera padhta hai, YOLO chalata hai, BrickPi se motors chalata hai, aur Wi-Fi pe laptop ko data bhejta hai.
- **Khud kaise karoge:** Pi ko ek "Linux laptop" samjho. SSH se commands do, Python scripts chalao. GPIO/I2C/SPI ke liye `raspi-config` se interface on karo.

### A2. OS flash karna (Raspberry Pi Imager)
- **Kya hai:** Pi ka OS SD card pe "flash" (likha) jaata hai. Imager ek app hai jo OS download karke card pe likhta hai aur pehle se settings (Wi-Fi, user, SSH) daal deta hai.
- **Humne kaise use kiya:** Raspberry Pi OS 64-bit (Debian 13 Trixie) desktop. Hostname `lmspi`, user `pi`, Wi-Fi, SSH public-key — sab Imager ke "customisation" mein daala, isliye pehle boot pe hi bina password SSH chal gaya.
- **Khud kaise karoge:** Imager → Device: Pi 4 → OS: Raspberry Pi OS (64-bit) → Storage: SD card → Edit settings (hostname, user/password, Wi-Fi, locale `Asia/Kolkata`, keyboard `us`, SSH with public key) → Write. **64-bit kyun:** PyTorch/YOLO/NCNN sirf 64-bit pe aate hain. **Keyboard `in` mat lena** — wo Hindi (Devanagari) layout hai.

### A3. SSH aur SSH keys
- **Kya hai:** SSH = doosre computer pe secure terminal. **Key pair** = do files: private key (sirf tumhare laptop pe, secret) aur public key (Pi pe rakhte hain). Pi check karta hai ki tumhare paas matching private key hai — password ki zarurat nahi.
- **Kis kaam aata hai:** Servers, Pi, cloud machines ko remotely chalana; scripts automate karna (password type nahi karna padta).
- **Humne kaise use kiya:** Laptop pe `~/.ssh/id_ed25519` banayi, public key Imager se Pi pe daali. Ab saari Pi commands `ssh -o BatchMode=yes pi@10.77.218.209 "..."` se chalti hain.
- **Khud kaise karoge:**
  ```
  ssh-keygen -t ed25519            # key banao (Enter dabate jao)
  type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh pi@<ip> "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
  ssh pi@<ip>                      # ab bina password
  ```
  Files bhejna: `scp file.py pi@<ip>:~/`.

### A4. Network, IP address, DHCP, hotspot
- **Kya hai:** Har device ko network pe ek **IP address** milta hai (jaise `10.77.218.209`). **DHCP** = router/hotspot apne aap IP baantta hai. Same subnet (pehle 3 hisse same, jaise `10.77.218.x`) wale devices hi seedha baat kar sakte hain.
- **Humne kaise use kiya:** Pehle laptop "Galaxy A16" hotspot pe tha aur Pi "Siddhant Vashisth 11" pe — alag subnets, isliye SSH timeout. Dono ko ek network pe laaye to chal gaya. `lmspi.local` (mDNS naam) hotspot pe resolve nahi hua, isliye IP use karte hain.
- **Khud kaise karoge:** Pi pe `hostname -I` (IP dekho), laptop pe `ipconfig`. `ping <ip>` se check. IP badalta rahe to: router mein DHCP reservation, ya **Tailscale** (har device ko pakka `100.x.x.x` IP, kisi bhi network pe).

### A5. apt, venv, pip — Pi pe software
- **Kya hai:** `apt` = Linux ka app store (system packages). `pip` = Python packages. **venv** = ek project ke liye alag Python environment, taaki packages system se na takrayein.
- **Humne kaise use kiya:** `apt` se OpenCV, Picamera2, Sense HAT, serial, spidev; `python3 -m venv --system-site-packages ~/lms-venv` — `--system-site-packages` se apt wale packages bhi venv mein dikhte hain. Naye Debian mein system-wide `pip install` blocked hai, isliye venv zaroori.
- **Khud kaise karoge:** `sudo apt install -y <pkg>`; `~/lms-venv/bin/pip install <pkg>`; scripts `~/lms-venv/bin/python script.py` se chalao.

### A6. GPIO, SPI, I2C, UART — Pi kaise hardware se baat karta hai
- **Kya hai:** GPIO pins pe alag "bhashayein" chalti hain:
  - **I2C** — 2 taar (SDA, SCL), ek line pe kai sensors, har ek ka address (MAX30102 = 0x57, MPU6050 = 0x68). Dheema, sensors ke liye.
  - **SPI** — 4 taar, tez, ek master kai slaves. BrickPi3 isi pe.
  - **UART/Serial** — 2 taar (TX/RX), Arduino USB-serial isi tarah.
- **Humne kaise use kiya:** `raspi-config nonint do_spi 0` / `do_i2c 0` se on kiye. `/dev/spidev0.0` dikhna = SPI ready.
- **Khud kaise karoge:** I2C devices dhoondhne ke liye `i2cdetect -y 1` (address table dikhata hai). Serial ports: `ls /dev/ttyACM* /dev/ttyUSB*`.

### A7. BrickPi3 + LEGO EV3 motors (encoders)
- **Kya hai:** BrickPi3 ek HAT (Pi ke upar lagne wala board) hai jo LEGO EV3 motors/sensors ko Pi se jodta hai. Motors ko 9–12 V chahiye — Pi ke pins sirf 3.3 V dete hain, isliye alag battery BrickPi ke barrel jack mein. BrickPi Pi ko bhi 5 V de deta hai.
- **Encoder:** motor ke andar ek counter jo batata hai motor kitne degree ghooma. Isse speed control (`set_motor_dps` = degrees per second) possible hai.
- **Humne kaise use kiya:** Right motor = Port C, left = Port D. Test mein 40% power 2 sec → C 1578°, D 1449° (encoders sahi). Battery `bp.get_voltage_battery()` = ~11 V. Code: `rover/drivers/brickpi.py`.
- **Khud kaise karoge:**
  ```python
  import brickpi3

  bp = brickpi3.BrickPi3()
  bp.set_motor_dps(bp.PORT_C, 300)  # 300 degree/sec
  print(bp.get_motor_encoder(bp.PORT_C))
  bp.reset_all()  # hamesha end mein - motors band
  ```
  ⚠️ Pehle tracks hawa mein uthao.

### A8. EV3 ultrasonic sensor
- **Kya hai:** Awaaz (ultrasound) bhejta hai, echo wapas aane ka time naapke doori nikalta hai (chamgadad jaisa).
- **Humne kya seekha:** (1) Sensor ko start hone mein ~3.4 sec lagte hain — purana test script 1 sec rukta tha isliye "fail" bolta tha. (2) **255 cm = koi echo nahi** — matlab ya to kuch nahi saamne, ya cheez itni paas (<3 cm) ki echo miss ho gaya. Isliye `rover/safety.py` mein: paas wali reading ke turant baad 255 aaye to "blocked" maante hain, "clear" nahi.
- **Khud kaise karoge:** `bp.set_sensor_type(bp.PORT_2, bp.SENSOR_TYPE.EV3_ULTRASONIC_CM)`, 4 sec ruko, phir `bp.get_sensor(bp.PORT_2)`. `SensorError` aaye to retry.

### A9. Pixy2 camera (CMUcam5), Bayer images, SWIG
- **Kya hai:** Pixy2 ek "smart camera" hai jo apne andar colour tracking karta hai. Board pe "CMUcam5" likha tha par firmware 3.0.18 = **Pixy2** (purani Pixy1 library is pe nahi chali — isliye pehle errors aaye).
- **Bayer image:** Camera sensor har pixel pe sirf ek rang (R ya G ya B) naapta hai, ek checkerboard pattern mein. **Demosaic** = aas-paas ke pixels se baaki 2 rang andaaza lagana. Galat pattern lo to rang ulte ya jaali dikhti hai — humne 4 try kiye, `BayerRG` sahi nikla.
- **SWIG:** C++ library ko Python se call karne ka bridge. Pixy2 ki library C++ mein hai; humne usme 3 naye functions jode (raw frame, stop/resume) aur SWIG se Python module banaya.
- **Image saaf karna:** brightness 148→90 (jale hue highlights theek), 3 frames ka average (noise kam), grey-world white balance (rang natural), auto-levels (contrast), sharpening. File: `pi-tools/pixy_stream.py`.
- **Focus score:** Laplacian variance — image mein jitne tez edges, utna bada number. Lens ghumate hue number max karo. Humara 7 → 450.
- **Khud kaise karoge:** `lsusb` mein `b1ac:f000` dikhe = Pixy juda hai. Stream: `~/lms-tools/pixy_stream_ctl.sh start`, browser mein `http://<pi-ip>:8000`.

### A10. Servo motors aur pan-tilt, current spikes
- **Kya hai:** Servo ek motor jo ek di hui angle pe jaake ruk jaata hai (0–1000 Pixy units). Pan = left-right, tilt = upar-neeche.
- **Humne kya seekha:** (1) Is kit pe wiring ulti thi: S0 = tilt, S1 = pan — testing se pata chala, code mein mapping theek ki. (2) Servo jhatke se ghuma to bahut current khincha, USB ka voltage gira, Pixy **reset** ho gaya. Hal: chhote steps mein ghumana (ramp), aur stream ka auto-restart. Asli hal: servos ko alag 5 V supply / powered USB hub.
- **Khud kaise karoge:** Motor/servo jab bhi kisi chhoti supply (USB) se chale aur device reset ho — sabse pehle power supply pe shak karo. `dmesg | tail` mein "new USB device" dobara dikhe = device reset hua.

### A11. Sense HAT
- **Kya hai:** Pi ke upar lagne wala board: temperature, humidity, pressure, accelerometer, LED matrix (8×8).
- **Dikkat:** Ye Pi ke CPU ke bilkul upar baithta hai, isliye 2–5 °C zyada temperature padhta hai. Hal (code mein): `t_hawa = t_sensor − (t_cpu − t_sensor) / 1.5`. BrickPi aur Sense HAT dono GPIO header lete hain — ek Pi pe ek hi (ya GPIO splitter).
- **Humne kaise use kiya:** `barn/sensehat_pub.py` — har 30 sec temp/humidity/pressure MQTT pe bhejta hai, aur LED pe THI ka rang dikhata hai.
- **Khud kaise karoge:** `from sense_hat import SenseHat; s = SenseHat(); print(s.get_temperature(), s.get_humidity())`.

### A12. Arduino UNO, MAX30102 (PPG), MPU6050
- **Arduino UNO:** ek microcontroller — OS nahi, bas ek program loop mein chalta hai. 2 KB RAM (bahut kam!).
- **MAX30102 / PPG:** Lal aur infrared LED skin pe chamakti hai; blood har dhadkan pe thoda zyada light sokhta hai. Is "pulse" ko padhke **heart rate**, aur lal vs infrared ke ratio se **SpO₂** (khoon mein oxygen) nikalta hai. Skin se contact na ho to reading 0/galat — isliye 0 ko "missing" maante hain, **nakli value kabhi nahi** (purane code mein 0 ki jagah 98 bhar diya jaata tha — wo hata diya).
- **Library ka chakkar:** purana code DFRobot library use karta tha jo sirf DFRobot ke specific board pe chalti hai. Generic board ke liye **SparkFun MAX3010x** library — humne wahi use ki.
- **MPU6050:** accelerometer + gyroscope. Activity = acceleration ka 1 g (gravity) se kitna farak; steps = acceleration ke peaks gin-na.
- **RAM ki seekh:** SpO₂ algorithm khud ~800 bytes leta hai; humara pehla UNO sketch 113% RAM maang raha tha (chalte hi crash). Buffers ki extra copy hata ke 94% kiya. Isliye asli collar ke liye ESP32 (320 KB RAM).
- **Khud kaise karoge:** PlatformIO ya Arduino IDE → board UNO → library install → upload → Serial Monitor 115200 pe JSON lines dekho.

### A13. ESP32 aur wireless collar
- **Kya hai:** ESP32 = Wi-Fi + Bluetooth wala sasta microcontroller (320 KB RAM). Collar ka asli dimaag.
- **Humne kaise use kiya:** `firmware/collar_esp32/` — MAX30102 + MPU6050 + DS18B20 (body temp) padhta hai, har 5 sec JSON MQTT pe bhejta hai. Missing sensor = `null`.
- **Wireless design** (bijli + data): neeche **Part C** dekho.

---

## Part B — Software

### B1. Git, GitHub, monorepo, CI
- **Kya hai:** Git = code ki history (har badlav "commit"). GitHub = online backup + sharing. **Monorepo** = ek hi repo mein saare parts (rover, backend, web, ML). **CI** = har push pe GitHub apne aap tests chalata hai.
- **Humne kaise use kiya:** Private repo `sidvashisth2005/lms-rover`; `.github/workflows/ci.yml` lint + 37 tests + website build chalata hai. `.gitignore` se secrets (`.env`) aur badi files bahar.
- **Khud kaise karoge:** `git status` → `git add -A` → `git commit -m "..."` → `git push`. **Kabhi `.env`/passwords commit mat karna** (purane repo mein Roboflow key commit ho gayi thi — wo galti thi).

### B2. WSL (Windows Subsystem for Linux)
- **Kya hai:** Windows ke andar asli Linux (Ubuntu). Servers (Postgres, Redis, MQTT) Linux pe best chalte hain.
- **Humne kya seekha:** (1) Idle WSL apne aap band ho jaata hai → services mar jaati hain → `start_services.ps1` ek chhupa `sleep infinity` chalata hai. (2) `networkingMode=mirrored` se Windows ka `localhost` WSL tak pahunchta hai. (3) `localhost` pehle IPv6 try karta hai jisse Postgres connection 60 sec atakta tha → `127.0.0.1` use karte hain.
- **Khud kaise karoge:** `wsl -d Ubuntu-24.04` (Linux shell), `wsl -l -v` (chal raha ya nahi).

### B3. MQTT (Mosquitto)
- **Kya hai:** IoT ke liye halka messaging system. Devices ek **topic** pe "publish" karte hain (jaise `lms/collar/C007/vitals`), jo bhi us topic ko "subscribe" kare use message mil jaata hai. Beech mein **broker** (Mosquitto) = post office. **QoS 1** = "pahunchne tak dobara bhejo".
- **Kis kaam aata hai:** Sensors → server, chhoti bandwidth, unreliable network.
- **Humne kaise use kiya:** Collars, barn station, rover, simulator sab publish karte hain; `backend/workers/ingest.py` subscribe karta hai. Password zaroori (bina password wale connection mana). Ingest ka "persistent session" — ingest restart ho to broker messages sambhal ke rakhta hai.
- **Seekh:** pehle simulator tez bhej raha tha aur ingest har message alag se Redis likh raha tha → 18,000 mein se sirf 7,000 pahunche. Hal: QoS 1 + batching.
- **Khud kaise karoge:** WSL mein `mosquitto_sub -u lms -P <pass> -t 'lms/#' -v` (sab messages dekho), `mosquitto_pub -u lms -P <pass> -t test -m hello`.

### B4. Redis Streams
- **Kya hai:** Redis = memory mein chalne wala tez database. **Stream** = ek line (queue) jisme messages aate hain; consumer padhke "ACK" karta hai. Crash ho gaya to bina-ACK messages dobara milte hain.
- **Kyun beech mein:** Agar database dheema/band ho, to MQTT ke messages kho na jayein — Redis unhe sambhal ke rakhta hai.
- **Humne kaise use kiya:** `lms:in` stream (ingest → processor), `lms:dead` (galat messages debug ke liye), pub/sub `lms:live` (dashboard ko live updates), `lms:alerts` (Telegram).
- **Khud kaise karoge:** `redis-cli XLEN lms:in`, `redis-cli XINFO GROUPS lms:in`.

### B5. PostgreSQL + TimescaleDB
- **Kya hai:** Postgres = SQL database. TimescaleDB = uska add-on, time-series data (har second ki readings) ke liye — **hypertable** data ko time ke tukdon mein todta hai, `time_bucket` se charts ke liye average nikalte hain, purana data apne aap delete (retention).
- **Kyun MongoDB nahi:** MongoDB 5+ Pi 4 ke CPU pe nahi chalta; aur time-series ke liye Timescale behtar.
- **Humne kaise use kiya:** `infra/schema.sql` — tables `vitals`, `env_readings`, `alerts`, `animals`... API `time_bucket` se 24 h ke charts ~300 points mein deti hai.
- **Khud kaise karoge:** WSL mein `sudo -u postgres psql -d lms`, phir `SELECT * FROM alerts ORDER BY ts DESC LIMIT 5;`.

### B6. Data contract (pydantic schemas)
- **Kya hai:** Ek jagah likha hua "message ka format" jise sab parts maante hain. Pydantic Python mein data check karta hai (galat value → error).
- **Humne kaise use kiya:** `common/schemas.py` — `VitalsMsg` (hr 0–300, temp 25–45...). Sensor kharab = `null`, **nakli value kabhi nahi**. HR 0 = missing.
- **Khud kaise karoge:** Naya sensor jodna ho to pehle schema mein field jodo, phir firmware aur backend.

### B7. Simulator (synthetic data)
- **Kya hai:** Nakli lekin realistic data banane wala program — jab asli data na ho.
- **Humne kaise use kiya:** `simulator/model.py` — 50 gaayein, har ek ka apna normal HR/temp, din-raat ka pattern (subah-shaam khane ke time zyada activity), garmi ka asar, aur **labelled** bimariyan (fever, lameness, estrus, sensor gayab, glitch). Labels se hi detector ka score nikalte hain.
- **Khud kaise karoge:** `python -m simulator.run offline --days 14 --out simulator/out/test` (CSV), ya `live --backfill-hours 48 --demo` (MQTT pe).

### B8. Anomaly detection (health alerts)
- **Kya hai:** "Normal se hatke" cheez pakadna. Humne explainable (samjhaye ja sakne wale) rules banaye, black-box model nahi.
- **Humne kaise use kiya** (`ml/anomaly/detector.py`):
  1. **Median filter** — 5 readings ka median; ek kharab reading (43.5 °C glitch) alarm nahi bajati.
  2. **Herd comparison** — gaay ka temp us waqt ke poore jhund ke median se compare. Garmi mein sab garam → fever ka galat alarm nahi.
  3. **Personal baseline** — har gaay ki usi ghante ki normal activity yaad rakhte hain; phir jhund ke ratio se bhaag (garmi mein sab kam chalte hain).
  4. **Persistence + cooldown** — fever 20 min tak rahe tabhi alert; same alert baar-baar nahi.
  5. **Offline** — collar 10 min chup aur baaki jhund bol raha ho.
- **Score kaise naapa:** **Recall** = asli bimariyon mein se kitni pakdi (fever 98%). **Precision** = alerts mein se kitne sach the (77–80%). Bugs theek karke precision 31% → 80% hua.
- **Khud kaise karoge:** `python -m ml.anomaly.evaluate simulator/out/eval_mild` — rule badlo, dobara chalao, number dekho.

### B9. THI (heat stress)
- **Kya hai:** Temperature-Humidity Index — garmi + nami milake gaay pe kitna stress. 72+ halka, 79+ moderate, 89+ severe.
- **Formula:** `THI = (1.8T+32) − (0.55 − 0.0055·RH)·(1.8T − 26)` (`common/schemas.py`).
- **Hysteresis:** 72 pe shuru, par 70 se neeche tabhi khatam — warna 72 ke aas-paas alert baar-baar chalu-band.

### B10. Disease model (classical ML)
- **Kya hai:** Symptoms (haan/na) → bimari. Naive Bayes, Random Forest jaise models.
- **Humne kya theek kiya:** Purane data mein 2044 mein se sirf 433 unique rows thi, aur test ki 11/26 rows training mein bhi thi → purani accuracy jhoothi thi. **Duplicates hataaye**, **cross-validation** (data ke 5 hisse, baari-baari test) kiya. Farmer 2–3 hi symptom chunta hai, isliye **symptom dropout** se train kiya (random symptoms hata ke copies). Nateeja: 2–3 symptoms pe top-3 mein 97.8% (purana 51%).
- **Calibration:** probability ko bharosemand banana (90% bole to sach mein ~90% sahi).
- **Khud kaise karoge:** `python -m ml.disease.train` — models compare karke best save karta hai.

### B11. Object detection — YOLO
- **Kya hai:** Image mein cheezein dhoondhkar unke charon taraf box banana + naam (cow 0.96). YOLO = "You Only Look Once" — ek hi pass mein sab boxes, isliye tez. YOLO11n = sabse chhota (nano) version.
- **Pretrained vs fine-tuned:** COCO dataset pe pehle se trained model 80 cheezein jaanta hai (cow, person...). **Fine-tuning** = apne data pe aage train karna taaki humare kaam mein behtar ho.
- **mAP50 kya hai:** Box 50%+ overlap ho to "sahi"; precision-recall ka average score (0–1). Humara gaay model: stock 0.631 → fine-tuned **0.726**.
- **Negatives:** ghode/bhed/kutte ki images bina gaay ke — taaki rover ghode ko gaay na samjhe.
- **Pseudo-labelling:** Open Images ki photos mein insaan label nahi the → bade model (YOLO11x) se auto-label kiye. Missing person label = model seekhta "insaan = background" = rover ke liye khatarnak.
- **Thermal guard:** Training laptop GPU pe; 78 °C pe pause, 70 °C pe chalu (`ml/detection/train.py`).
- **Khud kaise karoge:**
  ```
  from ultralytics import YOLO
  m = YOLO("yolo11n.pt"); m.train(data="data.yaml", epochs=60, imgsz=512, batch=8)
  ```
  `data.yaml` mein images/labels folders aur class names. Label file har image ke liye: `class x_center y_center width height` (0–1 mein).

### B12. ONNX, NCNN — model ko Pi pe chalana
- **Kya hai:** Training PyTorch mein hoti hai (bhaari). **ONNX** = model ka universal format jo OpenCV bhi chala leta hai. **NCNN** = mobile/ARM ke liye tez engine.
- **Humne kaise use kiya:** 320 px pe export. Pi 4 pe ONNX: ~121 ms/frame (~8 fps, 4 threads). Laptop CPU: ~10 ms. `rover/vision.py` OpenCV DNN se chalata hai.
- **Khud kaise karoge:** `model.export(format="onnx", imgsz=320)`.

### B13. Rover control — PD controller, tracker, safety, watchdog
- **PD controller:** Target frame ke beech se kitna hata hai (error) → utna mudo (**P** = proportional), aur error kitni tezi se badal raha (**D** = derivative, jhatke kam). Purane code ke KP 0.32, KD 0.18 reuse kiye.
- **Doori:** Box ki height frame ka kitna hissa → paas/door. Bahut paas = peeche, theek = ruko, door = aage.
- **IoU tracker:** Har frame mein boxes ko pichhle frame ke boxes se overlap (IoU) se milake same ID — rover ek hi gaay ke peeche rahe.
- **Safety layer** (`rover/safety.py`) — har motor command ka aakhri check: obstacle <20 cm, insaan bilkul paas (box >85% frame, ROVER_PERSON_STOP), battery <9 V → aage jaana band (peeche/mudna allowed).
- **Watchdog:** Manual mein 0.5 sec tak command na aaye → ruk jao (browser band ho gaya ya net gaya to rover bhaage nahi).
- **Mock:** Har driver ka nakli version, taaki laptop pe bina hardware test ho (`--mock --camera synthetic`).
- **Khud kaise karoge:** `python -m rover.server --mock --camera synthetic`, browser `http://localhost:8080/status`.

### B14. Backend API — FastAPI, JWT, WebSocket
- **FastAPI:** Python mein web API banane ka framework; `/docs` pe apne aap documentation.
- **JWT:** Login ke baad ek signed "token" milta hai; har request ke saath bhejo. Server signature check karta hai.
- **WebSocket:** Hamesha khula connection — server khud dashboard ko naya data "push" karta hai (refresh nahi).
- **Proxy:** Dashboard sirf API se baat karta hai; API Pi ke rover tak request le jaati hai — Pi internet pe kabhi seedha nahi khulta.
- **Khud kaise karoge:** `http://localhost:8000/docs` kholo, login karke endpoints try karo.

### B15. Dashboard — React + Vite + Tailwind
- **Kya hai:** React = UI components; Vite = tez dev server/build; Tailwind = CSS classes; Recharts = charts.
- **Humne kaise use kiya:** `web/src/pages/` — Herd, AnimalDetail, Alerts, Environment, Rover, Disease. `npm run build` → FastAPI hi website serve karta hai. Playwright (headless browser) se screenshots leke check kiya — isi se "63 galat offline alerts" wala bug pakda.
- **Khud kaise karoge:** `cd web; npm run dev` → `http://localhost:5173`, file save karo, page turant badlega.

### B16. Telegram bot alerts
- **Kya hai:** BotFather se bot banao → token. Bot API ko HTTP request bhejke message.
- **Humne kaise use kiya:** `backend/workers/notifier.py` — warning/critical alerts, har gaay+type 3 ghante mein ek baar.
- **Khud kaise karoge:** `https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<ID>&text=hi`. Token secret hai — chat/git mein kabhi nahi.

### B17. Firmware — PlatformIO
- **Kya hai:** Microcontrollers ke liye build tool (Arduino IDE ka advanced version) — libraries apne aap download, compile, upload.
- **Humne kaise use kiya:** Dono firmware compile check: ESP32 (RAM 14%), UNO (RAM 94%). Config/passwords `lms_config.h` mein (git se bahar). Seekh: library ki bhi `config.h` naam ki file thi → naam takraya → humari file `lms_config.h`.
- **Khud kaise karoge:** `pio run` (compile), `pio run -t upload` (board pe daalo), `pio device monitor` (serial dekho).

### B18. Hosting — Cloudflare Tunnel
- **Kya hai:** Laptop ki website ko internet pe ek https link dena, bina router settings ke.
- **Humne kaise use kiya:** `infra/tunnel.ps1` (bana hai, abhi chalaya nahi). Pehle lamba password rakhna — login ke baad rover bhi chalta hai.

### B19. Laptop ki suraksha (disk + garmi)
- C: drive pe sirf ~10 GB khaali tha → saare caches `D:\DevCache` pe (env variables), WSL disk D: pe.
- GPU training thermal guard ke saath; ab tak max 72 °C, koi pause nahi.

---

## Part C — Wireless collar: design

### C1. Bijli (power)
```
Li-ion / LiPo 3.7 V (2000 mAh)  →  TP4056 charger (USB-C)  →  3.3 V LDO  →  ESP32 + sensors
                                                     (battery voltage → ESP32 ADC pin, divider se)
```
Battery kitni chalegi = **capacity (mAh) ÷ average current (mA)**:

| Mode | Average current | 2000 mAh pe |
|---|---|---|
| ESP32 hamesha on, Wi-Fi har 5 sec | ~130–160 mA | ~12–15 ghante |
| Deep sleep: 1 min mein 10 sec naapo + bhejo | ~15–20 mA | ~4–5 din |
| ESP-NOW / LoRa + deep sleep | ~2–5 mA | ~2–4 hafte |

**Seekh:** Collar mein sabse bada kharcha radio (Wi-Fi) ka hai, sensors ka nahi. Isliye "kitni der jaagna" sabse zaroori design decision hai.

### C2. Data kaise jayega
| Tareeka | Range | Battery | Gateway chahiye? |
|---|---|---|---|
| Wi-Fi + MQTT | 30–50 m | Kam | Nahi (router) |
| ESP-NOW | 100–200 m | Achhi | Haan — ek ESP32, USB se Pi/laptop pe |
| BLE | 10–30 m | Achhi | Pi ka Bluetooth |
| LoRa | 1–5 km | Sabse achhi | LoRa module wala gateway |

Kisi bhi tareeke mein gateway ke baad sab same: **MQTT broker → ingest → Redis → processor → DB → dashboard/Telegram.** Backend kuch nahi badalta.

### C3. Plan
1. **Abhi:** Wi-Fi + MQTT (firmware ready), power bank se demo.
2. **Phir:** firmware mein deep sleep + battery %.
3. **Khet ke liye:** ESP-NOW (barn) ya LoRa (khula maidan) gateway.
4. **Manual zaroori:** laptop firewall mein TCP 1883 kholna (admin PowerShell):
   `New-NetFirewallRule -DisplayName "LMS MQTT" -Direction Inbound -Protocol TCP -LocalPort 1883 -Action Allow`

---

## Part D — Kya bacha hai

**Hardware:** motors ko dashboard se chalana + turn direction calibrate, follow mode, Sense HAT, UNO + MAX30102 (board type batana), rover jodna.

**Software (permission pe):** login token logs se hatana, rover server pe password, landing page ke nakli numbers, workers ka auto-restart, API tests, NCNN, IsolationForest, insaan model ko rover mein lagana.

**Tumhe khud:** firewall 1883, Telegram token badalna, Roboflow key revoke, lamba password, (optional) Tailscale.
