"""Secure media ingestion. The ONLY entry point
that turns uploaded bytes into a `MediaAsset` row -- signature sniffing,
size/dimension/duration limits, content hashing, and content-addressed
storage all happen here, in this order, before anything is ever
persisted. A file that fails any check is never written to disk and
never gets a database row (see docs/security/MEDIA_UPLOAD_SECURITY.md).
"""
from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.cv import media_validation, storage, video_sampling
from app.cv.media_validation import MediaValidationError
from app.cv.video_sampling import VideoOpenError
from app.models.media_asset import MediaAsset

settings = get_settings()


def ingest_media(
    db: Session,
    *,
    organization_id: str,
    declared_filename: Optional[str],
    content: bytes,
    uploaded_by_user_id: Optional[str],
) -> MediaAsset:
    """Raises MediaValidationError for anything rejected -- the caller
    (app/api/routes/media.py) turns that into a 400 with the exact
    reason. Nothing is written to disk or to the database on a
    rejection path; only a successfully-validated file ever becomes a
    MediaAsset row."""
    sniffed = media_validation.sniff_signature(content)
    media_validation.validate_size(sniffed.media_type, len(content))

    content_hash = hashlib.sha256(content).hexdigest()

    # Idempotent re-upload: the exact same bytes from the same org
    # return the existing row rather than being re-validated and
    # re-stored -- same discipline as the relationship_service
    # (row, created) pattern, simplified here to "just return the row"
    # since a MediaAsset has no additional fields a second upload could
    # legitimately change.
    existing_stmt = select(MediaAsset).where(MediaAsset.organization_id == organization_id, MediaAsset.content_hash == content_hash)
    existing = db.execute(existing_stmt).scalar_one_or_none()
    if existing is not None:
        return existing

    storage_key = storage.build_storage_key(organization_id, content_hash, sniffed.extension)
    display_name = media_validation.sanitize_display_filename(declared_filename)

    if sniffed.media_type == "image":
        width, height = media_validation.validate_image_dimensions(content)
        storage.write_bytes(storage_key, content)
        media_asset = MediaAsset(
            organization_id=organization_id,
            media_type="image",
            status="stored",
            declared_filename=display_name,
            detected_mime_type=sniffed.mime_type,
            content_hash=content_hash,
            storage_key=storage_key,
            byte_size=len(content),
            width_px=width,
            height_px=height,
            uploaded_by_user_id=uploaded_by_user_id,
        )
    else:
        # A video container's real properties can only be measured by
        # actually opening it -- write first, probe second, and clean
        # up on failure so an invalid video never lingers on disk.
        storage.write_bytes(storage_key, content)
        try:
            info = video_sampling.probe_video(storage.path_for(storage_key))
        except VideoOpenError as exc:
            storage.delete(storage_key)
            raise MediaValidationError(str(exc)) from exc

        if info["duration_seconds"] > settings.CV_MAX_VIDEO_DURATION_SECONDS:
            storage.delete(storage_key)
            raise MediaValidationError(
                f"video duration {info['duration_seconds']:.1f}s exceeds the {settings.CV_MAX_VIDEO_DURATION_SECONDS}s limit"
            )
        if info["width"] > settings.CV_MAX_VIDEO_DIMENSION_PX or info["height"] > settings.CV_MAX_VIDEO_DIMENSION_PX:
            storage.delete(storage_key)
            raise MediaValidationError(
                f"video dimensions {info['width']}x{info['height']} exceed the {settings.CV_MAX_VIDEO_DIMENSION_PX}px-per-side limit"
            )

        media_asset = MediaAsset(
            organization_id=organization_id,
            media_type="video",
            status="stored",
            declared_filename=display_name,
            detected_mime_type=sniffed.mime_type,
            content_hash=content_hash,
            storage_key=storage_key,
            byte_size=len(content),
            width_px=info["width"],
            height_px=info["height"],
            duration_seconds=info["duration_seconds"],
            frame_count=info["frame_count"],
            fps=info["fps"],
            uploaded_by_user_id=uploaded_by_user_id,
        )

    db.add(media_asset)
    db.commit()
    db.refresh(media_asset)
    return media_asset


def get_media_asset(db: Session, organization_id: str, media_asset_id: str) -> Optional[MediaAsset]:
    stmt = select(MediaAsset).where(MediaAsset.id == media_asset_id, MediaAsset.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_media_query(organization_id: str, *, media_type: Optional[str] = None):
    stmt = select(MediaAsset).where(MediaAsset.organization_id == organization_id)
    if media_type:
        stmt = stmt.where(MediaAsset.media_type == media_type)
    return stmt.order_by(MediaAsset.created_at.desc())


def read_media_content(media_asset: MediaAsset) -> bytes:
    return storage.read_bytes(media_asset.storage_key)
