"""The public symptom checker's knowledge base (ml/disease/kb)."""

import pytest

from ml.disease import kb


def test_knowledge_base_loads_and_is_consistent():
    data = kb.load()  # raises on unknown signs, missing languages, bad urgency
    assert len(data["diseases"]) >= 50
    for species in kb.SPECIES:
        assert len(kb.diseases_for(species)) >= 15
        assert kb.symptoms_for(species)


@pytest.mark.parametrize("species", kb.SPECIES)
def test_hallmark_signs_put_each_disease_in_the_top_three(species):
    valid = {s["id"] for s in kb.symptoms_for(species)}
    for d in kb.diseases_for(species):
        signs = [s for s, w in d["symptoms"].items() if w >= 2 and s in valid]
        ids = [r["id"] for r in kb.predict(species, signs, top=3)["results"]]
        assert d["id"] in ids, (species, d["id"], ids)


def test_known_cases():
    assert kb.predict("goat", ["high_fever", "mouth_sores", "diarrhoea"])["results"][0]["id"] == "ppr"
    assert kb.predict("dog", ["vomiting", "bloody_diarrhoea", "young_unvaccinated"])["results"][0]["id"] == "parvo"
    assert kb.predict("cow", ["after_birth_down", "cannot_stand", "low_temp"])["results"][0]["id"] == "milk_fever"
    r = kb.predict("cow", ["high_fever", "throat_swelling", "fast_breathing"])
    assert r["results"][0]["id"] == "hs" and r["emergency"]


def test_signs_of_other_species_are_ignored():
    r = kb.predict("cow", ["vomiting", "swollen_udder"])
    assert r["unknown"] == ["vomiting"] and r["selected"] == ["swollen_udder"]
    assert kb.predict("cat", ["no_such_sign"])["results"] == []


def test_self_check_tells_diseases_apart():
    for species, r in kb.self_check(trials=100).items():
        assert r["top3"] >= 0.9, (species, r)
