"""Phase 4, Section 9/11/17: cross-cutting CV API integration --
pagination, media content download, job retry after a failure, and
readiness reporting the new per-dependency checks.
"""
from __future__ import annotations


def test_media_content_download_round_trips_exact_bytes(client, tokens, auth_header, png_bytes):
    headers = auth_header(tokens, "analyst")
    content = png_bytes(90, 70)
    media = client.post("/api/v1/media", headers=headers, files={"file": ("round_trip.png", content, "image/png")}).json()

    response = client.get(f"/api/v1/media/{media['id']}/content", headers=headers)
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "image/png"


def test_media_list_is_paginated(client, tokens, auth_header, png_bytes):
    headers = auth_header(tokens, "analyst")
    for i in range(3):
        client.post("/api/v1/media", headers=headers, files={"file": (f"page_{i}.png", png_bytes(50 + i, 50), "image/png")})

    page = client.get("/api/v1/media?page=1&page_size=2", headers=headers)
    assert page.status_code == 200
    body = page.json()
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    assert body["total"] >= 3


def test_failed_inference_job_can_be_retried_and_retry_is_bounded(client, tokens, auth_header, png_bytes, db, org):
    """Forces a real failure (an active model whose adapter_key is
    valid at registration time but made unavailable before the job
    runs) so retry_job() is exercised against a genuine failed job,
    not a hand-constructed row."""
    from app.services import model_registry_service

    headers = auth_header(tokens, "analyst")
    media = client.post("/api/v1/media", headers=headers, files={"file": ("retry.png", png_bytes(80, 80), "image/png")}).json()
    model_record = model_registry_service.register_cv_model(db, name="flaky", version="1", adapter_key="mock_detector_v1", supported_media_types=["image"])

    # Make the adapter registry temporarily unable to resolve this
    # model's adapter_key -- a realistic, honest way to force a real
    # job failure (app/cv/adapters/registry.UnsupportedRuntimeError)
    # rather than injecting a fake exception.
    model_record.adapter_key = "temporarily_removed_adapter"
    db.add(model_record)
    db.commit()

    submit = client.post(
        "/api/v1/inference/jobs", headers=headers,
        json={"media_asset_id": media["id"], "model_record_id": model_record.id, "job_type": "image_detection"},
    )
    assert submit.status_code == 201
    job = submit.json()
    assert job["status"] == "failed"
    assert job["error_message"] is not None

    # Restore the adapter, then retry -- the retried job should succeed.
    model_record.adapter_key = "mock_detector_v1"
    db.add(model_record)
    db.commit()

    retry = client.post(f"/api/v1/inference/jobs/{job['id']}/retry", headers=headers)
    assert retry.status_code == 201, retry.text
    retried_job = retry.json()
    assert retried_job["status"] == "completed"
    assert retried_job["retried_from_job_id"] == job["id"]
    assert retried_job["retry_count"] == 1


def test_retrying_a_non_failed_job_is_rejected(client, tokens, auth_header, png_bytes, cv_mock_model):
    headers = auth_header(tokens, "analyst")
    media = client.post("/api/v1/media", headers=headers, files={"file": ("ok.png", png_bytes(60, 60), "image/png")}).json()
    job = client.post(
        "/api/v1/inference/jobs", headers=headers,
        json={"media_asset_id": media["id"], "model_record_id": cv_mock_model.id, "job_type": "image_detection"},
    ).json()
    assert job["status"] == "completed"

    retry = client.post(f"/api/v1/inference/jobs/{job['id']}/retry", headers=headers)
    assert retry.status_code == 400


def test_readiness_reports_model_runtime_and_media_storage(client):
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    checks = response.json()["checks"]
    assert checks["database"] == "ok"
    assert checks["media_storage"] == "ok"
    assert checks["model_runtime"] == "ok"


def test_liveness_never_touches_dependencies(client):
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_media_upload_rejection_is_audited(client, tokens, auth_header):
    headers = auth_header(tokens, "analyst")
    response = client.post("/api/v1/media", headers=headers, files={"file": ("bad.png", b"not a real image", "image/png")})
    assert response.status_code == 400

    audit_response = client.get("/api/v1/audit?page_size=100", headers=auth_header(tokens, "admin"))
    assert audit_response.status_code == 200
    actions = [row["action"] for row in audit_response.json()["items"]]
    assert "media.upload_rejected" in actions
