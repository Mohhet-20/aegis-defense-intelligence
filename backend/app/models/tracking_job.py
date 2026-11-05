"""TrackingJob (Section 3A/9). One explicit, authorized run of
one tracker algorithm over the already-persisted `DetectionResult` rows
of exactly one completed `video_frame_analysis` InferenceJob.

Same discipline as the `IngestionJob`, the `FusionJob`, and
the `InferenceJob`: a real, inspectable record of what a run
actually did, status transitions that are never faked, and failure that
is captured rather than swallowed.

Execution model, stated honestly, unchanged from every prior job table in
this codebase: this runs SYNCHRONOUSLY inside the API request that submits
it (app/services/tracking_service.py). There is still no background
worker/queue anywhere in this codebase. Status vocabulary is deliberately
the same four values InferenceJob/FusionJob/IngestionJob already use
("pending"/"running"/"completed"/"failed") rather than the
"QUEUED/RUNNING/SUCCEEDED" example vocabulary the specification's own text
suggested -- Section 1's own instruction to "reuse existing ... conventions"
wins over introducing a second lifecycle vocabulary for an equivalent
semantic, and the specification's own wording allows this ("adapt these
names to the actual implementation").

Tracking is deliberately restricted to a source InferenceJob of
job_type="video_frame_analysis" -- a single image detection job has
exactly one frame, so there is nothing to associate across frames, and
building a "tracking job" over one frame would be a nonsensical, untested
code path. See docs/architecture/OBJECT_TRACKING_ARCHITECTURE.md.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

TRACKING_JOB_STATUSES = ("pending", "running", "completed", "failed")
TRACKING_RESULT_SCHEMA_VERSION = "1.0"
TRACKING_MAX_RETRIES = 3


class TrackingJob(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "tracking_jobs"
    __table_args__ = (
        # Same NULL-never-collides idempotency pattern as InferenceJob.
        UniqueConstraint("organization_id", "idempotency_key", name="uq_tracking_jobs_org_idempotency_key"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    media_asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    # The source of the detections this run associates into tracks --
    # Section 9's "input detection-result references are recorded"
    # requirement is satisfied at this granularity (one source job) plus
    # each TrackObservation's own detection_result_id (finer-grained).
    inference_job_id: Mapped[str] = mapped_column(String(36), ForeignKey("inference_jobs.id", ondelete="CASCADE"), nullable=False, index=True)

    # A key into app/tracking/trackers/registry.py's closed allow-list --
    # same "never a dynamic import of an arbitrary string" discipline as
    # the ModelRecord.adapter_key ("keep algorithm-
    # specific code behind the tracker interface").
    tracker_key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tracker_version: Mapped[str] = mapped_column(String(20), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    result_schema_version: Mapped[str] = mapped_column(String(10), nullable=False, default=TRACKING_RESULT_SCHEMA_VERSION)

    # Exact run configuration -- min_iou_threshold, max_missed_frames,
    # min_hits_to_confirm, require_class_match. Always recorded, even
    # when every value came from a settings default (Section 9's lineage
    # requirement, same pattern InferenceJob.parameters already uses).
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    frames_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frames_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detections_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tracks_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retried_from_job_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("tracking_jobs.id", ondelete="SET NULL"), nullable=True)

    triggered_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # processing_duration_seconds is NOT a stored column -- it is always
    # derived from (finished_at - started_at) at read time (schemas/tracking.py),
    # so it can never drift from the two timestamps that actually define it.
    error_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
