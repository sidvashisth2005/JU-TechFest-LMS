"""Streaming anomaly detector used both by the live processor and by offline evaluation.

Feed it messages in time order (`on_vitals`, `on_env`, `on_station_event`, `tick`). It returns
AlertMsg objects.

How it decides:
1. Glitch filter - each signal is the median of the last few readings, so one bad sample
   (a loose sensor reading 43.5 C) never raises an alarm.
2. Herd comparison - an animal's temperature and heart rate are compared with the herd
   median at the same moment. Heat waves move the whole herd, so they don't look like fever.
3. Personal baseline - activity is compared with the animal's own usual level for that hour
   of day (cows are far more active at feeding time than at night).
4. Persistence - a condition must hold for a while before it alerts, and an alert for the
   same animal and kind is not repeated until it clears and a cooldown passes.
5. Optional multivariate model (ml/anomaly/multivariate.py) - an IsolationForest trained on
   healthy herd-relative readings flags combinations no single rule covers ("unusual_pattern",
   info level). Pass `scorer=` to enable it; tick() scores the whole herd in one batch.
"""

import statistics
from collections import deque
from dataclasses import dataclass, field

from common.schemas import AlertMsg, EnvMsg, StationEventMsg, VitalsMsg, thi

MIN = 60.0
HOUR = 3600.0


@dataclass
class Config:
    smooth_n: int = 5  # readings in the median filter
    # fever: absolute temperature AND margin above the herd
    fever_temp: float = 39.5
    fever_margin: float = 0.6
    fever_critical_temp: float = 40.0
    fever_hold: float = 20 * MIN
    # tachycardia
    hr_high: float = 92
    hr_margin: float = 15
    hr_hold: float = 30 * MIN
    # activity relative to the animal's own hour-of-day baseline
    activity_window: float = 6 * HOUR
    low_activity_ratio: float = 0.6
    high_activity_window: float = 2 * HOUR
    high_activity_ratio: float = 1.7
    high_activity_min_excess: float = 0.025  # g above normal; ignores tiny night-time ratios
    baseline_alpha: float = 0.15  # weight of one new hourly value in the baseline
    baseline_min_days: int = 2  # own baseline for an hour of day once it has seen that hour this often
    # environment (THI)
    thi_mild: float = 72
    thi_moderate: float = 79
    thi_severe: float = 89
    thi_clear: float = 70
    # environment (air pressure): a fall of 3 hPa in 3 h is "falling rapidly" in weather reports
    pressure_window: float = 3 * HOUR
    pressure_min_span: float = 1.5 * HOUR  # need this much history before judging the trend
    storm_drop: float = 3.0
    storm_clear: float = 1.5
    # barn station (Sense HAT IMU)
    knock_clear: float = 30 * MIN  # a bump alert closes itself after this long without bumps
    station_offline_after: float = 15 * MIN
    # device health
    offline_after: float = 10 * MIN
    battery_low: float = 3.5
    cooldown: float = 6 * HOUR
    # multivariate model (only used when a scorer is given)
    model_every: float = 15 * MIN  # score the herd this often
    model_hold_n: int = 3  # consecutive unusual scores before an alert


class _Window:
    """Sliding time window keeping running sums of actual and expected activity."""

    def __init__(self, span: float):
        self.span = span
        self.q: deque = deque()  # (ts, actual, expected)
        self.actual = 0.0
        self.expected = 0.0

    def add(self, ts: float, actual: float, expected: float) -> None:
        self.q.append((ts, actual, expected))
        self.actual += actual
        self.expected += expected
        while self.q and self.q[0][0] < ts - self.span:
            _, x, e = self.q.popleft()
            self.actual -= x
            self.expected -= e

    def covered(self) -> float:
        return self.q[-1][0] - self.q[0][0] if self.q else 0.0

    def ratio(self) -> float | None:
        return self.actual / self.expected if self.expected > 1e-9 else None


@dataclass
class _Animal:
    temp: deque = field(default_factory=lambda: deque(maxlen=5))
    hr: deque = field(default_factory=lambda: deque(maxlen=5))
    win_long: _Window | None = None  # activity vs expected over activity_window
    win_short: _Window | None = None  # same over high_activity_window
    last_seen: float = 0.0
    temp_s: float | None = None
    hr_s: float | None = None
    since: dict = field(default_factory=dict)  # condition -> ts it started
    # hour-of-day activity baseline
    hour_sum: float = 0.0
    hour_n: int = 0
    hour_key: int | None = None
    baseline: dict = field(default_factory=dict)  # hour -> mean activity
    baseline_n: dict = field(default_factory=dict)  # hour -> times learned
    ratio_long: float | None = None  # latest activity/normal ratios, shared for herd comparison
    ratio_short: float | None = None
    model_bad: int = 0  # consecutive unusual multivariate scores


class Detector:
    def __init__(self, config: Config | None = None, scorer=None):
        self.cfg = config or Config()
        self.scorer = scorer  # ml.anomaly.multivariate.Scorer or None
        self._model_at = -1e18
        self.animals: dict[str, _Animal] = {}
        self.open: dict[tuple[str, str], float] = {}  # (subject, kind) -> ts raised
        self.closed: dict[tuple[str, str], float] = {}  # (subject, kind) -> ts cleared
        self.herd_hour: dict[int, list[float]] = {}  # hour -> recent herd activity means
        self.herd_hour_median: dict[int, float] = {}
        self._herd_cache: tuple[float, float | None, float | None] = (-1e18, None, None)
        self._herd_act_cache: tuple[float, float | None, float | None] = (-1e18, None, None)
        self.thi_level: dict[str, str | None] = {}
        self.pressure: dict[str, deque] = {}  # station -> (ts, hPa) over pressure_window
        self.station_seen: dict[str, float] = {}
        self.last_knock: dict[str, float] = {}
        # (subject, kind, ts) of alerts that cleared by themselves; the caller drains this
        self.resolved: list[tuple[str, str, float]] = []

    # ---------------- public API ----------------
    def on_vitals(self, m: VitalsMsg) -> list[AlertMsg]:
        cfg = self.cfg
        a = self.animals.get(m.animal_id)
        if a is None:
            a = self.animals[m.animal_id] = _Animal(
                temp=deque(maxlen=cfg.smooth_n),
                hr=deque(maxlen=cfg.smooth_n),
                win_long=_Window(cfg.activity_window),
                win_short=_Window(cfg.high_activity_window),
            )
        out: list[AlertMsg] = []

        if (m.animal_id, "sensor_offline") in self.open:
            out += self._clear(m.animal_id, "sensor_offline", m.ts)
        a.last_seen = m.ts

        if m.body_temp is not None:
            a.temp.append(m.body_temp)
            a.temp_s = statistics.median(a.temp) if len(a.temp) >= 3 else None
        if m.hr is not None:
            a.hr.append(m.hr)
            a.hr_s = statistics.median(a.hr) if len(a.hr) >= 3 else None
        if m.activity is not None:
            # each reading is paired with what is normal for this animal at that time of day,
            # so windows that straddle the steep feeding peaks compare like with like
            expected = self._expected_at(a, m.ts)
            if expected is not None:
                a.win_long.add(m.ts, m.activity, expected)
                a.win_short.add(m.ts, m.activity, expected)
            self._update_baseline(m.animal_id, a, m.ts, m.activity)

        herd_temp, herd_hr = self._herd_medians(m.ts)
        out += self._check_fever(m, a, herd_temp)
        out += self._check_hr(m, a, herd_hr)
        out += self._check_activity(m, a)
        if m.battery is not None and m.battery < cfg.battery_low:
            out += self._raise(
                m.animal_id, "battery_low", "info", m.ts, f"Collar battery low ({m.battery:.2f} V)", m.battery
            )
        return out

    def on_env(self, e: EnvMsg) -> list[AlertMsg]:
        out: list[AlertMsg] = []
        if (e.station_id, "sensor_offline") in self.open:
            out += self._clear(e.station_id, "sensor_offline", e.ts, station=True)
        self.station_seen[e.station_id] = max(self.station_seen.get(e.station_id, 0.0), e.ts)
        if e.pressure is not None:
            out += self._check_pressure(e)
        return out + self._check_thi(e)

    def _check_pressure(self, e: EnvMsg) -> list[AlertMsg]:
        cfg = self.cfg
        q = self.pressure.setdefault(e.station_id, deque())
        q.append((e.ts, e.pressure))
        while q and q[0][0] < e.ts - cfg.pressure_window:
            q.popleft()
        if q[-1][0] - q[0][0] < cfg.pressure_min_span:
            return []
        drop = max(p for _, p in q) - e.pressure
        if drop >= cfg.storm_drop:
            hours = cfg.pressure_window / HOUR
            return self._raise(
                e.station_id,
                "storm_risk",
                "warning",
                e.ts,
                f"Air pressure falling fast ({drop:.1f} hPa in {hours:.0f} h): storm or heavy rain likely",
                drop,
                station=True,
            )
        if drop < cfg.storm_clear:
            return self._clear(e.station_id, "storm_risk", e.ts, station=True)
        return []

    def on_station_event(self, ev: StationEventMsg) -> list[AlertMsg]:
        """Knocks, tilt and gate events from a barn station's motion sensors."""
        sid, ts = ev.station_id, ev.ts
        if ev.kind == "knock":
            self.last_knock[sid] = ts
            g = f" ({ev.value:.1f} g)" if ev.value is not None else ""
            return self._raise(sid, "station_bumped", "info", ts, f"Barn station was bumped{g}", ev.value, station=True)
        if ev.kind == "tilted":
            deg = f" {ev.value:.0f} deg" if ev.value is not None else ""
            return self._raise(
                sid,
                "station_tilted",
                "warning",
                ts,
                f"Barn station tilted{deg}: knocked over or loose?",
                ev.value,
                station=True,
            )
        if ev.kind == "level":
            return self._clear(sid, "station_tilted", ts, station=True)
        if ev.kind == "gate_open":
            mins = f" for {ev.value / MIN:.0f} min" if ev.value else ""
            return self._raise(sid, "gate_open", "warning", ts, f"Barn gate open{mins}", ev.value, station=True)
        if ev.kind == "gate_closed":
            return self._clear(sid, "gate_open", ts, station=True)
        return []

    def _check_thi(self, e: EnvMsg) -> list[AlertMsg]:
        cfg = self.cfg
        index = thi(e.temp, e.humidity)
        if index is None:
            return []
        level = self.thi_level.get(e.station_id)
        if level is None and (e.station_id, "heat_stress") in self.open:
            level = "info"  # alert restored from the DB after a restart; lets it clear below thi_clear
        rank = {None: 0, "info": 1, "warning": 2, "critical": 3}
        if index >= cfg.thi_severe:
            target = "critical"
        elif index >= cfg.thi_moderate:
            target = "warning"
        elif index >= cfg.thi_mild:
            target = "info"
        else:
            target = level
        # escalate immediately; de-escalate only by clearing completely below thi_clear
        if index < cfg.thi_clear:
            new = None
        elif rank[target] > rank[level]:
            new = target
        else:
            new = level
        if new == level:
            return []
        self.thi_level[e.station_id] = new
        out = self._clear(e.station_id, "heat_stress", e.ts, station=True)
        if new is not None:
            label = {"info": "mild", "warning": "moderate", "critical": "severe"}[new]
            out += self._raise(
                e.station_id,
                "heat_stress",
                new,
                e.ts,
                f"{label.capitalize()} heat stress in barn (THI {index:.0f})",
                index,
                station=True,
                force=True,
            )
        return out

    def tick(self, now: float) -> list[AlertMsg]:
        """Call periodically (e.g. every minute) to catch collars that went silent.

        Silence is measured against the newest reading from any collar, not the wall clock:
        replayed or backfilled history, or a gateway outage that silences every collar at
        once, must not flag the whole herd as offline.
        """
        out = []
        newest = max((a.last_seen for a in self.animals.values()), default=0.0)
        ref = min(now, newest)
        for animal_id, a in self.animals.items():
            if a.last_seen and ref - a.last_seen > self.cfg.offline_after:
                mins = (ref - a.last_seen) / MIN
                out += self._raise(
                    animal_id, "sensor_offline", "warning", now, f"No data from collar for {mins:.0f} min"
                )
        for sid, seen in self.station_seen.items():
            if now - seen > self.cfg.station_offline_after:
                mins = (now - seen) / MIN
                out += self._raise(
                    sid, "sensor_offline", "info", now, f"No data from barn station for {mins:.0f} min", station=True
                )
        for (sid, kind), raised in list(self.open.items()):
            # after a restart the last knock is unknown: count from when the alert was raised
            if kind == "station_bumped" and now - self.last_knock.get(sid, raised) > self.cfg.knock_clear:
                out += self._clear(sid, "station_bumped", now, station=True)
        if self.scorer is not None and ref - self._model_at >= self.cfg.model_every:
            self._model_at = ref
            out += self._check_model(ref)
        return out

    def feature_rows(self, ref: float) -> list[tuple[str, list[float]]]:
        """Herd-relative features of every animal heard from in the last 15 min.

        (temp - herd temp, HR - herd HR, 6 h activity vs normal / herd, 2 h activity vs normal / herd)
        Relative values keep heat waves and feed changes, which move the whole herd, from looking odd.
        """
        herd_temp, herd_hr = self._herd_medians(ref)
        herd_long, herd_short = self._herd_activity(ref)
        if None in (herd_temp, herd_hr, herd_long, herd_short):
            return []
        rows = []
        for animal_id, a in self.animals.items():
            if ref - a.last_seen > 15 * MIN or None in (a.temp_s, a.hr_s, a.ratio_long, a.ratio_short):
                continue
            rows.append(
                (
                    animal_id,
                    [a.temp_s - herd_temp, a.hr_s - herd_hr, a.ratio_long / herd_long, a.ratio_short / herd_short],
                )
            )
        return rows

    def _check_model(self, ref: float) -> list[AlertMsg]:
        rows = self.feature_rows(ref)
        if not rows:
            return []
        out = []
        for (animal_id, feats), (unusual, score) in zip(rows, self.scorer.judge([f for _, f in rows]), strict=True):
            a = self.animals[animal_id]
            if not unusual:
                a.model_bad = 0
                out += self._clear(animal_id, "unusual_pattern", ref)
                continue
            a.model_bad += 1
            if a.model_bad >= self.cfg.model_hold_n:
                dt, dhr, act, _ = feats
                out += self._raise(
                    animal_id,
                    "unusual_pattern",
                    "info",
                    ref,
                    f"Unusual combination of vitals (temp {dt:+.1f} C, HR {dhr:+.0f} vs herd, activity {act:.0%})",
                    score,
                )
        return out

    # ---------------- checks ----------------
    def _check_fever(self, m, a, herd_temp) -> list[AlertMsg]:
        cfg = self.cfg
        if a.temp_s is None or herd_temp is None:
            return []
        cond = a.temp_s >= cfg.fever_temp and a.temp_s - herd_temp >= cfg.fever_margin
        if not self._held(a, "fever", cond, m.ts, cfg.fever_hold):
            return self._clear(m.animal_id, "fever", m.ts) if not cond else []
        sev = "critical" if a.temp_s >= cfg.fever_critical_temp else "warning"
        return self._raise(
            m.animal_id,
            "fever",
            sev,
            m.ts,
            f"Fever: {a.temp_s:.1f} C ({a.temp_s - herd_temp:+.1f} vs herd)",
            a.temp_s,
        )

    def _check_hr(self, m, a, herd_hr) -> list[AlertMsg]:
        cfg = self.cfg
        if a.hr_s is None or herd_hr is None:
            return []
        cond = a.hr_s >= cfg.hr_high and a.hr_s - herd_hr >= cfg.hr_margin
        if not self._held(a, "tachycardia", cond, m.ts, cfg.hr_hold):
            return self._clear(m.animal_id, "tachycardia", m.ts) if not cond else []
        return self._raise(
            m.animal_id,
            "tachycardia",
            "warning",
            m.ts,
            f"High heart rate: {a.hr_s:.0f} bpm ({a.hr_s - herd_hr:+.0f} vs herd)",
            a.hr_s,
        )

    def _check_activity(self, m, a) -> list[AlertMsg]:
        cfg = self.cfg
        out = []
        a.ratio_long = a.win_long.ratio() if a.win_long.covered() >= cfg.activity_window * 0.9 else None
        a.ratio_short = a.win_short.ratio() if a.win_short.covered() >= cfg.high_activity_window * 0.75 else None
        herd_long, herd_short = self._herd_activity(m.ts)
        # relative to the herd right now: heat or a feed change slows every cow at once
        ratio = a.ratio_long / herd_long if a.ratio_long is not None and herd_long else a.ratio_long
        if ratio is not None:
            if ratio < cfg.low_activity_ratio:
                out += self._raise(
                    m.animal_id,
                    "low_activity",
                    "warning",
                    m.ts,
                    f"Activity {ratio:.0%} of normal over 6 h (lameness or illness?)",
                    ratio,
                )
            elif ratio > cfg.low_activity_ratio + 0.15:
                out += self._clear(m.animal_id, "low_activity", m.ts)

        ratio = a.ratio_short / herd_short if a.ratio_short is not None and herd_short else a.ratio_short
        if ratio is not None:
            n = len(a.win_short.q)
            excess = (a.win_short.actual - a.win_short.expected) / n if n else 0.0
            if ratio > cfg.high_activity_ratio and excess >= cfg.high_activity_min_excess:
                out += self._raise(
                    m.animal_id,
                    "high_activity",
                    "info",
                    m.ts,
                    f"Activity {ratio:.1f}x normal for 2 h (possible estrus)",
                    ratio,
                )
            elif ratio < cfg.high_activity_ratio - 0.3:
                out += self._clear(m.animal_id, "high_activity", m.ts)
        return out

    # ---------------- baselines ----------------
    def _update_baseline(self, animal_id: str, a: _Animal, ts: float, value: float) -> None:
        hour_index = int(ts // HOUR)
        if a.hour_key is None:
            a.hour_key = hour_index
        if hour_index != a.hour_key:
            if a.hour_n:
                mean = a.hour_sum / a.hour_n
                hod = a.hour_key % 24
                # don't learn from hours when this animal already has an activity alert open
                abnormal = (animal_id, "low_activity") in self.open or (
                    animal_id,
                    "high_activity",
                ) in self.open
                if not abnormal:
                    prev = a.baseline.get(hod)
                    alpha = self.cfg.baseline_alpha
                    a.baseline[hod] = mean if prev is None else (1 - alpha) * prev + alpha * mean
                    a.baseline_n[hod] = a.baseline_n.get(hod, 0) + 1
                herd = self.herd_hour.setdefault(hod, [])
                herd.append(mean)
                if len(herd) > 500:
                    del herd[:-500]
                self.herd_hour_median[hod] = statistics.median(herd)
            a.hour_key, a.hour_sum, a.hour_n = hour_index, 0.0, 0
        a.hour_sum += value
        a.hour_n += 1

    def _expected_at(self, a: _Animal, ts: float) -> float | None:
        """Normal activity for this animal at this hour of day (herd value until it has history)."""
        hod = int(ts // HOUR) % 24
        if a.baseline_n.get(hod, 0) >= self.cfg.baseline_min_days:
            return a.baseline[hod]
        return self.herd_hour_median.get(hod)

    def _herd_activity(self, ts: float) -> tuple[float | None, float | None]:
        """Herd median of the animals' activity ratios (long, short window), cached per minute."""
        cached_at, lr, sr = self._herd_act_cache
        if ts - cached_at < MIN:
            return lr, sr
        fresh = [a for a in self.animals.values() if ts - a.last_seen < 15 * MIN]
        longs = [a.ratio_long for a in fresh if a.ratio_long is not None]
        shorts = [a.ratio_short for a in fresh if a.ratio_short is not None]
        lr = statistics.median(longs) if len(longs) >= 5 else None
        sr = statistics.median(shorts) if len(shorts) >= 5 else None
        self._herd_act_cache = (ts, lr, sr)
        return lr, sr

    def _herd_medians(self, ts: float) -> tuple[float | None, float | None]:
        cached_at, tm, hm = self._herd_cache
        if ts - cached_at < MIN:
            return tm, hm
        fresh = [a for a in self.animals.values() if ts - a.last_seen < 15 * MIN]
        temps = [a.temp_s for a in fresh if a.temp_s is not None]
        hrs = [a.hr_s for a in fresh if a.hr_s is not None]
        tm = statistics.median(temps) if len(temps) >= 5 else None
        hm = statistics.median(hrs) if len(hrs) >= 5 else None
        self._herd_cache = (ts, tm, hm)
        return tm, hm

    # ---------------- alert bookkeeping ----------------
    def _held(self, a: _Animal, cond_name: str, cond: bool, ts: float, hold: float) -> bool:
        if not cond:
            a.since.pop(cond_name, None)
            return False
        start = a.since.setdefault(cond_name, ts)
        return ts - start >= hold

    def _raise(self, subject, kind, severity, ts, message, value=None, station=False, force=False) -> list[AlertMsg]:
        key = (subject, kind)
        if key in self.open and not force:
            return []
        if not force and ts - self.closed.get(key, -1e18) < self.cfg.cooldown:
            return []
        self.open[key] = ts
        source = "baseline" if kind in ("low_activity", "high_activity") else "rule"
        if kind == "unusual_pattern":
            source = "model"
        return [
            AlertMsg(
                ts=ts,
                kind=kind,
                severity=severity,
                message=message,
                value=None if value is None else round(float(value), 3),
                animal_id=None if station else subject,
                station_id=subject if station else None,
                source=source,
            )
        ]

    def _clear(self, subject, kind, ts, station=False) -> list[AlertMsg]:
        key = (subject, kind)
        if key not in self.open:
            return []
        del self.open[key]
        self.closed[key] = ts
        self.resolved.append((subject, kind, ts))
        return []
