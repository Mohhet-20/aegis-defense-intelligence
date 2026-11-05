"""/14: analyst review of a detection, and the ONLY
path into the Evidence layer -- promoting a CONFIRMED detection. The
single most important test here proves a detection can never be
auto-promoted: promotion must fail for 'unreviewed' and for 'rejected'.
"""
from __future__ import annotations

import pytest

from app.services import detection_review_service


def _submit_and_get_first_detection(client, headers, png_bytes, cv_mock_model):
    media = client.post("/api/v1/media", headers=headers, files={"file": ("p.png", png_bytes(100, 100), "image/png")}).json()
    job = client.post(
        "/api/v1/inference/jobs", headers=headers,
        json={"media_asset_id": media["id"], "model_record_id": cv_mock_model.id, "job_type": "image_detection"},
    ).json()
    detections = client.get(f"/api/v1/inference/jobs/{job['id']}/detections", headers=headers).json()["items"]
    assert detections
    return detections[0], media


def test_unreviewed_detection_cannot_be_promoted_to_evidence(db):
    from app.models.detection_result import DetectionResult

    detection = DetectionResult(
        organization_id="org-x", inference_job_id="job-x", media_asset_id="media-x", model_record_id="model-x",
        class_label="mock_object", confidence=0.9, bbox_x_min=0.1, bbox_y_min=0.1, bbox_x_max=0.5, bbox_y_max=0.5,
    )
    with pytest.raises(detection_review_service.ReviewError, match="confirmed"):
        detection_review_service.promote_to_evidence(db, detection, title="t", summary=None, created_by_user_id=None)


def test_rejected_detection_cannot_be_promoted_to_evidence(db):
    from app.models.detection_result import DetectionResult

    detection = DetectionResult(
        organization_id="org-x", inference_job_id="job-x", media_asset_id="media-x", model_record_id="model-x",
        class_label="mock_object", confidence=0.9, bbox_x_min=0.1, bbox_y_min=0.1, bbox_x_max=0.5, bbox_y_max=0.5,
        review_status="rejected",
    )
    with pytest.raises(detection_review_service.ReviewError, match="confirmed"):
        detection_review_service.promote_to_evidence(db, detection, title="t", summary=None, created_by_user_id=None)


def test_confirmed_detection_can_be_promoted_to_evidence(client, tokens, auth_header, png_bytes, cv_mock_model):
    headers = auth_header(tokens, "analyst")
    detection, media = _submit_and_get_first_detection(client, headers, png_bytes, cv_mock_model)

    review = client.post(f"/api/v1/detections/{detection['id']}/review", headers=headers, json={"review_status": "confirmed", "review_note": "looks right"})
    assert review.status_code == 200
    assert review.json()["review_status"] == "confirmed"

    promote = client.post(f"/api/v1/detections/{detection['id']}/promote-to-evidence", headers=headers, json={"title": "Detected object in photo.png", "summary": "Confirmed by analyst."})
    assert promote.status_code == 201, promote.text
    evidence = promote.json()
    assert evidence["evidence_type"] == "media_reference"
    assert evidence["detection_result_id"] == detection["id"]
    assert evidence["external_reference_uri"] == f"media_asset://{media['id']}"


def test_promoting_an_unreviewed_detection_via_api_is_rejected(client, tokens, auth_header, png_bytes, cv_mock_model):
    headers = auth_header(tokens, "analyst")
    detection, _media = _submit_and_get_first_detection(client, headers, png_bytes, cv_mock_model)

    response = client.post(f"/api/v1/detections/{detection['id']}/promote-to-evidence", headers=headers, json={"title": "t"})
    assert response.status_code == 409


def test_rejecting_a_detection_then_promoting_is_also_rejected(client, tokens, auth_header, png_bytes, cv_mock_model):
    headers = auth_header(tokens, "analyst")
    detection, _media = _submit_and_get_first_detection(client, headers, png_bytes, cv_mock_model)

    client.post(f"/api/v1/detections/{detection['id']}/review", headers=headers, json={"review_status": "rejected"})
    response = client.post(f"/api/v1/detections/{detection['id']}/promote-to-evidence", headers=headers, json={"title": "t"})
    assert response.status_code == 409


def test_viewer_cannot_review_a_detection(client, tokens, auth_header, png_bytes, cv_mock_model):
    analyst_headers = auth_header(tokens, "analyst")
    detection, _media = _submit_and_get_first_detection(client, analyst_headers, png_bytes, cv_mock_model)

    viewer_headers = auth_header(tokens, "viewer")
    response = client.post(f"/api/v1/detections/{detection['id']}/review", headers=viewer_headers, json={"review_status": "confirmed"})
    assert response.status_code == 403


def test_review_audit_trail_is_recorded(client, tokens, auth_header, png_bytes, cv_mock_model, db, org):
    headers = auth_header(tokens, "analyst")
    detection, _media = _submit_and_get_first_detection(client, headers, png_bytes, cv_mock_model)
    client.post(f"/api/v1/detections/{detection['id']}/review", headers=headers, json={"review_status": "confirmed"})

    from app.services import audit_service

    history = audit_service.list_for_target(db, org.id, target_type="detection_result", target_id=detection["id"])
    assert any(h.action == "detection.review" for h in history)
