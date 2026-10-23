"""Barn station logic that doesn't touch hardware, so it can be tested on the laptop.

Used by barn/sensehat_pub.py:
- KnockDetector   sudden jolt in the accelerometer (an animal bumped the station)
- TiltDetector    station leaning away from its mounting position (knocked over / loose)
- GateDetector    magnet on the gate moved away from the magnetometer (gate open)
- VibrationMeter  RMS of acceleration changes between readings
- Menu            joystick -> which LED screen to show / what to do
- drawing helpers for the 8x8 LED (spirit level, compass arrow)
"""

import math
from dataclasses import dataclass

Vec = tuple[float, float, float]


def norm(v: Vec) -> float:
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def angle_between(a: Vec, b: Vec) -> float:
    """Angle between two vectors in degrees."""
    na, nb = norm(a), norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    c = (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (na * nb)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


class KnockDetector:
    """A knock is |a| jumping away from its resting value. The resting value is learned
    (cheap accelerometers rarely read exactly 1 g), and one knock fires once per `quiet_s`."""

    def __init__(self, threshold_g: float = 0.5, quiet_s: float = 5.0):
        self.threshold = threshold_g
        self.quiet = quiet_s
        self.rest: float | None = None
        self.last = -1e18

    def update(self, ts: float, a: Vec) -> float | None:
        m = norm(a)
        if self.rest is None:
            self.rest = m
            return None
        dev = abs(m - self.rest)
        if dev < self.threshold / 3:
            self.rest += 0.02 * (m - self.rest)  # follow slow drift only while still
        if dev >= self.threshold and ts - self.last >= self.quiet:
            self.last = ts
            return dev
        return None


class TiltDetector:
    """Compares the smoothed gravity direction with the one at start-up (= how it is mounted)."""

    def __init__(self, tilt_deg: float = 30.0, level_deg: float = 12.0, hold_s: float = 3.0, warmup: int = 20):
        self.tilt_deg, self.level_deg, self.hold = tilt_deg, level_deg, hold_s
        self.warmup = warmup
        self._sum = [0.0, 0.0, 0.0]
        self._n = 0
        self.ref: Vec | None = None
        self.g: Vec | None = None
        self.angle = 0.0
        self.tilted = False
        self._since: float | None = None

    def update(self, ts: float, a: Vec) -> str | None:
        if self.ref is None:
            self._sum = [s + x for s, x in zip(self._sum, a, strict=True)]
            self._n += 1
            if self._n >= self.warmup:
                self.ref = (self._sum[0] / self._n, self._sum[1] / self._n, self._sum[2] / self._n)
                self.g = self.ref
            return None
        k = 0.2
        self.g = tuple(g + k * (x - g) for g, x in zip(self.g, a, strict=True))
        self.angle = angle_between(self.g, self.ref)
        want = self.angle >= self.tilt_deg if not self.tilted else self.angle > self.level_deg
        if want == self.tilted:
            self._since = None
            return None
        if self._since is None:
            self._since = ts
        if ts - self._since < self.hold:
            return None
        self._since = None
        self.tilted = want
        return "tilted" if want else "level"


class GateDetector:
    """A magnet fixed on the gate sits next to the station while the gate is closed. When the
    gate opens the magnetic field changes a lot; after `open_after_s` that is reported once.
    The field at start-up is taken as "closed", so start the station with the gate shut."""

    def __init__(
        self, threshold_ut: float = 25.0, open_after_s: float = 30.0, close_after_s: float = 3.0, warmup: int = 20
    ):
        self.threshold, self.open_after, self.close_after = threshold_ut, open_after_s, close_after_s
        self.warmup = warmup
        self._sum = [0.0, 0.0, 0.0]
        self._n = 0
        self.ref: Vec | None = None
        self.deviation = 0.0
        self.open = False
        self.opened_at: float | None = None
        self._since: float | None = None

    def update(self, ts: float, m: Vec) -> tuple[str, float] | None:
        """Returns ("gate_open", seconds open) or ("gate_closed", seconds it was open)."""
        if self.ref is None:
            self._sum = [s + x for s, x in zip(self._sum, m, strict=True)]
            self._n += 1
            if self._n >= self.warmup:
                self.ref = (self._sum[0] / self._n, self._sum[1] / self._n, self._sum[2] / self._n)
            return None
        self.deviation = norm((m[0] - self.ref[0], m[1] - self.ref[1], m[2] - self.ref[2]))
        away = self.deviation >= self.threshold
        if away == self.open:
            self._since = None
            return None
        if self._since is None:
            self._since = ts
        if ts - self._since < (self.open_after if away else self.close_after):
            return None
        start, self._since = self._since, None
        self.open = away
        if away:
            self.opened_at = start
            return ("gate_open", ts - start)
        was = ts - (self.opened_at or ts)
        self.opened_at = None
        return ("gate_closed", was)


class VibrationMeter:
    """RMS of the change in acceleration between samples, since the last read()."""

    def __init__(self):
        self.prev: Vec | None = None
        self.sq = 0.0
        self.n = 0

    def update(self, a: Vec) -> None:
        if self.prev is not None:
            d = norm((a[0] - self.prev[0], a[1] - self.prev[1], a[2] - self.prev[2]))
            self.sq += d * d
            self.n += 1
        self.prev = a

    def read(self) -> float | None:
        if not self.n:
            return None
        v = math.sqrt(self.sq / self.n)
        self.sq, self.n = 0.0, 0
        return v


# ---------------- joystick menu ----------------
SCREENS = ["home", "temp", "humidity", "thi", "dew", "pressure", "alerts", "level", "compass", "ip"]
HOLD_ACK_S = 2.0
IDLE_HOME_S = 30.0


@dataclass
class Menu:
    """left/right = previous/next screen, middle click = send a reading now,
    middle held 2 s = acknowledge the station's alerts, up/down = brighter/dimmer.
    After 30 s without input it goes back to the home screen."""

    index: int = 0
    last_input: float = 0.0
    _pressed_at: float | None = None
    _held_fired: bool = False

    @property
    def screen(self) -> str:
        return SCREENS[self.index]

    def handle(self, ts: float, direction: str, action: str) -> str | None:
        """Feed one joystick event; returns 'next'/'prev'/'publish'/'ack'/'bright'/'dim' or None."""
        self.last_input = ts
        if direction == "middle":
            if action == "pressed":
                self._pressed_at, self._held_fired = ts, False
            elif action == "held" and self._pressed_at is not None and not self._held_fired:
                if ts - self._pressed_at >= HOLD_ACK_S:
                    self._held_fired = True
                    return "ack"
            elif action == "released":
                fired, self._pressed_at = self._held_fired, None
                return None if fired else "publish"
            return None
        if action != "pressed":
            return None
        if direction == "right":
            self.index = (self.index + 1) % len(SCREENS)
            return "next"
        if direction == "left":
            self.index = (self.index - 1) % len(SCREENS)
            return "prev"
        if direction == "up":
            return "bright"
        if direction == "down":
            return "dim"
        return None

    def tick(self, ts: float) -> bool:
        """Go home after a while without input; True if the screen changed."""
        if self.index and ts - self.last_input > IDLE_HOME_S:
            self.index = 0
            return True
        return False


# ---------------- LED drawing (8x8, list of 64 RGB tuples) ----------------
OFF = (0, 0, 0)
SEVERITY_COLOURS = {"info": (0, 90, 220), "warning": (230, 110, 0), "critical": (220, 0, 0)}


def level_pixels(roll: float, pitch: float, ok_deg: float = 3.0) -> list:
    """Spirit level: a 2x2 bubble that moves with the tilt; green when level, red otherwise."""

    def wrap(d):
        return (d + 180) % 360 - 180

    r, p = wrap(roll), wrap(pitch)
    level = abs(r) < ok_deg and abs(p) < ok_deg
    colour = (0, 200, 0) if level else (220, 30, 0)
    # 15 deg of tilt moves the bubble to the edge
    x = 3 + max(-3, min(3, round(r / 5)))
    y = 3 + max(-3, min(3, round(p / 5)))
    px = [OFF] * 64
    for i in (3, 4):  # centre cross so the target is visible
        px[i * 8 + 0] = px[i * 8 + 7] = px[0 * 8 + i] = px[7 * 8 + i] = (40, 40, 40)
    for dy in (0, 1):
        for dx in (0, 1):
            px[(y + dy) * 8 + (x + dx)] = colour
    return px


def compass_pixels(heading: float) -> list:
    """Arrow from the centre towards magnetic north for a station facing `heading` degrees."""
    px = [OFF] * 64
    a = math.radians(-heading)  # north is at -heading relative to where the station faces (up)
    for step in range(0, 8):
        r = step * 0.5
        x = 3.5 + r * math.sin(a)
        y = 3.5 - r * math.cos(a)
        xi, yi = int(round(x - 0.5)), int(round(y - 0.5))
        if 0 <= xi < 8 and 0 <= yi < 8:
            px[yi * 8 + xi] = (220, 0, 0) if step >= 5 else (200, 200, 200)
    return px


def compass_label(heading: float | None) -> str:
    if heading is None:
        return "?"
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int(((heading % 360) + 22.5) // 45) % 8]
