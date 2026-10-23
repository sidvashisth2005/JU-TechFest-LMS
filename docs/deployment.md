# Real deployment (after the hackathon)

The demo runs everything on one laptop. A real farm needs the server to stay up when the laptop is off. The collars need to work where there is no Wi-Fi, and the rover has to be reachable without being on the same network. The code does not change; only where it runs and how devices connect.

```
 FARM                                                  CLOUD (VPS, always on)
 collars ──ESP-NOW/LoRa──► gateway ESP32 ─USB─► gateway Pi          Mosquitto (TLS :8883)
 Sense HAT ───────────────────────────────────► (Mosquitto bridge) ═══TLS═══► Redis, TimescaleDB
 rover Pi (rover.server :8080) ◄────────── Tailscale ──────────────► workers, API, dashboard
                                                                     Caddy https://lms.example.com
```

## 1. Server: a small cloud VM

- **Options:** Oracle Cloud Always Free (Ampere ARM, 4 cores / 24 GB, free), or any ₹400–800/month VPS (2 vCPU, 4 GB) running Ubuntu 24.04.
- **Install:** `infra/wsl_install.sh` and `infra/setup.sh` are plain Ubuntu apt/systemd scripts and should run unchanged (tested only in WSL so far). Copy `.env` and change the passwords. Clone the repo (a deploy key or `gh` login is needed because it is private).
- **Processes:** run each process as a systemd service instead of `run_all.ps1`. The services are ingest, processor, notifier, and the API (`uvicorn backend.api.main:app --host 127.0.0.1 --port 8000`). The pattern is the same as `infra/pi/*.service`: `Restart=always` plus an `EnvironmentFile`.
- **Web:** put Caddy in front for automatic https (`lms.example.com { reverse_proxy 127.0.0.1:8000 }`). Or keep Cloudflare, using a named tunnel with your own domain (docs/hosting.md).
- **Firewall:** open only 443 (web) and 8883 (MQTT over TLS). Postgres and Redis stay on localhost.
- **Backups:** a nightly `pg_dump` copied off the server. TimescaleDB compression keeps a year of 1-minute data for 50 cows small (a few hundred MB).

## 2. MQTT over the internet: TLS + one bridge per farm

Collars should not each hold internet credentials. One **gateway Pi** per farm runs Mosquitto locally. Local devices publish to it exactly as today, and the gateway forwards everything to the cloud over one encrypted connection. If the internet drops, the bridge queues messages and sends them later.

Cloud `/etc/mosquitto/conf.d/lms.conf`:
```
listener 8883
certfile /etc/letsencrypt/live/mqtt.example.com/fullchain.pem
keyfile  /etc/letsencrypt/live/mqtt.example.com/privkey.pem
password_file /etc/mosquitto/passwd
allow_anonymous false
```

Gateway Pi `/etc/mosquitto/conf.d/bridge.conf`:
```
listener 1883
allow_anonymous false
password_file /etc/mosquitto/passwd

connection lms-cloud
address mqtt.example.com:8883
bridge_cafile /etc/ssl/certs/ca-certificates.crt
remote_username farm1-gateway
remote_password <from the cloud passwd file>
topic lms/# out 1
cleansession false
```

On the gateway Pi, `MQTT_HOST=127.0.0.1` in `~/lms-rover/.env`, so the Sense HAT and serial bridge publish locally.

## 3. Collar radio: what to use where

| Farm | Radio | Range | Battery | In this repo |
|---|---|---|---|---|
| Small shed, Wi-Fi everywhere | Wi-Fi + MQTT (`wifi_sleep`) | ~30–50 m indoors | days–weeks | `firmware/collar_esp32 -e wifi_sleep` |
| Barn + yard, no Wi-Fi needed | ESP-NOW to a gateway ESP32 | ~100 m line of sight | weeks | `-e espnow` + `firmware/gateway_espnow` |
| Open grazing, km range | LoRa (SX1276/SX1262, 868/865 MHz India) | 1–5 km | months | future: same JSON, a LoRa gateway feeding `barn/serial_bridge.py` |

For LoRa, the JSON should be packed into about 20 bytes (e.g. CBOR or fixed fields), because LoRa payloads are small and slow. The gateway unpacks it and publishes the same `VitalsMsg`, so nothing after the gateway changes.

## 4. Reaching the rover from anywhere: Tailscale

The rover Pi joins a Tailscale network (free for personal use) and gets a fixed `100.x.y.z` address that works across Wi-Fi, hotspot, or 4G:

```bash
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up     # on the Pi, once
```

Install Tailscale on the cloud server too, then set `ROVER_URL=http://<rover-tailscale-ip>:8080`. The rover port is never exposed to the internet. Calls still need `X-Rover-Token`, and only logged-in dashboard users reach the proxy.

## 5. Security checklist before going live

- Use long random values for `API_ADMIN_PASSWORD`, `API_JWT_SECRET`, `ROVER_TOKEN` and the MQTT passwords, with a different MQTT user per gateway.
- Revoke and regenerate any token that was ever printed or committed (the Telegram token and the old Roboflow key).
- Keep `.env` at `chmod 600` and out of git.
- Rate limit the login: the API already sleeps after a failed login. Add Caddy rate limiting for more.
- Update OS packages regularly. `unattended-upgrades` on the server and the Pis.

## 6. Scaling notes

- One processor handles a 50-cow herd at 1 reading/min/cow with large headroom. For many farms, run several processors, sharding the stream by farm or animal (the detector keeps per-animal state in memory).
- If the server dies, Redis Streams keep unprocessed messages, and the processor rereads pending entries after a restart.
- Real collar data should be used to re-tune the detector thresholds, and to re-test the IsolationForest layer (docs/ml.md).
