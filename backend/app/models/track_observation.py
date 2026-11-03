"""TrackObservation (Phase 5, Section 3C). Links one `DetectionResult`
to one `Track` at a specific frame -- the association a tracking run
produced, never a rewrite of the detection it points at.

Every field that describes "what was detected" (bbox, class_label,
confidence) is a READ-ONLY mirror of the referenced DetectionResult at
the moment this observation was created, kept here purely so a track's
history can be queried and rendered without a join back to
`detection_results` on every request -- the exact same denormalize-for-
read-convenience judgment Phase 4 made putting `media_asset_id` and
`model_record_id` directly on `DetectionResult`. The original
`DetectionResult` row is the single source of truth; nothing in this
platform ever edits these mirrored columns after creation (Section 3C:
"Preserve the original detection. A tracking association must not
rewrite or fabricate the original detector output.").

There is deliberately no "interpolated" observation_state in this
phase -- Section 7 explicitly forbids silently interpolating a missing
position into authoritative evidence, so a frame with no matched
detection for a track simply has no TrackObservation row for that
track/frame at all. The one value `observation_state` can hold today is
`"matched"`; the column exists (rather than being omitted) so a future,
deliberate decision to add a distinguishable display-only interpolated
value has somewhere to go without a schema migration.
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

OBSERVATION_STATES = ("matched",)


class TrackObservation(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "track_observations"
    __table_args__ = (
        CheckConstraint("bbox_x_min >= 0.0 AND bbox_x_min < bbox_x_max AND bbox_x_max <= 1.0", name="ck_track_observations_bbox_x_bounds"),
        CheckConstraint("bbox_y_min >= 0.0 AND bbox_y_min < bbox_y_max AND bbox_y_max <= 1.0", name="ck_track_observations_bbox_y_bounds"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    track_id: Mapped[str] = mapped_column(String(36), ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False, index=True)
    detection_result_id: Mapped[str] = mapped_column(String(36), ForeignKey("detection_results.id", ondelete="RESTRICT"), nullable=False, index=True)
    # Denormalized for the same join-avoidance reason as DetectionResult's
    # own media_asset_id.
    media_asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False, index=True)

    frame_index: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    frame_timestamp_seconds: Mapped[float] = mapped_column(Float, nullable=False)

    bbox_x_min: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_y_min: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_x_max: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_y_max: Mapped[float] = mapped_column(Float, nullable=False)
    class_label: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # How this observation was associated to its track, e.g.
    # "iou_hungarian_v1" (the tracker_key) or "new_track" for the first
    # observation of a track -- never "unknown."
    association_method: Mapped[str] = mapped_column(String(50), nullable=False)
    # 1 - IoU for a matched pair (lower is a better match), or NULL for a
    # track's first observation (there is no prior box to compare
    # against). Never fabricated when there was no real comparison.
    association_cost: Mapped[float] = mapped_column(Float, nullable=True)

    observation_state: Mapped[str] = mapped_column(String(20), nullable=False, default="matched")
