"""Barn station logic (barn/station.py): no Sense HAT needed."""

from barn.station import (
    SCREENS,
    GateDetector,
    KnockDetector,
    Menu,
    TiltDetector,
    VibrationMeter,
    compass_label,
    compass_pixels,
    level_pixels,
)

FLAT = (0.0, 0.0, 0.98)


def test_knock_fires_once_then_waits():
    k = KnockDetector(threshold_g=0.5, quiet_s=5)
    assert k.update(0, FLAT) is None
    assert k.update(0.04, FLAT) is None
    hit = k.update(0.08, (0.9, 0.3, 1.6))
    assert hit is not None and hit > 0.5
    assert k.update(0.12, (0.9, 0.3, 1.6)) is None  # same knock
    assert k.update(6, (0.9, 0.3, 1.6)) is not None  # a new one later


def test_knock_ignores_small_wobbles():
    k = KnockDetector()
    for i in range(100):
        assert k.update(i * 0.04, (0.02 * (i % 3), 0.0, 0.98 + 0.03 * (i % 2))) is None


def test_tilt_needs_to_hold_and_comes_back_level():
    t = TiltDetector(tilt_deg=30, level_deg=12, hold_s=3, warmup=5)
    for i in range(5):
        t.update(i * 0.04, FLAT)
    leaning = (0.75, 0.0, 0.65)  # ~49 deg
    events = [t.update(1 + i * 0.04, leaning) for i in range(200)]
    assert events.count("tilted") == 1 and t.tilted
    back = [t.update(10 + i * 0.04, FLAT) for i in range(200)]
    assert back.count("level") == 1 and not t.tilted


def test_short_tilt_is_ignored():
    t = TiltDetector(hold_s=3, warmup=5)
    for i in range(5):
        t.update(i * 0.04, FLAT)
    assert all(t.update(1 + i * 0.04, (0.9, 0, 0.3)) is None for i in range(25))  # 1 s only


def test_gate_open_after_delay_and_closed():
    g = GateDetector(threshold_ut=25, open_after_s=30, close_after_s=3, warmup=5)
    closed, opened = (40.0, 5.0, -20.0), (5.0, 5.0, -20.0)
    for i in range(5):
        g.update(i, closed)
    assert all(g.update(10 + i, opened) is None for i in range(30))
    ev = g.update(40, opened)
    assert ev and ev[0] == "gate_open" and ev[1] >= 30
    assert g.update(100, closed) is None
    ev = g.update(103, closed)
    assert ev and ev[0] == "gate_closed" and ev[1] > 60


def test_vibration_rms_and_reset():
    v = VibrationMeter()
    assert v.read() is None
    for a in [FLAT, (0.1, 0, 0.98), FLAT, (0.1, 0, 0.98)]:
        v.update(a)
    assert abs(v.read() - 0.1) < 1e-9
    assert v.read() is None


def test_menu_cycles_clicks_holds_and_goes_home():
    m = Menu()
    assert m.handle(0, "right", "pressed") == "next" and m.screen == SCREENS[1]
    assert m.handle(0.1, "right", "released") is None
    assert m.handle(0.2, "left", "pressed") == "prev" and m.screen == "home"
    assert m.handle(0.3, "left", "pressed") == "prev" and m.screen == SCREENS[-1]
    # click = publish now
    m.handle(1, "middle", "pressed")
    assert m.handle(1.2, "middle", "released") == "publish"
    # hold 2 s = ack, and the release after it does nothing
    m.handle(2, "middle", "pressed")
    assert m.handle(3, "middle", "held") is None
    assert m.handle(4.1, "middle", "held") == "ack"
    assert m.handle(4.5, "middle", "held") is None
    assert m.handle(5, "middle", "released") is None
    assert m.handle(6, "up", "pressed") == "bright" and m.handle(7, "down", "pressed") == "dim"
    assert m.tick(40) is True and m.screen == "home"


def test_led_drawings():
    flat = level_pixels(0, 0)
    assert len(flat) == 64 and (0, 200, 0) in flat
    assert (220, 30, 0) in level_pixels(20, -20)
    north = compass_pixels(0)
    assert north[0 * 8 + 3] == (220, 0, 0) or north[0 * 8 + 4] == (220, 0, 0)  # arrow points up
    assert compass_label(0) == "N" and compass_label(100) == "E" and compass_label(359) == "N"
