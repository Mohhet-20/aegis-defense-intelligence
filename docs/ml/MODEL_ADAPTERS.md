# Model adapters

Every detector the platform can run implements one small contract
(`app/cv/adapters/base.py`) and is listed in one closed registry
(`app/cv/adapters/registry.py`). Three ship today:

| Adapter key | What it is | Classes | Real model? | Measured on real photos (mAP@0.5, 200 COCO images) |
|---|---|---|---|---|
| `ssd_mobilenet_v1_coco` | SSD + MobileNet v1, trained on COCO (TensorFlow Object Detection API, Apache-2.0), run on CPU through OpenCV DNN | person, vehicle | **yes -- pretrained deep detector** | **0.461** (person AP 0.457, vehicle AP 0.466; ~15 ms/image) |
| `opencv_hog_person_v1` | OpenCV's HOG + linear SVM people detector (2005-era classical CV), bundled with `opencv-python-headless` | person | yes -- classical | 0.003 (person AP 0.005) |
| `mock_detector_v1` | Deterministic boxes derived from a hash of the image bytes | mock_object | **no** -- pipeline testing only | 0.000 |

How those numbers were produced, and what they do not mean: [`MODEL_EVALUATION.md`](MODEL_EVALUATION.md).

## The contract

```python
class CVModelAdapter(Protocol):
    adapter_key: str
    task_type: str
    is_real_model: bool
    def predict(self, image_bgr: np.ndarray) -> list[RawDetection]: ...
```

`predict()` takes one decoded HxWx3 uint8 BGR frame and returns pixel-space, unvalidated
`RawDetection`s. It must not raise on a well-formed array. Every adapter's output then goes through
the same `app/cv/postprocessing.py` (class allow-list, geometry checks, confidence threshold, NMS,
per-frame cap) and the same human review before anything can become evidence.

## The registry

`ModelRecord.adapter_key` is only a string; `_FACTORIES` in the registry is the closed, hand-written
map that turns it into code. There is no dynamic import, so a database row can never make the
platform load arbitrary code. An unknown key -- or a known key whose weights are missing or fail
verification -- raises `UnsupportedRuntimeError`, which becomes a clean job failure or HTTP 409.

## SSD-MobileNet v1 COCO (`ssd_mobilenet_v1_coco`)

- **Weights:** downloaded by `python scripts/fetch_models.py` (or `--from-dir` for offline installs)
  into `CV_MODEL_DIR` (default `backend/model_artifacts/`, git-ignored). The archive and each
  extracted file are checked against SHA-256 values pinned in `app/cv/model_assets.py`; only the one
  expected member is extracted from the archive. A `PROVENANCE.json` records sources and licence.
- **On load:** the adapter re-verifies both files; a missing or modified file is refused with the
  command that fixes it. `fetch_models.py --check` verifies an installation without downloading.
- **Runtime:** OpenCV DNN (`cv2.dnn.readNetFromTensorflow`), 300x300 input, CPU only, one network
  instance guarded by a lock (OpenCV networks are not safe for concurrent `forward()`).
- **Classes:** COCO `person` → `person`; COCO bicycle, car, motorcycle, airplane, bus, train, truck,
  boat → `vehicle`; all other COCO classes are dropped. No identity, face or biometric output.
- **Limits:** a 2017 mobile-class detector. It misses small and occluded objects (recall ~0.43 at the
  default 0.35 confidence threshold) and was trained on everyday photographs, not aerial,
  thermal or any operational imagery. Its output is advisory and reviewed by a person.

## OpenCV HOG person detector (`opencv_hog_person_v1`)

Real, classical inference with weights bundled in OpenCV. On real photographs it finds almost nothing
(measured AP 0.005), which is why the SSD adapter exists; it remains as a dependency-free baseline.
`opencv-python-headless` is pinned to 4.14: version 5.0 removed `cv2.HOGDescriptor` from the Python
bindings (found by running the adapter, not by reading release notes).

## Mock detector (`mock_detector_v1`)

Not inference. Deterministic boxes derived from the image bytes so the whole pipeline (API, jobs,
postprocessing, review UI) can be built and tested anywhere. Its class label, `mock_object`, can never
be confused with a real detection, and every view labels it as mock.

## Adding an adapter

1. Implement the contract in `app/cv/adapters/<name>.py`.
2. If it needs downloaded weights, describe them in `app/cv/model_assets.py` with pinned SHA-256s and
   verify them before loading (see the SSD adapter).
3. Add it to `_FACTORIES`; add any new class label to `ALLOWED_CLASS_LABELS`
   (`app/models/detection_result.py`) deliberately, one at a time.
4. Register a `ModelRecord` (MLOps registry or `scripts/seed.py`).
5. Evaluate it on real images (`dataset: coco_val2017_subset`) before presenting any result.

## What the adapters do not do

No face recognition, biometric matching or person identification; no GPU assumption; no network
access at inference time; no automated action of any kind.
