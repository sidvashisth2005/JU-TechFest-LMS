"""infra/pi_watch.py wake-up: the dashboard comes back only when the rover boots again."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "infra"))
import pi_watch  # noqa: E402


def _setup(tmp_path, monkeypatch, slept: dict | None):
    started = []
    monkeypatch.setattr(pi_watch, "SLEEP", tmp_path / "dashboard_sleep.json")
    monkeypatch.setattr(pi_watch.subprocess, "Popen", lambda *a, **k: started.append(a))
    if slept is not None:
        pi_watch.SLEEP.write_text(json.dumps(slept))
    return started


def test_new_boot_wakes_the_dashboard_once(tmp_path, monkeypatch):
    started = _setup(tmp_path, monkeypatch, {"since": time.time(), "rover_boot": "boot-1"})
    pi_watch.wake_if_rover_restarted("boot-1")  # last beacons of the rover being shut down
    assert started == [] and pi_watch.SLEEP.exists()
    pi_watch.wake_if_rover_restarted("boot-2")  # switched on again
    assert len(started) == 1 and not pi_watch.SLEEP.exists()
    pi_watch.wake_if_rover_restarted("boot-2")
    assert len(started) == 1


def test_not_asleep_does_nothing(tmp_path, monkeypatch):
    started = _setup(tmp_path, monkeypatch, None)
    pi_watch.wake_if_rover_restarted("boot-9")
    assert started == []


def test_unknown_boot_waits_out_the_shutdown(tmp_path, monkeypatch):
    started = _setup(tmp_path, monkeypatch, {"since": time.time(), "rover_boot": None})
    pi_watch.wake_if_rover_restarted("boot-1")
    assert started == []
    pi_watch.SLEEP.write_text(json.dumps({"since": time.time() - 120, "rover_boot": None}))
    pi_watch.wake_if_rover_restarted("boot-1")
    assert len(started) == 1
