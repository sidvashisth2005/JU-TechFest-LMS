"""Export the trained cow detector for the rover.

    ~/lms-ml/bin/python -m ml.detection.export --weights ~/lms-runs/cow-yolo11n/weights/best.pt

Writes to ml/detection/models/:
  cow.onnx + cow.names.json   used by rover/vision.py (OpenCV DNN, works on laptop and Pi)
  cow_ncnn_model/             NCNN export, faster on the Pi 4 (benchmark when hardware is back)
"""

import argparse
import json
import shutil
from pathlib import Path

from ultralytics import YOLO

OUT = Path(__file__).resolve().parent / "models"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--imgsz", type=int, default=320, help="Pi-friendly input size")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(Path(args.weights).expanduser()))

    onnx = Path(model.export(format="onnx", imgsz=args.imgsz, opset=12, simplify=True, dynamic=False))
    shutil.copy2(onnx, OUT / "cow.onnx")
    (OUT / "cow.names.json").write_text(json.dumps({str(k): v for k, v in model.names.items()}))

    ncnn = Path(model.export(format="ncnn", imgsz=args.imgsz))
    target = OUT / "cow_ncnn_model"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ncnn, target)
    print(f"exported to {OUT}")


if __name__ == "__main__":
    main()
