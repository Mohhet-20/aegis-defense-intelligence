"""SSDMobileNetCocoAdapter: a pretrained deep-learning object detector.

SSD (Single Shot MultiBox Detector) with a MobileNet v1 backbone, trained on COCO
by the TensorFlow Object Detection API team, run on CPU through OpenCV's DNN
module (already a dependency -- no PyTorch/TensorFlow runtime is installed).
Weights are fetched by scripts/fetch_models.py and verified against pinned
SHA-256 hashes (app/cv/model_assets.py) before they are ever loaded.

Output is limited to the platform's class allow-list: COCO "person" -> person,
COCO vehicle classes -> vehicle; every other COCO class is dropped. This is a
generic object localizer: no identity, face or biometric output of any kind.
Detections are advisory and go through the same post-processing and human
review as every other adapter's output.
"""
from __future__ import annotations

import threading

import cv2
import numpy as np

from app.cv.adapters.base import RawDetection
from app.cv.model_assets import SSD_MOBILENET_V1_COCO, verified_paths

# COCO category ids as used by the TF Object Detection API (and instances_*.json).
COCO_PERSON = 1
COCO_VEHICLES = {2: "bicycle", 3: "car", 4: "motorcycle", 5: "airplane", 6: "bus", 7: "train", 8: "truck", 9: "boat"}
INPUT_SIZE = (300, 300)
# Keep low-confidence candidates; postprocessing applies the job's threshold and NMS.
MIN_CANDIDATE_CONFIDENCE = 0.05

_net = None
_lock = threading.Lock()


def _get_net():
    global _net
    with _lock:
        if _net is None:
            paths = verified_paths(SSD_MOBILENET_V1_COCO)
            _net = cv2.dnn.readNetFromTensorflow(str(paths["frozen_inference_graph.pb"]), str(paths["ssd_mobilenet_v1_coco_2017_11_17.pbtxt"]))
        return _net


def platform_label(coco_category_id: int) -> str | None:
    if coco_category_id == COCO_PERSON:
        return "person"
    if coco_category_id in COCO_VEHICLES:
        return "vehicle"
    return None


class SSDMobileNetCocoAdapter:
    adapter_key = "ssd_mobilenet_v1_coco"
    task_type = "object_detection"
    is_real_model = True

    def __init__(self) -> None:
        # Fail fast (with instructions) if the weights are missing or tampered with.
        _get_net()

    def predict(self, image_bgr: np.ndarray) -> list[RawDetection]:
        if image_bgr is None or image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
            return []
        height, width = image_bgr.shape[:2]
        blob = cv2.dnn.blobFromImage(image_bgr, size=INPUT_SIZE, swapRB=True, crop=False)
        net = _get_net()
        with _lock:  # cv2.dnn.Net is not safe for concurrent forward() calls
            net.setInput(blob)
            out = net.forward()
        detections: list[RawDetection] = []
        for row in out[0, 0]:
            confidence = float(row[2])
            label = platform_label(int(row[1]))
            if label is None or not np.isfinite(confidence) or confidence < MIN_CANDIDATE_CONFIDENCE:
                continue
            x_min, y_min, x_max, y_max = (float(np.clip(v, 0.0, 1.0)) for v in row[3:7])
            if x_max <= x_min or y_max <= y_min:
                continue
            detections.append(RawDetection(
                class_label=label, confidence=min(confidence, 1.0),
                x_min=x_min * width, y_min=y_min * height, x_max=x_max * width, y_max=y_max * height,
            ))
        return detections
