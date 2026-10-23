"""BrickPi3 motors and EV3 ultrasonic sensor (real hardware) plus mocks with the same interface."""

import threading
import time

from rover.config import RoverConfig

# EV3 ultrasonic reports 255 cm when no echo comes back: nothing in range, OR an object
# so close (< ~3 cm) the echo is missed. Callers get None and decide (see safety.py).
NO_ECHO_CM = 255.0
ULTRASONIC_WARMUP_S = 4.0  # the EV3 sensor needs ~3.4 s after set_sensor_type


class BrickPiHardware:
    """Owns the BrickPi3: tracks, ultrasonic and battery voltage."""

    def __init__(self, cfg: RoverConfig):
        import brickpi3  # only on the Pi

        self.bp = brickpi3.BrickPi3()
        self._errors = brickpi3.SensorError
        self.left = getattr(self.bp, cfg.left_port)
        self.right = getattr(self.bp, cfg.right_port)
        self.us_port = getattr(self.bp, cfg.ultrasonic_port)
        self.sign = cfg.drive_sign
        self.bp.set_sensor_type(self.us_port, self.bp.SENSOR_TYPE.EV3_ULTRASONIC_CM)
        self._us_ready_at = time.time() + ULTRASONIC_WARMUP_S
        self._lock = threading.Lock()

    def drive(self, left_dps: float, right_dps: float) -> None:
        with self._lock:
            self.bp.set_motor_dps(self.left, self.sign * left_dps)
            self.bp.set_motor_dps(self.right, self.sign * right_dps)

    def stop(self) -> None:
        with self._lock:
            self.bp.set_motor_power(self.left, 0)
            self.bp.set_motor_power(self.right, 0)

    def distance_cm(self) -> float | None:
        if time.time() < self._us_ready_at:
            return None
        with self._lock:
            try:
                v = float(self.bp.get_sensor(self.us_port))
            except self._errors:
                return None
        return None if v >= NO_ECHO_CM else v

    def battery_v(self) -> float | None:
        with self._lock:
            try:
                return round(self.bp.get_voltage_battery(), 2)
            except Exception:  # SPI hiccup: report unknown rather than crash the loop
                return None

    def close(self) -> None:
        with self._lock:
            self.bp.reset_all()


class MockHardware:
    """Laptop stand-in. Logs motor commands; distance and battery can be changed at runtime."""

    def __init__(self, cfg: RoverConfig, distance_cm: float | None = 120.0, battery_v: float = 11.4):
        self.left_dps = 0.0
        self.right_dps = 0.0
        self.mock_distance = distance_cm
        self.mock_battery = battery_v
        self.log: list[tuple[float, float, float]] = []

    def drive(self, left_dps: float, right_dps: float) -> None:
        if (left_dps, right_dps) != (self.left_dps, self.right_dps):
            self.log.append((time.time(), left_dps, right_dps))
            del self.log[:-200]
        self.left_dps, self.right_dps = left_dps, right_dps

    def stop(self) -> None:
        self.drive(0.0, 0.0)

    def distance_cm(self) -> float | None:
        return self.mock_distance

    def battery_v(self) -> float | None:
        return self.mock_battery

    def close(self) -> None:
        self.stop()
