"""Time the rover's detector options on this machine (meant for the Pi 4).

    ~/lms-venv/bin/python -m ml.detection.bench_pi [--image photo.jpg] [--ssd FOLDER] [--n 30]

Stop the rover service first (it uses the CPU and the camera): lms-pi.sh stop rover.
Prints the mean time of one detect() call (preprocess + inference + decode) per option.
NCNN options need `pip install ncnn`; missing ones are skipped.
"""

import argparse
import time
from pathlib import Path

import cv2
import numpy as np

from rover.vision import make_detector

MODELS = Path(__file__).resolve().parent / "models"
OPTIONS = [
    f"yolo:{MODELS / 'coco_yolo11n.onnx'}@320",
    f"yolo:{MODELS / 'coco_yolo11n_416.onnx'}@416",
    f"ncnn:{MODELS / 'coco_yolo11n_ncnn_model'}@320",
    f"ncnn:{MODELS / 'coco_yolo11n_416_ncnn_model'}@416",
]


def bench(det, frame, n: int) -> float:
    for _ in range(3):
        det.detect(frame)
    t0 = time.perf_counter()
    for _ in range(n):
        det.detect(frame)
    return (time.perf_counter() - t0) / n * 1000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--image", help="a camera photo (default: random noise, 640x480)")
    ap.add_argument("--ssd", help="MobileNet-SSD folder (deploy.prototxt + mobilenet.caffemodel) to compare")
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args()
    frame = cv2.imread(args.image) if args.image else np.random.randint(0, 255, (480, 640, 3), np.uint8)
    print(f"OpenCV {cv2.__version__}, {cv2.getNumThreads()} threads, frame {frame.shape[1]}x{frame.shape[0]}")
    for spec in OPTIONS:
        try:
            det = make_detector(spec)
        except Exception as e:  # e.g. ncnn not installed
            print(f"{spec.split('/')[-1]:<40} skipped: {e}")
            continue
        ms = bench(det, frame, args.n)
        print(f"{spec.split('/')[-1]:<40} {ms:6.1f} ms  ({1000 / ms:4.1f} fps)")
    if args.ssd:
        from ml.detection.compare_detectors import MobileNetSsd

        ms = bench(MobileNetSsd(args.ssd, conf=0.4), frame, args.n)
        print(f"{'MobileNet-SSD 300':<40} {ms:6.1f} ms  ({1000 / ms:4.1f} fps)")


if __name__ == "__main__":
    main()
