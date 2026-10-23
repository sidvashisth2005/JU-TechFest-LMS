# Autostart: laptop + Pi apne aap chalu

Ek command se poora LMS do mode mein switch hota hai:

| Mode | Kya hota hai |
|---|---|
| **on** (autostart) | Windows login ke ~30 sec baad laptop pe database, MQTT, workers aur website chupchaap chalu. Pi power on hote hi rover server (camera, YOLO, motors, safety) chalu. Bas `http://localhost:8000` kholo aur login karo. |
| **off** (normal) | Kuch bhi apne aap nahi chalta. Jab chahiye tab haath se chalao (neeche dekho). |

## Ek command

Repo folder `D:\Project\LMS` mein PowerShell khol ke:

```powershell
.\infra\autostart.ps1            # toggle: on hai to off, off hai to on
.\infra\autostart.ps1 on         # pakka on
.\infra\autostart.ps1 off        # pakka off
.\infra\autostart.ps1 status     # sirf dekhna
```

Output aisa aata hai:

```
mode: on
laptop autostart: ON
pi rover at boot: ON
```

- Command chalate waqt **Pi on aur same Wi-Fi pe hona chahiye**, kyunki Pi ka setting SSH se badalta hai. Pi band ho to warning aayegi; laptop wala hissa phir bhi badal jaayega. Pi on karke dobara chala do.
- Ye sirf **agli login / agla boot** badalta hai. Jo abhi chal raha hai woh chalta rahega.
- Ek PowerShell "execution policy" error aaye to: `powershell -ExecutionPolicy Bypass -File .\infra\autostart.ps1 on`

## Andar kya hota hai

**Laptop** (`infra/autostart.ps1`)
- `on`: Windows Startup folder mein shortcut `LMS backend.lnk` banata hai
  (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`). Woh login pe hidden `infra/run_all.ps1` chalata hai:
  - `infra/start_services.ps1` → WSL mein PostgreSQL + TimescaleDB, Redis, Mosquitto (+ WSL keepalive)
  - `ingest`, `processor`, `notifier` workers
  - API + dashboard on port **8000** (`web/dist` bhi yahi serve karta hai)
  - har part `backend.supervise` ke andar chalta hai: crash ho to khud restart. Logs: `logs\*.log`
- `off`: shortcut hata deta hai.

**Pi** (`infra/pi/lms-pi.sh` ke through, SSH se)
- `on`: `lms-pi.sh enable rover` → systemd service `lms-rover` boot pe chalegi (crash pe 3 s mein restart).
- `off`: `lms-pi.sh disable rover`.
- Service settings Pi pe `~/lms-rover/.env` mein: `ROVER_CAMERA=picamera2`,
  `ROVER_DETECTOR=yolo:ml/detection/models/coco_yolo11n.onnx`, `ROVER_TOKEN`, `MQTT_HOST` (laptop IP),
  `ROVER_DRIVE_SIGN`, `ROVER_TURN_SIGN`.
- Pi hotspot se apne aap judta hai (NetworkManager autoconnect).

Rover boot pe **idle** mode mein shuru hota hai: motors sirf dashboard ke command pe chalte hain, aur bina
`ROVER_TOKEN` ke koi command nahi le sakta.

## Normal mode mein haath se chalana

```powershell
.\infra\run_all.ps1        # laptop: services + workers + dashboard
.\infra\stop_all.ps1       # laptop: sab band
```

Pi pe (ya laptop se `ssh pi@<pi-ip> "<command>"`):

```bash
~/lms-rover/infra/pi/lms-pi.sh start rover     # abhi chalao
~/lms-rover/infra/pi/lms-pi.sh stop rover      # band
~/lms-rover/infra/pi/lms-pi.sh status
~/lms-rover/infra/pi/lms-pi.sh logs rover      # live log (Ctrl+C)
```

## Dhyaan rakhne wali baatein

- **Pi ka IP**: laptop dashboard Pi ko `.env` ke `ROVER_URL` se dhoondhta hai (abhi
  `http://10.207.184.209:8080`). Hotspot / Wi-Fi badalne se IP badle to:
  1. Pi pe `hostname -I` se naya IP dekho
  2. laptop `.env` mein `ROVER_URL` update karo
  3. Pi ki `~/lms-rover/.env` mein `MQTT_HOST` = laptop ka naya IP (`ipconfig` → Wi-Fi IPv4)
  4. `.\infra\stop_all.ps1` phir `.\infra\run_all.ps1`, aur Pi pe `lms-pi.sh restart rover`

  (`lmspi` naam se bhi Pi milta hai, lekin har lookup ~2.7 s leta hai, isliye IP use karte hain.)
- **Rover service ke chalte camera / BrickPi uske paas hain.** `rpicam-still` ya `pi-tools/drive_test.py`
  chalane se pehle `lms-pi.sh stop rover` karo.
- **Dashboard login**: laptop `.env` mein `API_ADMIN_USER` / `API_ADMIN_PASSWORD`. Password badla to
  API restart (`stop_all.ps1` → `run_all.ps1`).
- **Internet pe kholna** (Cloudflare tunnel, `run_all.ps1 -Tunnel`) autostart ka hissa **nahi** hai, jaan
  boojh ke. Public karne se pehle lamba password rakho.
- **Battery**: BrickPi battery 9.0 V se neeche ho to rover drive karne se mana karta hai.
- LAN devices (Pi, ESP collar) ke MQTT ke liye laptop firewall rule ek baar: `infra/firewall_mqtt.ps1`
  (admin). Ho chuka hai.

## Files

| File | Kaam |
|---|---|
| `infra/autostart.ps1` | on / off / toggle / status |
| `infra/run_all.ps1`, `infra/stop_all.ps1` | laptop backend start / stop |
| `infra/start_services.ps1`, `infra/stop_services.ps1` | sirf WSL services |
| `infra/pi/lms-pi.sh` | Pi services control |
| `infra/pi/lms-rover.service` | Pi systemd unit |
| `infra/firewall_mqtt.ps1` | laptop firewall rule for port 1883 |
