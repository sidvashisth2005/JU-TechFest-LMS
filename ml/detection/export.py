"""Export the trained cow detector for the rover.

    ~/lms-ml/bin/python -m ml.detection.export --weights ~/lms-runs/cow-yolo11n/weights/best.pt

Writes to ml/detection/models/ (stem from --out-name, default "cow"):
  <name>.onnx + <name>.names.json   used by rover/vision.py (OpenCV DNN, laptop and Pi)
  <name>_ncnn_model/                NCNN export, faster on the Pi 4
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
    ap.add_argument("--out-name", default="cow", help="file stem in ml/detection/models (cow, cow_person, ...)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(Path(args.weights).expanduser()))

    onnx = Path(model.export(format="onnx", imgsz=args.imgsz, opset=12, simplify=True, dynamic=False))
    shutil.copy2(onnx, OUT / f"{args.out_name}.onnx")
    (OUT / f"{args.out_name}.names.json").write_text(json.dumps({str(k): v for k, v in model.names.items()}))

    ncnn = Path(model.export(format="ncnn", imgsz=args.imgsz))
    target = OUT / f"{args.out_name}_ncnn_model"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ncnn, target)
    print(f"exported to {OUT}")


if __name__ == "__main__":
    main()
