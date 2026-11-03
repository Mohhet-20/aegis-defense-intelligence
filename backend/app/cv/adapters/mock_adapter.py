"""MockDetectionAdapter. A deterministic,
fully-synthetic adapter that performs NO real inference -- it exists so
the inference pipeline, API, and frontend can be built, tested, and
demonstrated end-to-end in any environment, including one with no real
CV model available at all, without ever claiming a result it did not
actually produce.

Determinism is the whole point: given the same image bytes and the same
`max_detections`, this ALWAYS returns the same bounding boxes and
confidences, derived from a sha256 hash of the pixel data -- not from
`random`, and not from anything time-based. This is what makes
`test_image_inference.py` able to assert exact output, and what makes a
demo reproducible across machines.
"""
from __future__ import annotations

import hashlib

import numpy as np

from app.cv.adapters.base import RawDetection


class MockDetectionAdapter:
    adapter_key = "mock_detector_v1"
    task_type = "object_detection"
    is_real_model = False

    def __init__(self, max_detections: int = 2) -> None:
        self.max_detections = max(1, min(max_detections, 5))

    def predict(self, image_bgr: np.ndarray) -> list[RawDetection]:
        height, width = image_bgr.shape[0], image_bgr.shape[1]
        digest = hashlib.sha256(image_bgr.tobytes()).digest()

        detections: list[RawDetection] = []
        for i in range(self.max_detections):
            # Every value below is derived deterministically from the
            # digest -- two different byte offsets per detection so
            # repeated detections on the same image don't collapse to
            # one identical box.
            a, b, c, d, e = digest[i * 5 % 28], digest[(i * 5 + 1) % 28], digest[(i * 5 + 2) % 28], digest[(i * 5 + 3) % 28], digest[(i * 5 + 4) % 28]
            box_w = max(8, int(width * (0.15 + (a / 255.0) * 0.25)))
            box_h = max(8, int(height * (0.15 + (b / 255.0) * 0.25)))
            x_min = int((c / 255.0) * max(1, width - box_w))
            y_min = int((d / 255.0) * max(1, height - box_h))
            confidence = round(0.5 + (e / 255.0) * 0.45, 4)  # always in [0.5, 0.95]
            detections.append(
                RawDetection(
                    class_label="mock_object",
                    confidence=confidence,
                    x_min=float(x_min),
                    y_min=float(y_min),
                    x_max=float(min(width, x_min + box_w)),
                    y_max=float(min(height, y_min + box_h)),
                )
            )
        return detections
