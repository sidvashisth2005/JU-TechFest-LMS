import numpy as np

from rover.config import RoverConfig
from rover.controller import Controller
from rover.safety import Safety
from rover.vision import Det, GreenDetector, IouTracker

W, H = 640, 480


def cow(cx, height, tid=1):
    return Det("cow", 0.9, (cx - 40, 300 - height, cx + 40, 300), tid)


def test_manual_watchdog_stops():
    c = Controller(RoverConfig())
    c.manual("forward", 50, now=100.0)
    assert c.step([], W, H, 100.2) == (300.0, 300.0)
    assert c.step([], W, H, 101.0) == (0.0, 0.0)  # no command for 1 s


def test_follow_steers_towards_target_and_holds_distance():
    c = Controller(RoverConfig())
    c.set_mode("follow")
    left, right = c.step([cow(560, 60)], W, H, 1.0)  # far and to the right
    assert left > right  # turns right while moving forward
    left, right = c.step([cow(320, int(0.6 * H))], W, H, 1.1)  # centred, comfortable distance
    assert (left, right) == (0.0, 0.0)
    left, right = c.step([cow(320, int(0.8 * H))], W, H, 1.2)  # too close
    assert left < 0 and right < 0


def test_follow_never_targets_people_and_stops_when_lost():
    c = Controller(RoverConfig())
    c.set_mode("follow")
    person = Det("person", 0.95, (300, 100, 340, 400), 5)
    assert c.step([person], W, H, 1.0) == (0.0, 0.0)
    assert c.target is None


def test_safety_blocks_forward_but_allows_reverse_and_turning():
    s = Safety(RoverConfig())
    s.update(15, 1.0)
    assert s.filter(200, 200, 1.0, 11.0) == (0.0, 0.0)
    assert s.filter(-200, -200, 1.0, 11.0) == (-200, -200)
    assert s.filter(300, 100, 1.0, 11.0) == (100.0, -100.0)


def test_no_echo_right_after_close_reading_is_blocked():
    s = Safety(RoverConfig())
    s.update(4.0, 1.0)
    s.update(None, 1.2)  # EV3 reads 255 when an object is almost touching
    assert s.blocked(1.2)
    assert not s.blocked(5.0)  # long after: no echo means clear


def test_low_battery_stops_everything():
    s = Safety(RoverConfig())
    s.update(100, 1.0)
    assert s.filter(-200, -200, 1.0, 8.5) == (0.0, 0.0)


def test_green_detector_and_tracker_keep_ids():
    img = np.zeros((H, W, 3), np.uint8)
    img[200:260, 300:360] = (40, 200, 40)
    det = GreenDetector()
    tracker = IouTracker()
    first = tracker.update(det.detect(img))
    img2 = np.zeros_like(img)
    img2[205:265, 305:365] = (40, 200, 40)
    second = tracker.update(det.detect(img2))
    assert len(first) == len(second) == 1
    assert first[0].track_id == second[0].track_id
