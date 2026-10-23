from statistics import mean

from simulator.model import DAY, HOUR, Herd

T0 = 1_790_000_000.0  # fixed start so runs are reproducible


def readings(herd, animal_id, t0, hours, interval=300):
    out = []
    t = t0
    while t < t0 + hours * HOUR:
        msgs, _ = herd.step(t, interval)
        out += [m for m in msgs if m.animal_id == animal_id]
        t += interval
    return out


def test_same_seed_same_data():
    a, _ = Herd(5, seed=1).step(T0, 60)
    b, _ = Herd(5, seed=1).step(T0, 60)
    assert [m.model_dump() for m in a] == [m.model_dump() for m in b]


def test_healthy_cows_stay_in_normal_range():
    herd = Herd(20, seed=3, climate="cool", event_rate=0)
    temps, hrs = [], []
    t = T0
    while t < T0 + DAY:
        msgs, _ = herd.step(t, 600)
        temps += [m.body_temp for m in msgs]
        hrs += [m.hr for m in msgs if m.hr is not None]
        t += 600
    assert 38.0 < mean(temps) < 39.2
    assert 50 < mean(hrs) < 85


def test_fever_raises_temperature_and_heart_rate():
    base = Herd(3, seed=5, climate="cool", event_rate=0)
    sick = Herd(3, seed=5, climate="cool", event_rate=0)
    sick.force_event("C002", "fever", T0, 24)
    normal = readings(base, "C002", T0 + 4 * HOUR, 6)
    fever = readings(sick, "C002", T0 + 4 * HOUR, 6)
    assert mean(m.body_temp for m in fever) > mean(m.body_temp for m in normal) + 1.0
    hr_f = [m.hr for m in fever if m.hr]
    hr_n = [m.hr for m in normal if m.hr]
    assert mean(hr_f) > mean(hr_n) + 10


def test_dropout_sends_nothing():
    herd = Herd(2, seed=1, event_rate=0)
    herd.force_event("C001", "sensor_dropout", T0, 2)
    assert readings(herd, "C001", T0 + 10 * 60, 1) == []
    assert readings(herd, "C002", T0 + 10 * 60, 1) != []


def test_hot_climate_produces_heat_stress_labels():
    herd = Herd(2, seed=2, climate="hot", event_rate=0)
    t = T0
    while t < T0 + 3 * DAY:
        herd.step(t, 600)
        t += 600
    herd.finish(t)
    assert any(e.kind == "heat_stress" for e in herd.labels())
