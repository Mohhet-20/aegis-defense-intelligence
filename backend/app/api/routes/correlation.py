from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.correlation import (
    CorrelationReviewRequest,
    EventCorrelationResponse,
    RecomputeCorrelationsRequest,
    RecomputeCorrelationsResponse,
)
from app.services import audit_service, correlation_service

router = APIRouter(prefix="/correlation", tags=["correlation"])


@router.get("", response_model=Page[EventCorrelationResponse])
def list_correlations(
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.CORRELATION_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = correlation_service.list_correlations_query(current_user.organization_id)
    return paginate(db, stmt, page_params.page, page_params.page_size, EventCorrelationResponse)


@router.get("/{correlation_id}", response_model=EventCorrelationResponse)
def get_correlation(
    correlation_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.CORRELATION_READ)),
    db: Session = Depends(get_db),
) -> EventCorrelationResponse:
    correlation = correlation_service.get_correlation(db, current_user.organization_id, correlation_id)
    if correlation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Correlation not found")
    return EventCorrelationResponse.model_validate(correlation)


@router.post("/recompute", response_model=RecomputeCorrelationsResponse)
def recompute_correlations(
    payload: RecomputeCorrelationsRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.CORRELATION_MANAGE)),
    db: Session = Depends(get_db),
) -> RecomputeCorrelationsResponse:
    """The ONE explicit, authorized, auditable way correlation
    candidates are produced -- there is no background job
    silently creating these."""
    kwargs = {}
    if payload.time_window_seconds is not None:
        kwargs["time_window_seconds"] = payload.time_window_seconds
    if payload.spatial_threshold_meters is not None:
        kwargs["spatial_threshold_meters"] = payload.spatial_threshold_meters

    result = correlation_service.recompute(db, current_user.organization_id, **kwargs)
    audit_service.record(
        db, action="correlation.recompute", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="event_correlation_batch", target_id=result["batch_id"], request_id=getattr(request.state, "request_id", None),
        context_metadata=result,
    )
    db.commit()
    return RecomputeCorrelationsResponse(**result)


@router.post("/{correlation_id}/review", response_model=EventCorrelationResponse)
def review_correlation(
    correlation_id: str,
    payload: CorrelationReviewRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.CORRELATION_MANAGE)),
    db: Session = Depends(get_db),
) -> EventCorrelationResponse:
    correlation = correlation_service.get_correlation(db, current_user.organization_id, correlation_id)
    if correlation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Correlation not found")
    updated = correlation_service.review_correlation(
        db, correlation, review_status=payload.review_status, reviewed_by_user_id=current_user.id
    )
    audit_service.record(
        db, action="correlation.review", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="event_correlation", target_id=correlation.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"review_status": payload.review_status},
    )
    db.commit()
    return EventCorrelationResponse.model_validate(updated)
