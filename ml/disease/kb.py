"""Symptom checker for cows, goats, sheep, dogs and cats, built on a curated knowledge base.

    from ml.disease import kb
    kb.symptoms_for("goat")                      # what to show for a goat
    kb.predict("goat", ["high_fever", "mouth_sores", "diarrhoea"])
    python -m ml.disease.kb                       # self-check of the knowledge base

The knowledge base (ml/disease/kb/*.json) lists common diseases of these species with
their signs, each marked hallmark (3), common (2) or occasional (1), plus urgency, whether
the disease spreads (to animals / to people), what to do now and how to prevent it, in
English, Hindi and Hinglish. It was written from standard veterinary references for
Indian conditions; it is a guide for owners, not a diagnosis.

Scoring is naive Bayes over the ticked signs only (an unticked sign is unknown, not
absent): P(sign | disease) = 0.9 / 0.6 / 0.3 for hallmark / common / occasional and a
small leak (0.02) for a sign the disease does not cause; the prior is the disease's
prevalence (1 rare .. 3 common). Results are normalised over that species' diseases.
"""

import json
import math
import random
from functools import lru_cache
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent / "kb"
SPECIES = ("cow", "goat", "sheep", "dog", "cat")
GROUPS = {"A": SPECIES, "R": ("cow", "goat", "sheep"), "P": ("dog", "cat")}
LIKELIHOOD = {3: 0.9, 2: 0.6, 1: 0.3}
LEAK = 0.02
LANGS = ("en", "hi", "hl")
URGENCY_RANK = {"emergency": 3, "soon": 2, "manage": 1}


@lru_cache(maxsize=1)
def load() -> dict:
    """Read and validate the knowledge base; raises ValueError on any inconsistency."""
    sym_file = json.loads((KB_DIR / "symptoms.json").read_text(encoding="utf-8"))
    categories = sym_file["categories"]
    symptoms = {}
    for s in sym_file["symptoms"]:
        species = GROUPS.get(s["species"], s["species"])
        s = {**s, "species": list(species)}
        if s["id"] in symptoms:
            raise ValueError(f"duplicate symptom {s['id']}")
        if s["cat"] not in categories:
            raise ValueError(f"symptom {s['id']}: unknown category {s['cat']}")
        for field in ("name", "short", "detail"):
            if set(s[field]) != set(LANGS):
                raise ValueError(f"symptom {s['id']}: {field} needs {LANGS}")
        symptoms[s["id"]] = s
    diseases = {}
    for path in sorted(KB_DIR.glob("diseases_*.json")):
        for d in json.loads(path.read_text(encoding="utf-8"))["diseases"]:
            if d["id"] in diseases:
                raise ValueError(f"duplicate disease {d['id']}")
            if not set(d["species"]) <= set(SPECIES) or d["urgency"] not in URGENCY_RANK:
                raise ValueError(f"disease {d['id']}: bad species or urgency")
            for field in ("name", "about", "action", "prevent"):
                if set(d[field]) != set(LANGS):
                    raise ValueError(f"disease {d['id']}: {field} needs {LANGS}")
            for sid, w in d["symptoms"].items():
                if sid not in symptoms or w not in LIKELIHOOD:
                    raise ValueError(f"disease {d['id']}: bad symptom {sid}={w}")
            diseases[d["id"]] = d
    return {"categories": categories, "symptoms": symptoms, "diseases": diseases}


def diseases_for(species: str) -> list[dict]:
    return [d for d in load()["diseases"].values() if species in d["species"]]


def symptoms_for(species: str) -> list[dict]:
    """Signs that matter for this species: applicable to it and used by one of its diseases."""
    kb = load()
    used = {sid for d in diseases_for(species) for sid in d["symptoms"]}
    return [s for s in kb["symptoms"].values() if species in s["species"] and s["id"] in used]


def predict(species: str, selected: list[str], top: int = 5) -> dict:
    if species not in SPECIES:
        raise ValueError(f"species must be one of {SPECIES}")
    valid = {s["id"] for s in symptoms_for(species)}
    chosen = [s for s in dict.fromkeys(selected) if s in valid]
    unknown = [s for s in selected if s not in valid]
    if not chosen:
        return {"species": species, "results": [], "selected": [], "unknown": unknown, "ask_about": []}
    scored = []
    for d in diseases_for(species):
        logp = math.log(d["prevalence"]) + sum(math.log(LIKELIHOOD.get(d["symptoms"].get(s, 0), LEAK)) for s in chosen)
        scored.append((logp, d))
    m = max(lp for lp, _ in scored)
    total = sum(math.exp(lp - m) for lp, _ in scored)
    ranked = sorted(((math.exp(lp - m) / total, d) for lp, d in scored), key=lambda r: -r[0])
    results = []
    for p, d in ranked[:top]:
        if p < 0.01 and results:
            break
        matched = [s for s in chosen if s in d["symptoms"]]
        missing = sorted(
            (s for s, w in d["symptoms"].items() if s not in chosen and w >= 2 and s in valid),
            key=lambda s: -d["symptoms"][s],
        )
        results.append(
            {
                "id": d["id"],
                "probability": round(p, 3),
                "match": "strong" if p >= 0.5 else "possible" if p >= 0.15 else "less likely",
                "matched": matched,
                "also_check": missing[:4],
                **{k: d[k] for k in ("name", "about", "action", "prevent", "urgency", "contagious", "zoonotic")},
            }
        )
    # the signs that would best separate the top candidates: hallmark/common signs of the
    # leading diseases that were not ticked, most useful first
    ask: dict[str, float] = {}
    for r in results[:3]:
        for s in r["also_check"]:
            ask[s] = ask.get(s, 0) + r["probability"]
    return {
        "species": species,
        "results": results,
        "selected": chosen,
        "unknown": unknown,
        "ask_about": [s for s, _ in sorted(ask.items(), key=lambda kv: -kv[1])][:6],
        "emergency": any(r["urgency"] == "emergency" and r["probability"] >= 0.15 for r in results),
    }


def self_check(trials: int = 200, seed: int = 7) -> dict:
    """How often the right disease comes out on top when an owner ticks 2-3 of its signs,
    picked the way they show up (hallmark signs more often). This checks that the diseases
    are told apart by the knowledge base; it is not a field accuracy."""
    rng = random.Random(seed)
    out = {}
    for species in SPECIES:
        top1 = top3 = n = 0
        for d in diseases_for(species):
            signs = [s for s in d["symptoms"] if s in {x["id"] for x in symptoms_for(species)}]
            weights = [LIKELIHOOD[d["symptoms"][s]] for s in signs]
            for _ in range(trials // 10):
                k = min(len(signs), rng.choice((2, 3)))
                picked = set()
                while len(picked) < k:
                    picked.add(rng.choices(signs, weights)[0])
                ids = [r["id"] for r in predict(species, list(picked), top=3)["results"]]
                n += 1
                top1 += ids[:1] == [d["id"]]
                top3 += d["id"] in ids
        out[species] = {"diseases": len(diseases_for(species)), "top1": round(top1 / n, 3), "top3": round(top3 / n, 3)}
    return out


if __name__ == "__main__":
    kb = load()
    print(f"{len(kb['diseases'])} diseases, {len(kb['symptoms'])} signs")
    for species, r in self_check().items():
        print(f"{species:<6} {r}")
