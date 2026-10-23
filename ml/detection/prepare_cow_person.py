"""Build a two-class detection dataset (0 = cow, 1 = person) in YOLO format.

    ~/lms-ml/bin/python -m ml.detection.prepare_cow_person --out ~/lms-data/cow_person
    ~/lms-ml/bin/python -m ml.detection.pseudo_label_persons --data ~/lms-data/cow_person   # then this

Why one model with both classes: on the Pi 4 the rover can afford one detector pass per
frame. It needs cows (to follow) and people (to stop for, and never to follow).

Label quality rules - a missing person box teaches the model "person = background", which
is the dangerous kind of error for a rover:
- COCO labels every person in every image, so COCO images are used with all cow and person
  boxes kept, and COCO alone forms the validation set.
- Open Images labels are not exhaustive: a cattle photo can show an unlabelled farmer. Those
  images go to training only, with their person boxes filled in afterwards by
  pseudo_label_persons.py (a large pretrained detector); they are listed in manifest.json.

Sources (FiftyOne dataset zoo; the files downloaded for the cow model are reused):
- COCO 2017 train: every image with a cow; people sampled from all images with people;
  farm-like scenes (people with horses/sheep/cows); animal images with neither class
- COCO 2017 validation: images with cows and a sample of images with people
- Open Images V7 validation + test: images labelled "Cattle"
"""

import argparse
import json
import random
import shutil
from pathlib import Path

import fiftyone as fo
import fiftyone.zoo as foz

CLASSES = {"cow": 0, "person": 1}
COCO_IDS = {"cow": 19, "person": 0}  # for scoring the stock COCO model on the same images
OI_TO_OURS = {
    "Cattle": "cow",
    "Person": "person",
    "Man": "person",
    "Woman": "person",
    "Boy": "person",
    "Girl": "person",
}


def load_coco(split: str, classes: list[str], max_samples=None, seed=0, name=None):
    return foz.load_zoo_dataset(
        "coco-2017",
        split=split,
        label_types=["detections"],
        classes=classes,
        max_samples=max_samples,
        shuffle=max_samples is not None,
        seed=seed,
        dataset_name=name,
    )


class Writer:
    def __init__(self, out: Path):
        self.out = out
        self.seen: set[str] = set()
        self.counts: dict = {}
        self.pseudo: list[str] = []  # train images whose person boxes must be filled in

    def add(self, sample, split: str, source: str, mapping: dict, needs_pseudo: bool = False) -> bool:
        src = Path(sample.filepath)
        name = f"{source}_{src.name}"
        if name in self.seen:
            return False
        self.seen.add(name)
        rows, coco_rows = [], []
        dets = sample.ground_truth.detections if sample.ground_truth is not None else []
        for d in dets:
            ours = mapping.get(d.label)
            if ours is None:
                continue
            x, y, w, h = d.bounding_box
            if w <= 0 or h <= 0:
                continue
            box = f"{x + w / 2:.6f} {y + h / 2:.6f} {w:.6f} {h:.6f}"
            rows.append(f"{CLASSES[ours]} {box}\n")
            coco_rows.append(f"{COCO_IDS[ours]} {box}\n")
        for sub, lines in (("labels", rows), ("labels_coco", coco_rows)):
            d = self.out / sub / split
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{Path(name).stem}.txt").write_text("".join(lines))
        img_dir = self.out / "images" / split
        img_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, img_dir / name)
        key = f"{split}/{source}"
        self.counts[key] = self.counts.get(key, 0) + 1
        if needs_pseudo:
            self.pseudo.append(f"images/{split}/{name}")
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / "lms-data" / "cow_person"))
    ap.add_argument("--person-train", type=int, default=3000, help="COCO train images sampled for people")
    ap.add_argument("--farm-train", type=int, default=1500, help="COCO train images with people + farm animals")
    ap.add_argument("--neg-train", type=int, default=800, help="COCO train animal images with no cow or person")
    ap.add_argument("--person-val", type=int, default=400, help="COCO val images sampled for people")
    ap.add_argument("--oi-max", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    out = Path(args.out).expanduser()
    random.seed(args.seed)
    if out.exists():
        shutil.rmtree(out)
    w = Writer(out)
    coco_map = {"cow": "cow", "person": "person"}

    # --- COCO train (exhaustive labels: cows and people both kept) ---
    for s in load_coco("train", ["cow"], name="lp-coco-cow-train"):
        w.add(s, "train", "coco", coco_map)
    farm = load_coco(
        "train", ["horse", "sheep", "cow"], max_samples=args.farm_train * 3, seed=args.seed, name="lp-farm"
    )
    n_farm = n_neg = 0
    for s in farm:
        labels = {d.label for d in (s.ground_truth.detections or [])}
        if "person" in labels and n_farm < args.farm_train:
            n_farm += w.add(s, "train", "coco", coco_map)
        elif not labels & {"person", "cow"} and n_neg < args.neg_train:
            n_neg += w.add(s, "train", "coco", coco_map)  # negative: empty label file
    for s in load_coco("train", ["person"], max_samples=args.person_train, seed=args.seed, name="lp-person-train"):
        w.add(s, "train", "coco", coco_map)

    # --- COCO validation: the only scored split, so only exhaustively labelled images ---
    for s in load_coco("validation", ["cow"], name="lp-coco-cow-val"):
        w.add(s, "val", "coco", coco_map)
    for s in load_coco("validation", ["person"], max_samples=args.person_val, seed=args.seed, name="lp-person-val"):
        w.add(s, "val", "coco", coco_map)

    # --- Open Images cattle: train only; people filled in later by pseudo-labelling ---
    for split in ("validation", "test"):
        oi = foz.load_zoo_dataset(
            "open-images-v7",
            split=split,
            label_types=["detections"],
            classes=["Cattle"],
            max_samples=args.oi_max,
            shuffle=True,
            seed=args.seed,
            dataset_name=f"lp-oi-cattle-{split}",
        )
        for s in oi:
            w.add(s, "train", "oi", OI_TO_OURS, needs_pseudo=True)

    names = "\n".join(f"  {i}: {n}" for n, i in CLASSES.items())
    (out / "data.yaml").write_text(f"path: {out}\ntrain: images/train\nval: images/val\nnames:\n{names}\n")
    manifest = {
        "classes": CLASSES,
        "coco_ids": COCO_IDS,
        "counts": w.counts,
        "needs_person_pseudo_labels": w.pseudo,
        "pseudo_labelled": False,
        "sources": {
            "coco-2017": "CC BY 4.0 annotations; images under their Flickr licenses",
            "open-images-v7": "CC BY 4.0 annotations; images listed as CC BY 2.0",
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    instances = {"cow": 0, "person": 0}
    for f in (out / "labels").rglob("*.txt"):
        for line in f.read_text().splitlines():
            instances["cow" if line.startswith("0 ") else "person"] += 1
    print("images:", w.counts)
    print("boxes before pseudo-labelling:", instances)
    print(f"{len(w.pseudo)} Open Images training images need person pseudo-labels")
    fo.delete_non_persistent_datasets()


if __name__ == "__main__":
    main()
