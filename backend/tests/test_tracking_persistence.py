"""/16: persistence of tracking runs. Exercises
`tracking_service.submit_tracking_job()` against real, persisted
MediaAsset/InferenceJob/DetectionResult rows (via the
`tracking_source_factory` fixture -- see conftest.py for why this is
necessary instead of the mock-adapter image pipeline), never a
standalone in-memory demo.
"""
from __future__ import annotations

from app.models.detection_result import DetectionResult
from app.models.track import Track
from app.models.track_observation import TrackObservation
from app.models.tracking_job import TrackingJob
from app.services import tracking_service


def test_submit_creates_job_and_tracks(db, org, seeded_users, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="parallel", num_frames=15)
    job = tracking_service.submit_tracking_job(
        db, organization_id=org.id, inference_job_id=inference_job.id, triggered_by_user_id=seeded_users["analyst"].id,
    )
    assert job.status == "completed"
    assert job.tracker_key == "iou_hungarian_v1"
    assert job.frames_considered == 15
    assert job.frames_processed == 15
    assert job.detections_considered == 30  # 2 objects * 15 frames
    assert job.tracks_created == 2  # "parallel" -- two clean, non-crossing tracks

    tracks = db.execute(tracking_service.list_tracks_query(org.id, job.id)).scalars().all()
    assert len(tracks) == 2
    for track in tracks:
        assert track.tracking_job_id == job.id
        assert track.state in ("confirmed", "ended")
        assert track.matched_observations_count > 0
    # Sequence-scoped track IDs are unique within this job.
    sequence_ids = [t.sequence_track_id for t in tracks]
    assert len(sequence_ids) == len(set(sequence_ids))


def test_observations_link_back_to_the_real_detection_rows_never_rewriting_them(db, org, seeded_users, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=10)
    job = tracking_service.submit_tracking_job(db, organization_id=org.id, inference_job_id=inference_job.id, triggered_by_user_id=None)
    assert job.tracks_created == 1

    track = db.execute(tracking_service.list_tracks_query(org.id, job.id)).scalars().first()
    observations = db.execute(tracking_service.list_observations_query(org.id, track.id)).scalars().all()
    assert len(observations) == 10

    for obs in observations:
        detection = db.get(DetectionResult, obs.detection_result_id)
        assert detection is not None
        # The observation mirrors the detection at creation time -- and
        # the original detection row is never edited by this process.
        assert obs.class_label == detection.class_label
        assert obs.bbox_x_min == detection.bbox_x_min
        assert obs.bbox_y_min == detection.bbox_y_min
        assert obs.confidence == detection.confidence
        assert detection.review_status == "unreviewed"  # tracking never touches detection review state


def test_rerunning_the_same_source_creates_an_entirely_distinct_result(db, org, seeded_users, tracking_source_factory):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=8)
    job1 = tracking_service.submit_tracking_job(db, organization_id=org.id, inference_job_id=inference_job.id, triggered_by_user_id=None)
    job2 = tracking_service.submit_tracking_job(db, organization_id=org.id, inference_job_id=inference_job.id, triggered_by_user_id=None)

    assert job1.id != job2.id
    tracks1 = db.execute(tracking_service.list_tracks_query(org.id, job1.id)).scalars().all()
    tracks2 = db.execute(tracking_service.list_tracks_query(org.id, job2.id)).scalars().all()
    assert len(tracks1) == len(tracks2) == 1
    # Never the same row -- a rerun is a brand-new TrackingJob with its
    # own fresh Track/TrackObservation rows, never a mutation in place.
    assert tracks1[0].id != tracks2[0].id
    assert tracks1[0].tracking_job_id != tracks2[0].tracking_job_id


def test_a_failed_run_is_recorded_and_rolled_back_without_orphaned_tracks(db, org, seeded_users, tracking_source_factory, monkeypatch):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=5)

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated tracker failure")

    monkeypatch.setattr("app.services.tracking_service.get_tracker", _boom)

    job = tracking_service.submit_tracking_job(db, organization_id=org.id, inference_job_id=inference_job.id, triggered_by_user_id=None)
    assert job.status == "failed"
    assert job.error_category == "RuntimeError"
    assert "simulated tracker failure" in job.error_message

    tracks = db.execute(tracking_service.list_tracks_query(org.id, job.id)).scalars().all()
    assert tracks == []  # the rollback left no partial Track rows behind
    # The job row itself still exists and is queryable -- failure is
    # recorded, never silently swallowed.
    reloaded = tracking_service.get_job(db, org.id, job.id)
    assert reloaded is not None
    assert reloaded.status == "failed"


def test_retry_after_failure_creates_a_new_job_and_can_succeed(db, org, seeded_users, tracking_source_factory, monkeypatch):
    media, inference_job = tracking_source_factory(pattern="single", num_frames=5)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.services.tracking_service.get_tracker", _boom)
    failed_job = tracking_service.submit_tracking_job(db, organization_id=org.id, inference_job_id=inference_job.id, triggered_by_user_id=None)
    assert failed_job.status == "failed"

    monkeypatch.undo()
    retried_job = tracking_service.retry_job(db, org.id, failed_job, triggered_by_user_id=None)
    assert retried_job.id != failed_job.id
    assert retried_job.retried_from_job_id == failed_job.id
    assert retried_job.status == "completed"
    assert retried_job.tracks_created == 1


def test_tracking_jobs_are_paginated(db, org, seeded_users, tracking_source_factory):
    for _ in range(3):
        media, inference_job = tracking_source_factory(pattern="single", num_frames=5)
        tracking_service.submit_tracking_job(db, organization_id=org.id, inference_job_id=inference_job.id, triggered_by_user_id=None)

    from app.api.pagination import paginate
    from app.schemas.tracking import TrackingJobResponse

    stmt = tracking_service.list_jobs_query(org.id)
    page = paginate(db, stmt, 1, 2, TrackingJobResponse)
    assert page.total == 3
    assert len(page.items) == 2


def test_tenant_isolation_a_second_org_sees_no_jobs_or_tracks(db, org, seeded_users, tracking_source_factory):
    from app.models.organization import Organization

    other_org = Organization(name="Other Org", status="active")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)

    media, inference_job = tracking_source_factory(pattern="single", num_frames=5)
    job = tracking_service.submit_tracking_job(db, organization_id=org.id, inference_job_id=inference_job.id, triggered_by_user_id=None)

    assert tracking_service.get_job(db, other_org.id, job.id) is None
    other_org_jobs = db.execute(tracking_service.list_jobs_query(other_org.id)).scalars().all()
    assert other_org_jobs == []

    track = db.execute(tracking_service.list_tracks_query(org.id, job.id)).scalars().first()
    assert tracking_service.get_track(db, other_org.id, track.id) is None
