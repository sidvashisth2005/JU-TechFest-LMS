"""Last word on every motor command: obstacle stop, low battery stop.

The EV3 ultrasonic returns "no echo" (None here) both when nothing is in range and when an
object is closer than ~3 cm. On the bench a hand at 3.6 cm read 255 on the next sample.
So "no echo" right after a close reading counts as blocked, not as a clear path.
"""

from rover.config import RoverConfig


class Safety:
    def __init__(self, cfg: RoverConfig):
        self.cfg = cfg
        self.distance: float | None = None
        self._last_valid: tuple[float, float] | None = None  # (cm, ts)
        self.reason: str | None = None

    def update(self, distance_cm: float | None, now: float) -> None:
        self.distance = distance_cm
        if distance_cm is not None:
            self._last_valid = (distance_cm, now)

    def blocked(self, now: float) -> bool:
        stop = self.cfg.stop_distance_cm
        if self.distance is not None:
            return self.distance < stop
        if self._last_valid is None:
            return False
        cm, ts = self._last_valid
        return cm < 2 * stop and now - ts < self.cfg.close_echo_window_s

    def filter(self, left: float, right: float, now: float, battery_v: float | None) -> tuple[float, float]:
        """Return the command that is safe to send right now and set `reason` if it was changed."""
        self.reason = None
        if battery_v is not None and battery_v < self.cfg.battery_min_v:
            self.reason = f"battery low ({battery_v:.1f} V)"
            return 0.0, 0.0
        forward = (left + right) / 2
        if forward > 0 and self.blocked(now):
            turn = (left - right) / 2  # keep turning (to steer away); drop the forward part
            self.reason = "obstacle ahead"
            return turn, -turn
        return left, right
