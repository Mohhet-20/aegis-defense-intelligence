"""Detection postprocessing and validation. The
ONLY path from an adapter's `RawDetection` list to something that is
ever persisted as a `DetectionResult`. Three responsibilities, always
in this order:

1. Reject anything non-finite, out-of-range, or using a class_label
   outside the explicit allow-list (never silently clamp a bad value --
   drop that one detection and count it as rejected).
2. Run real non-maximum suppression via `cv2.dnn.NMSBoxes` -- a tested
   OpenCV library function, never hand-rolled IoU-sorting math (Section
   6 is explicit about this).
3. Normalize pixel-space coordinates to 0..1 fractions of the frame's
   width/height, and cap the result at
   `settings.CV_MAX_DETECTIONS_PER_FRAME`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.config import get_settings
from app.cv.adapters.base import RawDetection
from app.models.detection_result import ALLOWED_CLASS_LABELS

settings = get_settings()


@dataclass(frozen=True)
class ValidatedDetection:
    class_label: str
    confidence: float
    bbox_x_min: float
    bbox_y_min: float
    bbox_x_max: float
    bbox_y_max: float


def _is_finite(*values: float) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def _structurally_valid(det: RawDetection, frame_width: int, frame_height: int) -> bool:
    if det.class_label not in ALLOWED_CLASS_LABELS:
        return False
    if not _is_finite(det.confidence, det.x_min, det.y_min, det.x_max, det.y_max):
        return False
    if not (0.0 <= det.confidence <= 1.0):
        return False
    if det.x_min < 0 or det.y_min < 0 or det.x_max > frame_width or det.y_max > frame_height:
        return False
    if det.x_max <= det.x_min or det.y_max <= det.y_min:
        return False
    return True


def postprocess(
    raw_detections: list[RawDetection],
    *,
    frame_width: int,
    frame_height: int,
    confidence_threshold: float | None = None,
    nms_iou_threshold: float | None = None,
) -> tuple[list[ValidatedDetection], int]:
    """Returns (validated_detections, rejected_count). `rejected_count`
    is always reported honestly to the caller (InferenceJob doesn't
    silently drop bad model output without a trace) even though
    individual rejection reasons are not persisted per-detection."""
    import cv2  # local import: keeps this module importable without cv2 for pure unit tests of the math

    confidence_threshold = settings.CV_DEFAULT_CONFIDENCE_THRESHOLD if confidence_threshold is None else confidence_threshold
    nms_iou_threshold = settings.CV_DEFAULT_NMS_IOU_THRESHOLD if nms_iou_threshold is None else nms_iou_threshold

    structurally_valid = [d for d in raw_detections if _structurally_valid(d, frame_width, frame_height)]
    rejected_count = len(raw_detections) - len(structurally_valid)

    above_threshold = [d for d in structurally_valid if d.confidence >= confidence_threshold]
    rejected_count += len(structurally_valid) - len(above_threshold)

    if not above_threshold:
        return [], rejected_count

    # cv2.dnn.NMSBoxes wants boxes as (x, y, w, h), not (x_min, y_min,
    # x_max, y_max) -- converted here, nowhere else.
    xywh_boxes = [[d.x_min, d.y_min, d.x_max - d.x_min, d.y_max - d.y_min] for d in above_threshold]
    scores = [d.confidence for d in above_threshold]
    keep_indices = cv2.dnn.NMSBoxes(xywh_boxes, scores, confidence_threshold, nms_iou_threshold)
    # OpenCV has returned both a flat array and a list-of-lists across
    # versions for this call -- normalize defensively rather than
    # assume one shape.
    flat_indices = [int(i[0]) if hasattr(i, "__len__") else int(i) for i in keep_indices] if len(keep_indices) else []

    kept = [above_threshold[i] for i in flat_indices]
    rejected_count += len(above_threshold) - len(kept)

    kept.sort(key=lambda d: d.confidence, reverse=True)
    kept = kept[: settings.CV_MAX_DETECTIONS_PER_FRAME]

    validated = [
        ValidatedDetection(
            class_label=d.class_label,
            confidence=round(d.confidence, 6),
            bbox_x_min=round(d.x_min / frame_width, 6),
            bbox_y_min=round(d.y_min / frame_height, 6),
            bbox_x_max=round(d.x_max / frame_width, 6),
            bbox_y_max=round(d.y_max / frame_height, 6),
        )
        for d in kept
    ]
    return validated, rejected_count
