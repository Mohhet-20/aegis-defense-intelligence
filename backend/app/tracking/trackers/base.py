"""The reusable tracker interface. Every tracker
implementation -- today just one -- is driven exactly this way, so
app/services/tracking_service.py never has algorithm-specific code.
Adding a second tracker later means writing a new class against this
same Protocol-shaped contract and adding one line to
app/tracking/trackers/registry.py -- never touching the service or the
API layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass(frozen=True)
class TrackerDetectionInput:
    """One already-validated, already-persisted DetectionResult, as the
    tracker needs to see it -- fractional (0..1) bbox coordinates, the
    detection's own id for lineage, nothing else. The tracker never sees
    raw pixels; it operates purely on the detector's own structured
    output (no facial/biometric data ever reaches this
    layer)."""

    detection_result_id: str
    class_label: str
    confidence: float
    bbox_x_min: float
    bbox_y_min: float
    bbox_x_max: float
    bbox_y_max: float

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.bbox_x_min, self.bbox_y_min, self.bbox_x_max, self.bbox_y_max)


@dataclass
class TrackObservationRecord:
    """One frame's worth of a track's history, as the tracker emits it
    -- app/services/tracking_service.py turns this directly into a
    TrackObservation row, unchanged."""

    frame_index: int
    timestamp_seconds: float
    detection_result_id: str
    class_label: str
    confidence: float
    bbox: tuple[float, float, float, float]
    association_method: str
    association_cost: Optional[float]


@dataclass
class TrackLifecycleEvent:
    frame_index: int
    timestamp_seconds: float
    from_state: Optional[str]
    to_state: str
    reason: str


@dataclass
class FinalizedTrack:
    """One track's complete history at the end of a run -- everything
    app/services/tracking_service.py needs to persist a Track row plus
    its TrackObservation rows, and nothing it needs to compute itself."""

    internal_track_id: int
    class_label: Optional[str]
    final_state: str
    observations: list[TrackObservationRecord] = field(default_factory=list)
    lifecycle_events: list[TrackLifecycleEvent] = field(default_factory=list)
    missed_frames_count: int = 0


@dataclass
class TrackerUpdateResult:
    """What `ObjectTracker.update()` reports happened on one frame --
    used by tests and by tracking_service's per-frame bookkeeping
    (detections_considered, frames_processed)."""

    new_track_count: int
    matched_count: int
    unmatched_detection_count: int


class ObjectTracker(Protocol):
    """Section 4's reusable tracker abstraction. `update()` is called
    once per sampled frame, in strictly increasing frame_index order;
    `finalize()` is called exactly once after the last frame to close
    out every track still active at sequence end ("Track
    termination at sequence end")."""

    tracker_key: str
    tracker_version: str
    is_deterministic: bool

    def update(self, frame_index: int, timestamp_seconds: float, detections: list[TrackerDetectionInput]) -> TrackerUpdateResult:
        """Accepts one frame's detections (possibly empty -- Section 5:
        "Empty frames" must be handled) and updates every active track's
        state. Raises `ValueError` for an out-of-order frame_index
        ("Invalid frame order") rather than silently
        reordering or ignoring it."""
        ...

    def finalize(self) -> list[FinalizedTrack]:
        """Ends every remaining active track and returns the complete,
        final history of every track this run ever created -- tentative,
        confirmed, missing, reacquired, ended, and rejected alike
        (Section 3B: never silently drop a candidate). Idempotent: a
        second call returns the same already-finalized list rather than
        re-ending anything."""
        ...
