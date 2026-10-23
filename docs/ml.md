# ML and AI: methods and results

All numbers come from scripts in this repo and can be reproduced with the commands shown.

## 1. Disease suggestion from symptoms (`ml/disease/`)

**Data.** The hackathon dataset (93 binary symptoms, 26 diseases) has 2,044 training rows but only 433 distinct ones, and 11 of its 26 test rows also appear in training, so the original accuracy was inflated. Train and test were merged and de-duplicated (448 distinct cases) and models were compared with stratified 5-fold cross-validation repeated 3 times.

**Two settings.** *Full*: all of a case's symptoms (5–8). *Partial*: only 2–3 random symptoms, which is what a farmer typically ticks. "Dropout" training adds copies of each case with random symptoms removed.

| Model | Training | Full top-1 | Partial top-1 | Partial top-3 |
|---|---|---|---|---|
| Decision tree (hackathon) | plain | 0.839 | 0.478 | 0.514 |
| Random forest | plain | 1.000 | 0.847 | 0.971 |
| Logistic regression | dropout | 1.000 | 0.877 | 0.976 |
| **Bernoulli naive Bayes (chosen)** | **dropout** | **1.000** | **0.865** | **0.978** |

The chosen model is calibrated (sigmoid) and returns the top 3 diseases with probabilities. Caveat: the dataset is synthetic; the dashboard labels results as suggestions, not a diagnosis.

Reproduce: `python -m ml.disease.train`

## 2. Health anomaly detection from collar data (`ml/anomaly/`)

**Ground truth.** Real labelled cattle sensor data was not available, so `simulator/` generates a herd with individual baselines, daily rhythms, barn heat stress, and randomly injected events with labels: fever, lameness, estrus, collar dropouts and single-sample sensor glitches. Evaluation: 50 cows × 21 days, event rate ×4, first 2 days excluded (baselines warming up), two climates.

**Detector.** Streaming and explainable (see `docs/architecture.md`): median glitch filter, comparison with the herd at the same moment, per-animal hour-of-day activity baselines normalised by the herd, persistence and cooldown, auto-resolution.

| Event | Mild climate recall | Hot climate recall | Median time to alert |
|---|---|---|---|
| Fever | 40/41 (0.98) | 40/41 (0.98) | 1.4–1.6 h |
| Lameness (low activity) | 18/19 (0.95) | 18/19 (0.95) | 7.2 h (uses a 6 h window) |
| Estrus (high activity) | 58/64 (0.91) | 58/64 (0.91) | 1.6–1.7 h |
| Collar offline | 35/35 (1.00) | 35/35 (1.00) | 11 min |
| Barn heat stress | 22/22 | 7/7 | — |

| Alert quality | Mild | Hot |
|---|---|---|
| Precision (animal alerts explained by a real event) | 0.77 | 0.80 |
| False alarms per 100 cow-days | 7.3 | 6.1 |
| False alarms from sensor glitches | 0 | 0 |
| False fever alarms | 0 | 0 |

Remaining false alarms are activity alerts (info/warning level). What changed the numbers most during development: precision went from 0.31 to 0.77 by pairing each activity sample with its own hour's expected value (2 h windows straddling the feeding peak had inflated ratios), and the hot-climate case improved again by dividing each cow's ratio by the herd's (heat slows every cow at once).

Reproduce:
```
python -m simulator.run offline --days 21 --event-rate 4 --climate mild --seed 11 --out simulator/out/eval_mild
python -m ml.anomaly.evaluate simulator/out/eval_mild
```

## 3. Cow detection for the rover (`ml/detection/`)

The hackathon rover followed a green marker and the web app used a Roboflow *person* model. The rebuild fine-tunes YOLO11n for cows:

- Data: COCO 2017 cow images, Open Images V7 "Cattle", and negatives (horses, sheep, dogs, people without cows) so the rover does not chase them.
- Baseline: the stock COCO-pretrained YOLO11n scored on the same validation images (class "cow").
- Training on the laptop GPU with a thermal guard (pauses above 78 °C until 70 °C, short rest after each batch).
- Export: ONNX at 320 px for OpenCV DNN (laptop and Pi) and NCNN for the Pi 4.

**Results** (validation: 139 images never used in training — COCO 2017 val cows + held-out Open Images cattle):

| Model | mAP50 | mAP50-95 | Precision | Recall |
|---|---|---|---|---|
| Stock YOLO11n (COCO "cow" class) | 0.631 | 0.440 | 0.718 | 0.567 |
| **Fine-tuned YOLO11n (ours)** | **0.726** | **0.491** | **0.749** | **0.659** |

Training data: 3,638 images (1,968 COCO cow, 470 Open Images cattle, 1,200 negatives). 60 epochs at 512 px took 66 minutes on the RTX 3050 laptop GPU; the thermal guard log shows a peak of 64 °C and no pauses. The exported ONNX model (320 px) runs at about 10 ms per frame on the laptop CPU through `rover/vision.py`, and finds cows on grass where the legacy green-marker tracker locks onto the field. Pi 4 speed (ONNX via OpenCV and NCNN) is to be measured when the hardware is back.

Reproduce (in WSL): `bash ml/detection/run_pipeline.sh`, or step by step `python -m ml.detection.prepare_data`, `python -m ml.detection.train`, `python -m ml.detection.export --weights ~/lms-runs/cow-yolo11n/weights/best.pt`. Results are written to `~/lms-runs/cow-yolo11n/report.json`.

## 4. Person detection (prepared, not trained yet)

The rover must recognise people: to stop when one is close (the ultrasonic only looks straight ahead) and never to follow one. The plan is a single two-class model, **cow + person**, so the Pi 4 runs one detector pass per frame instead of two.

**Label quality.** A person visible in an image but missing from its labels teaches the model that people are background, which is the dangerous error for a rover. So:
- COCO labels every person in every image; COCO images keep all their cow and person boxes, and only COCO images are used for validation.
- Open Images cattle photos often show farmers without person boxes. They are used for training only, after `pseudo_label_persons.py` fills in people with a large pretrained detector (YOLO11x, confidence ≥ 0.5, inference only).

**Dataset** (`ml/detection/prepare_cow_person.py`): COCO train images with cows, farm scenes (people with horses/sheep/cows), a sample of images with people, and animal-only negatives; COCO validation cows plus a sample of people; Open Images V7 cattle. Built on 2026-10-10: training 5,926 images (5,404 COCO + 522 Open Images), validation 463 COCO images; 9,551 cow and 16,752 person boxes from the original labels, plus 254 person boxes pseudo-labelled on 59 of the 522 Open Images photos. Counts are in the dataset's `manifest.json`.

**Rover side (done):** `rover/safety.py` blocks forward motion when a confident person box is taller than 35 % of the frame (backing away and turning stay allowed); `rover/controller.py` never picks a person as the follow target. Works with any model that outputs a `person` class.

**To train later** (in WSL, gentle settings with the thermal guard):
```
bash ml/detection/run_cow_person_pipeline.sh data    # already run: dataset + pseudo-labels
bash ml/detection/run_cow_person_pipeline.sh train   # 80 epochs, then export to ml/detection/models/cow_person.*
```
The report will give per-class precision/recall for the stock COCO model and the fine-tuned one on the same validation images; person recall is the number that matters most.
