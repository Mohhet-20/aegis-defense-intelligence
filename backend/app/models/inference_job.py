"""InferenceJob. One explicit, authorized run of
one registered model (`ModelRecord`) over one `MediaAsset` -- an image
(single-frame) or a bounded sample of video frames. Same discipline as
Phase 2's `IngestionJob` and Phase 3's `FusionJob`: a real, inspectable
record of what a run actually did, status transitions that are never
faked, and failure that is captured rather than swallowed.

Execution model (documented honestly, not left implicit): like
IngestionJob/FusionJob before it, this runs synchronously inside the API
request that submits it (app/services/inference_service.py) -- there is
still no background worker process anywhere in this codebase. "Bounded
concurrency" here means a bounded amount of WORK per job (frame sampling
caps, detection-per-frame caps), not a worker pool; see
docs/ml/INFERENCE_PIPELINE.md's "What this does NOT do" section for the
explicit, undiscarded gap this leaves for a future phase.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

INFERENCE_JOB_TYPES = ("image_detection", "video_frame_analysis")
INFERENCE_JOB_STATUSES = ("pending", "running", "completed", "failed")

MAX_RETRIES = 3


class InferenceJob(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "inference_jobs"
    __table_args__ = (
        # NULL idempotency_key rows never collide (standard SQL NULL
        # semantics) -- only a client-supplied key is deduplicated; see
        # app/services/inference_service.py's "return the existing job"
        # path ("idempotency for retried submissions").
        UniqueConstraint("organization_id", "idempotency_key", name="uq_inference_jobs_org_idempotency_key"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    media_asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    model_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("model_records.id", ondelete="RESTRICT"), nullable=False, index=True)

    job_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)

    # Exact run configuration -- confidence_threshold, nms_iou_threshold,
    # and for video: frame_sample_interval_seconds, max_frames. Always
    # recorded even when every value came from a settings default, so a
    # DetectionResult's lineage can be traced to EXACTLY what produced it
    # (Section 4's required lineage), not "whatever the default happened
    # to be at the time."
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)

    frames_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detections_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retried_from_job_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("inference_jobs.id", ondelete="SET NULL"), nullable=True)

    triggered_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
