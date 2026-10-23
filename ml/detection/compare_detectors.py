"""Compare detectors on the same images, the same way: accuracy (cow, person) and speed.

    python -m ml.detection.compare_detectors --data /root/lms-data/cow_person \
        --ssd /root/lms-data/mobilenet_ssd [--threads 4] [--out report.json]

Models:
- MobileNet-SSD (Caffe, Pascal VOC, 300x300) through OpenCV DNN, as in the usual Pi scripts
- the rover's YOLO11n ONNX models through rover/vision.py (exactly what runs on the Pi)

Every model sees every validation image. A detection matches a ground-truth box of the same
class at IoU >= 0.5 (each box matched once). AP50 is the VOC all-points average precision over
detections down to confidence 0.01. Recall and precision are also given at each model's own
operating threshold (the rover's 0.35 for YOLO, 0.4 for the SSD script). Speed is the mean
time of one detect() call (preprocess + inference + decode) after a warm-up, with OpenCV
limited to --threads threads (the Pi 4 has 4 cores; absolute numbers on a laptop are faster).

--min-frac 0.2 scores only "near" objects: ground-truth boxes and detections at least that
fraction of the image height (what a rover acts on); smaller ones are ignored on both sides.
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from rover.vision import Det, YoloOnnxDetector

MODELS = Path(__file__).resolve().parent / "models"
VOC = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus", "car", "cat", "chair", "cow",
    "diningtable", "dog", "horse", "motorbike", "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor",
]  # fmt: skip
CLASSES = ("cow", "person")


class MobileNetSsd:
    """The friend's model: chuanqi305 MobileNet-SSD (VOC), preprocessing as in pi_realtime.py."""

    def __init__(self, folder: str, conf: float = 0.01):
        folder = Path(folder)
        self.net = cv2.dnn.readNetFromCaffe(str(folder / "deploy.prototxt"), str(folder / "mobilenet.caffemodel"))
        self.conf = conf
        self.name = "MobileNet-SSD (VOC, 300 px)"

    def detect(self, frame: np.ndarray) -> list[Det]:
        h, w = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
        self.net.setInput(blob)
        out = self.net.forward()[0, 0]  # N x (image, class, conf, x1, y1, x2, y2)
        dets = []
        for _, cls, conf, x1, y1, x2, y2 in out:
            label = VOC[int(cls)] if 0 <= int(cls) < len(VOC) else ""
            if conf >= self.conf and label in CLASSES:
                box = (max(0.0, x1 * w), max(0.0, y1 * h), min(w, x2 * w), min(h, y2 * h))
                dets.append(Det(label, float(conf), box))
        return dets


def load_truth(label_file: Path, w: int, h: int, names: dict) -> list[tuple[str, tuple]]:
    out = []
    if label_file.exists():
        for line in label_file.read_text().splitlines():
            p = line.split()
            if len(p) == 5 and names.get(int(p[0])) in CLASSES:
                cx, cy, bw, bh = (float(v) for v in p[1:])
                box = ((cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h)
                out.append((names[int(p[0])], box))
    return out


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def score(results, n_truth: int, op_conf: float) -> dict:
    """results: (confidence, is_true_positive) for every detection of one class."""
    if n_truth == 0:
        return {}
    results = sorted(results, key=lambda r: -r[0])
    tp = np.cumsum([r[1] for r in results]) if results else np.array([])
    fp = np.cumsum([not r[1] for r in results]) if results else np.array([])
    rec = tp / n_truth if len(tp) else np.array([0.0])
    prec = tp / np.maximum(tp + fp, 1e-9) if len(tp) else np.array([0.0])
    # VOC all-points AP
    mrec = np.concatenate(([0.0], rec, [1.0]))
    mpre = np.concatenate(([0.0], prec, [0.0]))
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    idx = np.where(mrec[1:] != mrec[:-1])[0]
    ap = float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))
    kept = [r for r in results if r[0] >= op_conf]
    k_tp = sum(r[1] for r in kept)
    return {
        "AP50": round(ap, 3),
        f"recall@{op_conf}": round(k_tp / n_truth, 3),
        f"precision@{op_conf}": round(k_tp / len(kept), 3) if kept else None,
        "truth_boxes": n_truth,
    }


def evaluate(model, images, labels_dir: Path, names: dict, op_conf: float, classes, min_frac: float = 0.0) -> dict:
    per_class = {c: [] for c in classes}
    n_truth = dict.fromkeys(classes, 0)
    times = []
    for k, img_path in enumerate(images):
        frame = cv2.imread(str(img_path))
        if frame is None:
            continue
        h, w = frame.shape[:2]
        t0 = time.perf_counter()
        dets = model.detect(frame)
        if k >= 5:  # warm-up
            times.append(time.perf_counter() - t0)
        truth = load_truth(labels_dir / (img_path.stem + ".txt"), w, h, names)
        truth = [(lab, b) for lab, b in truth if b[3] - b[1] >= min_frac * h]
        dets = [d for d in dets if d.height >= min_frac * h]
        for c in classes:
            gts = [b for lab, b in truth if lab == c]
            n_truth[c] += len(gts)
            used = [False] * len(gts)
            for d in sorted((d for d in dets if d.label == c), key=lambda d: -d.confidence):
                best, best_i = 0.0, -1
                for i, g in enumerate(gts):
                    if not used[i]:
                        v = iou(d.box, g)
                        if v > best:
                            best, best_i = v, i
                hit = best >= 0.5
                if hit:
                    used[best_i] = True
                per_class[c].append((d.confidence, hit))
    return {
        "model": model.name,
        "ms_per_frame": round(1000 * float(np.mean(times)), 1),
        "classes": {c: score(per_class[c], n_truth[c], op_conf) for c in classes},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", required=True, help="YOLO dataset folder with data.yaml, images/val, labels/val")
    ap.add_argument("--ssd", required=True, help="folder with deploy.prototxt + mobilenet.caffemodel")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument(
        "--yolo", action="append", default=[], metavar="PATH@SIZE", help="extra YOLO ONNX to score (person+cow)"
    )
    ap.add_argument("--min-frac", type=float, default=0.0, help="only objects this tall (fraction of image)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    cv2.setNumThreads(args.threads)
    data = Path(args.data)
    names = {}
    in_names = False
    for line in (data / "data.yaml").read_text().splitlines():  # tiny YAML: just the names block
        if line.startswith("names:"):
            in_names = True
        elif in_names and ":" in line and line.startswith(" "):
            k, v = line.split(":", 1)
            names[int(k.strip())] = v.strip()
    images = sorted((data / "images" / "val").glob("*.jpg"))
    labels = data / "labels" / "val"
    runs = [
        (MobileNetSsd(args.ssd), 0.4, CLASSES),
        (YoloOnnxDetector(str(MODELS / "coco_yolo11n.onnx"), conf=0.01), 0.35, CLASSES),
        (YoloOnnxDetector(str(MODELS / "cow.onnx"), conf=0.01), 0.35, ("cow",)),
    ]
    for spec in args.yolo:
        path, _, size = spec.partition("@")
        det = YoloOnnxDetector(path, imgsz=int(size or 320), conf=0.01)
        det.name = f"yolo {Path(path).name} @ {size or 320} px"
        runs.append((det, 0.35, CLASSES))
    report = {"images": len(images), "threads": args.threads, "min_frac": args.min_frac, "results": []}
    for model, op_conf, classes in runs:
        r = evaluate(model, images, labels, names, op_conf, classes, args.min_frac)
        print(json.dumps(r), flush=True)
        report["results"].append(r)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
