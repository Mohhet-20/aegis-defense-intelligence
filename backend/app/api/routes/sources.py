from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.data_source import (
    ConfigValidationResponse,
    ConnectivityCheckResponse,
    DataSourceCreateRequest,
    DataSourceResponse,
    DataSourceUpdateRequest,
    ReliabilityWeightRequest,
)
from app.schemas.ingestion import IngestionJobResponse
from app.services import audit_service, ingestion_service, source_service

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=Page[DataSourceResponse])
def list_sources(
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SOURCE_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = source_service.list_sources_query(current_user.organization_id)
    return paginate(db, stmt, page_params.page, page_params.page_size, DataSourceResponse)


@router.post("", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
def create_source(
    payload: DataSourceCreateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SOURCE_MANAGE)),
    db: Session = Depends(get_db),
) -> DataSourceResponse:
    source = source_service.create_source(db, organization_id=current_user.organization_id, **payload.model_dump())
    audit_service.record(
        db, action="source.create", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="data_source", target_id=source.id, request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return DataSourceResponse.model_validate(source)


def _get_or_404(db: Session, organization_id: str, source_id: str):
    source = source_service.get_source(db, organization_id, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data source not found")
    return source


@router.get("/{source_id}", response_model=DataSourceResponse)
def get_source(
    source_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SOURCE_READ)),
    db: Session = Depends(get_db),
) -> DataSourceResponse:
    return DataSourceResponse.model_validate(_get_or_404(db, current_user.organization_id, source_id))


@router.patch("/{source_id}", response_model=DataSourceResponse)
def update_source(
    source_id: str,
    payload: DataSourceUpdateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SOURCE_MANAGE)),
    db: Session = Depends(get_db),
) -> DataSourceResponse:
    source = _get_or_404(db, current_user.organization_id, source_id)
    updated = source_service.update_source(db, source, **payload.model_dump(exclude_unset=True))
    audit_service.record(
        db, action="source.update", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="data_source", target_id=source.id, request_id=getattr(request.state, "request_id", None),
        context_metadata=payload.model_dump(exclude_none=True),
    )
    db.commit()
    return DataSourceResponse.model_validate(updated)


@router.post("/{source_id}/enable", response_model=DataSourceResponse)
def enable_source(
    source_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SOURCE_MANAGE)),
    db: Session = Depends(get_db),
) -> DataSourceResponse:
    source = _get_or_404(db, current_user.organization_id, source_id)
    updated = source_service.enable_source(db, source)
    audit_service.record(
        db, action="source.enable", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="data_source", target_id=source.id, request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return DataSourceResponse.model_validate(updated)


@router.post("/{source_id}/disable", response_model=DataSourceResponse)
def disable_source(
    source_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SOURCE_MANAGE)),
    db: Session = Depends(get_db),
) -> DataSourceResponse:
    source = _get_or_404(db, current_user.organization_id, source_id)
    updated = source_service.disable_source(db, source)
    audit_service.record(
        db, action="source.disable", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="data_source", target_id=source.id, request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return DataSourceResponse.model_validate(updated)


@router.put("/{source_id}/reliability", response_model=DataSourceResponse)
def set_reliability(
    source_id: str,
    payload: ReliabilityWeightRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SOURCE_MANAGE)),
    db: Session = Depends(get_db),
) -> DataSourceResponse:
    source = _get_or_404(db, current_user.organization_id, source_id)
    try:
        updated = source_service.set_reliability_weight(db, source, weight=payload.weight, reason=payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    audit_service.record(
        db, action="source.reliability_change", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="data_source", target_id=source.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"new_weight": payload.weight, "reason": payload.reason},
    )
    db.commit()
    return DataSourceResponse.model_validate(updated)


@router.post("/{source_id}/validate-config", response_model=ConfigValidationResponse)
def validate_config(
    source_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SOURCE_MANAGE)),
    db: Session = Depends(get_db),
) -> ConfigValidationResponse:
    source = _get_or_404(db, current_user.organization_id, source_id)
    errors = source_service.validate_configuration(source)
    return ConfigValidationResponse(valid=not errors, errors=errors)


@router.post("/{source_id}/check-connectivity", response_model=ConnectivityCheckResponse)
def check_connectivity(
    source_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SOURCE_MANAGE)),
    db: Session = Depends(get_db),
) -> ConnectivityCheckResponse:
    source = _get_or_404(db, current_user.organization_id, source_id)
    from app.connectors.registry import is_connector_driven

    applicable = is_connector_driven(source.source_type)
    ok, detail = source_service.check_connectivity(source)
    source_service.record_connectivity_result(db, source, ok=ok, error_category="connection" if not ok else None)
    return ConnectivityCheckResponse(ok=ok, detail=detail, applicable=applicable)


@router.post("/{source_id}/run", response_model=IngestionJobResponse, status_code=status.HTTP_201_CREATED)
def run_source(
    source_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INGESTION_RUN)),
    db: Session = Depends(get_db),
) -> IngestionJobResponse:
    """Explicitly fetches one batch from a connector-driven source
    (http_api, synthetic_demo) -- never available for a file-upload-
    only source, which has nothing to "run" (it only ever receives an
    uploaded file via POST /ingestion/jobs)."""
    source = _get_or_404(db, current_user.organization_id, source_id)
    try:
        job = ingestion_service.run_connector_source(
            db,
            organization_id=current_user.organization_id,
            source=source,
            created_by_user_id=current_user.id,
            trigger_type="api",
            correlation_id=getattr(request.state, "request_id", None),
        )
    except ingestion_service.NoConnectorForSourceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ingestion_service.SourceDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    audit_service.record(
        db, action="source.run", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="ingestion_job", target_id=job.id, outcome="success" if job.status != "failed" else "failure",
        request_id=getattr(request.state, "request_id", None),
        context_metadata={"accepted": job.accepted_count, "rejected": job.rejected_count, "duplicate": job.duplicate_count, "status": job.status},
    )
    db.commit()
    return IngestionJobResponse.model_validate(job)
