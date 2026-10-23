"""Target detection for the rover camera.

    make_detector("green")                       legacy green-marker tracking (HSV 35-90)
    make_detector("yolo:ml/detection/models/coco_yolo11n.onnx")  YOLO ONNX via OpenCV DNN
    make_detector("ncnn:ml/detection/models/cow_ncnn_model")      YOLO NCNN (faster on the Pi)

Detections get a track id from a small IoU tracker so the follow controller can stick to
the same animal between frames.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

COCO_NAMES = {0: "person", 18: "sheep", 19: "cow"}  # the COCO classes the rover cares about


@dataclass
class Det:
    label: str
    confidence: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 pixels
    track_id: int | None = None

    @property
    def cx(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]


class GreenDetector:
    """The hackathon rover's tracker: the biggest green blob."""

    name = "green"
    LOWER = np.array([35, 70, 60])
    UPPER = np.array([90, 255, 255])
    MIN_AREA = 300

    def __init__(self):
        self.kernel = np.ones((5, 5), np.uint8)

    def detect(self, frame: np.ndarray) -> list[Det]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.LOWER, self.UPPER)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = []
        for c in cnts:
            if cv2.contourArea(c) < self.MIN_AREA:
                continue
            x, y, w, h = cv2.boundingRect(c)
            out.append(Det("green_marker", 1.0, (x, y, x + w, y + h)))
        return sorted(out, key=lambda d: -d.height)[:5]


class _YoloBase:
    """Shared letterbox + decode for YOLOv8/YOLO11 exports (output (4+classes) x N)."""

    def __init__(self, names_file: Path, imgsz: int, conf: float, iou: float, labels):
        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou
        if names_file.exists():
            self.names = {int(k): v for k, v in json.loads(names_file.read_text()).items()}
        else:
            self.names = COCO_NAMES  # stock COCO model
        self.keep = set(labels) if labels else set(self.names.values())

    def _letterbox(self, frame: np.ndarray):
        h, w = frame.shape[:2]
        scale = self.imgsz / max(h, w)
        nh, nw = round(h * scale), round(w * scale)
        canvas = np.full((self.imgsz, self.imgsz, 3), 114, np.uint8)
        top, left = (self.imgsz - nh) // 2, (self.imgsz - nw) // 2
        canvas[top : top + nh, left : left + nw] = cv2.resize(frame, (nw, nh))
        return canvas, scale, top, left

    def _decode(self, out: np.ndarray, frame_shape, scale, top, left) -> list[Det]:
        """`out`: N x (4 + classes) rows of (cx, cy, w, h, class scores...) in letterbox pixels."""
        h, w = frame_shape[:2]
        scores = out[:, 4:]
        cls = scores.argmax(1)
        conf = scores[np.arange(len(cls)), cls]
        ids = [i for i in np.flatnonzero(conf >= self.conf) if self.names.get(int(cls[i])) in self.keep]
        if not ids:
            return []
        boxes = []
        for i in ids:
            cx, cy, bw, bh = out[i, :4]
            boxes.append(
                [
                    float((cx - bw / 2 - left) / scale),
                    float((cy - bh / 2 - top) / scale),
                    float(bw / scale),
                    float(bh / scale),
                ]
            )
        picked = cv2.dnn.NMSBoxes(boxes, [float(conf[i]) for i in ids], self.conf, self.iou)
        dets = []
        for k in np.array(picked).flatten():
            x, y, bw, bh = boxes[k]
            i = ids[k]
            dets.append(
                Det(
                    self.names[int(cls[i])],
                    round(float(conf[i]), 3),
                    (max(0, x), max(0, y), min(w, x + bw), min(h, y + bh)),
                )
            )
        return dets


class YoloOnnxDetector(_YoloBase):
    """YOLO ONNX export run with OpenCV DNN (laptop and Pi; ~8 fps on a Pi 4 at 320 px)."""

    def __init__(self, path: str, imgsz: int = 320, conf: float = 0.35, iou: float = 0.45, labels=None):
        self.path = Path(path)
        self.name = f"yolo {self.path.name}"
        self.net = cv2.dnn.readNetFromONNX(str(self.path))
        super().__init__(self.path.with_suffix(".names.json"), imgsz, conf, iou, labels)

    def detect(self, frame: np.ndarray) -> list[Det]:
        canvas, scale, top, left = self._letterbox(frame)
        self.net.setInput(cv2.dnn.blobFromImage(canvas, 1 / 255.0, swapRB=True))
        out = self.net.forward()[0].T  # N x (4 + classes)
        return self._decode(out, frame.shape, scale, top, left)


class YoloNcnnDetector(_YoloBase):
    """YOLO NCNN export (a folder with model.ncnn.param/.bin), usually faster than ONNX on the Pi.

    Needs `pip install ncnn`. The folder sits next to `<name>.names.json`, e.g.
    ml/detection/models/cow_ncnn_model  +  ml/detection/models/cow.names.json.
    """

    def __init__(self, folder: str, imgsz: int = 320, conf: float = 0.35, iou: float = 0.45, labels=None, threads=4):
        import ncnn  # only needed for this backend

        self.folder = Path(folder)
        self.name = f"ncnn {self.folder.name}"
        self.net = ncnn.Net()
        self.net.opt.num_threads = threads
        self.net.load_param(str(self.folder / "model.ncnn.param"))
        self.net.load_model(str(self.folder / "model.ncnn.bin"))
        self._ncnn = ncnn
        stem = self.folder.name.removesuffix("_ncnn_model")
        super().__init__(self.folder.parent / f"{stem}.names.json", imgsz, conf, iou, labels)

    def detect(self, frame: np.ndarray) -> list[Det]:
        canvas, scale, top, left = self._letterbox(frame)
        rgb = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1), dtype=np.float32) / 255.0
        ex = self.net.create_extractor()
        ex.input("in0", self._ncnn.Mat(rgb))
        _, out = ex.extract("out0")
        out = np.array(out).reshape(-1, np.array(out).shape[-1]).T  # (4+classes) x N -> N x (4+classes)
        return self._decode(out, frame.shape, scale, top, left)


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


@dataclass
class IouTracker:
    """Keeps ids stable across frames by matching boxes with the highest overlap."""

    min_iou: float = 0.3
    max_missed: int = 10
    _next: int = 1
    _tracks: dict = field(default_factory=dict)  # id -> (box, label, missed)

    def update(self, dets: list[Det]) -> list[Det]:
        unmatched = set(self._tracks)
        for d in sorted(dets, key=lambda d: -d.confidence):
            best, best_iou = None, self.min_iou
            for tid in unmatched:
                box, label, _ = self._tracks[tid]
                score = iou(box, d.box)
                if label == d.label and score > best_iou:
                    best, best_iou = tid, score
            if best is None:
                best = self._next
                self._next += 1
            else:
                unmatched.discard(best)
            d.track_id = best
            self._tracks[best] = (d.box, d.label, 0)
        for tid in unmatched:
            box, label, missed = self._tracks[tid]
            if missed + 1 > self.max_missed:
                del self._tracks[tid]
            else:
                self._tracks[tid] = (box, label, missed + 1)
        return dets


def make_detector(spec: str):
    if spec == "green":
        return GreenDetector()
    if spec.startswith("yolo:"):
        return YoloOnnxDetector(spec[len("yolo:") :])
    if spec.startswith("ncnn:"):
        return YoloNcnnDetector(spec[len("ncnn:") :])
    raise ValueError(f"unknown detector {spec!r}")


def annotate(frame: np.ndarray, dets: list[Det], target: Det | None, lines: list[str]) -> np.ndarray:
    for d in dets:
        color = (0, 200, 255) if target is not None and d.track_id == target.track_id else (60, 220, 60)
        x1, y1, x2, y2 = map(int, d.box)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        tag = f"{d.label} {d.confidence:.2f}" + (f" #{d.track_id}" if d.track_id else "")
        cv2.putText(frame, tag, (x1, max(12, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    if lines:
        # dark translucent strip behind the status text so it reads on any background
        bar_h = 8 + 20 * len(lines)
        strip = frame[:bar_h].copy()
        cv2.rectangle(strip, (0, 0), (frame.shape[1], bar_h), (0, 0, 0), -1)
        frame[:bar_h] = cv2.addWeighted(strip, 0.55, frame[:bar_h], 0.45, 0)
        for i, text in enumerate(lines):
            cv2.putText(frame, text, (8, 20 + 20 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)
    return frame
