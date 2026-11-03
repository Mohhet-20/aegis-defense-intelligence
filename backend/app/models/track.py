"""Track (Phase 5, Section 3B/6). A temporary, sequence-scoped
association of detections produced by exactly one TrackingJob run.

"Sequence-scoped" is the operative word, enforced here, not just in
prose: `sequence_track_id` is unique only within its own
`tracking_job_id` (see the UniqueConstraint below), and nothing in this
platform ever treats two tracks from two different jobs/videos -- or
even two tracks from a RERUN of the same video -- as the same
real-world object. A track ID is evidence that a tracking algorithm
associated some detections within one run; it is never evidence of a
real-world identity. See Section 2's own framing and
docs/architecture/OBJECT_TRACKING_ARCHITECTURE.md.

`lifecycle_events` is a JSON list of {frame_index, timestamp_seconds,
from_state, to_state, reason} entries recording every state transition
this track went through during its run (Section 3D's "track segment and
gap" requirement) -- kept as a JSON column on this row rather than a
6th table, the same "don't over-normalize a first vertical slice"
judgment Phase 4 made for DetectionResult.raw_model_output. Every gap
(a run of missed frames between two confirmed observations) and every
reacquisition is reconstructable from this list plus the track's own
TrackObservation rows -- nothing about a gap is silently discarded.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

# Section 6's lifecycle states, named explicitly rather than borrowing the
# specification's own example vocabulary verbatim -- equivalent semantics,
# as the specification itself invites ("adapt these names ... maintain
# equivalent clear semantics"). Deliberately NOT "destroyed", "captured",
# "hostile", or anything implying a real-world outcome this data never
# establishes (Section 6's own explicit prohibition).
TRACK_STATES = (
    "tentative",     # just created, has not yet met the confirmation threshold
    "confirmed",     # has matched >= min_hits_to_confirm observations
    "missing",       # confirmed, but has not matched a detection recently (within max_missed_frames)
    "reacquired",    # was "missing", then matched again before exceeding max_missed_frames
    "ended",          # exceeded max_missed_frames, or the sequence ended -- no more observations will ever be added
    "rejected",       # a tentative track that never confirmed before being abandoned; kept for transparency, never silently dropped
)


class Track(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "tracks"
    __table_args__ = (
        UniqueConstraint("tracking_job_id", "sequence_track_id", name="uq_tracks_job_sequence_track_id"),
        CheckConstraint("last_frame_index >= first_frame_index", name="ck_tracks_frame_order"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    tracking_job_id: Mapped[str] = mapped_column(String(36), ForeignKey("tracking_jobs.id", ondelete="CASCADE"), nullable=False, index=True)

    # A small, job-local integer identity ("track-1", "track-2", ...) --
    # never reused within the same job (Section 3B: "do not reuse a
    # track ID within the same tracking job"), and never implied to
    # carry meaning across a rerun: a retry creates an entirely new
    # TrackingJob with its own fresh sequence_track_id numbering.
    sequence_track_id: Mapped[str] = mapped_column(String(50), nullable=False)

    # The detector's own class_label for this track -- taken from its
    # first matched observation and never changed afterward, even if a
    # later observation in the same track reports a different label
    # (tracked in quality_summary.class_label_changes instead of
    # silently overwriting this field, see track lifecycle tests).
    class_label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)

    first_frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    last_frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    first_timestamp_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    last_timestamp_seconds: Mapped[float] = mapped_column(Float, nullable=False)

    matched_observations_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missed_frames_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    state: Mapped[str] = mapped_column(String(20), nullable=False, default="tentative", index=True)

    # {"mean_confidence": ..., "mean_association_cost": ..., "class_label_changes": N,
    #  "fragmentation_count": N, "bbox_area_first": ..., "bbox_area_last": ...} --
    # descriptive only, never a fabricated "quality score."
    quality_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    lifecycle_events: Mapped[list] = mapped_column(JSON, default=list)
