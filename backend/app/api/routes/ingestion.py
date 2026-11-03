from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.config import get_settings
from app.core.uploads import read_bounded
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.ingestion import IngestionJobResponse
from app.schemas.raw_record import RawRecordResponse
from app.services import audit_service, ingestion_service, source_service

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/jobs", response_model=IngestionJobResponse, status_code=status.HTTP_201_CREATED)
async def create_ingestion_job(
    request: Request,
    source_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INGESTION_RUN)),
    db: Session = Depends(get_db),
) -> IngestionJobResponse:
    source = source_service.get_source(db, current_user.organization_id, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data source not found")
    if not source.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"source '{source.name}' is disabled and cannot accept new ingestion jobs")

    content = await read_bounded(file, get_settings().MAX_REQUEST_BODY_BYTES)
    job = ingestion_service.run_ingestion(
        db,
        organization_id=current_user.organization_id,
        source_id=source_id,
        filename=file.filename or "upload",
        content=content,
        created_by_user_id=current_user.id,
        data_origin="user_upload",
        correlation_id=getattr(request.state, "request_id", None),
    )
    audit_service.record(
        db, action="ingestion.run", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="ingestion_job", target_id=job.id, outcome="success" if job.status != "failed" else "failure",
        request_id=getattr(request.state, "request_id", None),
        context_metadata={
            "accepted": job.accepted_count, "rejected": job.rejected_count,
            "duplicate": job.duplicate_count, "status": job.status,
        },
    )
    db.commit()
    return IngestionJobResponse.model_validate(job)


@router.get("/jobs", response_model=Page[IngestionJobResponse])
def list_ingestion_jobs(
    source_id: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INGESTION_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = ingestion_service.list_jobs_query(current_user.organization_id, source_id=source_id)
    return paginate(db, stmt, page_params.page, page_params.page_size, IngestionJobResponse)


@router.get("/jobs/{job_id}", response_model=IngestionJobResponse)
def get_ingestion_job(
    job_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INGESTION_READ)),
    db: Session = Depends(get_db),
) -> IngestionJobResponse:
    job = ingestion_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion job not found")
    return IngestionJobResponse.model_validate(job)


@router.get("/jobs/{job_id}/raw-records", response_model=Page[RawRecordResponse])
def list_job_raw_records(
    job_id: str,
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.RAW_RECORD_READ)),
    db: Session = Depends(get_db),
) -> Page:
    """Gated separately from INGESTION_READ ("access
    controls on provenance/raw data") -- a raw record's payload may
    carry source-side detail a normalized Event intentionally drops."""
    job = ingestion_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion job not found")
    stmt = ingestion_service.list_raw_records_for_job_query(current_user.organization_id, job_id)
    return paginate(db, stmt, page_params.page, page_params.page_size, RawRecordResponse)


@router.post("/jobs/{job_id}/retry", response_model=IngestionJobResponse, status_code=status.HTTP_201_CREATED)
def retry_ingestion_job(
    job_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INGESTION_RUN)),
    db: Session = Depends(get_db),
) -> IngestionJobResponse:
    job = ingestion_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion job not found")
    try:
        new_job = ingestion_service.retry_job(
            db, current_user.organization_id, job, created_by_user_id=current_user.id,
            correlation_id=getattr(request.state, "request_id", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    audit_service.record(
        db, action="ingestion.retry", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="ingestion_job", target_id=new_job.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"retried_job_id": job.id, "status": new_job.status},
    )
    db.commit()
    return IngestionJobResponse.model_validate(new_job)
