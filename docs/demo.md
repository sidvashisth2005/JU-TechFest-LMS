# Hackathon demo plan (laptop server + Cloudflare quick tunnel)

The laptop runs everything: MQTT, Redis, PostgreSQL/TimescaleDB, the workers, the API and the dashboard. The Pi runs the rover and the barn sensors and talks to the laptop over the same Wi-Fi. A Cloudflare quick tunnel gives judges a public https link that works on their phones.

```
collar / UNO / Sense HAT ──MQTT──►  LAPTOP  ◄──HTTP── rover Pi (:8080)
  50 simulated cows ───────MQTT──►  (WSL services + workers + API :8000)
                                        │
                              Cloudflare tunnel ──► https://xxxx.trycloudflare.com (judges' phones)
```

## The day before

- [ ] `git pull`. Run `.venv\Scripts\python -m pytest`; everything must pass.
- [ ] `cd web; npm run build; cd ..` so the API serves the latest dashboard.
- [ ] Charge the BrickPi battery pack (above 10.5 V) and the phone used for the hotspot.
- [ ] Laptop power settings: never sleep when plugged in.
- [ ] Pi: `bash infra/pi/deploy.sh`, then `lms-pi.sh status`.
- [ ] Drive test with the tracks lifted. `ROVER_TURN_SIGN` and `ROVER_DRIVE_SIGN` must already be calibrated.
- [ ] Note the Pi IP at the venue Wi-Fi/hotspot. If it changed, update `ROVER_URL` in the laptop `.env` and `MQTT_HOST` in the Pi `.env`.
- [ ] Collar: follow docs/collar.md. Hotspot on 2.4 GHz, `scan` shows PPG + MPU6050, the USB backup (`-Collar auto`) tried once, and the UNO pre-flashed with the env for your PPG board.
- [ ] Record a 60 s backup video of the rover following a cow toy and of the dashboard live (in case anything fails on stage).

## Start (about 2 minutes before you present)

```powershell
.\infra\run_all.ps1 -Simulator -Tunnel          # add -MockRover only if the real rover is NOT available
.venv\Scripts\python infra\check_services.py     # all OK?
Get-Content logs\tunnel.log | Select-String trycloudflare   # the public link
```

On the Pi: `ssh pi@<pi-ip> "~/lms-rover/infra/pi/lms-pi.sh start all"`.
Open the public link on your phone and log in once to check it.

## Script (6 minutes)

| Time | Show | Say |
|---|---|---|
| 0:00 | Landing page | Problem: a sick cow is noticed late. The farmer sees a fever only when the cow stops eating. LMS watches every cow all the time. |
| 0:40 | Collar on the table (UNO/ESP32 + MAX30102 + MPU6050) | Heart rate, SpO₂, activity and steps go over Wi-Fi/ESP-NOW → MQTT. Missing values are sent as null and never invented. |
| 1:20 | Herd page (50 cows, colours) | 49 cows are simulated, plus our real collar. Data flows MQTT → Redis Stream → worker → TimescaleDB → live WebSocket. |
| 2:00 | Click a red cow → Animal page | Fever alert: temperature compared with the herd at the same moment, so a heat wave is not mistaken for fever. Measured on 21 simulated days: 98% of fevers caught, about 1.5 h after onset. |
| 2:40 | Alerts page + Telegram on phone | The same alert reaches the farmer's phone. Alerts clear themselves when the cow recovers. |
| 3:10 | Barn page | Sense HAT gives temperature and humidity. THI (temperature-humidity index) shows the heat-stress level. |
| 3:40 | Rover page (live video) | Pi + BrickPi3 + EV3 motors. YOLO11n finds cows (fine-tuned mAP50 0.73), and the rover follows a cow with a PD controller. |
| 4:30 | Put a hand in front of the ultrasonic / walk in front | Safety: it stops below 25 cm, stops for a close person, stops on low battery, and stops after 0.5 s without commands. |
| 5:10 | Disease page: tick 3 symptoms | Naive Bayes over 26 diseases: right answer in the top 3 97.8% of the time with only 2–3 symptoms. It is a suggestion, so call the vet. |
| 5:40 | Architecture slide (docs/architecture.md) | Today it runs on a laptop. The real deployment moves the same code to a cloud server plus one gateway Pi per farm (docs/deployment.md). |

## If something breaks

| Problem | Quick fix |
|---|---|
| Public link does not open | Use `http://localhost:8000` on the laptop screen. `.\infra\tunnel.ps1` makes a new link (the URL changes). |
| Rover page shows "rover unreachable" | Check the Pi IP (`hostname -I` on the Pi) and fix `ROVER_URL` in `.env`. The API reads `.env` at start, so stop and rerun run_all. Last resort: `-MockRover` and play the backup video. |
| Rover page says "rover rejected ROVER_TOKEN" | The token in the Pi `~/lms-rover/.env` differs from the laptop `.env`. Copy it, then `lms-pi.sh restart rover`. |
| Real collar shows nothing | Open the serial monitor. `mqtt ... rc=-2` means wrong IP or port 1883 is blocked in the laptop firewall. Fastest fix: USB cable + `.\infra\run_all.ps1 -Collar auto`. Still nothing? Use the UNO backup (docs/collar.md). HR stays null without good finger contact. |
| Rover turns the wrong way | Set `ROVER_TURN_SIGN=-1` in the Pi `.env`, then `lms-pi.sh restart rover`. |
| Rover camera black or frozen | `lms-pi.sh restart rover`. The Pixy resets if the servos jump, so do not move the pan-tilt during the demo. |
| Dashboard empty after a restart | The simulator backfills 48 h. Wait about a minute, or check `logs\simulator.log`. |
| Laptop very slow | Run `.\infra\stop_all.ps1`, then `.\infra\run_all.ps1 -Tunnel` without `-Simulator` (only real devices). |

## Questions judges ask (short answers)

- **Is the data real?** The real collar and Sense HAT are real. The other 49 cows are simulated, because a real herd was not available. The simulator has labelled illnesses, so we could measure recall and precision honestly.
- **Why not one model for everything?** Rules plus herd comparison are explainable to a vet. We tried an IsolationForest layer too: it found nothing extra in simulation, so it is off (`docs/ml.md`).
- **How long does the collar battery last?** In ESP-NOW sleep mode the radio is on for milliseconds each minute. Expect weeks on an 18650 cell instead of about a day in always-on Wi-Fi. Not measured yet on hardware.
- **Range?** Wi-Fi/ESP-NOW reach about 50–100 m outdoors. For a large farm, LoRa collars with a LoRa gateway (see deployment).
- **Cost?** ESP32 + MAX30102 + MPU6050 + DS18B20 + battery is roughly ₹1,000–1,500 per collar at hobby prices.
