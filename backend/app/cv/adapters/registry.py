"""The adapter allow-list. A ModelRecord's
`adapter_key` column is just a string; THIS map is what actually turns
that string into Python code that runs -- and only a key already
present here can ever be executed. This is a deliberate, closed set,
never a dynamic import of an arbitrary dotted path, so a ModelRecord row
can never cause this platform to load or execute code it doesn't already
ship with ("no arbitrary code execution").
"""
from __future__ import annotations

from typing import Callable

from app.cv.adapters.base import CVModelAdapter
from app.cv.adapters.mock_adapter import MockDetectionAdapter
from app.cv.adapters.opencv_hog_adapter import OpenCVHOGPersonAdapter
from app.cv.adapters.ssd_mobilenet_adapter import SSDMobileNetCocoAdapter
from app.cv.model_assets import ModelAssetsUnavailable


class UnsupportedRuntimeError(RuntimeError):
    """Raised for a ModelRecord whose adapter_key is not (or is no
    longer) available in this runtime environment -- a clean, specific,
    documented error, never a bare crash. See docs/ml/MODEL_ADAPTERS.md
    "Registering a new adapter" for the exact procedure to add a real
    adapter (e.g. Ultralytics YOLO) in an environment that can install
    it."""


_FACTORIES: dict[str, Callable[[], CVModelAdapter]] = {
    "mock_detector_v1": lambda: MockDetectionAdapter(),
    "opencv_hog_person_v1": lambda: OpenCVHOGPersonAdapter(),
    # Pretrained weights are downloaded separately (scripts/fetch_models.py); the
    # key is always registered so model records stay valid, but get_adapter()
    # raises UnsupportedRuntimeError until verified weights are installed.
    "ssd_mobilenet_v1_coco": lambda: SSDMobileNetCocoAdapter(),
}


def available_adapter_keys() -> list[str]:
    return sorted(_FACTORIES.keys())


def get_adapter(adapter_key: str) -> CVModelAdapter:
    factory = _FACTORIES.get(adapter_key)
    if factory is None:
        raise UnsupportedRuntimeError(
            f"adapter_key '{adapter_key}' is not available in this runtime. "
            f"Available adapters: {available_adapter_keys()}. "
            "See docs/ml/MODEL_ADAPTERS.md to register a new one."
        )
    try:
        return factory()
    except ModelAssetsUnavailable as exc:
        raise UnsupportedRuntimeError(str(exc)) from exc
