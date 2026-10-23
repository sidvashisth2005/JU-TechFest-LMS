"""MQTT topic names. Every publisher and subscriber builds topics through these helpers."""

PREFIX = "lms"

COLLAR_VITALS_SUB = f"{PREFIX}/collar/+/vitals"
BARN_ENV_SUB = f"{PREFIX}/barn/+/env"
BARN_EVENT_SUB = f"{PREFIX}/barn/+/event"
ROVER_STATUS_SUB = f"{PREFIX}/rover/+/status"
ROVER_DETECTIONS_SUB = f"{PREFIX}/rover/+/detections"
ALERTS = f"{PREFIX}/alerts"


def collar_vitals(animal_id: str) -> str:
    return f"{PREFIX}/collar/{animal_id}/vitals"


def barn_env(station_id: str) -> str:
    return f"{PREFIX}/barn/{station_id}/env"


def barn_event(station_id: str) -> str:
    return f"{PREFIX}/barn/{station_id}/event"


def barn_state(station_id: str) -> str:
    """Backend -> station (retained): open alert count for the station's LED."""
    return f"{PREFIX}/barn/{station_id}/state"


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
