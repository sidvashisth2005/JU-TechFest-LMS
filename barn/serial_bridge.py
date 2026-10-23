"""Forward JSON lines from the Arduino UNO collar prototype to MQTT.

    python -m barn.serial_bridge --port /dev/ttyACM0 [--animal C001]

The UNO (firmware/uno_bridge) prints {"animal_id": "...", "hr": ..., ...} every 5 s. Each
line is validated against common.schemas.VitalsMsg and published to
lms/collar/<animal_id>/vitals. Status lines and garbage are logged and skipped. Values are
passed through unchanged: no offsets, no substitutes for missing readings.
"""

import argparse
import json
import logging
import time

from pydantic import ValidationError

from barn.mqtt import connect
from common import topics
from common.schemas import VitalsMsg

log = logging.getLogger("serial_bridge")


def parse_line(line: str, default_animal: str | None) -> VitalsMsg | None:
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
    data.setdefault("animal_id", default_animal)
    data["ts"] = time.time()  # the UNO has no clock
    try:
        return VitalsMsg.model_validate(data)
    except ValidationError as e:
        log.warning("rejected %s: %s", line[:120], e.errors()[0]["msg"])
        return None


def main():
    import serial  # pyserial (python3-serial on the Pi)

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--animal", default=None, help="animal id if the sketch doesn't send one")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    client = connect("lms-serial-bridge")
    while True:
        try:
            with serial.Serial(args.port, args.baud, timeout=2) as ser:
                log.info("reading %s", args.port)
                while True:
                    raw = ser.readline().decode(errors="ignore")
                    if not raw:
                        continue
                    msg = parse_line(raw, args.animal)
                    if msg:
                        client.publish(
                            topics.collar_vitals(msg.animal_id), msg.model_dump_json(exclude_none=True), qos=1
                        )
                        log.info("%s hr=%s spo2=%s act=%s", msg.animal_id, msg.hr, msg.spo2, msg.activity)
        except serial.SerialException as e:
            log.error("serial error (%s), retrying in 5 s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
