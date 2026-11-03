"""IoUHungarianTracker. The one baseline tracker
this phase ships: per-frame IoU computed between every active track's
last known box and every current detection, assigned via the Hungarian
algorithm (app/tracking/association.py), with explicit, configurable
lifecycle rules layered on top of the raw assignment.

This is also the project's "deterministic tracker fixture for tests"
(Section 4, requirement 1) and its "baseline multi-object tracking
algorithm" (requirement 2) in one -- not two separate implementations.
Given identical inputs and configuration, this tracker's output is
always byte-identical: the Hungarian solver is a pure function of the
cost matrix, and nothing in this class uses randomness, wall-clock time,
or any other non-deterministic input. Building a second, throwaway
"fixture tracker" purely for tests would have duplicated this guarantee
for no additional coverage -- Section 4 itself only asks for one
deterministic fixture, not a second one with its own untested behavior.

Known, documented limitations (stated honestly, not hidden, per
Section 4's "Do not claim advanced tracking performance simply because
track IDs appear on screen"):
- Pure appearance-free IoU association. Two objects that cross paths
  and briefly overlap can be assigned to each other's prior track (an
  "identity switch") -- there is no appearance/embedding model here to
  disambiguate that case. Section 2 forbids biometric/appearance
  embeddings anyway, so this is an accepted, permanent limitation of
  this approach, not a gap to be closed later with a stronger model.
- No motion prediction (Section 8 was deliberately deferred -- see
  docs/ml/TRACK_LIFECYCLE.md) -- a track's "last known box" is its most
  recent OBSERVED box, never a predicted position, so a fast-moving
  object that leaves its own IoU neighborhood between sampled frames
  (Phase 4's video sampling is itself sparse, by design) may fail to
  re-associate and will instead end one track and start a new one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.tracking.association import AssociationCandidate, AssociationDetection, associate
from app.tracking.trackers.base import (
    FinalizedTrack,
    TrackLifecycleEvent,
    TrackObservationRecord,
    TrackerDetectionInput,
    TrackerUpdateResult,
)

TRACKER_KEY = "iou_hungarian_v1"
TRACKER_VERSION = "1.0"


@dataclass
class TrackerConfig:
    min_iou_threshold: float = 0.3
    max_missed_frames: int = 5
    min_hits_to_confirm: int = 2
    require_class_match: bool = True
    max_active_tracks: int = 100


@dataclass
class _TrackState:
    internal_id: int
    class_label: Optional[str] = None
    state: str = "tentative"
    last_bbox: Optional[tuple[float, float, float, float]] = None
    last_frame_index: Optional[int] = None
    total_hits: int = 0
    missed_frames_count: int = 0
    observations: list[TrackObservationRecord] = field(default_factory=list)
    lifecycle_events: list[TrackLifecycleEvent] = field(default_factory=list)
    is_active: bool = True

    def transition(self, frame_index: int, timestamp_seconds: float, to_state: str, reason: str) -> None:
        if to_state == self.state:
            return
        self.lifecycle_events.append(
            TrackLifecycleEvent(frame_index=frame_index, timestamp_seconds=timestamp_seconds, from_state=self.state, to_state=to_state, reason=reason)
        )
        self.state = to_state


class IoUHungarianTracker:
    tracker_key = TRACKER_KEY
    tracker_version = TRACKER_VERSION
    is_deterministic = True

    def __init__(self, config: Optional[TrackerConfig] = None):
        self.config = config or TrackerConfig()
        self._tracks: dict[int, _TrackState] = {}
        self._next_internal_id = 1
        self._last_frame_index: Optional[int] = None
        self._finalized = False

    def _active_ids(self) -> list[int]:
        return [tid for tid, t in self._tracks.items() if t.is_active]

    def update(self, frame_index: int, timestamp_seconds: float, detections: list[TrackerDetectionInput]) -> TrackerUpdateResult:
        if self._finalized:
            raise ValueError("tracker has already been finalized; create a new instance for a new sequence")
        if self._last_frame_index is not None and frame_index <= self._last_frame_index:
            raise ValueError(
                f"frame_index must strictly increase (got {frame_index} after {self._last_frame_index}) -- "
                "duplicate and out-of-order frames are both rejected, never silently reordered"
            )
        self._last_frame_index = frame_index

        active_ids = self._active_ids()
        candidates = [
            AssociationCandidate(track_index=tid, class_label=self._tracks[tid].class_label or "", last_bbox=self._tracks[tid].last_bbox)
            for tid in active_ids
            if self._tracks[tid].last_bbox is not None
        ]
        det_candidates = [AssociationDetection(detection_index=i, class_label=d.class_label, bbox=d.bbox) for i, d in enumerate(detections)]

        result = associate(candidates, det_candidates, min_iou_threshold=self.config.min_iou_threshold, require_class_match=self.config.require_class_match)

        matched_detection_indices: set[int] = set()
        for match in result.matches:
            track = self._tracks[match.track_index]
            det = detections[match.detection_index]
            matched_detection_indices.add(match.detection_index)

            track.last_bbox = det.bbox
            track.last_frame_index = frame_index
            track.missed_frames_count = 0
            track.total_hits += 1
            track.observations.append(
                TrackObservationRecord(
                    frame_index=frame_index, timestamp_seconds=timestamp_seconds, detection_result_id=det.detection_result_id,
                    class_label=det.class_label, confidence=det.confidence, bbox=det.bbox,
                    association_method=self.tracker_key, association_cost=match.cost,
                )
            )

            if track.state == "tentative" and track.total_hits >= self.config.min_hits_to_confirm:
                track.transition(frame_index, timestamp_seconds, "confirmed", f"reached min_hits_to_confirm={self.config.min_hits_to_confirm}")
            elif track.state == "missing":
                track.transition(frame_index, timestamp_seconds, "reacquired", "matched a detection again before exceeding max_missed_frames")
            elif track.state == "reacquired":
                track.transition(frame_index, timestamp_seconds, "confirmed", "matched again after reacquisition")

        for tid in result.unmatched_track_indices:
            track = self._tracks[tid]
            track.missed_frames_count += 1

            if track.state == "confirmed":
                track.transition(frame_index, timestamp_seconds, "missing", "no matching detection this frame")

            exceeded = track.missed_frames_count > self.config.max_missed_frames
            if exceeded and track.state in ("confirmed", "missing", "reacquired"):
                track.transition(frame_index, timestamp_seconds, "ended", f"exceeded max_missed_frames={self.config.max_missed_frames}")
                track.is_active = False
            elif exceeded and track.state == "tentative":
                track.transition(frame_index, timestamp_seconds, "rejected", "never reached min_hits_to_confirm before missed-frame limit")
                track.is_active = False

        new_track_count = 0
        unmatched_detection_count = 0
        for i, det in enumerate(detections):
            if i in matched_detection_indices:
                continue
            if len(self._active_ids()) >= self.config.max_active_tracks:
                unmatched_detection_count += 1  # dropped -- the per-job active-track cap was reached, never silently exceeded
                continue

            internal_id = self._next_internal_id
            self._next_internal_id += 1
            track = _TrackState(internal_id=internal_id, class_label=det.class_label, last_bbox=det.bbox, last_frame_index=frame_index, total_hits=1)
            track.lifecycle_events.append(
                TrackLifecycleEvent(frame_index=frame_index, timestamp_seconds=timestamp_seconds, from_state=None, to_state="tentative", reason="created from an unmatched detection")
            )
            track.observations.append(
                TrackObservationRecord(
                    frame_index=frame_index, timestamp_seconds=timestamp_seconds, detection_result_id=det.detection_result_id,
                    class_label=det.class_label, confidence=det.confidence, bbox=det.bbox,
                    association_method="new_track", association_cost=None,
                )
            )
            if track.total_hits >= self.config.min_hits_to_confirm:
                track.transition(frame_index, timestamp_seconds, "confirmed", f"reached min_hits_to_confirm={self.config.min_hits_to_confirm} on first observation")
            self._tracks[internal_id] = track
            new_track_count += 1

        return TrackerUpdateResult(new_track_count=new_track_count, matched_count=len(result.matches), unmatched_detection_count=unmatched_detection_count)

    def finalize(self) -> list[FinalizedTrack]:
        if not self._finalized:
            last_frame = self._last_frame_index or 0
            for tid in self._active_ids():
                track = self._tracks[tid]
                if track.state == "tentative":
                    track.transition(last_frame, track.observations[-1].timestamp_seconds if track.observations else 0.0, "rejected", "sequence ended before confirmation")
                else:
                    track.transition(last_frame, track.observations[-1].timestamp_seconds if track.observations else 0.0, "ended", "sequence ended")
                track.is_active = False
            self._finalized = True

        return [
            FinalizedTrack(
                internal_track_id=t.internal_id, class_label=t.class_label, final_state=t.state,
                observations=list(t.observations), lifecycle_events=list(t.lifecycle_events), missed_frames_count=t.missed_frames_count,
            )
            for t in sorted(self._tracks.values(), key=lambda t: t.internal_id)
        ]
