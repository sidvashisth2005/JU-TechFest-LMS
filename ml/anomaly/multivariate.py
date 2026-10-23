"""Layer 3 of the anomaly detector: an IsolationForest over herd-relative vitals.

The rules (fever, tachycardia, activity) each watch one signal. This model looks at the four
together and flags a cow whose combination is rare in healthy data, e.g. slightly warm AND
slightly fast heart AND a bit less active, none of which crosses a rule threshold alone.
It raises "unusual_pattern" at info level only: a hint to look at the cow, never an alarm.

    # train on healthy stretches of one simulated herd (seed 7), labelled events left out
    python -m ml.anomaly.multivariate train simulator/out/run1
    # score it on other herds (seed 11) and compare with the rules
    python -m ml.anomaly.multivariate eval simulator/out/eval_mild simulator/out/eval_hot

The processor uses ml/anomaly/models/iforest.joblib only when LMS_IFOREST=1 is set (off by default:
on simulated herds it caught nothing the rules missed and added false info alerts).
"""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np

MODEL_PATH = Path(__file__).parent / "models" / "iforest.joblib"
FEATURES = ["temp_vs_herd", "hr_vs_herd", "activity_6h_vs_herd", "activity_2h_vs_herd"]
HOUR = 3600.0


class Scorer:
    """Wraps the saved model. judge() takes feature rows, returns (unusual, score) per row."""

    def __init__(self, path: Path = MODEL_PATH):
        saved = joblib.load(path)
        self.model = saved["model"]
        self.threshold = saved["threshold"]

    def judge(self, rows: list[list[float]]) -> list[tuple[bool, float]]:
        scores = self.model.score_samples(np.asarray(rows, dtype=float))
        return [(bool(s < self.threshold), float(s)) for s in scores]


def load_scorer(path: Path = MODEL_PATH) -> Scorer | None:
    return Scorer(path) if path.exists() else None


def _replay(data: Path, scorer=None, every: float = 15 * 60):
    """Run the detector over a simulator folder. Returns (alerts, feature snapshots)."""
    from ml.anomaly.detector import Detector
    from ml.anomaly.evaluate import stream

    det = Detector(scorer=scorer)
    alerts, snaps = [], []
    next_tick = next_snap = None
    for kind, msg in stream(data):
        if kind == "vitals":
            alerts += det.on_vitals(msg)
            continue
        alerts += det.on_env(msg)
        if next_tick is None:
            next_tick, next_snap = msg.ts + 60, msg.ts + every
        if msg.ts >= next_tick:
            alerts += det.tick(msg.ts)
            next_tick = msg.ts + 60
        if scorer is None and msg.ts >= next_snap:
            snaps += [(msg.ts, aid, f) for aid, f in det.feature_rows(msg.ts)]
            next_snap = msg.ts + every
    return alerts, snaps


def _busy(labels, animal_id, ts, grace=8 * HOUR) -> bool:
    """True if the animal has any labelled event around ts (so the row is not 'healthy')."""
    return any(e["animal_id"] == animal_id and e["start"] - HOUR <= ts <= e["end"] + grace for e in labels)


def train(data: Path, out: Path, quantile: float, seed: int) -> None:
    from sklearn.ensemble import IsolationForest

    from ml.anomaly.evaluate import load_labels

    meta = json.loads((data / "meta.json").read_text())
    labels = load_labels(data)
    warmup = meta["t0"] + 2 * 86400
    _, snaps = _replay(data)
    healthy = [f for ts, aid, f in snaps if ts >= warmup and not _busy(labels, aid, ts)]
    x = np.asarray(healthy)
    model = IsolationForest(n_estimators=200, random_state=seed).fit(x)
    threshold = float(np.quantile(model.score_samples(x), quantile))
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": model, "threshold": threshold, "features": FEATURES, "trained_on": data.name, "quantile": quantile},
        out,
    )
    print(f"trained on {len(x)} healthy snapshots from {data.name} ({len(snaps)} total)")
    print(f"threshold {threshold:.4f} = {quantile:.2%} of healthy rows flagged; saved {out}")


def evaluate(data: Path, scorer: Scorer) -> dict:
    from ml.anomaly.evaluate import LATE_GRACE, load_labels

    meta = json.loads((data / "meta.json").read_text())
    labels = load_labels(data)
    warmup = meta["t0"] + 2 * 86400
    alerts, _ = _replay(data, scorer)
    model = [a for a in alerts if a.kind == "unusual_pattern" and a.ts >= warmup]
    rules = [a for a in alerts if a.kind != "unusual_pattern"]
    explained = [a for a in model if _busy(labels, a.animal_id, a.ts)]
    cow_days = meta["cows"] * (meta["t_end"] - warmup) / 86400
    per_kind = {}
    for kind in ("fever", "lameness", "estrus"):
        events = [e for e in labels if e["kind"] == kind and e["start"] >= warmup]

        def hit(alist, e):
            return [
                a.ts for a in alist if a.animal_id == e["animal_id"] and e["start"] <= a.ts <= e["end"] + LATE_GRACE
            ]

        touched = [e for e in events if hit(model, e)]
        only_model = [e for e in touched if not hit(rules, e)]
        earlier = [e for e in touched if hit(rules, e) and min(hit(model, e)) < min(hit(rules, e))]
        per_kind[kind] = {
            "events": len(events),
            "model_alerted": len(touched),
            "missed_by_rules_caught_by_model": len(only_model),
            "model_before_rules": len(earlier),
        }
    return {
        "model_alerts": len(model),
        "explained_by_event": len(explained),
        "precision": round(len(explained) / len(model), 3) if model else None,
        "false_per_100_cow_days": round(100 * (len(model) - len(explained)) / cow_days, 2),
        "events": per_kind,
    }


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("data")
    t.add_argument("--out", default=str(MODEL_PATH))
    t.add_argument("--quantile", type=float, default=0.002, help="share of healthy rows called unusual")
    t.add_argument("--seed", type=int, default=0)
    e = sub.add_parser("eval")
    e.add_argument("data", nargs="+")
    e.add_argument("--model", default=str(MODEL_PATH))
    e.add_argument("--json", help="also write the report here")
    args = ap.parse_args()
    if args.cmd == "train":
        train(Path(args.data), Path(args.out), args.quantile, args.seed)
        return
    scorer = Scorer(Path(args.model))
    reports = {}
    for d in args.data:
        rep = reports[Path(d).name] = evaluate(Path(d), scorer)
        print(f"\n=== {Path(d).name} ===")
        print(json.dumps(rep, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
