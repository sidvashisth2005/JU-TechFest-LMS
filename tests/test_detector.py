from common.schemas import EnvMsg, VitalsMsg
from ml.anomaly.detector import Detector

T0 = 1_790_000_000.0
MIN = 60.0


def feed_herd(det, t0, minutes, sick=None, sick_temp=40.2, glitch_at=None, n=10):
    """Ten cows at 38.6 C reporting every minute; optionally one sick cow."""
    alerts = []
    for i in range(minutes):
        t = t0 + i * MIN
        for c in range(n):
            aid = f"C{c:03d}"
            temp = 38.6 + 0.05 * (c % 3)
            if aid == sick:
                temp = sick_temp
            if glitch_at is not None and aid == "C001" and i == glitch_at:
                temp = 43.5
            alerts += det.on_vitals(VitalsMsg(animal_id=aid, ts=t, hr=65, body_temp=temp, activity=0.08))
    return alerts


def test_fever_alert_after_hold_time():
    alerts = feed_herd(Detector(), T0, 40, sick="C004")
    fever = [a for a in alerts if a.kind == "fever"]
    assert len(fever) == 1
    assert fever[0].animal_id == "C004"
    assert fever[0].severity == "critical"
    assert fever[0].ts - T0 >= 20 * MIN


def test_single_glitch_does_not_alert():
    alerts = feed_herd(Detector(), T0, 60, glitch_at=10)
    assert alerts == []


def test_whole_herd_warm_is_not_fever():
    det = Detector()
    alerts = []
    for i in range(60):
        for c in range(10):
            alerts += det.on_vitals(
                VitalsMsg(animal_id=f"C{c:03d}", ts=T0 + i * MIN, hr=70, body_temp=39.7, activity=0.08)
            )
    assert not [a for a in alerts if a.kind == "fever"]


def test_offline_collar():
    det = Detector()
    feed_herd(det, T0, 5)
    # C000 goes silent, the rest keep reporting
    for i in range(5, 30):
        for c in range(1, 10):
            det.on_vitals(VitalsMsg(animal_id=f"C{c:03d}", ts=T0 + i * MIN, hr=65, body_temp=38.6, activity=0.08))
    out = det.tick(T0 + 30 * MIN)
    assert [a.animal_id for a in out if a.kind == "sensor_offline"] == ["C000"]
    assert det.tick(T0 + 31 * MIN) == []  # no repeat while still offline
    # coming back clears it and records the resolution
    det.on_vitals(VitalsMsg(animal_id="C000", ts=T0 + 32 * MIN, hr=65, body_temp=38.6, activity=0.08))
    assert ("C000", "sensor_offline") not in det.open
    assert det.resolved[-1][:2] == ("C000", "sensor_offline")


def test_whole_herd_silent_is_not_per_collar_offline():
    det = Detector()
    feed_herd(det, T0, 5)
    assert det.tick(T0 + 60 * MIN) == []  # gateway/backfill gap, not ten broken collars


def test_heat_stress_escalates_and_clears():
    det = Detector()

    def env(t, temp, rh):
        return det.on_env(EnvMsg(station_id="barn1", ts=t, temp=temp, humidity=rh))

    assert env(T0, 22, 50) == []  # THI ~68
    first = env(T0 + 60, 30, 60)  # THI ~80 -> moderate
    assert first and first[0].kind == "heat_stress" and first[0].severity == "warning"
    assert env(T0 + 120, 29, 60) == []  # still stressed, no repeat
    assert env(T0 + 180, 21, 50) == []  # clears silently
    again = env(T0 + 240, 36, 70)  # THI ~92 -> severe
    assert again[0].severity == "critical"


class _AlwaysOdd:
    """Stand-in for the IsolationForest scorer: calls one cow unusual."""

    def judge(self, rows):
        return [(i == 0, -0.9 if i == 0 else -0.4) for i in range(len(rows))]


def test_multivariate_layer_needs_consecutive_unusual_scores():
    det = Detector(scorer=_AlwaysOdd())
    det.feature_rows = lambda ref: [("C000", [0.4, 9.0, 0.7, 0.8]), ("C001", [0.0, 0.0, 1.0, 1.0])]
    alerts = []
    for k in range(4):
        start = T0 + k * 15 * MIN
        feed_herd(det, start, 15)  # the herd keeps reporting; tick() only rescores on new data
        alerts += det.tick(start + 15 * MIN)
    odd = [a for a in alerts if a.kind == "unusual_pattern"]
    assert len(odd) == 1  # third unusual score in a row; not repeated while open
    assert odd[0].animal_id == "C000" and odd[0].source == "model" and odd[0].severity == "info"


def test_storm_risk_on_fast_pressure_fall_and_clears():
    det = Detector()

    def env(t, p):
        return det.on_env(EnvMsg(station_id="barn1", ts=t, pressure=p))

    out = []
    for i in range(0, 181, 10):  # 3 h, falling 4 hPa
        out += env(T0 + i * MIN, 1012 - 4 * i / 180)
    assert [a.kind for a in out] == ["storm_risk"] and out[0].station_id == "barn1"
    for i in range(190, 400, 10):  # steady again for 3 h
        out += env(T0 + i * MIN, 1008)
    assert ("barn1", "storm_risk") not in det.open


def test_pressure_needs_history_before_judging():
    det = Detector()
    assert det.on_env(EnvMsg(station_id="barn1", ts=T0, pressure=1012)) == []
    assert det.on_env(EnvMsg(station_id="barn1", ts=T0 + 30 * MIN, pressure=1005)) == []  # too little history


def test_station_events_raise_and_clear():
    from common.schemas import StationEventMsg

    det = Detector()

    def ev(t, kind, value=None):
        return det.on_station_event(StationEventMsg(station_id="barn1", ts=t, kind=kind, value=value))

    assert ev(T0, "tilted", 45)[0].kind == "station_tilted"
    assert ev(T0 + 5, "level") == [] and ("barn1", "station_tilted") not in det.open
    assert ev(T0, "gate_open", 120)[0].severity == "warning"
    ev(T0 + 60, "gate_closed")
    assert ("barn1", "gate_open") not in det.open
    bump = ev(T0, "knock", 1.2)
    assert bump[0].kind == "station_bumped" and bump[0].severity == "info"
    assert ev(T0 + 10, "knock", 0.9) == []  # one open bump alert, not one per knock
    det.tick(T0 + 31 * MIN)
    assert ("barn1", "station_bumped") not in det.open
    assert ev(T0, "hello") == [] and ev(T0, "ack") == []


def test_silent_station_goes_offline_and_comes_back():
    det = Detector()
    det.on_env(EnvMsg(station_id="barn1", ts=T0, temp=25, humidity=40))
    out = det.tick(T0 + 20 * MIN)
    assert out and out[0].kind == "sensor_offline" and out[0].station_id == "barn1"
    det.on_env(EnvMsg(station_id="barn1", ts=T0 + 21 * MIN, temp=25, humidity=40))
    assert ("barn1", "sensor_offline") not in det.open


def test_station_alerts_restored_after_restart_still_clear():
    """Processor restart: open alerts come back from the DB without the detector's memory."""
    det = Detector()
    det.open[("barn1", "station_bumped")] = T0
    det.open[("barn1", "heat_stress")] = T0
    det.tick(T0 + 31 * MIN)
    assert ("barn1", "station_bumped") not in det.open
    det.on_env(EnvMsg(station_id="barn1", ts=T0 + 32 * MIN, temp=20, humidity=50))  # THI ~66
    assert ("barn1", "heat_stress") not in det.open
