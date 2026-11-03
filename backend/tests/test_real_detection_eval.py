"""Real-image detection evaluation (app/cv/coco_eval.py) and the pretrained SSD adapter.

Math and API tests use a tiny generated manifest and run everywhere. Tests that need
the downloaded weights (scripts/fetch_models.py) or the COCO subset
(scripts/fetch_eval_data.py) skip themselves when those are not installed.
"""
from __future__ import annotations

import hashlib
import json

import cv2
import numpy as np
import pytest

from app.core.config import get_settings
from app.cv import coco_eval
from app.cv.adapters.base import RawDetection
from app.cv.adapters.ssd_mobilenet_adapter import platform_label
from app.cv.model_assets import SSD_MOBILENET_V1_COCO, installed

API = "/api/v1"
B = coco_eval.Box


# --------------------------------------------------------------- matching / AP ---
def test_match_image_greedy_by_confidence_with_crowd_regions():
    gts = [B("person", 0, 0, 10, 10), B("person", 20, 0, 30, 10), B("person", 40, 0, 60, 20, ignore=True)]
    preds = [
        B("person", 0, 0, 10, 10, 0.9),     # TP (gt 1)
        B("person", 1, 1, 10, 10, 0.8),     # duplicate of gt 1 -> FP
        B("person", 41, 0, 60, 20, 0.7),    # on the crowd region -> ignored
        B("person", 80, 80, 90, 90, 0.6),   # nowhere -> FP
    ]
    scored, n_gt = coco_eval.match_image(preds, gts, 0.5)
    assert n_gt == 2
    assert [(c, tp) for c, tp, _ in scored] == [(0.9, True), (0.8, False), (0.6, False)]


def test_average_precision_edge_cases():
    assert coco_eval.average_precision([], 0) is None              # undefined, never 0
    assert coco_eval.average_precision([], 3) == 0.0
    assert coco_eval.average_precision([(0.9, True, 1.0), (0.8, True, 1.0)], 2) == pytest.approx(1.0)
    # one hit then one miss with 2 GT: recall reaches 0.5 at precision 1.0 -> AP ~ 51/101
    assert coco_eval.average_precision([(0.9, True, 1.0), (0.1, False, 0.0)], 2) == pytest.approx(51 / 101)


# ------------------------------------------------------ evaluate() on a tiny set ---
def _tiny_dataset(root, n=4):
    """n 64x48 images; image i has one 'person' box; images also get a crowd region."""
    d = root / coco_eval.DATASET_NAME
    (d / "images").mkdir(parents=True)
    images = []
    for i in range(n):
        img = np.zeros((48, 64, 3), np.uint8)
        ok, buf = cv2.imencode(".jpg", img)
        data = buf.tobytes()
        (d / "images" / f"{i}.jpg").write_bytes(data)
        images.append({"image_id": i, "file": f"images/{i}.jpg", "sha256": hashlib.sha256(data).hexdigest(), "width": 64, "height": 48,
                       "licence": None, "boxes": [{"label": "person", "x_min": 10, "y_min": 10, "x_max": 30, "y_max": 30, "ignore": False}]})
    (d / "manifest.json").write_text(json.dumps({"dataset_name": coco_eval.DATASET_NAME, "dataset_version": "test-n%d" % n,
                                                  "source": "generated for tests", "images": images}))
    return d


class _HalfRightAdapter:
    """Finds the person in even-numbered calls, hallucinates a vehicle in odd ones."""
    adapter_key, task_type, is_real_model = "test", "object_detection", False

    def __init__(self):
        self.calls = 0

    def predict(self, image_bgr):
        self.calls += 1
        if self.calls % 2:
            return [RawDetection("person", 0.9, 10, 10, 30, 30)]
        return [RawDetection("vehicle", 0.8, 40, 5, 60, 40)]


def test_evaluate_on_generated_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "CV_EVAL_DATA_DIR", str(tmp_path))
    _tiny_dataset(tmp_path, 4)
    r = coco_eval.evaluate(_HalfRightAdapter(), operating_threshold=0.35)
    person, vehicle = r["per_class"]["person"], r["per_class"]["vehicle"]
    assert r["is_synthetic"] is False and r["sample_count"] == 4
    assert (person["tp"], person["fp"], person["fn"], person["ground_truth"]) == (2, 0, 2, 4)
    assert person["precision"] == 1.0 and person["recall"] == 0.5
    assert (vehicle["tp"], vehicle["fp"], vehicle["ground_truth"]) == (0, 2, 0)
    assert vehicle["ap50"] is None and vehicle["recall"] is None   # no vehicle ground truth: undefined
    assert r["overall"]["map50"] == pytest.approx(person["ap50"])  # mAP averages only defined APs


def test_evaluate_refuses_tampered_images(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "CV_EVAL_DATA_DIR", str(tmp_path))
    d = _tiny_dataset(tmp_path, 2)
    (d / "images" / "1.jpg").write_bytes(b"not the recorded image")
    with pytest.raises(coco_eval.DatasetUnavailable, match="SHA-256"):
        coco_eval.evaluate(_HalfRightAdapter())


def test_missing_dataset_has_an_actionable_message(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "CV_EVAL_DATA_DIR", str(tmp_path / "nothing-here"))
    with pytest.raises(coco_eval.DatasetUnavailable, match="fetch_eval_data.py"):
        coco_eval.load_manifest()


# ------------------------------------------------------------------- API / MLOps ---
def test_evaluation_api_real_dataset(client, tokens, auth_header, cv_mock_model, tmp_path, monkeypatch):
    h = auth_header(tokens, "analyst")
    monkeypatch.setattr(get_settings(), "CV_EVAL_DATA_DIR", str(tmp_path / "absent"))
    r = client.post(f"{API}/evaluation/runs", headers=h, json={"model_record_id": cv_mock_model.id, "dataset": "coco_val2017_subset"})
    assert r.status_code == 409 and "fetch_eval_data.py" in r.json()["detail"]

    monkeypatch.setattr(get_settings(), "CV_EVAL_DATA_DIR", str(tmp_path))
    _tiny_dataset(tmp_path, 3)
    r = client.post(f"{API}/evaluation/runs", headers=h, json={"model_record_id": cv_mock_model.id, "dataset": "coco_val2017_subset"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_synthetic"] is False and body["dataset_name"] == "coco_val2017_subset" and body["sample_count"] == 3
    # the mock adapter only emits "mock_object": no person is found, every person is a false negative
    assert body["metrics_detail"]["per_class"]["person"]["fn"] == 3

    bad = client.post(f"{API}/evaluation/runs", headers=h, json={"model_record_id": cv_mock_model.id, "dataset": "imagenet"})
    assert bad.status_code == 422


def test_mlops_detection_experiment_on_real_dataset(client, tokens, auth_header, cv_mock_model, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "CV_EVAL_DATA_DIR", str(tmp_path))
    _tiny_dataset(tmp_path, 3)
    r = client.post(f"{API}/mlops/experiments", headers=auth_header(tokens, "analyst"), json={
        "model_record_id": cv_mock_model.id, "experiment_name": "real-images",
        "detection": {"fixture": "coco_val2017_subset", "sample_count": 3}})
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "succeeded", run
    assert run["is_synthetic"] is False and run["dataset_name"] == "coco_val2017_subset"


# ------------------------------------------------------- pretrained SSD adapter ---
def test_coco_class_mapping_stays_inside_the_allow_list():
    from app.models.detection_result import ALLOWED_CLASS_LABELS

    assert platform_label(1) == "person"
    assert {platform_label(i) for i in range(2, 10)} == {"vehicle"}
    assert platform_label(17) is None and platform_label(72) is None  # cat, tv: dropped
    assert {"person", "vehicle"} <= set(ALLOWED_CLASS_LABELS)


needs_weights = pytest.mark.skipif(not installed(SSD_MOBILENET_V1_COCO), reason="SSD weights not installed (scripts/fetch_models.py)")


@needs_weights
def test_ssd_adapter_returns_allow_listed_pixel_boxes_and_tolerates_bad_input():
    from app.cv.adapters.registry import get_adapter

    adapter = get_adapter("ssd_mobilenet_v1_coco")
    assert adapter.is_real_model
    assert adapter.predict(np.zeros((10, 10), np.uint8)) == []        # not HxWx3: no crash, no output
    blank = adapter.predict(np.zeros((240, 320, 3), np.uint8))
    for d in blank:
        assert d.class_label in ("person", "vehicle") and 0 <= d.x_min < d.x_max <= 320 and 0 <= d.y_min < d.y_max <= 240


@needs_weights
@pytest.mark.skipif(not (coco_eval.dataset_root() / "manifest.json").is_file(), reason="COCO subset not installed (scripts/fetch_eval_data.py)")
def test_ssd_on_real_coco_images_beats_the_classical_baseline():
    from app.cv.adapters.registry import get_adapter

    ssd = coco_eval.evaluate(get_adapter("ssd_mobilenet_v1_coco"), sample_count=60)
    hog = coco_eval.evaluate(get_adapter("opencv_hog_person_v1"), sample_count=60)
    assert ssd["overall"]["map50"] > 0.25                       # a real detector finds real people/vehicles
    assert ssd["per_class"]["person"]["ap50"] > hog["per_class"]["person"]["ap50"] + 0.2
