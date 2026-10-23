"""Run the virtual herd.

Offline (dataset for ML, no broker needed):
    python -m simulator.run offline --days 14 --out simulator/out/run1

Live (publish to MQTT like real collars):
    python -m simulator.run live --cows 50 --backfill-hours 48 --demo

Live mode first publishes `--backfill-hours` of history quickly (timestamps in the past;
use 48 h or more so activity baselines exist for every hour of the day),
then keeps publishing in real time. `--demo` starts a fever, lameness, estrus and a
dropout on a few cows right away so alerts show up within minutes.
"""

import argparse
import csv
import json
import os
import time
from pathlib import Path

from common import topics
from simulator.model import DAY, HOUR, Herd

VITALS_FIELDS = ["ts", "animal_id", "hr", "spo2", "body_temp", "activity", "steps", "battery", "rssi"]
ENV_FIELDS = ["ts", "station_id", "temp", "humidity", "pressure", "thi"]


def write_labels(herd: Herd, path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["animal_id", "kind", "start", "end", "severity"])
        for e in herd.labels():
            w.writerow([e.animal_id or "", e.kind, round(e.start, 1), round(e.end, 1), round(e.severity, 2)])


def run_offline(args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    herd = Herd(args.cows, args.seed, args.climate, args.event_rate)
    t0 = args.start if args.start else time.time() - args.days * DAY
    t_end = t0 + args.days * DAY
    n = 0
    with (out / "vitals.csv").open("w", newline="") as fv, (out / "env.csv").open("w", newline="") as fe:
        wv = csv.DictWriter(fv, VITALS_FIELDS)
        we = csv.DictWriter(fe, ENV_FIELDS)
        wv.writeheader()
        we.writeheader()
        t = t0
        while t < t_end:
            msgs, env = herd.step(t, args.interval)
            for m in msgs:
                wv.writerow(m.model_dump(exclude={"animal_id"}) | {"animal_id": m.animal_id})
            we.writerow(env.model_dump() | {"thi": env.thi})
            n += len(msgs)
            t += args.interval
    herd.finish(t_end)
    write_labels(herd, out / "labels.csv")
    (out / "meta.json").write_text(json.dumps(vars(args) | {"t0": t0, "t_end": t_end}, indent=2))
    print(f"wrote {n} vitals rows, {len(herd.labels())} labelled events to {out}")


def mqtt_client():
    import paho.mqtt.client as mqtt
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"lms-sim-{os.getpid()}")
    c.username_pw_set(os.environ["MQTT_USER"], os.environ["MQTT_PASSWORD"])
    c.max_queued_messages_set(0)
    c.connect(os.environ.get("MQTT_HOST", "127.0.0.1"), int(os.environ.get("MQTT_PORT", 1883)))
    c.loop_start()
    return c


def publish(client, msgs, env, wait: bool = False) -> None:
    """QoS 1 like the real collars. `wait` blocks until the broker has the whole tick (backfill)."""
    info = None
    for m in msgs:
        info = client.publish(topics.collar_vitals(m.animal_id), m.model_dump_json(exclude_none=True), qos=1)
    env_info = client.publish(topics.barn_env(env.station_id), env.model_dump_json(exclude_none=True), qos=1)
    if wait:
        for i in (info, env_info):
            if i is not None:
                i.wait_for_publish(timeout=30)


def run_live(args) -> None:
    herd = Herd(args.cows, args.seed, args.climate, args.event_rate)
    client = mqtt_client()
    now = time.time()

    if args.demo:
        demo = [
            ("C007", "fever", 1.5, 30),
            ("C012", "lameness", 8, 72),
            ("C021", "estrus", 2, 14),
            ("C033", "sensor_dropout", 0, 2),
        ]
        for animal_id, kind, hours_ago, hours in demo:
            if any(c.animal_id == animal_id for c in herd.cows):
                herd.force_event(animal_id, kind, now - hours_ago * HOUR, hours)
                print(f"demo: {kind} on {animal_id}")

    # history, sent as fast as the broker takes it
    t = now - args.backfill_hours * HOUR
    if args.backfill_hours:
        print(f"backfilling {args.backfill_hours} h ...", flush=True)
        step = max(args.interval, args.backfill_interval)
        while t < now:
            msgs, env = herd.step(t, step)
            publish(client, msgs, env, wait=True)
            t += step
            time.sleep(args.backfill_pause)
        print("backfill done, now live", flush=True)

    labels_path = Path(args.labels) if args.labels else None
    try:
        next_tick = time.time()
        while True:
            t = time.time()
            msgs, env = herd.step(t, args.interval)
            publish(client, msgs, env)
            print(f"{time.strftime('%H:%M:%S')} sent {len(msgs)} collars + env (THI {env.thi})", flush=True)
            next_tick += args.interval
            time.sleep(max(0.0, next_tick - time.time()))
    except KeyboardInterrupt:
        pass
    finally:
        herd.finish(time.time())
        if labels_path:
            labels_path.parent.mkdir(parents=True, exist_ok=True)
            write_labels(herd, labels_path)
            print(f"labels written to {labels_path}")
        client.loop_stop()
        client.disconnect()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    for name in ("offline", "live"):
        p = sub.add_parser(name)
        p.add_argument("--cows", type=int, default=50)
        p.add_argument("--seed", type=int, default=7)
        p.add_argument("--climate", choices=["hot", "mild", "cool"], default="hot")
        p.add_argument("--event-rate", type=float, default=1.0, help="multiplier on event frequency")
        p.add_argument(
            "--interval",
            type=float,
            default=30.0 if name == "live" else 60.0,
            help="seconds between readings per cow",
        )
    off = sub.choices["offline"]
    off.add_argument("--days", type=float, default=14)
    off.add_argument("--start", type=float, default=None, help="Unix start time (default: --days ago)")
    off.add_argument("--out", default="simulator/out/run")
    live = sub.choices["live"]
    live.add_argument("--backfill-hours", type=float, default=0)
    live.add_argument("--backfill-interval", type=float, default=60.0)
    live.add_argument("--backfill-pause", type=float, default=0.01, help="seconds between backfill ticks")
    live.add_argument("--demo", action="store_true")
    live.add_argument("--labels", default="simulator/out/live_labels.csv")
    args = ap.parse_args()
    run_offline(args) if args.mode == "offline" else run_live(args)


if __name__ == "__main__":
    main()
