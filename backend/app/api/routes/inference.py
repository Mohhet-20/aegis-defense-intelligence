from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.detection import DetectionResultResponse
from app.schemas.inference import InferenceJobResponse, SubmitInferenceJobRequest
from app.services import audit_service, inference_service

router = APIRouter(prefix="/inference", tags=["inference"])


@router.post("/jobs", response_model=InferenceJobResponse, status_code=status.HTTP_201_CREATED)
def submit_inference_job(
    payload: SubmitInferenceJobRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INFERENCE_RUN)),
    db: Session = Depends(get_db),
) -> InferenceJobResponse:
    try:
        job = inference_service.submit_inference_job(
            db, organization_id=current_user.organization_id,
            media_asset_id=payload.media_asset_id, model_record_id=payload.model_record_id,
            job_type=payload.job_type, triggered_by_user_id=current_user.id,
            confidence_threshold=payload.confidence_threshold, nms_iou_threshold=payload.nms_iou_threshold,
            frame_sample_interval_seconds=payload.frame_sample_interval_seconds, max_frames=payload.max_frames,
            idempotency_key=payload.idempotency_key,
        )
    except inference_service.InferenceSubmissionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    audit_service.record(
        db, action="inference.submit", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="inference_job", target_id=job.id, outcome="success" if job.status == "completed" else "failure",
        request_id=getattr(request.state, "request_id", None),
        context_metadata={"status": job.status, "job_type": job.job_type, "detections_created": job.detections_created},
    )
    db.commit()
    return InferenceJobResponse.model_validate(job)


@router.get("/jobs", response_model=Page[InferenceJobResponse])
def list_inference_jobs(
    media_asset_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INFERENCE_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = inference_service.list_jobs_query(current_user.organization_id, media_asset_id=media_asset_id, status=status_filter)
    return paginate(db, stmt, page_params.page, page_params.page_size, InferenceJobResponse)


@router.get("/jobs/{job_id}", response_model=InferenceJobResponse)
def get_inference_job(
    job_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INFERENCE_READ)),
    db: Session = Depends(get_db),
) -> InferenceJobResponse:
    job = inference_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inference job not found")
    return InferenceJobResponse.model_validate(job)


@router.get("/jobs/{job_id}/detections", response_model=Page[DetectionResultResponse])
def list_job_detections(
    job_id: str,
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INFERENCE_READ)),
    db: Session = Depends(get_db),
) -> Page:
    job = inference_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inference job not found")
    stmt = inference_service.list_detections_query(current_user.organization_id, job_id)
    return paginate(db, stmt, page_params.page, page_params.page_size, DetectionResultResponse)


@router.post("/jobs/{job_id}/retry", response_model=InferenceJobResponse, status_code=status.HTTP_201_CREATED)
def retry_inference_job(
    job_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INFERENCE_RUN)),
    db: Session = Depends(get_db),
) -> InferenceJobResponse:
    job = inference_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inference job not found")
    try:
        new_job = inference_service.retry_job(db, current_user.organization_id, job, triggered_by_user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    audit_service.record(
        db, action="inference.retry", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="inference_job", target_id=new_job.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"retried_job_id": job.id, "status": new_job.status},
    )
    db.commit()
    return InferenceJobResponse.model_validate(new_job)
