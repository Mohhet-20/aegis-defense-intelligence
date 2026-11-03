"""DetectionResult. One validated, normalized
detected-object instance, produced by exactly one InferenceJob running
exactly one ModelRecord/adapter -- the lineage link between a model's raw
output and anything an analyst or this platform's Evidence layer does
with it next.

Every row here has ALREADY passed app/cv/postprocessing.py's validation
(finite numbers, 0<=x_min<x_max<=1, 0<=y_min<y_max<=1, 0<=confidence<=1,
class_label in the allow-list, NMS-deduplicated) before it is ever
inserted -- this table is not where that validation happens, it is what
exists only because that validation already passed. See
docs/data/DETECTION_RESULT_SCHEMA.md.

Bounding boxes are stored as fractions of the image's width/height (0..1
on both axes), NOT pixel coordinates. This is deliberate: it is what
makes the frontend's bounding-box overlay correct under responsive
image resizing without this table ever needing to know
what size the browser is currently rendering the image at -- the
frontend just multiplies by whatever the displayed <img> element's
current width/height happens to be.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

DETECTION_SCHEMA_VERSION = "1.0"

DETECTION_REVIEW_STATUSES = ("unreviewed", "confirmed", "rejected")

# Section 13/15's safety constraints, enforced as code, not just prose:
# a DetectionResult's class_label can ONLY ever be one of these. This is
# the single choke point that keeps this platform from ever persisting
# (and therefore ever displaying, exporting, or linking into Evidence) a
# label implying identity, hostile intent, or anything this project's
# defensive, human-in-the-loop scope forbids. Adding a new real adapter
# later means extending this list deliberately, never accepting
# whatever string a model happens to emit.
ALLOWED_CLASS_LABELS = (
    "mock_object",       # MockDetectionAdapter -- deterministic, not a real detection
    "person",            # OpenCVHOGPersonAdapter -- generic person-shaped bounding box;
                          # explicitly NOT an identity, NOT a face, NOT biometric data
    "vehicle",
    "unknown_object",
)


class DetectionResult(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "detection_results"
    __table_args__ = (
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_detection_results_confidence_range"),
        CheckConstraint("bbox_x_min >= 0.0 AND bbox_x_min < bbox_x_max AND bbox_x_max <= 1.0", name="ck_detection_results_bbox_x_bounds"),
        CheckConstraint("bbox_y_min >= 0.0 AND bbox_y_min < bbox_y_max AND bbox_y_max <= 1.0", name="ck_detection_results_bbox_y_bounds"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    inference_job_id: Mapped[str] = mapped_column(String(36), ForeignKey("inference_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    # Denormalized on purpose -- Section 4 requires every DetectionResult
    # to carry its full lineage without a join fan-out through the job
    # row every time one is displayed or exported.
    media_asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    model_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("model_records.id", ondelete="RESTRICT"), nullable=False, index=True)

    schema_version: Mapped[str] = mapped_column(String(10), nullable=False, default=DETECTION_SCHEMA_VERSION)

    # NULL for an image job (there is only one frame: the image itself).
    # Both set together for a video_frame_analysis job -- the exact
    # sampled frame this detection came from, preserved even though the
    # full decoded video is never kept in memory.
    frame_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    frame_timestamp_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    class_label: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    bbox_x_min: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_y_min: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_x_max: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_y_max: Mapped[float] = mapped_column(Float, nullable=False)

    # Adapter-specific extra detail (e.g. the raw pre-NMS box count) --
    # never a field this platform's own logic depends on; purely
    # informational, see docs/ml/MODEL_ADAPTERS.md.
    raw_model_output: Mapped[dict] = mapped_column(JSON, default=dict)

    # Analyst review -- Section 9's "never auto-promote an unreviewed
    # detection into a consequential assessment" lives here: nothing in
    # app/services/detection_review_service.py will create an Evidence
    # row for a DetectionResult whose review_status != "confirmed".
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unreviewed", index=True)
    reviewed_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
