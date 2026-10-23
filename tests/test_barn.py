from barn.sensehat_pub import band_colour, corrected_air_temp, letter_colour
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


def test_esp32_collar_line_with_nulls_and_rssi():
    line = (
        '{"animal_id":"C002","hr":64,"spo2":null,"body_temp":38.71,"activity":0.0312,'
        '"steps":2,"battery":null,"rssi":-58}'
    )
    m = parse_line(line, None)
    assert m.animal_id == "C002" and m.hr == 64 and m.spo2 is None and m.battery is None and m.rssi == -58


def test_esp32_debug_lines_are_skipped():
    for line in ("wifi: connected, ip 10.0.0.5, rssi -60 dBm", "pulse:51234 g:1.002", "ok: ssid = Hotspot"):
        assert parse_line(line, "C001") is None


def test_uno_status_line_is_skipped():
    assert parse_line('{"status":"ready","ppg":"max30100","ppg_ok":true,"imu":true,"imu_id":104}', None) is None


def test_env_line_from_esp8266_collar():
    from common.schemas import EnvMsg

    m = parse_line('{"station_id":"C001-collar","temp":31.2,"humidity":64.0,"pressure":null}', "C001")
    assert isinstance(m, EnvMsg)
    assert m.station_id == "C001-collar" and m.temp == 31.2 and m.humidity == 64.0


def test_sensehat_letter_readable_on_band_colours():
    assert letter_colour(band_colour(75)) == (0, 0, 255)  # yellow -> blue letter (black = LEDs off)
    assert letter_colour(band_colour(70)) == (255, 255, 255)
