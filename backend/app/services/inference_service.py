"""Inference pipeline orchestration. Submits
and runs one `InferenceJob` -- image detection (one frame) or bounded
video frame analysis (a sampled sequence of frames) -- against one
registered `ModelRecord`/adapter, persisting validated, postprocessed
`DetectionResult` rows.

Execution model, stated plainly: exactly like Phase 2's
`ingestion_service.run_ingestion()` and Phase 3's
`fusion_service.run_fusion_job()`, this function runs SYNCHRONOUSLY
inside the API request that calls it. There is still no background
worker/queue anywhere in this codebase. "Bounded concurrency" (Section
9) is enforced as a bound on the WORK one job can do (frame-sampling
caps, per-frame detection caps), not as a limit on how many jobs can run
at once -- a true worker pool with real concurrency limits is explicitly
deferred; see docs/ml/INFERENCE_PIPELINE.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.cv import postprocessing, storage, video_sampling
from app.cv.adapters.registry import get_adapter
from app.models.detection_result import DETECTION_SCHEMA_VERSION, DetectionResult
from app.models.inference_job import MAX_RETRIES, InferenceJob
from app.models.media_asset import MediaAsset
from app.models.model_record import ModelRecord
from app.services import model_registry_service

settings = get_settings()


class InferenceSubmissionError(ValueError):
    """A 400-worthy problem with the submission itself (bad media/model
    pairing, unknown ids) -- raised BEFORE any InferenceJob row is
    created, distinct from a job that was created and then failed
    during its own run."""


def _decode_image(content: bytes) -> np.ndarray:
    array = np.frombuffer(content, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise InferenceSubmissionError("stored media could not be decoded as an image")
    return image


def _resolve_submission(db: Session, organization_id: str, media_asset_id: str, model_record_id: str, job_type: str) -> tuple[MediaAsset, ModelRecord]:
    media_asset = db.execute(
        select(MediaAsset).where(MediaAsset.id == media_asset_id, MediaAsset.organization_id == organization_id)
    ).scalar_one_or_none()
    if media_asset is None:
        raise InferenceSubmissionError("media asset not found")
    if media_asset.status != "stored":
        raise InferenceSubmissionError(f"media asset is not usable (status={media_asset.status})")

    expected_media_type = "image" if job_type == "image_detection" else "video"
    if media_asset.media_type != expected_media_type:
        raise InferenceSubmissionError(f"job_type '{job_type}' requires a {expected_media_type} media asset, got '{media_asset.media_type}'")

    model_record = model_registry_service.get_cv_model(db, model_record_id, organization_id)
    if model_record is None:
        raise InferenceSubmissionError("model not found or is not a registered object-detection model")
    if model_record.status not in ("registered", "active"):
        raise InferenceSubmissionError(f"model '{model_record.name}' is not active (status={model_record.status})")
    if not model_registry_service.model_supports_media_type(model_record, media_asset.media_type):
        raise InferenceSubmissionError(f"model '{model_record.name}' does not support media_type '{media_asset.media_type}'")

    return media_asset, model_record


def _existing_job_for_idempotency_key(db: Session, organization_id: str, idempotency_key: Optional[str]) -> Optional[InferenceJob]:
    if not idempotency_key:
        return None
    stmt = select(InferenceJob).where(InferenceJob.organization_id == organization_id, InferenceJob.idempotency_key == idempotency_key)
    return db.execute(stmt).scalar_one_or_none()


def submit_inference_job(
    db: Session,
    *,
    organization_id: str,
    media_asset_id: str,
    model_record_id: str,
    job_type: str,
    triggered_by_user_id: Optional[str],
    confidence_threshold: Optional[float] = None,
    nms_iou_threshold: Optional[float] = None,
    frame_sample_interval_seconds: Optional[float] = None,
    max_frames: Optional[int] = None,
    idempotency_key: Optional[str] = None,
) -> InferenceJob:
    existing = _existing_job_for_idempotency_key(db, organization_id, idempotency_key)
    if existing is not None:
        return existing

    media_asset, model_record = _resolve_submission(db, organization_id, media_asset_id, model_record_id, job_type)

    parameters: dict = {
        "confidence_threshold": confidence_threshold if confidence_threshold is not None else settings.CV_DEFAULT_CONFIDENCE_THRESHOLD,
        "nms_iou_threshold": nms_iou_threshold if nms_iou_threshold is not None else settings.CV_DEFAULT_NMS_IOU_THRESHOLD,
    }
    if job_type == "video_frame_analysis":
        parameters["frame_sample_interval_seconds"] = (
            frame_sample_interval_seconds if frame_sample_interval_seconds is not None else settings.CV_VIDEO_FRAME_SAMPLE_INTERVAL_SECONDS
        )
        parameters["max_frames"] = min(max_frames or settings.CV_VIDEO_MAX_FRAMES_PER_JOB, settings.CV_VIDEO_MAX_FRAMES_PER_JOB)

    job = InferenceJob(
        organization_id=organization_id,
        media_asset_id=media_asset_id,
        model_record_id=model_record_id,
        job_type=job_type,
        status="pending",
        parameters=parameters,
        triggered_by_user_id=triggered_by_user_id,
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    _run_job(db, job, media_asset, model_record)
    return job


def _record_job_metrics(job: InferenceJob, outcome: str) -> None:
    """Phase 15: bounded-label job metrics (outcome and job_type only)."""
    from app.core.obs_metrics import registry

    registry.inc("inference_jobs_total", {"outcome": outcome})
    if job.started_at and job.finished_at:
        started = job.started_at if job.started_at.tzinfo else job.started_at.replace(tzinfo=timezone.utc)
        registry.observe("inference_job_duration_seconds", {"job_type": job.job_type}, (job.finished_at - started).total_seconds())


def _run_job(db: Session, job: InferenceJob, media_asset: MediaAsset, model_record: ModelRecord) -> None:
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()

    try:
        adapter = get_adapter(model_record.adapter_key)
        confidence_threshold = job.parameters.get("confidence_threshold")
        nms_iou_threshold = job.parameters.get("nms_iou_threshold")

        frames_processed = 0
        detections_created = 0

        if job.job_type == "image_detection":
            content = storage.read_bytes(media_asset.storage_key)
            image = _decode_image(content)
            height, width = image.shape[0], image.shape[1]
            raw = adapter.predict(image)
            validated, _rejected = postprocessing.postprocess(
                raw, frame_width=width, frame_height=height,
                confidence_threshold=confidence_threshold, nms_iou_threshold=nms_iou_threshold,
            )
            for det in validated:
                db.add(_build_detection_row(job, media_asset, model_record, det, frame_index=None, frame_timestamp_seconds=None))
                detections_created += 1
            frames_processed = 1
        else:
            path = storage.path_for(media_asset.storage_key)
            interval = job.parameters.get("frame_sample_interval_seconds", settings.CV_VIDEO_FRAME_SAMPLE_INTERVAL_SECONDS)
            max_frames = job.parameters.get("max_frames", settings.CV_VIDEO_MAX_FRAMES_PER_JOB)
            for frame_index, timestamp_seconds, frame in video_sampling.sample_frames(path, interval_seconds=interval, max_frames=max_frames):
                height, width = frame.shape[0], frame.shape[1]
                raw = adapter.predict(frame)
                validated, _rejected = postprocessing.postprocess(
                    raw, frame_width=width, frame_height=height,
                    confidence_threshold=confidence_threshold, nms_iou_threshold=nms_iou_threshold,
                )
                for det in validated:
                    db.add(_build_detection_row(job, media_asset, model_record, det, frame_index=frame_index, frame_timestamp_seconds=timestamp_seconds))
                    detections_created += 1
                frames_processed += 1

        job.frames_processed = frames_processed
        job.detections_created = detections_created
        job.status = "completed"
        job.finished_at = datetime.now(timezone.utc)
        _record_job_metrics(job, "completed")
    except Exception as exc:  # noqa: BLE001 -- a failed inference run is a real, reportable outcome, never a silent swallow
        db.rollback()
        job = db.merge(job)
        job.status = "failed"
        job.error_message = str(exc)[:2000]
        job.finished_at = datetime.now(timezone.utc)
        _record_job_metrics(job, "failed")

    db.add(job)
    db.commit()
    db.refresh(job)


def _build_detection_row(job: InferenceJob, media_asset: MediaAsset, model_record: ModelRecord, det, *, frame_index: Optional[int], frame_timestamp_seconds: Optional[float]) -> DetectionResult:
    return DetectionResult(
        organization_id=job.organization_id,
        inference_job_id=job.id,
        media_asset_id=media_asset.id,
        model_record_id=model_record.id,
        schema_version=DETECTION_SCHEMA_VERSION,
        frame_index=frame_index,
        frame_timestamp_seconds=frame_timestamp_seconds,
        class_label=det.class_label,
        confidence=det.confidence,
        bbox_x_min=det.bbox_x_min,
        bbox_y_min=det.bbox_y_min,
        bbox_x_max=det.bbox_x_max,
        bbox_y_max=det.bbox_y_max,
        raw_model_output={"adapter_key": model_record.adapter_key},
    )


def retry_job(db: Session, organization_id: str, job: InferenceJob, *, triggered_by_user_id: Optional[str]) -> InferenceJob:
    if job.status != "failed":
        raise ValueError(f"only a failed job can be retried (status={job.status})")
    if job.retry_count >= MAX_RETRIES:
        raise ValueError(f"job has already been retried {job.retry_count} times (limit {MAX_RETRIES})")

    media_asset = db.get(MediaAsset, job.media_asset_id)
    model_record = db.get(ModelRecord, job.model_record_id)
    if media_asset is None or model_record is None:
        raise ValueError("the media asset or model backing this job no longer exists")

    new_job = InferenceJob(
        organization_id=organization_id,
        media_asset_id=job.media_asset_id,
        model_record_id=job.model_record_id,
        job_type=job.job_type,
        status="pending",
        parameters=dict(job.parameters),
        triggered_by_user_id=triggered_by_user_id,
        retry_count=job.retry_count + 1,
        retried_from_job_id=job.id,
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    _run_job(db, new_job, media_asset, model_record)
    return new_job


def get_job(db: Session, organization_id: str, job_id: str) -> Optional[InferenceJob]:
    stmt = select(InferenceJob).where(InferenceJob.id == job_id, InferenceJob.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_jobs_query(organization_id: str, *, media_asset_id: Optional[str] = None, status: Optional[str] = None):
    stmt = select(InferenceJob).where(InferenceJob.organization_id == organization_id)
    if media_asset_id:
        stmt = stmt.where(InferenceJob.media_asset_id == media_asset_id)
    if status:
        stmt = stmt.where(InferenceJob.status == status)
    return stmt.order_by(InferenceJob.created_at.desc())


def list_detections_query(organization_id: str, job_id: str):
    return (
        select(DetectionResult)
        .where(DetectionResult.organization_id == organization_id, DetectionResult.inference_job_id == job_id)
        .order_by(DetectionResult.frame_index.asc().nullsfirst(), DetectionResult.confidence.desc())
    )
