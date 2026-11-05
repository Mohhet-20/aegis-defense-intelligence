"""/15/16: tracking authorization and input
validation. Every tracking/annotation/evaluation route decides
authorization server-side via require_permission (Section 9's split:
Analyst can run+read+annotate; Investigator can read+annotate but not
run; Viewer can only read) -- never a frontend-only check.
"""
from __future__ import annotations


def _submit(client, headers, inference_job_id, **extra):
    payload = {"inference_job_id": inference_job_id, **extra}
    return client.post("/api/v1/tracking/jobs", headers=headers, json=payload)


def test_viewer_cannot_submit_a_tracking_job(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=5)
    response = _submit(client, auth_header(tokens, "viewer"), inference_job.id)
    assert response.status_code == 403
    assert "tracking:run" in response.json()["detail"]


def test_investigator_cannot_submit_a_tracking_job(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=5)
    response = _submit(client, auth_header(tokens, "investigator"), inference_job.id)
    assert response.status_code == 403
    assert "tracking:run" in response.json()["detail"]


def test_investigator_can_read_tracking_jobs(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=5)
    submit = _submit(client, auth_header(tokens, "analyst"), inference_job.id)
    assert submit.status_code == 201
    job_id = submit.json()["id"]

    response = client.get(f"/api/v1/tracking/jobs/{job_id}", headers=auth_header(tokens, "investigator"))
    assert response.status_code == 200


def test_investigator_can_annotate_a_track_but_viewer_cannot(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=5)
    job = _submit(client, auth_header(tokens, "analyst"), inference_job.id).json()
    tracks = client.get(f"/api/v1/tracking/jobs/{job['id']}/tracks", headers=auth_header(tokens, "analyst")).json()["items"]
    track_id = tracks[0]["id"]

    viewer_response = client.post(
        f"/api/v1/tracking/tracks/{track_id}/annotations", headers=auth_header(tokens, "viewer"), json={"annotation_type": "note", "note": "hi"},
    )
    assert viewer_response.status_code == 403
    assert "track:annotate" in viewer_response.json()["detail"]

    investigator_response = client.post(
        f"/api/v1/tracking/tracks/{track_id}/annotations", headers=auth_header(tokens, "investigator"),
        json={"annotation_type": "possible_error", "note": "looks off"},
    )
    assert investigator_response.status_code == 201


def test_viewer_cannot_run_a_tracking_evaluation_but_can_read_results(client, seeded_users, tokens, auth_header):
    viewer_run = client.post("/api/v1/tracking/evaluation/runs", headers=auth_header(tokens, "viewer"), json={})
    assert viewer_run.status_code == 403
    assert "tracking_evaluation:run" in viewer_run.json()["detail"]

    analyst_run = client.post("/api/v1/tracking/evaluation/runs", headers=auth_header(tokens, "analyst"), json={})
    assert analyst_run.status_code == 201

    viewer_list = client.get("/api/v1/tracking/evaluation/runs", headers=auth_header(tokens, "viewer"))
    assert viewer_list.status_code == 200
    assert viewer_list.json()["total"] >= 1


def test_submission_rejects_an_unknown_tracker_key(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=5)
    response = _submit(client, auth_header(tokens, "analyst"), inference_job.id, tracker_key="not_a_real_tracker")
    assert response.status_code == 400
    assert "unknown tracker_key" in response.json()["detail"]


def test_submission_rejects_a_source_job_of_the_wrong_type(client, seeded_users, tokens, auth_header, png_bytes, cv_mock_model):
    headers = auth_header(tokens, "analyst")
    media = client.post("/api/v1/media", headers=headers, files={"file": ("p.png", png_bytes(80, 60), "image/png")}).json()
    image_job = client.post(
        "/api/v1/inference/jobs", headers=headers,
        json={"media_asset_id": media["id"], "model_record_id": cv_mock_model.id, "job_type": "image_detection"},
    ).json()
    response = _submit(client, headers, image_job["id"])
    assert response.status_code == 400
    assert "video_frame_analysis" in response.json()["detail"]


def test_submission_rejects_a_nonexistent_inference_job(client, seeded_users, tokens, auth_header):
    response = _submit(client, auth_header(tokens, "analyst"), "does-not-exist")
    assert response.status_code == 400
    assert "not found" in response.json()["detail"]


def test_annotation_note_over_max_length_is_rejected(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=5)
    job = _submit(client, auth_header(tokens, "analyst"), inference_job.id).json()
    tracks = client.get(f"/api/v1/tracking/jobs/{job['id']}/tracks", headers=auth_header(tokens, "analyst")).json()["items"]
    track_id = tracks[0]["id"]

    oversized_note = "x" * 2001  # the schema caps note at 2000 chars
    response = client.post(
        f"/api/v1/tracking/tracks/{track_id}/annotations", headers=auth_header(tokens, "analyst"),
        json={"annotation_type": "note", "note": oversized_note},
    )
    assert response.status_code == 422


def test_annotation_rejects_an_unknown_annotation_type(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=5)
    job = _submit(client, auth_header(tokens, "analyst"), inference_job.id).json()
    tracks = client.get(f"/api/v1/tracking/jobs/{job['id']}/tracks", headers=auth_header(tokens, "analyst")).json()["items"]
    track_id = tracks[0]["id"]

    response = client.post(
        f"/api/v1/tracking/tracks/{track_id}/annotations", headers=auth_header(tokens, "analyst"),
        json={"annotation_type": "hostile_classification"},
    )
    assert response.status_code == 422  # not in ANNOTATION_TYPES -- rejected before it ever reaches the service


def test_cross_tenant_access_to_a_tracking_job_returns_404(client, db, org, seeded_users, tokens, auth_header, tracking_source_factory):
    from app.core.security import hash_password
    from app.models.organization import Organization
    from app.models.user import User

    media, inference_job = tracking_source_factory(pattern="single", num_frames=5)
    job = _submit(client, auth_header(tokens, "analyst"), inference_job.id).json()

    other_org = Organization(name="Other Tenant Org", status="active")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)
    other_user = User(
        organization_id=other_org.id, username="otheranalyst", email="otheranalyst@test.example.com", display_name="Other Analyst",
        password_hash=hash_password("TestPassword123!"), role="analyst", is_active=True,
    )
    db.add(other_user)
    db.commit()

    login = client.post("/api/v1/auth/login", json={"username_or_email": "otheranalyst", "password": "TestPassword123!"})
    assert login.status_code == 200
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.get(f"/api/v1/tracking/jobs/{job['id']}", headers=other_headers)
    assert response.status_code == 404
