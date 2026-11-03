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
from app.schemas.sensor_ingestion import SensorIngestionJobResponse, SensorRawRecordResponse, SyntheticSensorBatchRequest
from app.services import audit_service, sensor_ingestion_service, source_service

router = APIRouter(prefix="/sensor-ingestion", tags=["sensor-ingestion"])


@router.post("/batches", response_model=SensorIngestionJobResponse, status_code=status.HTTP_201_CREATED)
async def submit_sensor_batch(
    request: Request,
    source_id: str = Form(...),
    format: str = Form(...),
    file: UploadFile = File(...),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVATION_INGEST)),
    db: Session = Depends(get_db),
) -> SensorIngestionJobResponse:
    source = source_service.get_source(db, current_user.organization_id, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data source not found")
    if not source.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"source '{source.name}' is disabled and cannot accept new ingestion jobs")
    if format not in ("json", "csv"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="format must be 'json' or 'csv'")

    content = await read_bounded(file, get_settings().MAX_REQUEST_BODY_BYTES)
    try:
        job = sensor_ingestion_service.submit_file_batch(
            db, organization_id=current_user.organization_id, source_id=source_id, fmt=format, content=content,
            created_by_user_id=current_user.id, correlation_id=getattr(request.state, "request_id", None),
        )
    except sensor_ingestion_service.BatchTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except sensor_ingestion_service.UnsupportedBatchFormatError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_service.record(
        db, action="sensor_ingestion.run", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="ingestion_job", target_id=job.id, outcome="success" if job.status != "failed" else "failure",
        request_id=getattr(request.state, "request_id", None),
        context_metadata={"accepted": job.accepted_count, "rejected": job.rejected_count, "duplicate": job.duplicate_count, "status": job.status},
    )
    db.commit()
    return SensorIngestionJobResponse.model_validate(job)


@router.post("/synthetic-batches", response_model=SensorIngestionJobResponse, status_code=status.HTTP_201_CREATED)
def submit_synthetic_sensor_batch(
    payload: SyntheticSensorBatchRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVATION_INGEST)),
    db: Session = Depends(get_db),
) -> SensorIngestionJobResponse:
    source = source_service.get_source(db, current_user.organization_id, payload.source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data source not found")

    config = payload.model_dump(exclude={"source_id"})
    if config.get("start_at") is not None:
        config["start_at"] = config["start_at"].isoformat()
    job = sensor_ingestion_service.submit_synthetic_batch(
        db, organization_id=current_user.organization_id, source_id=payload.source_id, config=config,
        created_by_user_id=current_user.id, correlation_id=getattr(request.state, "request_id", None),
    )
    audit_service.record(
        db, action="sensor_ingestion.run", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="ingestion_job", target_id=job.id, outcome="success" if job.status != "failed" else "failure",
        request_id=getattr(request.state, "request_id", None),
        context_metadata={"accepted": job.accepted_count, "rejected": job.rejected_count, "duplicate": job.duplicate_count, "status": job.status},
    )
    db.commit()
    return SensorIngestionJobResponse.model_validate(job)


@router.get("/batches", response_model=Page[SensorIngestionJobResponse])
def list_sensor_batches(
    source_id: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVATION_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = sensor_ingestion_service.list_jobs_query(current_user.organization_id, source_id=source_id)
    return paginate(db, stmt, page_params.page, page_params.page_size, SensorIngestionJobResponse)


@router.get("/batches/{job_id}", response_model=SensorIngestionJobResponse)
def get_sensor_batch(
    job_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVATION_READ)),
    db: Session = Depends(get_db),
) -> SensorIngestionJobResponse:
    job = sensor_ingestion_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sensor ingestion job not found")
    return SensorIngestionJobResponse.model_validate(job)


@router.get("/batches/{job_id}/records", response_model=Page[SensorRawRecordResponse])
def list_sensor_batch_records(
    job_id: str,
    validation_status: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.RAW_RECORD_READ)),
    db: Session = Depends(get_db),
) -> Page:
    job = sensor_ingestion_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sensor ingestion job not found")
    stmt = sensor_ingestion_service.list_raw_records_for_job_query(current_user.organization_id, job_id, validation_status=validation_status)
    return paginate(db, stmt, page_params.page, page_params.page_size, SensorRawRecordResponse)


@router.post("/batches/{job_id}/retry", response_model=SensorIngestionJobResponse, status_code=status.HTTP_201_CREATED)
def retry_sensor_batch(
    job_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVATION_INGEST)),
    db: Session = Depends(get_db),
) -> SensorIngestionJobResponse:
    job = sensor_ingestion_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sensor ingestion job not found")
    if job.status not in ("failed", "completed_with_errors"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="only a failed job (or one completed with errors) can be retried")
    try:
        new_job = sensor_ingestion_service.retry_job(
            db, current_user.organization_id, job, created_by_user_id=current_user.id,
            correlation_id=getattr(request.state, "request_id", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_service.record(
        db, action="sensor_ingestion.retry", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="ingestion_job", target_id=new_job.id, context_metadata={"retried_from_job_id": job.id},
    )
    db.commit()
    return SensorIngestionJobResponse.model_validate(new_job)
