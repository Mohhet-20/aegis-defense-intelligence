"""OpenCVHOGPersonAdapter. This platform's one
REAL, non-mock image object-detection adapter.

Why this instead of the specification's suggested Ultralytics YOLO: this
sandbox's network policy blocks the PyTorch CPU wheel index
(download.pytorch.org returns 403 through the environment's proxy), and
the default PyPI `torch` package pulls a multi-gigabyte CUDA toolkit
dependency chain (nvidia-cublas, nvidia-cudnn, etc. -- see the pip
dry-run output preserved in docs/ml/MODEL_ADAPTERS.md) that is both
unnecessary for CPU-only inference and large enough to risk exhausting
this session's disk allowance. The specification's own Section 4 says
exactly what to do here: "if the environment does not support [a real
adapter], provide a clean, documented error ... rather than crashing
unpredictably" and do not fake a result that was not produced.

So: this adapter uses OpenCV's bundled HOG (Histogram of Oriented
Gradients) + linear SVM person detector -- `cv2.HOGDescriptor` with
`cv2.HOGDescriptor_getDefaultPeopleDetector()`. This is REAL,
non-synthetic inference: a real, pretrained, published classical
computer-vision model, running real math over real decoded pixels, with
its weights already bundled inside the opencv-python-headless wheel
already installed in this environment -- no network fetch, no model
download, at request time or ever.

This is a GENERIC object-localizer, not an identity system: it answers
"is there a person-shaped silhouette here," never "who is this," and it
produces no embedding, no face data, and no identity of any kind -- see
docs/security/MEDIA_UPLOAD_SECURITY.md's non-goals and the module-level
ALLOWED_CLASS_LABELS allow-list in app/models/detection_result.py, which
this adapter's output is still subject to like every other adapter's.

Classical HOG detection is also honestly weaker than a modern deep
detector, especially on small/synthetic test imagery -- see
docs/ml/MODEL_ADAPTERS.md's "known limitations" section and
tests/test_image_inference.py's comment on why that test asserts
schema-correctness and non-crashing, not a specific detection count.
"""
from __future__ import annotations

import cv2
import numpy as np

from app.cv.adapters.base import RawDetection

_detector = None


def _get_detector() -> "cv2.HOGDescriptor":
    global _detector
    if _detector is None:
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        _detector = hog
    return _detector


class OpenCVHOGPersonAdapter:
    adapter_key = "opencv_hog_person_v1"
    task_type = "object_detection"
    is_real_model = True

    def predict(self, image_bgr: np.ndarray) -> list[RawDetection]:
        hog = _get_detector()
        # detectMultiScale's own docs recommend an 8x8 winStride; this
        # is the library's own tested default behavior, not a custom
        # heuristic this adapter invented.
        boxes, weights = hog.detectMultiScale(image_bgr, winStride=(8, 8), padding=(8, 8), scale=1.05)
        detections: list[RawDetection] = []
        for (x, y, w, h), weight in zip(boxes, weights):
            # cv2's HOG detector returns an unbounded "weight" (SVM
            # decision distance), not a probability -- squash it into
            # [0, 1] with a logistic function so downstream code can
            # treat every adapter's confidence the same way, rather than
            # silently assuming they all already come out of [0, 1].
            confidence = float(1.0 / (1.0 + np.exp(-float(weight))))
            detections.append(
                RawDetection(
                    class_label="person",
                    confidence=confidence,
                    x_min=float(x),
                    y_min=float(y),
                    x_max=float(x + w),
                    y_max=float(y + h),
                )
            )
        return detections
