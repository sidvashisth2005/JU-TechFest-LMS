"""Message schemas shared by firmware, simulator, edge publishers and the backend.

Rules:
- Sensor fields are optional. A missing or failed sensor sends null, never a made-up value.
- ts is Unix time in seconds (float). Devices without a clock may omit it; ingest fills receive time.
- Units are in the field names' docs and never change.
"""

import time
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["info", "warning", "critical"]


def now() -> float:
    return time.time()


class VitalsMsg(BaseModel):
    """One reading from an animal's collar. Topic: lms/collar/{animal_id}/vitals"""

    animal_id: str = Field(min_length=1, max_length=32)
    ts: float = Field(default_factory=now)
    hr: float | None = Field(None, ge=0, le=300, description="heart rate, beats/min")
    spo2: float | None = Field(None, ge=0, le=100, description="blood oxygen saturation, %")
    body_temp: float | None = Field(None, ge=25, le=45, description="body temperature, deg C")
    activity: float | None = Field(None, ge=0, description="mean acceleration magnitude above gravity, g")
    steps: int | None = Field(None, ge=0, description="steps counted since the previous message")
    battery: float | None = Field(None, ge=0, le=5, description="collar battery, volts")
    rssi: int | None = Field(None, description="Wi-Fi signal, dBm")

    @field_validator("hr", "spo2")
    @classmethod
    def zero_means_no_reading(cls, v: float | None) -> float | None:
        # MAX3010x libraries report 0 when there is no finger/skin contact
        return None if v == 0 else v


class EnvMsg(BaseModel):
    """Barn environment reading. Topic: lms/barn/{station_id}/env"""

    station_id: str = Field(min_length=1, max_length=32)
    ts: float = Field(default_factory=now)
    temp: float | None = Field(None, ge=-40, le=70, description="air temperature, deg C")
    humidity: float | None = Field(None, ge=0, le=100, description="relative humidity, %")
    pressure: float | None = Field(None, ge=300, le=1200, description="air pressure, hPa")

    @property
    def thi(self) -> float | None:
        return thi(self.temp, self.humidity)


class Detection(BaseModel):
    label: str
    confidence: float = Field(ge=0, le=1)
    box: tuple[float, float, float, float] = Field(description="x1, y1, x2, y2 in pixels")
    track_id: int | None = None


class DetectionsMsg(BaseModel):
    """Objects the rover camera sees. Topic: lms/rover/{rover_id}/detections"""

    rover_id: str
    ts: float = Field(default_factory=now)
    frame_w: int
    frame_h: int
    detections: list[Detection]


class RoverStatusMsg(BaseModel):
    """Topic: lms/rover/{rover_id}/status"""

    rover_id: str
    ts: float = Field(default_factory=now)
    mode: Literal["idle", "manual", "follow"]
    battery: float | None = Field(None, description="BrickPi battery, volts")
    distance_cm: float | None = Field(None, description="ultrasonic, None when no echo")
    blocked: bool = False
    left_dps: float = 0
    right_dps: float = 0


class AlertMsg(BaseModel):
    """Raised by the processor. Topic: lms/alerts"""

    ts: float = Field(default_factory=now)
    kind: str = Field(description="e.g. fever, tachycardia, low_activity, heat_stress, sensor_offline")
    severity: Severity
    message: str
    animal_id: str | None = None
    station_id: str | None = None
    value: float | None = None
    source: Literal["rule", "baseline", "model"] = "rule"


def thi(temp_c: float | None, rh: float | None) -> float | None:
    """Temperature-humidity index (NRC 1971), the standard heat-stress measure for cattle.

    >= 72 mild stress, >= 79 moderate, >= 89 severe.
    """
    if temp_c is None or rh is None:
        return None
    t_f = 1.8 * temp_c + 32
    return round(t_f - (0.55 - 0.0055 * rh) * (t_f - 58), 1)
