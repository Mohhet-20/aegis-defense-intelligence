from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.config import get_settings
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.tracking import (
    SubmitTrackingJobRequest,
    TrackerConfigDefaultsResponse,
    TrackerConfigOption,
    TrackingJobResponse,
    TrackingJobSummaryResponse,
    TrackMotionResponse,
    TrackObservationResponse,
    TrackResponse,
)
from app.services import audit_service, tracking_service
from app.tracking.trackers.registry import available_tracker_keys, get_tracker_version

router = APIRouter(prefix="/tracking", tags=["tracking"])
settings = get_settings()


@router.get("/config", response_model=TrackerConfigDefaultsResponse)
def get_tracking_config(current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_READ))) -> TrackerConfigDefaultsResponse:
    """Section 10: "List supported tracker algorithms" / "Retrieve
    permitted configurations and defaults" -- sourced live from the
    actual code allow-list (app/tracking/trackers/registry.py), never a
    hard-coded duplicate list that could drift from what is really
    executable."""
    return TrackerConfigDefaultsResponse(
        available_trackers=[TrackerConfigOption(tracker_key=k, tracker_version=get_tracker_version(k), is_deterministic=True) for k in available_tracker_keys()],
        default_tracker_key=settings.TRACKING_DEFAULT_TRACKER_KEY,
        min_iou_threshold=settings.TRACKING_MIN_IOU_THRESHOLD,
        max_missed_frames=settings.TRACKING_MAX_MISSED_FRAMES,
        min_hits_to_confirm=settings.TRACKING_MIN_HITS_TO_CONFIRM,
        require_class_match=settings.TRACKING_REQUIRE_CLASS_MATCH,
        max_active_tracks_per_job=settings.TRACKING_MAX_ACTIVE_TRACKS_PER_JOB,
    )


@router.post("/jobs", response_model=TrackingJobResponse, status_code=status.HTTP_201_CREATED)
def submit_tracking_job(
    payload: SubmitTrackingJobRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_RUN)),
    db: Session = Depends(get_db),
) -> TrackingJobResponse:
    try:
        job = tracking_service.submit_tracking_job(
            db, organization_id=current_user.organization_id, inference_job_id=payload.inference_job_id,
            triggered_by_user_id=current_user.id, tracker_key=payload.tracker_key,
            min_iou_threshold=payload.min_iou_threshold, max_missed_frames=payload.max_missed_frames,
            min_hits_to_confirm=payload.min_hits_to_confirm, require_class_match=payload.require_class_match,
            idempotency_key=payload.idempotency_key,
        )
    except tracking_service.TrackingSubmissionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    audit_service.record(
        db, action="tracking.submit", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="tracking_job", target_id=job.id, outcome="success" if job.status == "completed" else "failure",
        request_id=getattr(request.state, "request_id", None),
        context_metadata={"status": job.status, "tracks_created": job.tracks_created, "tracker_key": job.tracker_key},
    )
    db.commit()
    return TrackingJobResponse.model_validate(job)


@router.get("/jobs", response_model=Page[TrackingJobResponse])
def list_tracking_jobs(
    media_asset_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = tracking_service.list_jobs_query(current_user.organization_id, media_asset_id=media_asset_id, status=status_filter)
    return paginate(db, stmt, page_params.page, page_params.page_size, TrackingJobResponse)


@router.get("/jobs/{job_id}", response_model=TrackingJobResponse)
def get_tracking_job(
    job_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_READ)),
    db: Session = Depends(get_db),
) -> TrackingJobResponse:
    job = tracking_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracking job not found")
    return TrackingJobResponse.model_validate(job)


@router.post("/jobs/{job_id}/retry", response_model=TrackingJobResponse, status_code=status.HTTP_201_CREATED)
def retry_tracking_job(
    job_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_RUN)),
    db: Session = Depends(get_db),
) -> TrackingJobResponse:
    job = tracking_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracking job not found")
    try:
        new_job = tracking_service.retry_job(db, current_user.organization_id, job, triggered_by_user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    audit_service.record(
        db, action="tracking.retry", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="tracking_job", target_id=new_job.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"retried_job_id": job.id, "status": new_job.status},
    )
    db.commit()
    return TrackingJobResponse.model_validate(new_job)


@router.get("/jobs/{job_id}/summary", response_model=TrackingJobSummaryResponse)
def get_tracking_job_summary(
    job_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_READ)),
    db: Session = Depends(get_db),
) -> TrackingJobSummaryResponse:
    job = tracking_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracking job not found")
    return TrackingJobSummaryResponse(**tracking_service.get_job_summary(db, current_user.organization_id, job))


@router.get("/jobs/{job_id}/tracks", response_model=Page[TrackResponse])
def list_job_tracks(
    job_id: str,
    state: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_READ)),
    db: Session = Depends(get_db),
) -> Page:
    job = tracking_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracking job not found")
    stmt = tracking_service.list_tracks_query(current_user.organization_id, job_id, state=state)
    return paginate(db, stmt, page_params.page, page_params.page_size, TrackResponse)


@router.get("/jobs/{job_id}/frames/{frame_index}/tracks", response_model=list[TrackObservationResponse])
def get_frame_tracks(
    job_id: str,
    frame_index: int,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_READ)),
    db: Session = Depends(get_db),
) -> list[TrackObservationResponse]:
    job = tracking_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracking job not found")
    observations = tracking_service.list_frame_tracks(db, current_user.organization_id, job_id, frame_index)
    return [TrackObservationResponse.model_validate(o) for o in observations]


@router.get("/tracks/{track_id}", response_model=TrackResponse)
def get_track(
    track_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_READ)),
    db: Session = Depends(get_db),
) -> TrackResponse:
    track = tracking_service.get_track(db, current_user.organization_id, track_id)
    if track is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")
    return TrackResponse.model_validate(track)


@router.get("/tracks/{track_id}/observations", response_model=Page[TrackObservationResponse])
def list_track_observations(
    track_id: str,
    frame_min: Optional[int] = Query(default=None),
    frame_max: Optional[int] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_READ)),
    db: Session = Depends(get_db),
) -> Page:
    track = tracking_service.get_track(db, current_user.organization_id, track_id)
    if track is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")
    stmt = tracking_service.list_observations_query(current_user.organization_id, track_id, frame_min=frame_min, frame_max=frame_max)
    return paginate(db, stmt, page_params.page, page_params.page_size, TrackObservationResponse)


@router.get("/tracks/{track_id}/motion", response_model=TrackMotionResponse)
def get_track_motion(
    track_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_READ)),
    db: Session = Depends(get_db),
) -> TrackMotionResponse:
    track = tracking_service.get_track(db, current_user.organization_id, track_id)
    if track is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")
    return TrackMotionResponse(**tracking_service.get_track_motion(db, current_user.organization_id, track))
