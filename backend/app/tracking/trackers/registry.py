"""The tracker allow-list. A `TrackingJob.tracker_key`
is just a string column; THIS map is what actually turns that string
into Python code that runs -- the exact same closed-allow-list
discipline as Phase 4's `app/cv/adapters/registry.py`, applied to
trackers instead of CV model adapters. A key not already present here
can never be executed, regardless of what a client requests.
"""
from __future__ import annotations

from typing import Callable

from app.tracking.trackers.base import ObjectTracker
from app.tracking.trackers.iou_tracker import TRACKER_VERSION, IoUHungarianTracker, TrackerConfig

_FACTORIES: dict[str, Callable[[TrackerConfig], ObjectTracker]] = {
    "iou_hungarian_v1": lambda config: IoUHungarianTracker(config),
}

_VERSIONS: dict[str, str] = {
    "iou_hungarian_v1": TRACKER_VERSION,
}


class UnsupportedTrackerError(ValueError):
    """Raised for a tracker_key that is not (or is no longer) available
    -- a clean, specific, documented error, never a bare crash."""


def available_tracker_keys() -> list[str]:
    return sorted(_FACTORIES.keys())


def get_tracker_version(tracker_key: str) -> str:
    if tracker_key not in _VERSIONS:
        raise UnsupportedTrackerError(f"tracker_key '{tracker_key}' is not available. Available trackers: {available_tracker_keys()}")
    return _VERSIONS[tracker_key]


def get_tracker(tracker_key: str, config: TrackerConfig) -> ObjectTracker:
    factory = _FACTORIES.get(tracker_key)
    if factory is None:
        raise UnsupportedTrackerError(f"tracker_key '{tracker_key}' is not available. Available trackers: {available_tracker_keys()}")
    return factory(config)
