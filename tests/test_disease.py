import pytest

from ml.disease import predict as disease

pytestmark = pytest.mark.skipif(not (disease.ARTIFACTS / "disease_model.joblib").exists(), reason="model not trained")


def test_known_case_ranks_mastitis_first():
    out = disease.predict(["udder_swelling", "udder_heat", "milk_clots", "udder_pain"])
    assert out["predictions"][0]["disease"] == "mastitis"
    probs = [p["probability"] for p in out["predictions"]]
    assert probs == sorted(probs, reverse=True)
    assert len(probs) == 3


def test_unknown_symptoms_are_reported():
    out = disease.predict(["fever", "not_a_symptom"])
    assert out["unknown"] == ["not_a_symptom"]
    assert out["known"] == ["fever"]


def test_no_known_symptoms_gives_no_prediction():
    out = disease.predict(["nothing"])
    assert out["predictions"] == []
