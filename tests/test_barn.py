from barn.sensehat_pub import band_colour, corrected_air_temp
from barn.serial_bridge import parse_line


def test_uno_line_becomes_vitals_without_substitutes():
    m = parse_line('{"animal_id":"C001","hr":71,"spo2":null,"activity":0.0412,"steps":3}', None)
    assert m.animal_id == "C001" and m.hr == 71 and m.spo2 is None and m.steps == 3


def test_zero_heart_rate_is_missing_not_faked():
    m = parse_line('{"animal_id":"C001","hr":0,"spo2":0}', None)
    assert m.hr is None and m.spo2 is None


def test_status_and_garbage_lines_are_skipped():
    assert parse_line('{"status":"ready","max30102":true}', "C001") is None
    assert parse_line("Initializing MAX30102...", "C001") is None
    assert parse_line('{"animal_id":"C001","spo2":140}', None) is None  # impossible value


def test_default_animal_id():
    assert parse_line('{"hr":66}', "C009").animal_id == "C009"


def test_sensehat_cpu_heat_correction():
    assert corrected_air_temp(34.0, 52.0, 1.5) == 22.0
    assert corrected_air_temp(30.0, None, 1.5) == 30.0
    assert band_colour(70) == (0, 120, 0) and band_colour(90) == (200, 0, 0)
