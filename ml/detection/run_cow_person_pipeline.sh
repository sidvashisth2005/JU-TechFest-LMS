#!/bin/bash
# Cow + person detector (2 classes). Run in WSL from the repo root.
#   bash ml/detection/run_cow_person_pipeline.sh data    # download + build dataset + person pseudo-labels (no training)
#   bash ml/detection/run_cow_person_pipeline.sh train   # gentle training (thermal guard) + export
# Data: /root/lms-data/cow_person   Runs: /root/lms-runs/cow-person-yolo11n   (WSL disk, on D:)
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=/root/lms-ml/bin/python
DATA=/root/lms-data/cow_person
export FIFTYONE_DATABASE_DIR=/root/fiftyone-db FIFTYONE_DATASET_ZOO_DIR=/root/fiftyone
case "${1:-}" in
  data)
    echo "== $(date) prepare cow+person dataset"
    $PY -m ml.detection.prepare_cow_person --out "$DATA"
    echo "== $(date) pseudo-label people on Open Images training images"
    $PY -m ml.detection.pseudo_label_persons --data "$DATA"
    echo "== $(date) DATA_DONE"
    ;;
  train)
    echo "== $(date) train"
    $PY -m ml.detection.train --data "$DATA" --project /root/lms-runs --name cow-person-yolo11n \
        --epochs 80 --imgsz 512 --batch 8 --hot 78 --cool 70 --rest 0.05
    echo "== $(date) export"
    $PY -m ml.detection.export --weights /root/lms-runs/cow-person-yolo11n/weights/best.pt --out-name cow_person
    cp /root/lms-runs/cow-person-yolo11n/report.json ml/detection/models/cow_person_report.json
    echo "== $(date) TRAIN_DONE"
    ;;
  *)
    echo "usage: $0 data|train"; exit 1 ;;
esac
