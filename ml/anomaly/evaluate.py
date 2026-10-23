"""Score the anomaly detector against simulator ground truth.

    python -m simulator.run offline --days 21 --event-rate 4 --climate mild --out simulator/out/eval_mild
    python -m ml.anomaly.evaluate simulator/out/eval_mild

Prints, per event type: how many events were caught (recall) and how fast, plus how many
alerts were false alarms (precision, false alarms per 100 cow-days).
"""

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

from common.schemas import EnvMsg, VitalsMsg
from ml.anomaly.detector import Config, Detector
from simulator.model import EXPECTED_ALERT

HOUR = 3600.0
# alerts that are a legitimate consequence of each event type
EXPLAINS = {
    "fever": {"fever", "tachycardia", "low_activity"},
    "lameness": {"low_activity"},
    "estrus": {"high_activity", "tachycardia"},
    "sensor_dropout": {"sensor_offline"},
    "sensor_glitch": set(),
}
SCORED_KINDS = {"fever", "tachycardia", "low_activity", "high_activity", "sensor_offline"}
LATE_GRACE = 8 * HOUR  # activity alerts use a 6 h window, so they can trail the event


def _num(v):
    return None if v in ("", None) else float(v)


def stream(data: Path):
    """Yield ('env', EnvMsg) / ('vitals', VitalsMsg) in time order."""
    with (data / "vitals.csv").open() as fv, (data / "env.csv").open() as fe:
        vit = csv.DictReader(fv)
        pending = next(vit, None)
        for row in csv.DictReader(fe):
            ts = float(row["ts"])
            yield (
                "env",
                EnvMsg(
                    station_id=row["station_id"],
                    ts=ts,
                    temp=_num(row["temp"]),
                    humidity=_num(row["humidity"]),
                    pressure=_num(row["pressure"]),
                ),
            )
            while pending is not None and float(pending["ts"]) <= ts:
                p = pending
                yield (
                    "vitals",
                    VitalsMsg(
                        animal_id=p["animal_id"],
                        ts=float(p["ts"]),
                        hr=_num(p["hr"]),
                        spo2=_num(p["spo2"]),
                        body_temp=_num(p["body_temp"]),
                        activity=_num(p["activity"]),
                        steps=None if p["steps"] == "" else int(p["steps"]),
                        battery=_num(p["battery"]),
                    ),
                )
                pending = next(vit, None)


def run_detector(data: Path, cfg: Config | None = None):
    det = Detector(cfg)
    alerts = []
    next_tick = None
    for kind, msg in stream(data):
        if kind == "env":
            alerts += det.on_env(msg)
            if next_tick is None:
                next_tick = msg.ts + 60
            if msg.ts >= next_tick:
                alerts += det.tick(msg.ts)
                next_tick = msg.ts + 60
        else:
            alerts += det.on_vitals(msg)
    return alerts


def load_labels(data: Path):
    with (data / "labels.csv").open() as f:
        return [
            {
                "animal_id": r["animal_id"] or None,
                "kind": r["kind"],
                "start": float(r["start"]),
                "end": float(r["end"]),
            }
            for r in csv.DictReader(f)
        ]


def score(alerts, labels, meta):
    by_animal = defaultdict(list)
    for e in labels:
        if e["animal_id"]:
            by_animal[e["animal_id"]].append(e)
    t0, t_end = meta["t0"], meta["t_end"]
    warmup = t0 + 2 * 86400  # baselines need two days; ignore events that start earlier
    report = {}

    # recall per event type
    for kind, expected in EXPECTED_ALERT.items():
        if expected is None or kind == "heat_stress":
            continue
        events = [e for e in labels if e["kind"] == kind and e["start"] >= warmup]
        delays = []
        for e in events:
            hits = [
                a.ts
                for a in alerts
                if a.animal_id == e["animal_id"] and a.kind == expected and e["start"] <= a.ts <= e["end"] + LATE_GRACE
            ]
            if hits:
                delays.append((min(hits) - e["start"]) / HOUR)
        report[kind] = {
            "events": len(events),
            "caught": len(delays),
            "recall": round(len(delays) / len(events), 2) if events else None,
            "median_delay_h": round(statistics.median(delays), 2) if delays else None,
        }

    # heat stress (barn level)
    heat = [e for e in labels if e["kind"] == "heat_stress"]
    heat_alerts = [a for a in alerts if a.kind == "heat_stress"]
    caught = sum(1 for e in heat if any(e["start"] - HOUR <= a.ts <= e["start"] + HOUR for a in heat_alerts))
    report["heat_stress"] = {"events": len(heat), "caught": caught, "alerts": len(heat_alerts)}

    # precision: every scored animal alert should be explained by an event on that animal
    scored = [a for a in alerts if a.kind in SCORED_KINDS and a.animal_id and a.ts >= warmup]
    false_alarms = []
    for a in scored:
        explained = any(
            a.kind in EXPLAINS.get(e["kind"], set()) and e["start"] <= a.ts <= e["end"] + LATE_GRACE
            for e in by_animal[a.animal_id]
        )
        if not explained:
            false_alarms.append(a)
    cow_days = meta["cows"] * (t_end - warmup) / 86400
    glitch_alarms = sum(
        1
        for a in false_alarms
        for e in by_animal[a.animal_id]
        if e["kind"] == "sensor_glitch" and e["start"] <= a.ts <= e["end"] + HOUR
    )
    report["alerts"] = {
        "total": len(scored),
        "false": len(false_alarms),
        "precision": round(1 - len(false_alarms) / len(scored), 3) if scored else None,
        "false_per_100_cow_days": round(100 * len(false_alarms) / cow_days, 2),
        "false_by_kind": dict(sorted(_count(a.kind for a in false_alarms).items())),
        "caused_by_glitches": glitch_alarms,
    }
    return report


def _count(items):
    out = defaultdict(int)
    for i in items:
        out[i] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", nargs="+", help="simulator offline output folder(s)")
    ap.add_argument("--json", help="also write the report here")
    args = ap.parse_args()
    reports = {}
    for d in args.data:
        data = Path(d)
        meta = json.loads((data / "meta.json").read_text())
        alerts = run_detector(data)
        rep = score(alerts, load_labels(data), meta)
        reports[data.name] = rep
        print(f"\n=== {data.name} ({meta['cows']} cows, {meta['days']} days, climate {meta['climate']}) ===")
        print(f"{'event':16}{'events':>8}{'caught':>8}{'recall':>8}{'delay h':>9}")
        for k, r in rep.items():
            if k in ("alerts", "heat_stress"):
                continue
            print(f"{k:16}{r['events']:>8}{r['caught']:>8}{r['recall']!s:>8}{r['median_delay_h']!s:>9}")
        h = rep["heat_stress"]
        print(f"{'heat_stress':16}{h['events']:>8}{h['caught']:>8}   (barn alerts raised: {h['alerts']})")
        a = rep["alerts"]
        print(
            f"animal alerts {a['total']}, false {a['false']}, precision {a['precision']}, "
            f"{a['false_per_100_cow_days']} false/100 cow-days, from glitches {a['caused_by_glitches']}"
        )
        print(f"false alarms by kind: {a['false_by_kind']}")
    if args.json:
        Path(args.json).write_text(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
