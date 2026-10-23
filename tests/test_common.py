import pytest
from pydantic import ValidationError

from common import topics
from common.schemas import EnvMsg, VitalsMsg, thi


def test_topic_helpers_round_trip():
    t = topics.collar_vitals("C07")
    assert t == "lms/collar/C07/vitals"
    assert topics.device_id(t) == "C07"
    assert topics.device_id(topics.barn_env("barn1")) == "barn1"


def test_device_id_rejects_foreign_topic():
    with pytest.raises(ValueError):
        topics.device_id("other/collar/C07/vitals")


def test_vitals_zero_hr_spo2_become_missing():
    m = VitalsMsg(animal_id="C01", hr=0, spo2=0, body_temp=38.6)
    assert m.hr is None and m.spo2 is None
    assert m.body_temp == 38.6


def test_vitals_rejects_impossible_values():
    with pytest.raises(ValidationError):
        VitalsMsg(animal_id="C01", body_temp=60)
    with pytest.raises(ValidationError):
        VitalsMsg(animal_id="C01", spo2=120)


def test_thi_known_values():
    # 30 C / 70 % RH is moderate heat stress for cattle (THI ~81)
    assert thi(30, 70) == pytest.approx(81.4, abs=0.1)
    assert thi(20, 50) < 72
    assert thi(None, 50) is None
    assert EnvMsg(station_id="barn1", temp=30, humidity=70).thi == pytest.approx(81.4, abs=0.1)
