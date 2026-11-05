"""Job status is truthful and retry/cancel are only offered
where they are real. All AEGIS jobs run synchronously inside the request
that creates them (documented limitation: there is no worker queue), so a
job is never reported as 'running' after its request returned, and a finished
job cannot be retried or cancelled."""
from __future__ import annotations

import io
import json

from sqlalchemy import select

from app.models.inference_job import InferenceJob

API = "/api/v1"
TERMINAL = {"completed", "failed", "completed_with_errors", "partial", "succeeded", "cancelled"}


def test_inference_job_is_terminal_when_the_request_returns_and_completed_is_not_retryable(client, db, tokens, auth_header, png_bytes, cv_mock_model):
    h = auth_header(tokens, "analyst")
    media = client.post(f"{API}/media", headers=h, files={"file": ("a.png", png_bytes(), "image/png")}).json()
    job = client.post(f"{API}/inference/jobs", headers=h, json={"media_asset_id": media["id"], "model_record_id": cv_mock_model.id, "job_type": "image_detection"}).json()
    assert job["status"] in TERMINAL
    before = len(db.execute(select(InferenceJob)).scalars().all())
    retry = client.post(f"{API}/inference/jobs/{job['id']}/retry", headers=h)
    assert retry.status_code in (400, 409), retry.text
    db.expire_all()
    assert len(db.execute(select(InferenceJob)).scalars().all()) == before


def test_failed_job_is_reported_failed_with_a_sanitized_reason(client, db, tokens, auth_header, png_bytes):
    from app.services import model_registry_service

    h = auth_header(tokens, "analyst")
    media = client.post(f"{API}/media", headers=h, files={"file": ("a.png", png_bytes(), "image/png")}).json()
    model = model_registry_service.register_cv_model(db, name="m", version="1", adapter_key="mock_detector_v1", supported_media_types=["image"])
    model.adapter_key = "gone"
    db.add(model)
    db.commit()
    job = client.post(f"{API}/inference/jobs", headers=h, json={"media_asset_id": media["id"], "model_record_id": model.id, "job_type": "image_detection"})
    assert job.status_code == 201
    body = job.json()
    assert body["status"] == "failed" and body["error_message"]
    assert "Traceback" not in body["error_message"] and "/home/" not in body["error_message"]
    # a failed job must not look like it produced results
    dets = client.get(f"{API}/inference/jobs/{body['id']}/detections", headers=h).json()
    assert dets["total"] == 0


def test_ingestion_jobs_are_terminal_and_completed_not_retryable(client, tokens, auth_header, source):
    h = auth_header(tokens, "analyst")
    rec = [{"event_type": "a", "title": "t", "observed_at": "2026-01-01T00:00:00Z", "external_id": "j1"}]
    job = client.post(f"{API}/ingestion/jobs", data={"source_id": source.id}, headers=h,
                      files={"file": ("a.json", io.BytesIO(json.dumps(rec).encode()), "application/json")}).json()
    assert job["status"] in TERMINAL
    assert client.post(f"{API}/ingestion/jobs/{job['id']}/retry", headers=h).status_code in (400, 409)


def test_viewer_cannot_retry_any_job(client, tokens, auth_header):
    for path in ("ingestion/jobs", "inference/jobs", "tracking/jobs", "sensor-ingestion/batches"):
        assert client.post(f"{API}/{path}/00000000-0000-0000-0000-000000000001/retry", headers=auth_header(tokens, "viewer")).status_code == 403
