"""Tracking job orchestration. Submits and runs
one `TrackingJob` -- associating the already-persisted `DetectionResult`
rows of one completed `video_frame_analysis` InferenceJob into
sequence-scoped `Track`/`TrackObservation` rows via one tracker
(app/tracking/).

Execution model, stated plainly, exactly like every job table before it
in this codebase (IngestionJob/FusionJob/InferenceJob): this function
runs SYNCHRONOUSLY inside the API request that calls it. There is still
no background worker/queue anywhere in this codebase. Frames are
processed one at a time in a single pass (never holding the whole
video's detections in a structure larger than one organization's worth
of already-small DetectionResult rows for one job), and the tracker
itself only ever holds state for currently-active tracks, not the whole
video's history, per Section 11's "avoid holding every decoded video
frame in memory" (this service never touches video frames at all --
only the already-extracted, already-persisted detection rows
produced).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.detection_result import DetectionResult
from app.models.inference_job import InferenceJob
from app.models.media_asset import MediaAsset
from app.models.track import Track
from app.models.track_observation import TrackObservation
from app.models.tracking_job import TRACKING_MAX_RETRIES, TrackingJob
from app.tracking import motion
from app.tracking.trackers.base import TrackerDetectionInput
from app.tracking.trackers.iou_tracker import TrackerConfig
from app.tracking.trackers.registry import available_tracker_keys, get_tracker, get_tracker_version

settings = get_settings()


class TrackingSubmissionError(ValueError):
    """A 400-worthy problem with the submission itself -- raised BEFORE
    any TrackingJob row is created, distinct from a job that was
    created and then failed during its own run."""


def _resolve_submission(db: Session, organization_id: str, inference_job_id: str, tracker_key: str) -> tuple[InferenceJob, MediaAsset]:
    inference_job = db.execute(
        select(InferenceJob).where(InferenceJob.id == inference_job_id, InferenceJob.organization_id == organization_id)
    ).scalar_one_or_none()
    if inference_job is None:
        raise TrackingSubmissionError("source inference job not found")
    if inference_job.job_type != "video_frame_analysis":
        raise TrackingSubmissionError(
            f"tracking requires a 'video_frame_analysis' inference job as its source (got '{inference_job.job_type}') -- "
            "a single image_detection job has exactly one frame, so there is nothing to associate across frames"
        )
    if inference_job.status != "completed":
        raise TrackingSubmissionError(f"source inference job is not completed (status={inference_job.status})")

    media_asset = db.get(MediaAsset, inference_job.media_asset_id)
    if media_asset is None or media_asset.organization_id != organization_id:
        raise TrackingSubmissionError("source media asset not found")
    if not media_asset.width_px or not media_asset.height_px:
        raise TrackingSubmissionError("source media asset is missing measured frame dimensions; cannot convert to pixel-space motion")

    if tracker_key not in available_tracker_keys():
        raise TrackingSubmissionError(f"unknown tracker_key '{tracker_key}'. Available trackers: {available_tracker_keys()}")

    return inference_job, media_asset


def _existing_job_for_idempotency_key(db: Session, organization_id: str, idempotency_key: Optional[str]) -> Optional[TrackingJob]:
    if not idempotency_key:
        return None
    stmt = select(TrackingJob).where(TrackingJob.organization_id == organization_id, TrackingJob.idempotency_key == idempotency_key)
    return db.execute(stmt).scalar_one_or_none()


def submit_tracking_job(
    db: Session,
    *,
    organization_id: str,
    inference_job_id: str,
    triggered_by_user_id: Optional[str],
    tracker_key: Optional[str] = None,
    min_iou_threshold: Optional[float] = None,
    max_missed_frames: Optional[int] = None,
    min_hits_to_confirm: Optional[int] = None,
    require_class_match: Optional[bool] = None,
    idempotency_key: Optional[str] = None,
) -> TrackingJob:
    existing = _existing_job_for_idempotency_key(db, organization_id, idempotency_key)
    if existing is not None:
        return existing

    tracker_key = tracker_key or settings.TRACKING_DEFAULT_TRACKER_KEY
    inference_job, media_asset = _resolve_submission(db, organization_id, inference_job_id, tracker_key)

    config = {
        "min_iou_threshold": min_iou_threshold if min_iou_threshold is not None else settings.TRACKING_MIN_IOU_THRESHOLD,
        "max_missed_frames": max_missed_frames if max_missed_frames is not None else settings.TRACKING_MAX_MISSED_FRAMES,
        "min_hits_to_confirm": min_hits_to_confirm if min_hits_to_confirm is not None else settings.TRACKING_MIN_HITS_TO_CONFIRM,
        "require_class_match": require_class_match if require_class_match is not None else settings.TRACKING_REQUIRE_CLASS_MATCH,
        "max_active_tracks": settings.TRACKING_MAX_ACTIVE_TRACKS_PER_JOB,
    }

    job = TrackingJob(
        organization_id=organization_id,
        media_asset_id=media_asset.id,
        inference_job_id=inference_job_id,
        tracker_key=tracker_key,
        tracker_version=get_tracker_version(tracker_key),
        status="pending",
        config=config,
        triggered_by_user_id=triggered_by_user_id,
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    _run_job(db, job, media_asset)
    return job


def _run_job(db: Session, job: TrackingJob, media_asset: MediaAsset) -> None:
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()

    try:
        tracker_config = TrackerConfig(**job.config)
        tracker = get_tracker(job.tracker_key, tracker_config)

        detections = db.execute(
            select(DetectionResult)
            .where(DetectionResult.organization_id == job.organization_id, DetectionResult.inference_job_id == job.inference_job_id)
            .order_by(DetectionResult.frame_index.asc(), DetectionResult.confidence.desc())
        ).scalars().all()

        frame_map: dict[int, list[DetectionResult]] = {}
        for det in detections:
            if det.frame_index is None:
                continue  # defensive -- a video_frame_analysis job's detections always carry a frame_index; never crashes on a malformed row
            frame_map.setdefault(det.frame_index, []).append(det)
        sampled_frame_indices = sorted(frame_map.keys())

        frames_processed = 0
        detections_considered = 0
        for frame_index in sampled_frame_indices:
            frame_detections = frame_map[frame_index]
            timestamp_seconds = next((d.frame_timestamp_seconds for d in frame_detections if d.frame_timestamp_seconds is not None), float(frame_index))
            tracker_inputs = [
                TrackerDetectionInput(
                    detection_result_id=d.id, class_label=d.class_label, confidence=d.confidence,
                    bbox_x_min=d.bbox_x_min, bbox_y_min=d.bbox_y_min, bbox_x_max=d.bbox_x_max, bbox_y_max=d.bbox_y_max,
                )
                for d in frame_detections
            ]
            tracker.update(frame_index, timestamp_seconds, tracker_inputs)
            frames_processed += 1
            detections_considered += len(frame_detections)

        finalized_tracks = tracker.finalize()
        tracks_created = 0
        for finalized in finalized_tracks:
            observations_sorted = sorted(finalized.observations, key=lambda o: o.frame_index)
            if not observations_sorted:
                continue  # a track with zero observations cannot happen with this tracker, but never persist one if it somehow did

            track_row = Track(
                organization_id=job.organization_id,
                tracking_job_id=job.id,
                sequence_track_id=f"track-{finalized.internal_track_id}",
                class_label=finalized.class_label,
                first_frame_index=observations_sorted[0].frame_index,
                last_frame_index=observations_sorted[-1].frame_index,
                first_timestamp_seconds=observations_sorted[0].timestamp_seconds,
                last_timestamp_seconds=observations_sorted[-1].timestamp_seconds,
                matched_observations_count=len(observations_sorted),
                missed_frames_count=finalized.missed_frames_count,
                state=finalized.final_state,
                quality_summary=_build_quality_summary(observations_sorted, media_asset, sampled_frame_indices),
                lifecycle_events=[
                    {"frame_index": e.frame_index, "timestamp_seconds": e.timestamp_seconds, "from_state": e.from_state, "to_state": e.to_state, "reason": e.reason}
                    for e in finalized.lifecycle_events
                ],
            )
            db.add(track_row)
            db.flush()  # assigns track_row.id without ending the transaction

            for obs in observations_sorted:
                db.add(
                    TrackObservation(
                        organization_id=job.organization_id,
                        track_id=track_row.id,
                        detection_result_id=obs.detection_result_id,
                        media_asset_id=media_asset.id,
                        frame_index=obs.frame_index,
                        frame_timestamp_seconds=obs.timestamp_seconds,
                        bbox_x_min=obs.bbox[0], bbox_y_min=obs.bbox[1], bbox_x_max=obs.bbox[2], bbox_y_max=obs.bbox[3],
                        class_label=obs.class_label, confidence=obs.confidence,
                        association_method=obs.association_method, association_cost=obs.association_cost,
                        observation_state="matched",
                    )
                )
            tracks_created += 1

        job.frames_considered = len(sampled_frame_indices)
        job.frames_processed = frames_processed
        job.detections_considered = detections_considered
        job.tracks_created = tracks_created
        job.status = "completed"
        job.finished_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001 -- a failed tracking run is a real, reportable outcome, never a silent swallow
        db.rollback()
        job = db.merge(job)
        job.status = "failed"
        job.error_category = type(exc).__name__
        job.error_message = str(exc)[:2000]
        job.finished_at = datetime.now(timezone.utc)

    db.add(job)
    db.commit()
    db.refresh(job)


def _build_quality_summary(observations, media_asset: MediaAsset, sampled_frame_indices: list[int]) -> dict:
    confidences = [o.confidence for o in observations]
    costs = [o.association_cost for o in observations if o.association_cost is not None]
    points = [motion.ObservationPoint(frame_index=o.frame_index, timestamp_seconds=o.timestamp_seconds, bbox=o.bbox) for o in observations]
    summary = motion.compute_motion_summary(points, width_px=media_asset.width_px, height_px=media_asset.height_px, job_sampled_frame_indices=sampled_frame_indices)
    return {
        "mean_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
        "mean_association_cost": round(sum(costs) / len(costs), 4) if costs else None,
        "fragmentation_count": summary.fragmentation_count,
        "missed_sampled_frame_count": summary.missed_sampled_frame_count,
        "bbox_area_px_first": summary.bbox_area_px_first,
        "bbox_area_px_last": summary.bbox_area_px_last,
    }


def retry_job(db: Session, organization_id: str, job: TrackingJob, *, triggered_by_user_id: Optional[str]) -> TrackingJob:
    if job.status != "failed":
        raise ValueError(f"only a failed job can be retried (status={job.status})")
    if job.retry_count >= TRACKING_MAX_RETRIES:
        raise ValueError(f"job has already been retried {job.retry_count} times (limit {TRACKING_MAX_RETRIES})")

    media_asset = db.get(MediaAsset, job.media_asset_id)
    if media_asset is None:
        raise ValueError("the media asset backing this job no longer exists")

    new_job = TrackingJob(
        organization_id=organization_id,
        media_asset_id=job.media_asset_id,
        inference_job_id=job.inference_job_id,
        tracker_key=job.tracker_key,
        tracker_version=job.tracker_version,
        status="pending",
        config=dict(job.config),
        triggered_by_user_id=triggered_by_user_id,
        retry_count=job.retry_count + 1,
        retried_from_job_id=job.id,
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    _run_job(db, new_job, media_asset)
    return new_job


def get_job(db: Session, organization_id: str, job_id: str) -> Optional[TrackingJob]:
    stmt = select(TrackingJob).where(TrackingJob.id == job_id, TrackingJob.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_jobs_query(organization_id: str, *, media_asset_id: Optional[str] = None, status: Optional[str] = None):
    stmt = select(TrackingJob).where(TrackingJob.organization_id == organization_id)
    if media_asset_id:
        stmt = stmt.where(TrackingJob.media_asset_id == media_asset_id)
    if status:
        stmt = stmt.where(TrackingJob.status == status)
    return stmt.order_by(TrackingJob.created_at.desc())


def get_track(db: Session, organization_id: str, track_id: str) -> Optional[Track]:
    stmt = select(Track).where(Track.id == track_id, Track.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_tracks_query(organization_id: str, tracking_job_id: str, *, state: Optional[str] = None):
    stmt = select(Track).where(Track.organization_id == organization_id, Track.tracking_job_id == tracking_job_id)
    if state:
        stmt = stmt.where(Track.state == state)
    return stmt.order_by(Track.first_frame_index.asc())


def list_observations_query(organization_id: str, track_id: str, *, frame_min: Optional[int] = None, frame_max: Optional[int] = None):
    stmt = select(TrackObservation).where(TrackObservation.organization_id == organization_id, TrackObservation.track_id == track_id)
    if frame_min is not None:
        stmt = stmt.where(TrackObservation.frame_index >= frame_min)
    if frame_max is not None:
        stmt = stmt.where(TrackObservation.frame_index <= frame_max)
    return stmt.order_by(TrackObservation.frame_index.asc())


def list_frame_tracks(db: Session, organization_id: str, tracking_job_id: str, frame_index: int) -> list[TrackObservation]:
    stmt = (
        select(TrackObservation)
        .join(Track, Track.id == TrackObservation.track_id)
        .where(Track.tracking_job_id == tracking_job_id, TrackObservation.organization_id == organization_id, TrackObservation.frame_index == frame_index)
    )
    return list(db.execute(stmt).scalars().all())


def get_job_summary(db: Session, organization_id: str, job: TrackingJob) -> dict:
    tracks = db.execute(select(Track).where(Track.tracking_job_id == job.id, Track.organization_id == organization_id)).scalars().all()
    by_state: dict[str, int] = {}
    for t in tracks:
        by_state[t.state] = by_state.get(t.state, 0) + 1
    durations = [t.last_timestamp_seconds - t.first_timestamp_seconds for t in tracks]
    return {
        "tracks_by_state": by_state,
        "total_tracks": len(tracks),
        "mean_track_duration_seconds": round(sum(durations) / len(durations), 4) if durations else 0.0,
        "total_observations": sum(t.matched_observations_count for t in tracks),
    }


def get_track_motion(db: Session, organization_id: str, track: Track) -> dict:
    job = db.get(TrackingJob, track.tracking_job_id)
    media_asset = db.get(MediaAsset, job.media_asset_id)
    all_job_detections = db.execute(
        select(DetectionResult.frame_index).where(DetectionResult.inference_job_id == job.inference_job_id, DetectionResult.organization_id == organization_id).distinct()
    ).scalars().all()
    observations = db.execute(select(TrackObservation).where(TrackObservation.track_id == track.id).order_by(TrackObservation.frame_index.asc())).scalars().all()
    points = [motion.ObservationPoint(frame_index=o.frame_index, timestamp_seconds=o.frame_timestamp_seconds, bbox=(o.bbox_x_min, o.bbox_y_min, o.bbox_x_max, o.bbox_y_max)) for o in observations]
    summary = motion.compute_motion_summary(points, width_px=media_asset.width_px, height_px=media_asset.height_px, job_sampled_frame_indices=list(all_job_detections))
    return {
        "unit_note": summary.unit_note,
        "observation_count": summary.observation_count,
        "duration_seconds": summary.duration_seconds,
        "total_path_length_px": summary.total_path_length_px,
        "net_displacement_px": summary.net_displacement_px,
        "bbox_area_px_first": summary.bbox_area_px_first,
        "bbox_area_px_last": summary.bbox_area_px_last,
        "bbox_area_change_ratio": summary.bbox_area_change_ratio,
        "missed_sampled_frame_count": summary.missed_sampled_frame_count,
        "missing_frame_indices": summary.missing_frame_indices,
        "fragmentation_count": summary.fragmentation_count,
        "steps": [
            {
                "from_frame_index": s.from_frame_index, "to_frame_index": s.to_frame_index, "elapsed_seconds": s.elapsed_seconds,
                "center_from_px": list(s.center_from_px), "center_to_px": list(s.center_to_px),
                "displacement_px": s.displacement_px, "direction_degrees": s.direction_degrees,
            }
            for s in summary.steps
        ],
    }
