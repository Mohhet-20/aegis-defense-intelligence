"""Phase 5, Section 10/16: the tracking API surface -- submission,
status, track history, frame-range queries, the annotation workflow,
and retry behavior. Exercised through the real HTTP client, never by
calling service functions directly (that is test_tracking_persistence.py's
job).
"""
from __future__ import annotations


def _submit(client, headers, inference_job_id, **extra):
    return client.post("/api/v1/tracking/jobs", headers=headers, json={"inference_job_id": inference_job_id, **extra})


def test_valid_submission_returns_a_completed_job_with_real_counts(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="parallel", num_frames=12)
    headers = auth_header(tokens, "analyst")
    response = _submit(client, headers, inference_job.id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["media_asset_id"] == media.id
    assert body["inference_job_id"] == inference_job.id
    assert body["tracks_created"] == 2
    assert body["frames_processed"] == 12
    assert body["processing_duration_seconds"] is not None
    assert body["processing_duration_seconds"] >= 0


def test_invalid_media_reference_is_rejected_with_a_clear_400(client, seeded_users, tokens, auth_header):
    headers = auth_header(tokens, "analyst")
    response = _submit(client, headers, "not-a-real-inference-job-id")
    assert response.status_code == 400
    assert "not found" in response.json()["detail"]


def test_job_status_endpoint_returns_the_persisted_job(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=6)
    headers = auth_header(tokens, "analyst")
    submitted = _submit(client, headers, inference_job.id).json()

    response = client.get(f"/api/v1/tracking/jobs/{submitted['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == submitted["id"]
    assert response.json()["status"] == "completed"


def test_job_not_found_returns_404(client, seeded_users, tokens, auth_header):
    headers = auth_header(tokens, "analyst")
    response = client.get("/api/v1/tracking/jobs/does-not-exist", headers=headers)
    assert response.status_code == 404


def test_track_observation_history_is_retrievable_and_paginated(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=9)
    headers = auth_header(tokens, "analyst")
    job = _submit(client, headers, inference_job.id).json()
    tracks = client.get(f"/api/v1/tracking/jobs/{job['id']}/tracks", headers=headers).json()["items"]
    assert len(tracks) == 1
    track_id = tracks[0]["id"]

    response = client.get(f"/api/v1/tracking/tracks/{track_id}/observations", headers=headers, params={"page": 1, "page_size": 5})
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 9
    assert len(page["items"]) == 5
    frame_indices = [o["frame_index"] for o in page["items"]]
    assert frame_indices == sorted(frame_indices)  # ordered by frame_index ascending


def test_frame_range_retrieval_on_observations(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=9)
    headers = auth_header(tokens, "analyst")
    job = _submit(client, headers, inference_job.id).json()
    track_id = client.get(f"/api/v1/tracking/jobs/{job['id']}/tracks", headers=headers).json()["items"][0]["id"]

    response = client.get(
        f"/api/v1/tracking/tracks/{track_id}/observations", headers=headers, params={"frame_min": 3, "frame_max": 5},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert all(3 <= o["frame_index"] <= 5 for o in items)
    assert len(items) == 3


def test_frame_tracks_endpoint_returns_every_observation_at_that_frame(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="parallel", num_frames=10)
    headers = auth_header(tokens, "analyst")
    job = _submit(client, headers, inference_job.id).json()

    response = client.get(f"/api/v1/tracking/jobs/{job['id']}/frames/5/tracks", headers=headers)
    assert response.status_code == 200
    observations = response.json()
    assert len(observations) == 2  # both "parallel" objects were observed at frame 5
    assert {o["frame_index"] for o in observations} == {5}


def test_track_motion_endpoint_reports_pixel_only_descriptive_motion(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=8, width_px=320, height_px=240)
    headers = auth_header(tokens, "analyst")
    job = _submit(client, headers, inference_job.id).json()
    track_id = client.get(f"/api/v1/tracking/jobs/{job['id']}/tracks", headers=headers).json()["items"][0]["id"]

    response = client.get(f"/api/v1/tracking/tracks/{track_id}/motion", headers=headers)
    assert response.status_code == 200
    motion = response.json()
    assert "never a physical-world unit" in motion["unit_note"]
    assert motion["observation_count"] == 8
    assert motion["total_path_length_px"] > 0


def test_job_summary_endpoint(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="parallel", num_frames=10)
    headers = auth_header(tokens, "analyst")
    job = _submit(client, headers, inference_job.id).json()

    response = client.get(f"/api/v1/tracking/jobs/{job['id']}/summary", headers=headers)
    assert response.status_code == 200
    summary = response.json()
    assert summary["total_tracks"] == 2
    assert summary["total_observations"] == 20


def test_annotation_workflow_create_then_supersede(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=6)
    headers = auth_header(tokens, "analyst")
    job = _submit(client, headers, inference_job.id).json()
    track_id = client.get(f"/api/v1/tracking/jobs/{job['id']}/tracks", headers=headers).json()["items"][0]["id"]

    first = client.post(
        f"/api/v1/tracking/tracks/{track_id}/annotations", headers=headers, json={"annotation_type": "uncertain_association", "note": "initial read"},
    )
    assert first.status_code == 201
    first_id = first.json()["id"]
    assert first.json()["superseded_at"] is None

    second = client.post(
        f"/api/v1/tracking/tracks/{track_id}/annotations", headers=headers,
        json={"annotation_type": "reviewed", "note": "confirmed correct on closer look", "supersedes_annotation_id": first_id},
    )
    assert second.status_code == 201

    listing = client.get(f"/api/v1/tracking/tracks/{track_id}/annotations", headers=headers)
    assert listing.status_code == 200
    by_id = {a["id"]: a for a in listing.json()}
    assert by_id[first_id]["superseded_at"] is not None  # the original row was never deleted, only marked superseded
    assert by_id[second.json()["id"]]["supersedes_annotation_id"] == first_id


def test_retry_is_rejected_for_a_job_that_did_not_fail(client, seeded_users, tokens, auth_header, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=5)
    headers = auth_header(tokens, "analyst")
    job = _submit(client, headers, inference_job.id).json()
    assert job["status"] == "completed"

    response = client.post(f"/api/v1/tracking/jobs/{job['id']}/retry", headers=headers)
    assert response.status_code == 400
    assert "failed job" in response.json()["detail"]


def test_tracking_config_endpoint_lists_the_real_allow_listed_tracker(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/tracking/config", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 200
    body = response.json()
    keys = [t["tracker_key"] for t in body["available_trackers"]]
    assert "iou_hungarian_v1" in keys
    assert body["default_tracker_key"] == "iou_hungarian_v1"
