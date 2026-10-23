"""Fill in person boxes on the Open Images training images, whose people are not labelled.

    ~/lms-ml/bin/python -m ml.detection.pseudo_label_persons --data ~/lms-data/cow_person

Runs a large COCO-pretrained detector (YOLO11x, inference only - no training) over the
images listed in manifest.json and appends confident person boxes (class 1) to their label
files. Existing person boxes are kept; a predicted box that overlaps one (IoU > 0.5) is
skipped. Light on the GPU: small batches and a pause between them.
"""

import argparse
import json
import time
from pathlib import Path

from ultralytics import YOLO

PERSON_COCO = 0
PERSON_OURS = 1


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1, bx2, by2 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path.home() / "lms-data" / "cow_person"))
    ap.add_argument("--model", default="yolo11x.pt")
    ap.add_argument("--conf", type=float, default=0.5)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--rest", type=float, default=0.5, help="seconds between batches")
    args = ap.parse_args()
    data = Path(args.data).expanduser()
    manifest_path = data / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    images = [data / p for p in manifest["needs_person_pseudo_labels"]]
    model = YOLO(args.model)
    added = touched = 0
    for i in range(0, len(images), args.batch):
        chunk = images[i : i + args.batch]
        results = model.predict(
            [str(p) for p in chunk], classes=[PERSON_COCO], conf=args.conf, imgsz=640, verbose=False
        )
        for path, res in zip(chunk, results, strict=True):
            label = data / "labels" / "train" / f"{path.stem}.txt"
            lines = label.read_text().splitlines() if label.exists() else []
            existing = [tuple(map(float, ln.split()[1:])) for ln in lines if ln.startswith(f"{PERSON_OURS} ")]
            new = []
            for box in res.boxes.xywhn.tolist():
                if all(iou(box, e) <= 0.5 for e in existing):
                    new.append(f"{PERSON_OURS} " + " ".join(f"{v:.6f}" for v in box))
            if new:
                label.write_text("\n".join(lines + new) + "\n")
                added += len(new)
                touched += 1
        time.sleep(args.rest)
    manifest["pseudo_labelled"] = True
    manifest["pseudo_label_stats"] = {
        "model": args.model,
        "conf": args.conf,
        "images_checked": len(images),
        "images_with_new_people": touched,
        "person_boxes_added": added,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest["pseudo_label_stats"], indent=2))


if __name__ == "__main__":
    main()
