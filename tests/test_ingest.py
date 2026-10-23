import json

import pytest

from backend.workers.ingest import parse, route


def test_route_matches_wildcards():
    assert route("lms/collar/C001/vitals")[0] == "vitals"
    assert route("lms/barn/barn1/env")[0] == "env"
    assert route("lms/rover/r1/status")[0] == "rover_status"
    assert route("lms/collar/C001/other") is None


def test_topic_overrides_payload_id():
    name, m = parse("lms/collar/C009/vitals", json.dumps({"animal_id": "spoofed", "hr": 70}).encode())
    assert name == "vitals"
    assert m.animal_id == "C009"
    assert m.ts > 0  # filled when the device has no clock


@pytest.mark.parametrize(
    "payload",
    [b"not json", b"[1, 2]", json.dumps({"body_temp": 99}).encode()],
)
def test_bad_payloads_raise(payload):
    with pytest.raises(Exception):  # noqa: B017 - ValueError or ValidationError
        parse("lms/collar/C001/vitals", payload)
