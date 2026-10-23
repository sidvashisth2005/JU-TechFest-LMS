"""Publish barn temperature, humidity and pressure from a Sense HAT to MQTT.

    python -m barn.sensehat_pub [--station barn1] [--interval 30]

The Sense HAT sits on top of the Pi, so its sensors read warm from the CPU. The usual fix
(Raspberry Pi forums / astro-pi) is used: t_air = t_sensor - (t_cpu - t_sensor) / FACTOR,
with FACTOR calibrated once against a reference thermometer (--factor, default 1.5). The
LED matrix shows a coloured square for the heat-stress band so it can be read at a glance.
"""

import argparse
import logging
import time
from pathlib import Path

from barn.mqtt import connect
from common import topics
from common.schemas import EnvMsg, thi

log = logging.getLogger("sensehat")
BAND_COLOURS = [(72, (0, 120, 0)), (79, (200, 160, 0)), (89, (220, 80, 0)), (999, (200, 0, 0))]


def cpu_temp() -> float | None:
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
    except OSError:
        return None


def corrected_air_temp(sensor_c: float, cpu_c: float | None, factor: float) -> float:
    if cpu_c is None:
        return sensor_c
    return sensor_c - (cpu_c - sensor_c) / factor


def band_colour(index: float | None):
    if index is None:
        return (40, 40, 40)
    return next(colour for limit, colour in BAND_COLOURS if index < limit)


def main():
    from sense_hat import SenseHat

    ap = argparse.ArgumentParser()
    ap.add_argument("--station", default="barn1")
    ap.add_argument("--interval", type=float, default=30)
    ap.add_argument("--factor", type=float, default=1.5, help="CPU heat correction factor")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    sense = SenseHat()
    sense.low_light = True
    client = connect(f"lms-sensehat-{args.station}")
    while True:
        # humidity sensor's thermometer sits furthest from the CPU; average with the pressure one
        t_sensor = (sense.get_temperature_from_humidity() + sense.get_temperature_from_pressure()) / 2
        temp = corrected_air_temp(t_sensor, cpu_temp(), args.factor)
        msg = EnvMsg(
            station_id=args.station,
            ts=time.time(),
            temp=round(temp, 2),
            humidity=round(sense.get_humidity(), 1),
            pressure=round(sense.get_pressure(), 1),
        )
        client.publish(topics.barn_env(args.station), msg.model_dump_json(exclude_none=True), qos=1)
        index = thi(msg.temp, msg.humidity)
        sense.clear(band_colour(index))
        log.info("temp %.1f C  rh %.0f%%  THI %s", msg.temp, msg.humidity, index)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
