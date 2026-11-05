"""/17: secure media ingestion. Every test here
exercises app/services/media_service.py (and the app/cv/media_validation.py
+ app/cv/storage.py it calls) directly against a real file-signature
check, a real size/dimension check, and real content-addressed storage
-- never a mocked validator.
"""
from __future__ import annotations

import os

import pytest

from app.cv import media_validation, storage
from app.cv.media_validation import MediaValidationError
from app.services import media_service


def test_valid_png_upload_is_stored_and_hashed(db, org, png_bytes):
    content = png_bytes(100, 80)
    media_asset = media_service.ingest_media(db, organization_id=org.id, declared_filename="photo.png", content=content, uploaded_by_user_id=None)

    assert media_asset.media_type == "image"
    assert media_asset.status == "stored"
    assert media_asset.detected_mime_type == "image/png"
    assert media_asset.width_px == 100 and media_asset.height_px == 80
    assert media_asset.content_hash == __import__("hashlib").sha256(content).hexdigest()
    # The real, physical file exists at exactly the content-addressed path.
    assert storage.read_bytes(media_asset.storage_key) == content


def test_duplicate_upload_is_idempotent_not_duplicated(db, org, png_bytes):
    content = png_bytes(64, 64)
    first = media_service.ingest_media(db, organization_id=org.id, declared_filename="a.png", content=content, uploaded_by_user_id=None)
    second = media_service.ingest_media(db, organization_id=org.id, declared_filename="a_renamed.png", content=content, uploaded_by_user_id=None)

    assert first.id == second.id  # same org + same bytes -> the same row, not a second one
    rows = db.query(type(first)).filter_by(organization_id=org.id, content_hash=first.content_hash).all()
    assert len(rows) == 1


def test_unrecognized_file_signature_is_rejected_and_never_stored(db, org):
    content = b"#!/bin/sh\necho not an image or video\n"
    with pytest.raises(MediaValidationError):
        media_service.ingest_media(db, organization_id=org.id, declared_filename="script.png", content=content, uploaded_by_user_id=None)

    from app.models.media_asset import MediaAsset

    assert db.query(MediaAsset).filter_by(organization_id=org.id).count() == 0


def test_filename_path_traversal_is_sanitized_to_a_bare_name():
    sanitized = media_validation.sanitize_display_filename("../../etc/passwd.png")
    assert "/" not in sanitized and ".." not in sanitized
    assert sanitized == "passwd.png"


def test_filename_with_no_extension_or_empty_falls_back_safely():
    assert media_validation.sanitize_display_filename(None) == "upload"
    assert media_validation.sanitize_display_filename("") == "upload"
    assert media_validation.sanitize_display_filename("   ") == "upload"


def test_oversized_file_is_rejected(db, org, png_bytes, monkeypatch):
    content = png_bytes(50, 50)
    monkeypatch.setattr(media_service.settings, "CV_MAX_IMAGE_UPLOAD_BYTES", 10)  # smaller than any real PNG
    with pytest.raises(MediaValidationError, match="exceeds"):
        media_service.ingest_media(db, organization_id=org.id, declared_filename="big.png", content=content, uploaded_by_user_id=None)


def test_oversized_image_dimensions_are_rejected(db, org, png_bytes, monkeypatch):
    content = png_bytes(500, 500)
    monkeypatch.setattr(media_validation.settings, "CV_MAX_IMAGE_DIMENSION_PX", 100)
    with pytest.raises(MediaValidationError, match="exceed"):
        media_service.ingest_media(db, organization_id=org.id, declared_filename="huge.png", content=content, uploaded_by_user_id=None)


def test_valid_mp4_upload_records_real_measured_properties(db, org, mp4_bytes):
    content = mp4_bytes(width=64, height=48, fps=10.0, num_frames=30)
    media_asset = media_service.ingest_media(db, organization_id=org.id, declared_filename="clip.mp4", content=content, uploaded_by_user_id=None)

    assert media_asset.media_type == "video"
    assert media_asset.width_px == 64 and media_asset.height_px == 48
    assert media_asset.frame_count == 30
    assert media_asset.fps == pytest.approx(10.0, abs=0.5)
    assert media_asset.duration_seconds == pytest.approx(3.0, abs=0.5)


def test_video_exceeding_duration_limit_is_rejected_and_file_cleaned_up(db, org, mp4_bytes, monkeypatch):
    content = mp4_bytes(width=64, height=48, fps=10.0, num_frames=50)  # 5 real seconds
    monkeypatch.setattr(media_service.settings, "CV_MAX_VIDEO_DURATION_SECONDS", 1.0)

    with pytest.raises(MediaValidationError, match="duration"):
        media_service.ingest_media(db, organization_id=org.id, declared_filename="long.mp4", content=content, uploaded_by_user_id=None)

    # Nothing was left behind on disk for the rejected file.
    import hashlib

    content_hash = hashlib.sha256(content).hexdigest()
    key = storage.build_storage_key(org.id, content_hash, "mp4")
    assert not os.path.exists(storage.path_for(key))


def test_corrupt_video_container_is_rejected(db, org):
    # A valid-looking ftyp signature, but garbage after it -- not
    # actually decodable as a real MP4 container.
    content = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200
    from app.cv.video_sampling import VideoOpenError

    with pytest.raises((MediaValidationError, VideoOpenError)):
        media_service.ingest_media(db, organization_id=org.id, declared_filename="fake.mp4", content=content, uploaded_by_user_id=None)


def test_storage_resolve_refuses_to_escape_the_configured_root():
    with pytest.raises(storage.PathTraversalError):
        storage._resolve("../../../etc/passwd")
