"""Build a single-class "cow" detection dataset in YOLO format.

    ~/lms-ml/bin/python -m ml.detection.prepare_data --out ~/lms-data/cows

Sources (downloaded only for the classes needed, via FiftyOne's dataset zoo):
- COCO 2017: images containing cows (train + validation splits)
- Open Images V7 (validation + test splits): images labelled "Cattle"
- Negatives: COCO images with horses, sheep, dogs or people but no cow, so the model
  learns not to call them cows (the rover must not chase a horse or a person).

Validation uses COCO's own validation split plus a held-out slice of Open Images, so the
score reflects images the model never trained on. A second label set with the COCO class
id (19) is written for validation so the stock pretrained model can be scored the same way.
"""

import argparse
import random
import shutil
from pathlib import Path

import fiftyone.zoo as foz

COCO_COW = 19


def export(samples, field: str, label_names: set[str], out: Path, split: str, coco_ids: bool) -> int:
    """Write images + YOLO labels for `samples`; returns number of images."""
    img_dir = out / "images" / split
    lbl_dir = out / "labels" / split
    lbl_coco = out / "labels_coco" / split
    for d in (img_dir, lbl_dir, lbl_coco):
        d.mkdir(parents=True, exist_ok=True)
    n = 0
    for s in samples:
        dets = s[field].detections if s[field] is not None else []
        lines = []
        for d in dets:
            if d.label not in label_names:
                continue
            x, y, w, h = d.bounding_box  # relative, top-left based
            if w <= 0 or h <= 0:
                continue
            lines.append((x + w / 2, y + h / 2, w, h))
        src = Path(s.filepath)
        name = f"{src.parent.parent.name}_{src.name}" if "open-images" in s.filepath else src.name
        shutil.copy2(src, img_dir / name)
        stem = Path(name).stem
        (lbl_dir / f"{stem}.txt").write_text("".join(f"0 {a:.6f} {b:.6f} {c:.6f} {e:.6f}\n" for a, b, c, e in lines))
        if coco_ids:
            (lbl_coco / f"{stem}.txt").write_text(
                "".join(f"{COCO_COW} {a:.6f} {b:.6f} {c:.6f} {e:.6f}\n" for a, b, c, e in lines)
            )
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / "lms-data" / "cows"))
    ap.add_argument("--oi-max", type=int, default=3000, help="max Open Images cattle images")
    ap.add_argument("--neg-max", type=int, default=1200, help="max negative (no-cow) COCO images")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    out = Path(args.out).expanduser()
    random.seed(args.seed)

    coco_train = foz.load_zoo_dataset(
        "coco-2017", split="train", label_types=["detections"], classes=["cow"], dataset_name="lms-coco-cow-train"
    )
    coco_val = foz.load_zoo_dataset(
        "coco-2017", split="validation", label_types=["detections"], classes=["cow"], dataset_name="lms-coco-cow-val"
    )
    negatives = foz.load_zoo_dataset(
        "coco-2017",
        split="train",
        label_types=["detections"],
        classes=["horse", "sheep", "dog", "person"],
        max_samples=args.neg_max * 2,
        shuffle=True,
        seed=args.seed,
        dataset_name="lms-coco-neg",
    )
    # Open Images validation + test splits: their label files are ~100 MB instead of the
    # 2+ GB needed for the train split, and still hold several hundred cattle images
    oi = None
    for split in ("validation", "test"):
        part = foz.load_zoo_dataset(
            "open-images-v7",
            split=split,
            label_types=["detections"],
            classes=["Cattle"],
            max_samples=args.oi_max,
            shuffle=True,
            seed=args.seed,
            dataset_name=f"lms-oi-cattle-{split}",
        )
        if oi is None:
            oi = part
        else:
            oi.merge_samples(part)

    if out.exists():
        shutil.rmtree(out)
    counts = {}
    counts["coco_train"] = export(coco_train, "ground_truth", {"cow"}, out, "train", False)
    counts["coco_val"] = export(coco_val, "ground_truth", {"cow"}, out, "val", True)
    neg = [s for s in negatives if not any(d.label == "cow" for d in (s.ground_truth.detections or []))]
    random.shuffle(neg)
    counts["negatives"] = export(neg[: args.neg_max], "ground_truth", set(), out, "train", False)
    oi_ids = list(oi.values("id"))
    random.shuffle(oi_ids)
    n_val = len(oi_ids) // 10
    counts["oi_val"] = export(oi.select(oi_ids[:n_val]), "ground_truth", {"Cattle"}, out, "val", True)
    counts["oi_train"] = export(oi.select(oi_ids[n_val:]), "ground_truth", {"Cattle"}, out, "train", False)

    (out / "data.yaml").write_text(f"path: {out}\ntrain: images/train\nval: images/val\nnames:\n  0: cow\n")
    print("images:", counts)


if __name__ == "__main__":
    main()
