"""MediaAsset. A securely-ingested image or video
file: validated by real file-signature sniffing (never by trusting a
client-supplied MIME type or filename extension -- see
app/cv/media_validation.py), stored under a content-addressed name on a
private, non-web-served filesystem root (app/cv/storage.py), and
referenced everywhere else by this row's id, never by a raw path.

This is NOT the same idea as Phase 3's `Evidence.external_reference_uri`
-- Evidence points at content that lives somewhere else and is never
fetched. A MediaAsset is content this platform itself received, validated,
and is now responsible for storing safely. A MediaAsset is promoted into
the Evidence layer (evidence_type="media_reference") only after a
detection on it has been analyst-confirmed -- see
app/services/detection_review_service.py -- never automatically.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

MEDIA_TYPES = ("image", "video")
MEDIA_ASSET_STATUSES = ("stored", "rejected")

# The only signatures this platform will ever accept -- deliberately
# small and explicit ("do not trust client-supplied MIME
# type or file extension"). See app/cv/media_validation.py for the
# actual byte-signature sniffing that enforces this against the real
# file content, not the filename.
ALLOWED_IMAGE_MIME_TYPES = ("image/png", "image/jpeg")
ALLOWED_VIDEO_MIME_TYPES = ("video/mp4",)


class MediaAsset(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint("organization_id", "content_hash", name="uq_media_assets_org_content_hash"),
        CheckConstraint("byte_size > 0", name="ck_media_assets_byte_size_positive"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    media_type: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="stored", index=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # The ONLY filename kept from the client -- sanitized for display
    # purposes only (app/cv/media_validation.sanitize_display_filename),
    # NEVER used to build a filesystem path. The actual on-disk name is
    # `storage_key` below, derived entirely from content_hash.
    declared_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Detected from the real file bytes (app/cv/media_validation.py),
    # never copied from the client's Content-Type header.
    detected_mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # sha256 hex digest of the raw file bytes -- the basis of both the
    # content-addressed storage_key and the duplicate-upload dedup
    # (see app/services/media_service.py's idempotent create).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Path relative to settings.CV_MEDIA_STORAGE_ROOT -- always
    # `{organization_id}/{content_hash}.{ext}`, verified by
    # app/cv/storage.py to resolve inside the configured root before
    # every read or write (no path traversal, ever).
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)

    # Image: decoded pixel dimensions. Video: dimensions of the first
    # sampled frame (a real video can technically change resolution
    # mid-stream; this platform does not attempt to track that).
    width_px: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height_px: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Video only.
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    frame_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    uploaded_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
