"""The common model-adapter contract. Every
adapter -- mock or real -- implements exactly this interface, so
app/services/inference_service.py never has special-case code for one
adapter vs. another. A `RawDetection` is deliberately NOT a
DetectionResult: it carries pixel-space coordinates and an unvalidated
confidence straight from the adapter; app/cv/postprocessing.py is the
only place that normalizes, validates, and NMS-deduplicates these into
something that is ever persisted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class RawDetection:
    class_label: str
    confidence: float
    # Pixel-space, (x_min, y_min, x_max, y_max), origin top-left -- the
    # natural coordinate space for both OpenCV and a typical object
    # detector's raw output. Never assumed to already be normalized.
    x_min: float
    y_min: float
    x_max: float
    y_max: float


class CVModelAdapter(Protocol):
    """`adapter_key` must match exactly one key in app/cv/registry.py's
    ADAPTERS map -- that map, not this protocol, is the actual
    allow-list of code this platform will ever execute for a
    ModelRecord row."""

    adapter_key: str
    task_type: str
    is_real_model: bool  # False only for MockDetectionAdapter

    def predict(self, image_bgr: np.ndarray) -> list[RawDetection]:
        """`image_bgr` is an HxWx3 uint8 array (OpenCV's conventional
        channel order) of ONE already-decoded frame or image. Must
        never raise on a well-formed array; a model that finds nothing
        returns an empty list, not an exception."""
        ...
