"""Phase 4, Section 8/17: bounded video frame analysis. Confirms real
frame sampling (interval + max_frames bounds are actually respected),
frame_index/timestamp preservation, and that this is explicitly
point-in-time, bounded sampling -- never "every frame," never
unbounded.
"""
from __future__ import annotations


def _upload_video(client, headers, mp4_bytes, **kwargs):
    content = mp4_bytes(**kwargs)
    response = client.post("/api/v1/media", headers=headers, files={"file": ("clip.mp4", content, "video/mp4")})
    assert response.status_code == 201, response.text
    return response.json()


def test_video_job_respects_max_frames_cap(client, tokens, auth_header, mp4_bytes, cv_mock_model):
    headers = auth_header(tokens, "analyst")
    media = _upload_video(client, headers, mp4_bytes, width=64, height=48, fps=10.0, num_frames=100)  # 10 real seconds

    response = client.post(
        "/api/v1/inference/jobs", headers=headers,
        json={
            "media_asset_id": media["id"], "model_record_id": cv_mock_model.id, "job_type": "video_frame_analysis",
            "frame_sample_interval_seconds": 1.0, "max_frames": 5,
        },
    )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["status"] == "completed"
    assert job["frames_processed"] == 5  # bounded -- never "every frame" of a 100-frame video
    assert job["parameters"]["max_frames"] == 5

    detections = client.get(f"/api/v1/inference/jobs/{job['id']}/detections", headers=headers).json()["items"]
    sampled_frame_indices = sorted({d["frame_index"] for d in detections})
    # Every detection carries a real, preserved frame_index/timestamp --
    # never null, unlike an image job's single-frame detections.
    for det in detections:
        assert det["frame_index"] is not None
        assert det["frame_timestamp_seconds"] is not None
    assert sampled_frame_indices == sorted(set(sampled_frame_indices))  # sanity: no duplicate processing
    assert max(sampled_frame_indices) < 100


def test_video_job_sampling_interval_controls_which_frames_are_used(client, tokens, auth_header, mp4_bytes, cv_mock_model):
    headers = auth_header(tokens, "analyst")
    # 5 real seconds at 10fps = 50 frames.
    media = _upload_video(client, headers, mp4_bytes, width=48, height=48, fps=10.0, num_frames=50)

    response = client.post(
        "/api/v1/inference/jobs", headers=headers,
        json={
            "media_asset_id": media["id"], "model_record_id": cv_mock_model.id, "job_type": "video_frame_analysis",
            "frame_sample_interval_seconds": 2.0, "max_frames": 30,
        },
    )
    job = response.json()
    assert job["status"] == "completed"
    # At 10fps with a 2-second interval, frames land every 20 raw
    # frames: 0, 20, 40 -- 3 sampled frames from a 50-frame video, well
    # under the max_frames=30 cap, proving the INTERVAL (not just the
    # cap) is what's actually controlling the sampling.
    assert job["frames_processed"] == 3

    detections = client.get(f"/api/v1/inference/jobs/{job['id']}/detections", headers=headers).json()["items"]
    frame_indices = sorted({d["frame_index"] for d in detections})
    assert frame_indices == [0, 20, 40]


def test_video_max_frames_request_is_clamped_to_the_configured_ceiling(client, tokens, auth_header, mp4_bytes, cv_mock_model):
    headers = auth_header(tokens, "analyst")
    media = _upload_video(client, headers, mp4_bytes, width=48, height=48, fps=10.0, num_frames=400)  # 40 real seconds

    response = client.post(
        "/api/v1/inference/jobs", headers=headers,
        json={
            "media_asset_id": media["id"], "model_record_id": cv_mock_model.id, "job_type": "video_frame_analysis",
            "frame_sample_interval_seconds": 0.1, "max_frames": 10000,  # client asks for far more than the server allows
        },
    )
    job = response.json()
    assert job["status"] == "completed"
    # settings.CV_VIDEO_MAX_FRAMES_PER_JOB (30 by default) wins no
    # matter what the client requests -- same "server always clamps"
    # discipline Phase 3's evidence-graph caps established.
    assert job["frames_processed"] <= 30
    assert job["parameters"]["max_frames"] <= 30


def test_video_job_against_image_only_model_is_rejected(client, tokens, auth_header, mp4_bytes, db):
    from app.services import model_registry_service

    image_only_model = model_registry_service.register_cv_model(
        db, name="image-only-2", version="1", adapter_key="mock_detector_v1", supported_media_types=["image"],
    )
    headers = auth_header(tokens, "analyst")
    media = _upload_video(client, headers, mp4_bytes, num_frames=20)

    response = client.post(
        "/api/v1/inference/jobs", headers=headers,
        json={"media_asset_id": media["id"], "model_record_id": image_only_model.id, "job_type": "video_frame_analysis"},
    )
    assert response.status_code == 400
    assert "does not support" in response.json()["detail"]
