"""Load the trained disease model and suggest likely diseases for a set of symptoms."""

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


@lru_cache(maxsize=1)
def _load():
    import joblib

    path = ARTIFACTS / "disease_model.joblib"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing - run `python -m ml.disease.train` first")
    bundle = joblib.load(path)
    meta = json.loads((ARTIFACTS / "disease_model.json").read_text())
    return bundle["model"], bundle["symptoms"], meta


def symptoms() -> list[str]:
    return list(_load()[1])


def model_info() -> dict:
    _, syms, meta = _load()
    best = meta["results"][meta["training"]][meta["model"]]
    return {
        "model": meta["model"],
        "training": meta["training"],
        "diseases": meta["diseases"],
        "symptoms": len(syms),
        "partial_input_top3_accuracy": best["partial_top3"],
        "note": meta["note"],
    }


def predict(selected: list[str], top: int = 3) -> dict:
    """Return the `top` most likely diseases with probabilities.

    Unknown symptom names are returned in `unknown` rather than silently ignored.
    """
    model, syms, meta = _load()
    index = {s: i for i, s in enumerate(syms)}
    known = [s for s in dict.fromkeys(selected) if s in index]
    unknown = [s for s in selected if s not in index]
    if not known:
        return {"predictions": [], "known": [], "unknown": unknown, "note": meta["note"]}
    x = np.zeros((1, len(syms)), dtype=np.int8)
    x[0, [index[s] for s in known]] = 1
    proba = model.predict_proba(x)[0]
    order = np.argsort(-proba)[:top]
    return {
        "predictions": [{"disease": str(model.classes_[i]), "probability": round(float(proba[i]), 3)} for i in order],
        "known": known,
        "unknown": unknown,
        "note": meta["note"],
    }
