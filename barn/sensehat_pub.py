"""Barn station on a Raspberry Pi with a Sense HAT: every sensor, the LED and the joystick.

    python -m barn.sensehat_pub [--station barn1] [--interval 30]

Every --interval seconds it publishes air temperature, humidity, pressure and the station's
motion summary (tilt, vibration, compass heading, magnetic field) to lms/barn/{station}/env.
A background thread reads the IMU 25x a second and publishes events to lms/barn/{station}/event
as they happen: knock (bumped), tilted / level (knocked over / upright again), gate_open /
gate_closed (with BARN_GATE=1 and a magnet on the gate), plus hello (start-up, with its IP)
and ack (joystick). The backend sends back the station's open-alert count on
lms/barn/{station}/state, shown on the LED.

LED + joystick (barn/station.py Menu):
  home screen   BARN_LETTER (e.g. S) on the THI colour; "!" on the alert colour while alerts are open
  left / right  temp, humidity, THI, dew point, pressure (+3 h trend), alerts, spirit level,
                compass, IP address
  click         send a reading now           hold 2 s   acknowledge this station's alerts
  up / down     brighter / dimmer            30 s idle  back to the home screen

The Sense HAT sits on top of the Pi, so its sensors read warm from the CPU. The usual fix
(Raspberry Pi forums / astro-pi) is used: t_air = t_sensor - (t_cpu - t_sensor) / FACTOR,
with FACTOR calibrated once against a reference thermometer (--factor, default 1.5).

Settings (~/lms/.env): BARN_LETTER, BARN_BRIGHT=1, BARN_SCROLL (0.15 s per column),
BARN_KNOCK_G (0.5), BARN_TILT_DEG (30), BARN_GATE=1, BARN_GATE_UT (25), BARN_GATE_OPEN_S (30).
"""

import argparse
import logging
import os
import signal
import socket
import threading
import time
from collections import deque
from pathlib import Path

from barn.mqtt import connect
from barn.station import (
    SEVERITY_COLOURS,
    GateDetector,
    KnockDetector,
    Menu,
    TiltDetector,
    VibrationMeter,
    compass_pixels,
    level_pixels,
    norm,
)
from common import topics
from common.schemas import EnvMsg, StationEventMsg, StationStateMsg, dew_point

log = logging.getLogger("sensehat")
BAND_COLOURS = [(72, (0, 120, 0)), (79, (200, 160, 0)), (89, (220, 80, 0)), (999, (200, 0, 0))]
# screen -> (icon letter, colour) shown between scrolls of its value
ICONS = {
    "temp": ("T", (230, 90, 0)),
    "humidity": ("H", (0, 120, 230)),
    "thi": ("I", (200, 160, 0)),
    "dew": ("D", (0, 170, 170)),
    "pressure": ("P", (150, 0, 200)),
    "alerts": ("A", (220, 0, 0)),
    "ip": ("@", (200, 200, 200)),
    "level": ("L", (0, 200, 0)),
    "compass": ("C", (220, 0, 0)),
}
# name scrolled before each value, so you know what the number is
LABELS = {
    "temp": "TEMP",
    "humidity": "HUMIDITY",
    "thi": "THI",
    "dew": "DEW POINT",
    "pressure": "PRESSURE",
    "alerts": "ALERTS",
    "level": "LEVEL",
    "compass": "COMPASS",
    "ip": "IP",
}


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


def letter_colour(background) -> tuple:
    """Blue on light backgrounds (yellow), white on the rest. Never black: black = LED off."""
    return (0, 0, 255) if sum(background) > 300 else (255, 255, 255)


def ip_address() -> str:
    """This Pi's LAN address (no packet is sent; UDP connect only picks the route)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "no network"


def message_frames(sense, text: str, colour, back=(0, 0, 0)) -> list:
    """The frames SenseHat.show_message would draw, built up front so the main loop can show
    them one at a time and still react to the joystick between frames."""
    flat = [[0, 0, 0]] * 64
    for ch in text:
        flat = flat + sense._trim_whitespace(sense._get_char_pixels(ch)) + [[0, 0, 0]] * 8
    flat += [[0, 0, 0]] * 64
    px = [list(colour) if p == [255, 255, 255] else list(back) for p in flat]
    return [px[i * 8 : i * 8 + 64] for i in range(len(px) // 8 - 8)]


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


class Imu(threading.Thread):
    """Reads accelerometer, gyro and magnetometer ~25x/s; runs the detectors; keeps a summary."""

    def __init__(self, sense, on_event, hz: float = 25):
        super().__init__(daemon=True)
        self.sense, self.on_event, self.period = sense, on_event, 1 / hz
        self.knock = KnockDetector(env_float("BARN_KNOCK_G", 0.5))
        self.tilt = TiltDetector(env_float("BARN_TILT_DEG", 30))
        self.gate = (
            GateDetector(env_float("BARN_GATE_UT", 25), env_float("BARN_GATE_OPEN_S", 30))
            if os.environ.get("BARN_GATE") == "1"
            else None
        )
        self.vib = VibrationMeter()
        self.lock = threading.Lock()
        self.roll = self.pitch = self.yaw = 0.0
        self.mag: float | None = None
        self.ok = False

    def run(self):
        self.sense.set_imu_config(True, True, True)  # compass, gyro, accelerometer
        while True:
            t0 = time.time()
            try:
                o = self.sense.get_orientation_degrees()
                a = self.sense.get_accelerometer_raw()
                m = self.sense.get_compass_raw()
            except Exception:  # an I2C hiccup must not kill the station
                log.exception("IMU read failed")
                time.sleep(1)
                continue
            av, mv = (a["x"], a["y"], a["z"]), (m["x"], m["y"], m["z"])
            with self.lock:
                self.roll, self.pitch, self.yaw = o["roll"], o["pitch"], o["yaw"]
                self.mag = norm(mv)
                self.vib.update(av)
                self.ok = True
            g = self.knock.update(t0, av)
            if g is not None:
                self.on_event("knock", g)
            t = self.tilt.update(t0, av)
            if t:
                self.on_event(t, self.tilt.angle)
            if self.gate:
                ev = self.gate.update(t0, mv)
                if ev:
                    self.on_event(*ev)
            time.sleep(max(0.0, self.period - (time.time() - t0)))

    def summary(self) -> dict:
        with self.lock:
            if not self.ok:
                return {}
            vib = self.vib.read()
            return {
                "tilt": round(self.tilt.angle, 1) if self.tilt.ref else None,
                "vibration": None if vib is None else round(min(vib, 20), 4),
                "heading": round(self.yaw % 360, 1),
                "magnetic": None if self.mag is None else round(min(self.mag, 5000), 1),
            }


class Station:
    def __init__(self, args):
        from sense_hat import SenseHat

        self.args = args
        self.sense = SenseHat()
        self.sense.low_light = os.environ.get("BARN_BRIGHT", "0") != "1"
        self.letter = (args.letter or "")[:1]
        self.ip = ip_address()
        self.state = StationStateMsg()
        self.latest: EnvMsg | None = None
        self.pressures: deque = deque()  # (ts, hPa) for the 3 h trend on the LED
        self.menu = Menu()
        self.frame = None  # what the LED shows now, to redraw only on change
        self.next_scroll = 0.0
        self.scroll_speed = env_float("BARN_SCROLL", 0.15)  # seconds per column; higher = slower
        self.scroll: list | None = None  # frames of the message being scrolled
        self.scroll_i = 0
        self.scroll_at = 0.0
        self.intro_done = False  # level/compass name shown since entering the screen
        self.stop = False
        self.client = connect(
            f"lms-sensehat-{args.station}", subscribe={topics.barn_state(args.station): self.on_state}
        )
        self.imu = Imu(self.sense, self.send_event)

    # ---------- MQTT ----------
    def on_state(self, payload: bytes) -> None:
        try:
            self.state = StationStateMsg.model_validate_json(payload)
            self.frame = None  # redraw the home screen
        except ValueError:
            log.warning("bad state message: %r", payload[:100])

    def send_event(self, kind: str, value: float | None = None, detail: str | None = None) -> None:
        ev = StationEventMsg(
            station_id=self.args.station,
            kind=kind,
            value=None if value is None else round(value, 2),
            detail=detail,
        )
        self.client.publish(topics.barn_event(self.args.station), ev.model_dump_json(exclude_none=True), qos=1)
        log.info("event %s %s %s", kind, "" if value is None else f"{value:.2f}", detail or "")

    def read_and_publish(self) -> None:
        s = self.sense
        # humidity sensor's thermometer sits furthest from the CPU; average with the pressure one.
        # The LPS25H returns 0 until its first conversion is done, so skip zeros.
        t_hum, t_pres = s.get_temperature_from_humidity(), s.get_temperature_from_pressure()
        t_sensor = (t_hum + t_pres) / 2 if t_pres else t_hum
        temp = corrected_air_temp(t_sensor, cpu_temp(), self.args.factor)
        pressure = s.get_pressure()
        msg = EnvMsg(
            station_id=self.args.station,
            ts=time.time(),
            temp=round(temp, 2),
            humidity=round(s.get_humidity(), 1),
            pressure=round(pressure, 1) if pressure else None,
            **self.imu.summary(),
        )
        self.client.publish(topics.barn_env(self.args.station), msg.model_dump_json(exclude_none=True), qos=1)
        self.latest = msg
        if msg.pressure:
            self.pressures.append((msg.ts, msg.pressure))
            while self.pressures and self.pressures[0][0] < msg.ts - 3 * 3600:
                self.pressures.popleft()
        self.frame = None
        log.info(
            "temp %.1f C  rh %.0f%%  THI %s  tilt %s  vib %s",
            msg.temp,
            msg.humidity,
            msg.thi,
            msg.tilt,
            msg.vibration,
        )

    # ---------- LED ----------
    def show(self, key, draw) -> None:
        """Draw only when what should be on the LED changed."""
        if key != self.frame:
            self.frame = key
            draw()

    def text_for(self, screen: str) -> str:
        """Label + value, e.g. "TEMP 27.2C"."""
        return f"{LABELS[screen]} {self.value_for(screen)}"

    def value_for(self, screen: str) -> str:
        m = self.latest
        if screen == "ip":
            return self.ip
        if screen == "alerts":
            return str(self.state.open_alerts)
        if m is None:
            return "..."
        if screen == "temp":
            return f"{m.temp:.1f}C"
        if screen == "humidity":
            return f"{m.humidity:.1f}%"
        if screen == "thi":
            return f"{m.thi:.1f}"
        if screen == "dew":
            dp = dew_point(m.temp, m.humidity)
            return "?" if dp is None else f"{dp:.1f}C"
        if screen == "pressure":
            if m.pressure is None:
                return "?"
            text = f"{m.pressure:.1f}hPa"
            if len(self.pressures) > 1 and self.pressures[-1][0] - self.pressures[0][0] > 3600:
                text += f" {m.pressure - self.pressures[0][1]:+.1f}"
            return text
        return ""

    def render(self, now: float) -> None:
        screen, s = self.menu.screen, self.sense
        if screen == "home":
            if self.state.open_alerts:
                bg = SEVERITY_COLOURS.get(self.state.worst or "warning", (230, 110, 0))
                self.show(("alert", bg), lambda: s.show_letter("!", text_colour=(255, 255, 255), back_colour=bg))
                return
            bg = band_colour(self.latest.thi if self.latest else None)
            if self.letter:
                self.show(
                    ("letter", bg), lambda: s.show_letter(self.letter, text_colour=letter_colour(bg), back_colour=bg)
                )
            else:
                self.show(("fill", bg), lambda: s.clear(bg))
            return
        icon, colour = ICONS[screen]
        live = screen in ("level", "compass")  # graphics: name once, then the live picture
        if self.scroll is None and now >= self.next_scroll and not (live and self.intro_done):
            text = LABELS[screen] if live else self.text_for(screen)
            self.scroll, self.scroll_i, self.scroll_at = message_frames(s, text, colour), 0, now
        if self.scroll is None and live:
            with self.imu.lock:
                px = level_pixels(self.imu.roll, self.imu.pitch) if screen == "level" else compass_pixels(self.imu.yaw)
            self.show(("px", tuple(px)), lambda: s.set_pixels(px))
            return
        if self.scroll is not None:
            # one column per call, so a joystick press switches screens mid-message
            if now >= self.scroll_at:
                rotation = s.rotation
                s.set_rotation((rotation + 270) % 360, redraw=False)  # same as show_message
                s.set_pixels(self.scroll[self.scroll_i])
                s.set_rotation(rotation, redraw=False)
                self.scroll_i += 1
                self.scroll_at = now + self.scroll_speed
                if self.scroll_i >= len(self.scroll):
                    self.scroll, self.next_scroll, self.frame = None, now + 1.5, None
                    self.intro_done = True
            return
        self.show(("icon", screen), lambda: s.show_letter(icon, text_colour=colour))

    def flash(self, colour, seconds: float = 0.3) -> None:
        self.sense.clear(colour)
        time.sleep(seconds)
        self.frame = None

    # ---------- main loop ----------
    def run(self) -> None:
        self.imu.start()
        self.send_event("hello", detail=f"ip {self.ip}")
        # say where to find us (headless Pi); the IMU settles meanwhile
        self.sense.show_message(f"IP {self.ip}", scroll_speed=self.scroll_speed, text_colour=(0, 200, 255))
        next_pub = time.time()
        self.sense.stick.get_events()  # drop presses from before start
        while not self.stop:
            now = time.time()
            if now >= next_pub:
                try:
                    self.read_and_publish()
                except Exception:
                    log.exception("reading failed")
                next_pub = now + self.args.interval
            for e in self.sense.stick.get_events():
                action = self.menu.handle(e.timestamp, e.direction, e.action)
                if action in ("next", "prev"):
                    self.scroll, self.next_scroll, self.frame = None, 0, None
                    self.intro_done = False
                elif action == "publish":
                    self.flash((0, 60, 200), 0.15)
                    next_pub = 0
                elif action == "ack":
                    self.send_event("ack")
                    self.state = StationStateMsg(open_alerts=0)  # the backend confirms within a moment
                    self.flash((0, 200, 0), 0.6)
                elif action in ("bright", "dim"):
                    self.sense.low_light = action == "dim"
                    self.frame = None
            if self.menu.tick(now):
                self.frame = None
            self.render(now)
            time.sleep(0.02)
        self.sense.clear()
        self.client.loop_stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--station", default="barn1")
    ap.add_argument("--interval", type=float, default=30)
    ap.add_argument("--factor", type=float, default=1.5, help="CPU heat correction factor")
    ap.add_argument(
        "--letter",
        default=os.environ.get("BARN_LETTER") or None,
        help="letter on the THI colour on the home screen (else a plain square)",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    station = Station(args)

    def _stop(*_):
        station.stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    station.run()


if __name__ == "__main__":
    main()
