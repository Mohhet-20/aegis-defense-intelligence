# Model evaluation

`app/services/evaluation_service.py` scores a registered detector on one of two datasets. Metrics are
always computed on the server from the model's own output; a result is never accepted from a client.

| Dataset key | Contents | `is_synthetic` | What it tells you |
|---|---|---|---|
| `coco_val2017_subset` | Real photographs from the COCO 2017 validation set with human-labelled people and vehicles | **false** | How the detector performs on a public benchmark sample |
| `synthetic_single_rectangle_fixture` | Generated 240x240 images with one rectangle | true | Only that the inference/evaluation pipeline works end to end |

## Results (measured 2026-10-18, Windows 11 CPU, 200 images `val2017-seed0-n200`)

| Detector | mAP@0.5 | Person AP@0.5 | Person P / R at 0.35 | Vehicle AP@0.5 | Vehicle P / R at 0.35 | ms / image |
|---|---|---|---|---|---|---|
| SSD-MobileNet v1 COCO | **0.461** | 0.457 | 0.665 / 0.441 | 0.466 | 0.789 / 0.413 | 14.9 |
| OpenCV HOG person | 0.003 | 0.005 | 0.155 / 0.024 | 0.000 | -- / 0.000 | 30.7 |
| Mock (not a model) | 0.000 | 0.000 | -- / 0.000 | 0.000 | -- / 0.000 | 0.5 |

The sample contains 379 labelled people and 109 labelled vehicles; 92 of the 200 images contain
neither, so false positives on ordinary scenes count. "--" means undefined (no predictions), never 0.
Reproduce with the commands below; the numbers are deterministic for a given sample and model.

**What these numbers are not:** not accuracy on aerial, thermal, night or any operational imagery;
not a validation for any decision; not comparable to published COCO leaderboard figures (those use
all 80 classes, AP averaged over IoU 0.5–0.95, and the full 5,000-image set). They show that a real
pretrained detector runs inside the platform and how it compares with the baselines on the same data.

## How the real-image evaluation works (`app/cv/coco_eval.py`)

1. **Data** -- `python scripts/fetch_eval_data.py [--count 200 --seed 0]` downloads the COCO 2017
   annotations (SHA-256 pinned), samples images uniformly from *all* val2017 images with
   `random.Random(seed)`, downloads them into `CV_EVAL_DATA_DIR` (default `backend/eval_data/`,
   git-ignored) and writes `manifest.json` with each image's SHA-256, licence and person/vehicle
   boxes. Crowd annotations are kept as "ignore" regions.
2. **Inference** -- each image is verified against its hash, run through the adapter, then through
   the production `postprocess()` (allow-list, NMS, per-frame cap) with a 0.05 candidate floor so the
   precision-recall curve is complete.
3. **Matching** -- per image and class, predictions in descending confidence are matched to the
   unmatched ground-truth box with the highest IoU ≥ threshold (default 0.5). Predictions on a crowd
   region are ignored; the rest are false positives.
4. **Metrics** -- AP@0.5 per class (101-point interpolated area under the PR curve, as the COCO
   evaluator does at one IoU), mAP over classes with ground truth, and precision / recall / F1 / mean
   IoU at the platform's operating threshold (`CV_DEFAULT_CONFIDENCE_THRESHOLD`, 0.35). Undefined values
   are stored as null in `metrics_detail` (authoritative) and 0.0 in the legacy non-null columns.

## Running it

- **UI:** Computer vision & tracking → Model Evaluation → choose model, *Real photographs*, images.
- **API:** `POST /api/v1/evaluation/runs` `{"model_record_id": "...", "dataset": "coco_val2017_subset", "sample_count": 200}`
  (409 with instructions if the dataset or the model's weights are not installed).
- **MLOps:** `POST /api/v1/mlops/experiments` with `"detection": {"fixture": "coco_val2017_subset", "sample_count": 200}`;
  the run records the dataset fingerprint (image hashes) for reproducibility and can be compared
  against a baseline like any other experiment.

## Tests

`tests/test_real_detection_eval.py`: matching, crowd handling and AP edge cases; evaluation on a
generated manifest with known answers; tamper detection; API and MLOps paths. Two tests run the real
SSD model on the real images and skip automatically where the weights or images are not installed
(for example in CI). `tests/test_model_evaluation.py` covers the synthetic fixture.

## Not done

Multi-IoU AP (0.5:0.95), other COCO classes, confidence calibration, evaluation on non-public or
operational data, and gating model approval on an evaluation score.
