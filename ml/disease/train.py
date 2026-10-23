"""Train and evaluate the symptom -> disease model, then save the best one.

    python -m ml.disease.train

The hackathon dataset (legacy/AIML/Dataset) has 2044 training rows but only 433 distinct
ones, and 11 of the 26 test rows also appear in training, so its old accuracy figure was
inflated. Here every distinct row is used once and models are compared with repeated
stratified 5-fold cross-validation.

Two scores matter for the dashboard:
- full:    all of a case's symptoms are given (5-8 per row in this dataset)
- partial: only 2-3 random symptoms are given, which is what a farmer usually ticks
Training with symptom dropout (random subsets of each row) is tested as a way to make the
model robust to partial input.
"""

import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import RepeatedStratifiedKFold
from sklearn.naive_bayes import BernoulliNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "legacy" / "AIML" / "Dataset"
OUT = Path(__file__).resolve().parent / "artifacts"
SEED = 42


def load() -> tuple[pd.DataFrame, list[str]]:
    df = pd.concat([pd.read_csv(DATA / "Training.csv"), pd.read_csv(DATA / "Testing.csv")])
    df = df.drop_duplicates().reset_index(drop=True)
    symptoms = [c for c in df.columns if c != "prognosis"]
    return df, symptoms


def augment(X: np.ndarray, y: np.ndarray, copies: int, rng: np.random.Generator):
    """Add copies of each row keeping a random 2..all of its symptoms."""
    xs, ys = [X], [y]
    for _ in range(copies):
        Xa = X.copy()
        for row in Xa:
            on = np.flatnonzero(row)
            keep = rng.integers(2, len(on) + 1)
            row[rng.choice(on, len(on) - keep, replace=False)] = 0
        xs.append(Xa)
        ys.append(y)
    return np.vstack(xs), np.concatenate(ys)


def partial(X: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Keep only 2-3 random symptoms per row."""
    Xp = np.zeros_like(X)
    for i, row in enumerate(X):
        on = np.flatnonzero(row)
        k = min(len(on), rng.integers(2, 4))
        Xp[i, rng.choice(on, k, replace=False)] = 1
    return Xp


def topk(proba: np.ndarray, classes: np.ndarray, y: np.ndarray, k: int) -> float:
    idx = np.argsort(-proba, axis=1)[:, :k]
    return float(np.mean([y[i] in classes[idx[i]] for i in range(len(y))]))


MODELS = {
    "decision_tree": DecisionTreeClassifier(random_state=SEED),
    "random_forest": RandomForestClassifier(n_estimators=300, random_state=SEED, n_jobs=-1),
    "knn": KNeighborsClassifier(n_neighbors=5, metric="jaccard"),
    "bernoulli_nb": BernoulliNB(alpha=0.5),
    "logistic_regression": LogisticRegression(C=3.0, max_iter=3000),
}


def evaluate(df, symptoms, aug_copies: int) -> dict:
    X = df[symptoms].to_numpy(dtype=np.int8)
    y = df["prognosis"].to_numpy()
    cv = RepeatedStratifiedKFold(n_splits=5, n_repeats=3, random_state=SEED)
    rng = np.random.default_rng(SEED)
    scores = {name: {"full_top1": [], "full_top3": [], "partial_top1": [], "partial_top3": []} for name in MODELS}
    for train_idx, test_idx in cv.split(X, y):
        Xtr, ytr = X[train_idx], y[train_idx]
        if aug_copies:
            Xtr, ytr = augment(Xtr, ytr, aug_copies, rng)
        Xte, yte = X[test_idx], y[test_idx]
        Xpa = partial(Xte, rng)
        for name, base in MODELS.items():
            m = clone(base).fit(Xtr, ytr)
            for tag, Xe in (("full", Xte), ("partial", Xpa)):
                p = m.predict_proba(Xe)
                scores[name][f"{tag}_top1"].append(topk(p, m.classes_, yte, 1))
                scores[name][f"{tag}_top3"].append(topk(p, m.classes_, yte, 3))
    return {n: {k: round(float(np.mean(v)), 3) for k, v in s.items()} for n, s in scores.items()}


def main():
    t0 = time.time()
    df, symptoms = load()
    print(f"{len(df)} distinct cases, {len(symptoms)} symptoms, {df['prognosis'].nunique()} diseases")
    results = {}
    for copies in (0, 5):
        tag = "plain" if copies == 0 else f"dropout_x{copies}"
        results[tag] = evaluate(df, symptoms, copies)
        print(f"\n{tag}:  model                full@1 full@3 part@1 part@3")
        for name, s in results[tag].items():
            cols = "".join(f"{s[k]:>7}" for k in ("full_top1", "full_top3", "partial_top1", "partial_top3"))
            print(f"        {name:22}{cols}")

    # pick by partial-input top-3 (what the dashboard shows), then full top-1 as tie-break
    best_tag, best_name = max(
        ((t, n) for t in results for n in results[t]),
        key=lambda tn: (results[tn[0]][tn[1]]["partial_top3"], results[tn[0]][tn[1]]["full_top1"]),
    )
    print(f"\nbest: {best_name} ({best_tag})")

    X = df[symptoms].to_numpy(dtype=np.int8)
    y = df["prognosis"].to_numpy()
    if best_tag != "plain":
        X, y = augment(X, y, int(best_tag.split("x")[1]), np.random.default_rng(SEED))
    model = CalibratedClassifierCV(clone(MODELS[best_name]), method="sigmoid", cv=3).fit(X, y)

    OUT.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "symptoms": symptoms, "diseases": list(model.classes_)}, OUT / "disease_model.joblib")
    meta = {
        "model": best_name,
        "training": best_tag,
        "cases": len(df),
        "symptoms": len(symptoms),
        "diseases": int(df["prognosis"].nunique()),
        "cv": "5-fold stratified x3 on distinct rows",
        "results": results,
        "trained_at": time.strftime("%Y-%m-%d %H:%M"),
        "note": "Synthetic hackathon dataset; suggestions only, not a veterinary diagnosis.",
    }
    (OUT / "disease_model.json").write_text(json.dumps(meta, indent=2))
    print(f"saved to {OUT} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
