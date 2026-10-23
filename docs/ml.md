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

**Layer 3: IsolationForest (`ml/anomaly/multivariate.py`), tested and left off.** An IsolationForest (200 trees) learns what healthy cows look like from four herd-relative features: temperature vs herd, HR vs herd, 6 h activity vs normal, and 2 h activity vs normal. It was trained on 54,805 healthy 15-minute snapshots of a different simulated herd (seed 7, labelled events removed). The threshold flags 0.2% of healthy rows, and an alert needs 3 unusual scores in a row.

| On the eval herds (seed 11) | Mild | Hot |
|---|---|---|
| "unusual_pattern" alerts | 120 | 124 |
| Explained by a real event | 0.68 | 0.69 |
| Extra false alerts per 100 cow-days | 4.0 | 4.0 |
| Events the rules missed but the model caught | 0 | 0 |
| Events the model flagged before the rules | 2 | 3 |

It finds the same sick cows as the rules, a little later, plus extra false alerts, so the processor runs it only with `LMS_IFOREST=1`. That is probably a limit of the simulator: each simulated illness moves one or two signals strongly, which the rules already catch. Real collar data, where early illness shows up as small changes in several signals at once, is where this layer could earn its place. Re-test it then. Report: `ml/anomaly/models/iforest_report.json`.
```
python -m ml.anomaly.multivariate train simulator/out/run1
python -m ml.anomaly.multivariate eval simulator/out/eval_mild simulator/out/eval_hot
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

## 4. Person detection (cow + person model)

The rover must recognise people: to stop when one is close (the ultrasonic only looks straight ahead) and never to follow one. The plan is a single two-class model, **cow + person**, so the Pi 4 runs one detector pass per frame instead of two.

**Label quality.** A person visible in an image but missing from its labels teaches the model that people are background, which is the dangerous error for a rover. So:
- COCO labels every person in every image; COCO images keep all their cow and person boxes, and only COCO images are used for validation.
- Open Images cattle photos often show farmers without person boxes. They are used for training only, after `pseudo_label_persons.py` fills in people with a large pretrained detector (YOLO11x, confidence ≥ 0.5, inference only).

**Dataset** (`ml/detection/prepare_cow_person.py`): COCO train images with cows, farm scenes (people with horses/sheep/cows), a sample of images with people, and animal-only negatives; COCO validation cows plus a sample of people; Open Images V7 cattle. Built on 2026-10-10: training 5,926 images (5,404 COCO + 522 Open Images), validation 463 COCO images; 9,551 cow and 16,752 person boxes from the original labels, plus 254 person boxes pseudo-labelled on 59 of the 522 Open Images photos. Counts are in the dataset's `manifest.json`.

**Rover side (done):** `rover/safety.py` blocks forward motion when a confident person box is taller than 35 % of the frame (backing away and turning stay allowed); `rover/controller.py` never picks a person as the follow target. Works with any model that outputs a `person` class.

**Result (trained 2026-10-10, 80 epochs, 2.4 h, GPU peak 72 °C, no thermal pauses).** Same 463 COCO validation images for both models:

| | Stock YOLO11n (COCO) | Fine-tuned cow+person |
|---|---|---|
| Person mAP50 / recall | **0.676 / 0.589** | 0.633 / 0.525 |
| Cow mAP50 / recall | 0.714 / 0.609 | **0.724 / 0.636** |
| Overall mAP50 | **0.695** | 0.678 |

The fine-tuned model got slightly better at cows but **worse at people**. The stock model learned people from ~64,000 COCO images; fine-tuning on ~3,000 made it partly forget them (catastrophic forgetting). Because person recall is the safety-critical number, the rover keeps the **stock COCO YOLO11n** for people (it also detects cows almost as well), or the cow-only fine-tuned model when following cows matters most. The fine-tuned cow+person model is not deployed; its report is `ml/detection/models/cow_person_report.json`.

Next attempt, if needed: freeze the backbone (`freeze=10`), lower the learning rate, and mix in many more COCO person images so the model doesn't forget.

**Reproduce** (in WSL, gentle settings with the thermal guard):
```
bash ml/detection/run_cow_person_pipeline.sh data    # already run: dataset + pseudo-labels
bash ml/detection/run_cow_person_pipeline.sh train   # 80 epochs, then export to ml/detection/models/cow_person.*
```
The report will give per-class precision/recall for the stock COCO model and the fine-tuned one on the same validation images; person recall is the number that matters most.

## 5. Detector comparison: MobileNet-SSD vs YOLO11n (2026-10-24)

A friend's Pi script used **MobileNet-SSD** (chuanqi305, Caffe, Pascal VOC, 300 px). It was scored against the rover's YOLO11n on the same 463 COCO validation images (cow + person boxes), with the same matching (IoU ≥ 0.5), OpenCV DNN 4.10, 4 threads: `python -m ml.detection.compare_detectors --data /root/lms-data/cow_person --ssd /root/lms-data/mobilenet_ssd [--min-frac 0.2] [--yolo PATH@SIZE]`. "Near" = objects at least 20 % of the image height (what the rover acts on).

| Model | ms/frame (laptop, 4 thr) | Near cow AP50 / recall | Near person AP50 / recall | All cows AP50 | All people AP50 |
|---|---|---|---|---|---|
| MobileNet-SSD 300 | **12** | 0.60 / 0.61 | 0.61 / 0.58 | 0.26 | 0.30 |
| YOLO11n 256 | 11 | 0.79 / 0.67 | 0.79 / 0.64 | 0.49 | 0.50 |
| **YOLO11n 320 (rover)** | 15 | 0.80 / 0.77 | 0.82 / 0.71 | 0.50 | 0.56 |
| YOLO11n 416 | 27 | **0.83 / 0.76** | **0.85 / 0.76** | **0.62** | **0.63** |
| YOLO11n cow-only fine-tuned 320 | 18 | 0.75 / 0.74 | – | 0.58 | – |

Decision: keep YOLO11n. The SSD is ~1.3–1.6× faster but misses about 4 in 10 near people and gets half the AP on all objects; its Caffe format is also gone from OpenCV 5. Nothing from it was reused except the observation that a smaller input is faster (256 px costs too much person recall).

Quick wins done: the rover keeps more COCO classes (person, bird, cat, dog, horse, sheep, cow; follows cow/sheep/horse only); detectors take an input size (`yolo:PATH@416`, `ncnn:FOLDER@416`); COCO YOLO11n is exported at 416 px as ONNX and NCNN (`coco_yolo11n_416*`, NCNN output checked identical to ONNX on 40 images). Next: `python -m ml.detection.bench_pi` on the Pi 4 to pick between ONNX 320 (121 ms measured) and NCNN 320/416.
