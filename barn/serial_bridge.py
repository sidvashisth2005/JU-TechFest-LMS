"""Forward JSON lines from a collar on USB serial to MQTT.

    python -m barn.serial_bridge                       # --port auto: first USB serial board found
    python -m barn.serial_bridge --port COM5           # laptop (Windows)
    python -m barn.serial_bridge --port /dev/ttyUSB0 --animal C001   # Pi

Works with the UNO backup collar (firmware/uno_bridge), an ESP32 collar on a USB cable (it
prints every reading on serial too, so this is the no-Wi-Fi fallback) and the ESP-NOW
gateway (firmware/gateway_espnow). Each JSON line {"animal_id": "...", "hr": ..., ...} is
validated against common.schemas.VitalsMsg and published to lms/collar/<animal_id>/vitals.
Lines with a station_id (the ESP8266 collar's DHT22 air reading) are EnvMsg and go to
lms/barn/<station_id>/env.
Status lines and garbage are logged and skipped. Values are passed through unchanged: no
offsets, no substitutes for missing readings.
"""

import argparse
import json
import logging
import time

from pydantic import ValidationError

from barn.mqtt import connect
from common import topics
from common.schemas import EnvMsg, VitalsMsg

log = logging.getLogger("serial_bridge")

# USB-serial chips on Arduino/ESP32 boards: Arduino, CH340, CP210x, FTDI, ESP32-C3/S3 native USB
KNOWN_VIDS = {0x2341: "Arduino", 0x2A03: "Arduino", 0x1A86: "CH340", 0x10C4: "CP210x", 0x0403: "FTDI", 0x303A: "ESP32"}


def find_port() -> str | None:
    """First serial port that looks like a microcontroller board."""
    from serial.tools import list_ports

    ports = sorted(list_ports.comports(), key=lambda p: p.device)
    for p in ports:
        if p.vid in KNOWN_VIDS:
            log.info("auto port: %s (%s, %s)", p.device, KNOWN_VIDS[p.vid], p.description)
            return p.device
    log.warning("no known board found; ports seen: %s", [f"{p.device} {p.description}" for p in ports] or "none")
    return None


def parse_line(line: str, default_animal: str | None) -> VitalsMsg | EnvMsg | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        log.warning("bad JSON: %s", line[:120])
        return None
    if "status" in data or "error" in data:
        log.info("device: %s", data)
        return None
    data["ts"] = time.time()  # the boards have no clock
    try:
        if "station_id" in data:
            return EnvMsg.model_validate(data)
        data.setdefault("animal_id", default_animal)
        return VitalsMsg.model_validate(data)
    except ValidationError as e:
        log.warning("rejected %s: %s", line[:120], e.errors()[0]["msg"])
        return None


def main():
    import serial  # pyserial (python3-serial on the Pi)

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="auto", help="auto | COM5 | /dev/ttyACM0 | /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--animal", default=None, help="animal id if the sketch doesn't send one")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    client = connect("lms-serial-bridge")
    while True:
        port = find_port() if args.port == "auto" else args.port
        if port is None:
            time.sleep(5)
            continue
        try:
            with serial.Serial(port, args.baud, timeout=2) as ser:
                log.info("reading %s", port)
                while True:
                    raw = ser.readline().decode(errors="ignore")
                    if not raw:
                        continue
                    msg = parse_line(raw, args.animal)
                    if isinstance(msg, EnvMsg):
                        client.publish(topics.barn_env(msg.station_id), msg.model_dump_json(exclude_none=True), qos=1)
                        log.info("%s temp=%s humidity=%s", msg.station_id, msg.temp, msg.humidity)
                    elif msg:
                        client.publish(
                            topics.collar_vitals(msg.animal_id), msg.model_dump_json(exclude_none=True), qos=1
                        )
                        log.info("%s hr=%s spo2=%s act=%s", msg.animal_id, msg.hr, msg.spo2, msg.activity)
        except serial.SerialException as e:
            log.error("serial error (%s), retrying in 5 s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
