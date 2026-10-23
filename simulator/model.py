"""Physiology model for a virtual dairy herd and its barn.

Each cow has its own baseline. Readings follow a daily rhythm (activity peaks around
morning and evening feeding, body temperature peaks late afternoon) and respond to barn
heat stress. Health events are injected at random and recorded as ground-truth labels so
anomaly detectors can be scored.

Normal ranges used (adult dairy cattle): heart rate 48-84 bpm, rectal temperature
38.0-39.3 C, SpO2 95-100 %.
"""

import math
import random
from dataclasses import dataclass, field

from common.schemas import EnvMsg, VitalsMsg, thi

DAY = 86400.0
HOUR = 3600.0

# kind -> (rate per cow per day, min duration h, max duration h)
EVENT_TYPES = {
    "fever": (0.010, 12, 48),
    "lameness": (0.006, 48, 120),
    "estrus": (0.015, 10, 18),
    "sensor_dropout": (0.010, 1, 6),
    "sensor_glitch": (0.020, 0.005, 0.02),  # ~1 bad sample
}
# what a detector is expected to raise for each event (None = should stay quiet)
EXPECTED_ALERT = {
    "fever": "fever",
    "lameness": "low_activity",
    "estrus": "high_activity",
    "sensor_dropout": "sensor_offline",
    "sensor_glitch": None,
    "heat_stress": "heat_stress",
}


@dataclass
class Event:
    animal_id: str | None  # None = whole herd (heat stress)
    kind: str
    start: float
    end: float
    severity: float = 1.0  # 0.5..1.5 scales the effect

    def active(self, t: float) -> bool:
        return self.start <= t < self.end

    def ramp(self, t: float, hours: float = 2.0) -> float:
        """0 -> 1 over the first `hours`, back to 0 over the last `hours`."""
        up = (t - self.start) / (hours * HOUR)
        down = (self.end - t) / (hours * HOUR)
        return max(0.0, min(1.0, up, down))


@dataclass
class Cow:
    animal_id: str
    hr_base: float
    temp_base: float
    activity_base: float
    steps_per_min: float
    spo2_base: float
    phase: float  # personal shift of the daily rhythm, hours
    battery: float = 4.15
    events: list[Event] = field(default_factory=list)


def daily_activity(hour: float) -> float:
    """Relative activity over the day: low at night, peaks around 6:00 and 17:00 feeding."""
    morning = math.exp(-((hour - 6.5) ** 2) / 3.0)
    evening = math.exp(-((hour - 17.0) ** 2) / 4.0)
    daytime = 0.35 if 7 <= hour <= 19 else 0.1
    return 0.15 + daytime + 0.9 * morning + 0.8 * evening


class Barn:
    """Barn air temperature/humidity with a daily cycle. `climate` sets the season."""

    CLIMATES = {"hot": (31.0, 6.0, 55.0), "mild": (24.0, 5.0, 60.0), "cool": (16.0, 4.0, 70.0)}

    def __init__(self, station_id: str, climate: str, rng: random.Random):
        self.station_id = station_id
        self.mean, self.amp, self.rh_mean = self.CLIMATES[climate]
        self.rng = rng
        self.day_offset = 0.0

    def read(self, t: float) -> EnvMsg:
        hour = (t % DAY) / HOUR
        # slow day-to-day drift so some days are hotter than others
        day = int(t // DAY)
        drift = 2.5 * math.sin(day * 1.3)
        temp = self.mean + drift + self.amp * math.sin(2 * math.pi * (hour - 9) / 24) + self.rng.gauss(0, 0.3)
        rh = self.rh_mean - 1.8 * (temp - self.mean) + self.rng.gauss(0, 2)
        pressure = 1010 + 3 * math.sin(2 * math.pi * t / (5 * DAY)) + self.rng.gauss(0, 0.3)
        return EnvMsg(
            station_id=self.station_id,
            ts=t,
            temp=round(temp, 2),
            humidity=round(min(100, max(5, rh)), 1),
            pressure=round(pressure, 1),
        )


class Herd:
    def __init__(self, n_cows: int = 50, seed: int = 7, climate: str = "hot", event_rate: float = 1.0):
        self.rng = random.Random(seed)
        self.event_rate = event_rate
        self.barn = Barn("barn1", climate, self.rng)
        self.cows = [self._new_cow(i + 1) for i in range(n_cows)]
        self.herd_events: list[Event] = []
        self._heat_start: float | None = None
        self._scheduled_until = 0.0

    def _new_cow(self, n: int) -> Cow:
        g = self.rng.gauss
        return Cow(
            animal_id=f"C{n:03d}",
            hr_base=min(80, max(52, g(66, 6))),
            temp_base=min(39.0, max(38.2, g(38.6, 0.18))),
            activity_base=max(0.03, g(0.08, 0.015)),
            steps_per_min=max(2, g(6, 1.5)),
            spo2_base=min(99, max(95, g(97, 1))),
            phase=g(0, 0.5),
        )

    # ---------- events ----------
    def schedule(self, t0: float, t1: float) -> None:
        """Draw random events starting in [t0, t1) for every cow."""
        days = (t1 - t0) / DAY
        for cow in self.cows:
            for kind, (rate, dmin, dmax) in EVENT_TYPES.items():
                n = self._poisson(rate * self.event_rate * days)
                for _ in range(n):
                    start = self.rng.uniform(t0, t1)
                    if any(e.active(start) for e in cow.events):
                        continue
                    dur = self.rng.uniform(dmin, dmax) * HOUR
                    cow.events.append(Event(cow.animal_id, kind, start, start + dur, self.rng.uniform(0.7, 1.3)))
        self._scheduled_until = max(self._scheduled_until, t1)

    def force_event(self, animal_id: str, kind: str, start: float, hours: float, severity: float = 1.0) -> Event:
        cow = self.cow(animal_id)
        e = Event(animal_id, kind, start, start + hours * HOUR, severity)
        cow.events.append(e)
        return e

    def _poisson(self, lam: float) -> int:
        n, p, limit = 0, 1.0, math.exp(-lam)
        while True:
            p *= self.rng.random()
            if p < limit:
                return n
            n += 1

    def cow(self, animal_id: str) -> Cow:
        return next(c for c in self.cows if c.animal_id == animal_id)

    def finish(self, t: float) -> None:
        """Close a heat-stress period still open at the end of a run."""
        if self._heat_start is not None:
            self.herd_events.append(Event(None, "heat_stress", self._heat_start, t))
            self._heat_start = None

    def labels(self) -> list[Event]:
        out = list(self.herd_events)
        for c in self.cows:
            out.extend(c.events)
        return sorted(out, key=lambda e: e.start)

    # ---------- readings ----------
    def step(self, t: float, interval: float) -> tuple[list[VitalsMsg], EnvMsg]:
        """Readings for time t. `interval` is the seconds covered by this message (for step counts)."""
        if t >= self._scheduled_until:
            self.schedule(t, t + DAY)
        env = self.barn.read(t)
        heat = self._track_heat(t, env)
        msgs = [m for cow in self.cows if (m := self._read_cow(cow, t, interval, heat)) is not None]
        return msgs, env

    def _track_heat(self, t: float, env: EnvMsg) -> float:
        """Return heat load above THI 72 and record herd-level heat-stress periods as labels."""
        index = thi(env.temp, env.humidity) or 0
        load = max(0.0, index - 72)
        # hysteresis: a period starts at THI 72 and ends only below 70, so noise doesn't flap it
        if load > 0 and self._heat_start is None:
            self._heat_start = t
        elif index < 70 and self._heat_start is not None:
            self.herd_events.append(Event(None, "heat_stress", self._heat_start, t))
            self._heat_start = None
        return load

    def _read_cow(self, cow: Cow, t: float, interval: float, heat: float) -> VitalsMsg | None:
        g = self.rng.gauss
        active = [e for e in cow.events if e.active(t)]
        kinds = {e.kind: e for e in active}
        if "sensor_dropout" in kinds:
            return None

        hour = ((t % DAY) / HOUR + cow.phase) % 24
        act = cow.activity_base * daily_activity(hour)
        temp = cow.temp_base + 0.25 * math.sin(2 * math.pi * (hour - 11) / 24)
        hr = cow.hr_base + 25 * (act - cow.activity_base * 0.6)
        spo2 = cow.spo2_base

        # environment: heat stress raises temperature and heart rate, lowers activity
        temp += 0.06 * heat
        hr += 0.8 * heat
        act *= max(0.5, 1 - 0.03 * heat)

        if (e := kinds.get("fever")) is not None:
            r = e.ramp(t) * e.severity
            temp += 1.6 * r
            hr += 20 * r
            act *= 1 - 0.5 * r
            spo2 -= 1.5 * r
        if (e := kinds.get("lameness")) is not None:
            r = e.ramp(t, 6) * e.severity
            act *= 1 - 0.55 * r
        if (e := kinds.get("estrus")) is not None:
            r = e.ramp(t, 1) * e.severity
            act *= 1 + 1.8 * r
            hr += 8 * r

        steps_rate = cow.steps_per_min * act / cow.activity_base
        if (e := kinds.get("lameness")) is not None:
            steps_rate *= 1 - 0.6 * e.ramp(t, 6) * e.severity
        steps = max(0, round(steps_rate * interval / 60 + g(0, 1)))

        hr = hr + g(0, 2.5)
        temp = temp + g(0, 0.06)
        act = max(0.0, act + g(0, 0.006))
        spo2_val: float | None = min(100.0, spo2 + g(0, 0.8))
        hr_val: float | None = hr
        if self.rng.random() < 0.08:  # poor optical contact: no HR/SpO2 this reading
            hr_val = spo2_val = None

        if "sensor_glitch" in kinds:  # one bad sample, a detector should not alarm on it
            temp = self.rng.choice([30.5, 43.5])
            hr_val = self.rng.choice([None, 190.0])

        cow.battery = max(3.3, cow.battery - 0.00000035 * interval)
        return VitalsMsg(
            animal_id=cow.animal_id,
            ts=t,
            hr=None if hr_val is None else round(hr_val, 1),
            spo2=None if spo2_val is None else round(spo2_val, 1),
            body_temp=round(temp, 2),
            activity=round(act, 4),
            steps=steps,
            battery=round(cow.battery, 3),
            rssi=int(g(-62, 6)),
        )
