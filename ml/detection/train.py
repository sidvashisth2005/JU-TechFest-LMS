"""Fine-tune YOLO11n to detect cows, gently enough for a laptop.

    ~/lms-ml/bin/python -m ml.detection.train --data ~/lms-data/cows

Laptop protection (RTX 3050 Laptop, no settable power limit):
- thermal guard: checks the GPU temperature every few batches; at --hot (78 C) training
  pauses until the GPU cools to --cool (70 C)
- duty cycle: a short rest after every batch so the GPU never sits at 100% for hours
- small batch, 2 data-loader workers, 4 CPU threads
Temperatures are logged to <run>/thermal.csv.

Also scores the stock COCO-pretrained YOLO11n on the same validation images (its "cow"
class) so the fine-tuned model is compared against a real baseline.
"""

import argparse
import csv
import json
import os
import subprocess
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "4")

import torch  # noqa: E402
from ultralytics import YOLO  # noqa: E402

torch.set_num_threads(4)
COCO_COW = 19


def gpu_temp() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        return int(out.splitlines()[0])
    except Exception:
        return None


class ThermalGuard:
    def __init__(self, log_path: Path, hot: int, cool: int, rest_s: float, check_every: int):
        self.hot, self.cool, self.rest_s, self.check_every = hot, cool, rest_s, check_every
        self.batches = 0
        self.paused_s = 0.0
        self.max_temp = 0
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = log_path.open("a", newline="")
        self.writer = csv.writer(self.log)
        self.writer.writerow(["time", "temp_c", "event"])

    def __call__(self, trainer) -> None:
        self.batches += 1
        time.sleep(self.rest_s)
        if self.batches % self.check_every:
            return
        t = gpu_temp()
        if t is None:
            return
        self.max_temp = max(self.max_temp, t)
        self.writer.writerow([time.strftime("%H:%M:%S"), t, ""])
        if t >= self.hot:
            start = time.time()
            self.writer.writerow([time.strftime("%H:%M:%S"), t, "pause"])
            print(f"\n[thermal guard] GPU {t} C >= {self.hot} C, pausing to cool down", flush=True)
            while (t := gpu_temp()) is not None and t > self.cool:
                time.sleep(10)
            self.paused_s += time.time() - start
            self.writer.writerow([time.strftime("%H:%M:%S"), t, f"resume after {time.time() - start:.0f}s"])
            print(f"[thermal guard] GPU {t} C, resuming", flush=True)
        self.log.flush()


def coco_view(data_dir: Path) -> Path:
    """A validation view whose labels use COCO id 19, so the stock model can be scored."""
    view = data_dir / "val_coco"
    (view / "images").mkdir(parents=True, exist_ok=True)
    img, lbl = view / "images" / "val", view / "labels" / "val"
    if not img.exists():
        img.symlink_to(data_dir / "images" / "val", target_is_directory=True)
    lbl.parent.mkdir(parents=True, exist_ok=True)
    if not lbl.exists():
        lbl.symlink_to(data_dir / "labels_coco" / "val", target_is_directory=True)
    names = "\n".join(f"  {i}: c{i}" for i in range(80)).replace(f"  {COCO_COW}: c{COCO_COW}", f"  {COCO_COW}: cow")
    yaml = view / "data.yaml"
    yaml.write_text(f"path: {view}\ntrain: images/val\nval: images/val\nnames:\n{names}\n")
    return yaml


def score(model: YOLO, data: Path, imgsz: int, classes=None) -> dict:
    m = model.val(data=str(data), imgsz=imgsz, batch=8, workers=2, classes=classes, plots=False, verbose=False)
    return {
        "mAP50": round(float(m.box.map50), 4),
        "mAP50_95": round(float(m.box.map), 4),
        "precision": round(float(m.box.mp), 4),
        "recall": round(float(m.box.mr), 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path.home() / "lms-data" / "cows"))
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--imgsz", type=int, default=512)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--hot", type=int, default=78)
    ap.add_argument("--cool", type=int, default=70)
    ap.add_argument("--rest", type=float, default=0.05, help="seconds of rest after each batch")
    ap.add_argument("--project", default=str(Path.home() / "lms-runs"))
    ap.add_argument("--name", default="cow-yolo11n")
    args = ap.parse_args()

    data_dir = Path(args.data).expanduser()
    run_dir = Path(args.project) / args.name
    report = {"args": vars(args), "started": time.strftime("%Y-%m-%d %H:%M")}

    print("== baseline: stock COCO YOLO11n, class 'cow' ==", flush=True)
    report["baseline"] = score(YOLO(args.model), coco_view(data_dir), args.imgsz, classes=[COCO_COW])
    print(report["baseline"], flush=True)

    model = YOLO(args.model)
    guard = ThermalGuard(run_dir.parent / f"{args.name}-thermal.csv", args.hot, args.cool, args.rest, 20)
    model.add_callback("on_train_batch_end", guard)
    t0 = time.time()
    model.train(
        data=str(data_dir / "data.yaml"),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=2,
        device=0,
        patience=15,
        project=args.project,
        name=args.name,
        exist_ok=True,
        seed=0,
        plots=True,
    )
    report["train_minutes"] = round((time.time() - t0) / 60, 1)
    report["thermal"] = {"max_temp_c": guard.max_temp, "paused_minutes": round(guard.paused_s / 60, 1)}

    best = YOLO(str(run_dir / "weights" / "best.pt"))
    report["fine_tuned"] = score(best, data_dir / "data.yaml", args.imgsz)
    print("== fine-tuned ==", report["fine_tuned"], flush=True)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2))
    print(f"report: {run_dir / 'report.json'}")


if __name__ == "__main__":
    main()
