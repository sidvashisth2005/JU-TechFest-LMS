"""MQTT topic names. Every publisher and subscriber builds topics through these helpers."""

PREFIX = "lms"

COLLAR_VITALS_SUB = f"{PREFIX}/collar/+/vitals"
BARN_ENV_SUB = f"{PREFIX}/barn/+/env"
ROVER_STATUS_SUB = f"{PREFIX}/rover/+/status"
ROVER_DETECTIONS_SUB = f"{PREFIX}/rover/+/detections"
ALERTS = f"{PREFIX}/alerts"


def collar_vitals(animal_id: str) -> str:
    return f"{PREFIX}/collar/{animal_id}/vitals"


def barn_env(station_id: str) -> str:
    return f"{PREFIX}/barn/{station_id}/env"


def rover_status(rover_id: str) -> str:
    return f"{PREFIX}/rover/{rover_id}/status"


def rover_detections(rover_id: str) -> str:
    return f"{PREFIX}/rover/{rover_id}/detections"


def device_id(topic: str) -> str:
    """Return the id segment of a device topic, e.g. 'lms/collar/C07/vitals' -> 'C07'."""
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != PREFIX:
        raise ValueError(f"not an LMS device topic: {topic}")
    return parts[2]
