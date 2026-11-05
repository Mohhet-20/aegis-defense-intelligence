"""Shared pytest fixtures for the AEGIS backend test suite.

Each test function gets its own isolated in-memory SQLite database via
a StaticPool-backed engine, bound into the running FastAPI app through
a `get_db` dependency override -- never the real `aegis.db` file. This
means the test suite can run safely in any order, repeatedly, without
ever touching real data.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-only-secret-not-for-production-use")
# The real auth rate limit (10/minute) is tuned for production abuse
# prevention, not for a test suite that logs in dozens of times across
# many test functions within the same minute. Raise it only for tests --
# the production default in config.py is untouched.
os.environ.setdefault("RATE_LIMIT_AUTH", "100000/minute")
os.environ.setdefault("RATE_LIMIT_REFRESH", "100000/minute")
# Every CV test writes real media bytes through the real
# app/cv/storage.py -- isolated to a throwaway directory for this test
# process rather than the dev backend/media_storage/ directory, same
# "never touch real data/files" discipline as the in-memory test DB
# above. Must be set before app.core.config.get_settings() is first
# called anywhere (it's lru_cache'd), hence this being this early.
os.environ.setdefault("CV_MEDIA_STORAGE_ROOT", tempfile.mkdtemp(prefix="aegis_test_media_"))

import bcrypt as _bcrypt  # noqa: E402

# bcrypt's default cost factor (12 rounds) is deliberately slow -- the
# right choice in production, but it makes a suite that hashes dozens
# of test passwords take minutes instead of seconds. Lower the work
# factor for the test process only; app/core/security.py itself is
# untouched, and this has no effect outside the test run.
_original_gensalt = _bcrypt.gensalt


def _fast_gensalt(rounds: int = 4, prefix: bytes = b"2b"):
    return _original_gensalt(rounds=4, prefix=prefix)


_bcrypt.gensalt = _fast_gensalt

from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.data_source import DataSource  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.user import User  # noqa: E402

TEST_PASSWORD = "TestPassword123!"


@pytest.fixture()
def test_password() -> str:
    return TEST_PASSWORD


@pytest.fixture()
def db_engine():
    # Default: in-memory SQLite. Set TEST_DATABASE_URL (a disposable PostgreSQL
    # database -- every table in it is DROPPED after each test) to run the same
    # suite against PostgreSQL; see docs/testing/INTEGRATION_TESTING.md.
    pg_url = os.environ.get("TEST_DATABASE_URL")
    if pg_url:
        assert pg_url.startswith("postgresql"), "TEST_DATABASE_URL must be a PostgreSQL URL"
        engine = create_engine(pg_url)
        Base.metadata.drop_all(bind=engine)
    else:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()
    if pg_url:
        cleanup = create_engine(pg_url)
        Base.metadata.drop_all(bind=cleanup)
        cleanup.dispose()
    else:
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def SessionLocalForTest(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)


@pytest.fixture()
def db(SessionLocalForTest):
    session = SessionLocalForTest()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(SessionLocalForTest):
    def _override_get_db():
        session = SessionLocalForTest()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def org(db) -> Organization:
    organization = Organization(name="Test Organization", status="active")
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture()
def seeded_users(db, org) -> dict[str, User]:
    """One user per role, all sharing TEST_PASSWORD, in `org`."""
    users = {}
    for username, role in [
        ("admin", "administrator"),
        ("analyst", "analyst"),
        ("investigator", "investigator"),
        ("viewer", "viewer"),
    ]:
        user = User(
            organization_id=org.id,
            username=username,
            email=f"{username}@test.example.com",
            display_name=username.title(),
            password_hash=hash_password(TEST_PASSWORD),
            role=role,
            is_active=True,
        )
        db.add(user)
        users[username] = user
    db.commit()
    for user in users.values():
        db.refresh(user)
    return users


@pytest.fixture()
def tokens(client, seeded_users) -> dict[str, str]:
    """Access tokens for each seeded role, obtained through the real
    /auth/login endpoint -- never minted directly -- so these tests
    exercise the actual authentication path."""
    result = {}
    for username in seeded_users:
        response = client.post(
            "/api/v1/auth/login",
            json={"username_or_email": username, "password": TEST_PASSWORD},
        )
        assert response.status_code == 200, response.text
        result[username] = response.json()["access_token"]
    return result


@pytest.fixture()
def auth_header():
    """Returns a callable so tests can do auth_header(tokens, "admin")
    without a cross-module import (keeps every test file self-contained
    regardless of how pytest's rootdir/import mode resolves `tests` as
    a package)."""

    def _make(tokens: dict[str, str], role: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens[role]}"}

    return _make


@pytest.fixture()
def png_bytes():
    """A tiny real PNG -- used across the CV tests as a valid
    image upload. Built with Pillow, not hand-crafted bytes, so it is
    a genuinely valid, decodable PNG, not just a signature prefix."""
    import io

    from PIL import Image

    def _make(width: int = 120, height: int = 90, color: tuple[int, int, int] = (40, 90, 160)) -> bytes:
        img = Image.new("RGB", (width, height), color=color)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    return _make


@pytest.fixture()
def mp4_bytes():
    """A tiny real MP4 built with cv2.VideoWriter -- a genuinely
    decodable video container, not just a signature prefix."""
    import os
    import tempfile

    import cv2
    import numpy as np

    def _make(width: int = 64, height: int = 48, fps: float = 10.0, num_frames: int = 40) -> bytes:
        path = tempfile.mktemp(suffix=".mp4")
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        for i in range(num_frames):
            frame = np.full((height, width, 3), (i * 5) % 255, dtype=np.uint8)
            writer.write(frame)
        writer.release()
        with open(path, "rb") as fh:
            content = fh.read()
        os.remove(path)
        return content

    return _make


@pytest.fixture()
def cv_mock_model(db, org):
    from app.services import model_registry_service

    return model_registry_service.register_cv_model(
        db, name="test-mock-detector", version="v1", adapter_key="mock_detector_v1", supported_media_types=["image", "video"],
    )


@pytest.fixture()
def cv_hog_model(db, org):
    from app.services import model_registry_service

    return model_registry_service.register_cv_model(
        db, name="test-hog-person-detector", version="v1", adapter_key="opencv_hog_person_v1", supported_media_types=["image", "video"],
    )


@pytest.fixture()
def active_device_factory(db, org, seeded_users):
    """Registers + activates a Device in one call, through
    the real device_service (never a bare ORM insert, so its
    administrative_status/api_key_hash are set exactly as registration
    actually sets them). Returns a callable `_make(device_identifier=None)
    -> (Device, plaintext_api_key)`; each call makes a fresh device."""
    from app.services import device_service

    counter = {"n": 0}

    def _make(device_identifier: Optional[str] = None):
        counter["n"] += 1
        identifier = device_identifier or f"test-device-{counter['n']}"
        device, api_key = device_service.register_device(
            db, organization_id=org.id, actor_user_id=seeded_users["admin"].id,
            device_identifier=identifier, device_name=f"Device {identifier}", device_type="field_sensor_node",
        )
        device = device_service.activate_device(db, device, actor_user_id=seeded_users["admin"].id)
        return device, api_key

    return _make


@pytest.fixture()
def device_headers():
    """Returns a callable so tests can do device_headers(identifier, api_key)."""

    def _make(device_identifier: str, api_key: str) -> dict[str, str]:
        return {"X-Device-Id": device_identifier, "X-Device-Api-Key": api_key}

    return _make


@pytest.fixture()
def source(db, org) -> DataSource:
    data_source = DataSource(
        organization_id=org.id,
        name="Test Source",
        source_type="synthetic_generator",
        description="A source created for tests.",
        status="active",
        reliability_weight=1.0,
        config_metadata={},
    )
    db.add(data_source)
    db.commit()
    db.refresh(data_source)
    return data_source


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture()
def tracking_source_factory(db, org, cv_mock_model):
    """Builds a real `MediaAsset` + a completed `video_frame_analysis`
    `InferenceJob` with hand-crafted, SMOOTHLY-MOVING `DetectionResult`
    rows inserted directly -- deliberately bypassing the real CV adapter
    pipeline (the `app/cv/adapters/mock_adapter.py` derives each
    detection's box from a sha256 hash of the ENTIRE frame's pixel
    bytes, so with the existing `mp4_bytes` fixture's uniform-color
    frames, box positions jump unpredictably frame-to-frame -- fine for
    exercising the own pipeline, useless for testing the
    tracking logic, which needs predictable motion to produce a
    meaningful, non-fragmented track). This reuses the same kind of
    linear-motion construction already proven correct in
    app/tracking/synthetic_fixture.py, but persisted as real rows so
    `tracking_service.submit_tracking_job()` can be exercised through
    real, already-persisted detection data -- never a standalone
    in-memory demo.

    Returns a callable `_make(pattern=..., num_frames=..., skip_frames=...)`
    -> (media_asset, inference_job). Each call creates a fresh
    MediaAsset/InferenceJob pair (never reuses one across calls), so
    tests can build more than one source in the same test.

    Patterns:
    - "single": one object moving left-to-right along y=0.2. Pass
      `skip_frames` (a set of frame indices) to simulate a gap in
      detection -- the detection for that frame is simply never
      inserted (never interpolate a missing position).
    - "parallel": two objects moving left-to-right along y=0.2/y=0.8 --
      never close enough to each other to be confused; a clean,
      reliable multi-object sanity check.
    - "crossing": two objects starting at x=0.3/x=0.7 along the SAME
      y=0.5, with STEP=0.02 -- meets exactly at frame_index=10 (requires
      num_frames >= 11 to actually observe the crossing), the same
      deliberately-constructed identity-switch scenario as
      app/tracking/synthetic_fixture.py's own "crossing" sequence.
    """
    from app.models.detection_result import DetectionResult
    from app.models.inference_job import InferenceJob
    from app.models.media_asset import MediaAsset

    _counter = {"n": 0}
    STEP = 0.02
    HALF = 0.03

    def _centers_for(pattern: str, frame_index: int) -> list[tuple[float, float]]:
        if pattern == "single":
            return [(0.1 + STEP * frame_index, 0.2)]
        if pattern == "parallel":
            return [(0.1 + STEP * frame_index, 0.2), (0.1 + STEP * frame_index, 0.8)]
        if pattern == "crossing":
            return [(0.3 + STEP * frame_index, 0.5), (0.7 - STEP * frame_index, 0.5)]
        raise ValueError(f"unknown pattern '{pattern}'")

    def _make(
        *,
        pattern: str = "parallel",
        num_frames: int = 20,
        fps: float = 10.0,
        width_px: int = 320,
        height_px: int = 240,
        skip_frames: Optional[set] = None,
        confidence: float = 0.9,
        class_label: str = "mock_object",
    ):
        skip_frames = skip_frames or set()
        _counter["n"] += 1
        content_hash = f"tracking-fixture-{_counter['n']}"

        media = MediaAsset(
            organization_id=org.id, media_type="video", status="stored",
            declared_filename="tracking_fixture.mp4", detected_mime_type="video/mp4",
            content_hash=content_hash, storage_key=f"{org.id}/{content_hash}.mp4", byte_size=1000,
            width_px=width_px, height_px=height_px, duration_seconds=num_frames / fps, frame_count=num_frames, fps=fps,
        )
        db.add(media)
        db.commit()
        db.refresh(media)

        inference_job = InferenceJob(
            organization_id=org.id, media_asset_id=media.id, model_record_id=cv_mock_model.id,
            job_type="video_frame_analysis", status="completed",
            parameters={"frame_sample_interval_seconds": round(1.0 / fps, 6), "max_frames": num_frames},
            frames_processed=num_frames, detections_created=0,
        )
        db.add(inference_job)
        db.commit()
        db.refresh(inference_job)

        detections_created = 0
        for i in range(num_frames):
            if i in skip_frames:
                continue
            t = i / fps
            for cx, cy in _centers_for(pattern, i):
                db.add(
                    DetectionResult(
                        organization_id=org.id, inference_job_id=inference_job.id, media_asset_id=media.id, model_record_id=cv_mock_model.id,
                        frame_index=i, frame_timestamp_seconds=round(t, 6),
                        class_label=class_label, confidence=confidence,
                        bbox_x_min=round(max(0.0, cx - HALF), 6), bbox_y_min=round(max(0.0, cy - HALF), 6),
                        bbox_x_max=round(min(1.0, cx + HALF), 6), bbox_y_max=round(min(1.0, cy + HALF), 6),
                        review_status="unreviewed",
                    )
                )
                detections_created += 1
        inference_job.detections_created = detections_created
        db.add(inference_job)
        db.commit()
        db.refresh(inference_job)
        db.refresh(media)
        return media, inference_job

    return _make


# ---- Helpers -------------------------------------------------------
@pytest.fixture()
def org_b(db, test_password):
    """A second organization with one administrator (`badmin`)."""
    o = Organization(name="Org B", status="active")
    db.add(o)
    db.flush()
    u = User(organization_id=o.id, username="badmin", email="badmin@b.example.com", display_name="B Admin",
             password_hash=hash_password(test_password), role="administrator", is_active=True)
    db.add(u)
    db.commit()
    return o


@pytest.fixture()
def b_headers(client, org_b, test_password):
    r = client.post("/api/v1/auth/login", json={"username_or_email": "badmin", "password": test_password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def clf_samples():
    """Factory for a labelled binary classification set. `wrong` of the samples
    are predicted incorrectly (the first `wrong` positives are predicted negative)."""

    def _make(n_pos: int = 40, n_neg: int = 40, wrong: int = 0, with_probs: bool = False):
        out = []
        for i in range(n_pos):
            pred = "neg" if i < wrong else "pos"
            s = {"sample_ref": f"p{i}", "true_label": "pos", "predicted_label": pred}
            if with_probs:
                s["positive_probability"] = 0.2 if pred == "neg" else 0.9
            out.append(s)
        for i in range(n_neg):
            s = {"sample_ref": f"n{i}", "true_label": "neg", "predicted_label": "neg"}
            if with_probs:
                s["positive_probability"] = 0.1
            out.append(s)
        return out

    return _make


@pytest.fixture()
def referenced_rows(db, org):
    """Real rows for the ids that older service-level tests pass as foreign keys
    (author_user_id="user-1", reviewed_by_user_id="u2", asset_id="asset-1", ...).
    SQLite does not enforce foreign keys, so those tests passed there while
    PostgreSQL rejected the fabricated references. Opt in with
    `pytestmark = pytest.mark.usefixtures("referenced_rows")`."""
    from app.models.asset import Asset

    for uid in ("user-1", "user-2", "u1", "u2"):
        db.add(User(id=uid, organization_id=org.id, username=f"fixture-{uid}", email=f"fixture-{uid}@test.example.com",
                    display_name=f"Fixture {uid}", password_hash="!unusable", role="analyst", is_active=True))
    db.add(Asset(id="asset-1", organization_id=org.id, name="Fixture asset", entity_type="facility"))
    db.commit()
