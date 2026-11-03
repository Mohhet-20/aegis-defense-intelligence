"""TrackAnnotation (Phase 5, Section 3E). An analyst's note or flag
about one Track -- attributed, timestamped, and NEVER destructively
edited: correcting an earlier annotation creates a new row pointing
back at the one it supersedes (`supersedes_annotation_id`), the same
non-destructive-history discipline Phase 3 established for
`AssessmentRevision` and relationship review history.

An annotation never edits the Track or any TrackObservation it
describes -- Section 12F's own rule ("Do not allow the frontend to
modify original model detections under the guise of editing a track")
is enforced here by construction: there is no code path from this
model back into `Track`/`TrackObservation` at all.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

ANNOTATION_TYPES = (
    "reviewed",
    "possible_error",
    "fragmented_track",
    "false_association",
    "uncertain_association",
    "note",
)


class TrackAnnotation(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "track_annotations"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    track_id: Mapped[str] = mapped_column(String(36), ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False, index=True)

    annotation_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    created_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Non-destructive correction chain -- an analyst "correcting" an
    # earlier annotation creates a NEW row with this set to the old
    # row's id; the old row is never updated or deleted (Section 3E:
    # "Preserve annotation history when a decision is corrected").
    supersedes_annotation_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("track_annotations.id", ondelete="SET NULL"), nullable=True)
    superseded_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
