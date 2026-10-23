#!/bin/bash
# Full cow-detector pipeline in WSL: data -> gentle training -> export.
#   setsid nohup bash ml/detection/run_pipeline.sh > /root/lms-pipeline.log 2>&1 &
# Data and runs live in the WSL disk (on D:). The exported model lands in ml/detection/models/.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=/root/lms-ml/bin/python
export FIFTYONE_DATABASE_DIR=/root/fiftyone-db FIFTYONE_DATASET_ZOO_DIR=/root/fiftyone
echo "== $(date) prepare data"
$PY -m ml.detection.prepare_data --out /root/lms-data/cows
echo "== $(date) train"
$PY -m ml.detection.train --data /root/lms-data/cows --project /root/lms-runs --epochs 60 --imgsz 512 --batch 8 --hot 78 --cool 70 --rest 0.05
echo "== $(date) export"
$PY -m ml.detection.export --weights /root/lms-runs/cow-yolo11n/weights/best.pt
cp /root/lms-runs/cow-yolo11n/report.json ml/detection/models/report.json
echo "== $(date) PIPELINE_DONE"
