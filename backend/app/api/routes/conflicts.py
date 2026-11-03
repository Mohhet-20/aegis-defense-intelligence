from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.conflict import ConflictResolveRequest, ConflictResponse, DetectConflictsRequest, DetectConflictsResponse
from app.schemas.relationship import ReviewHistoryEntry
from app.services import audit_service, conflict_service

router = APIRouter(prefix="/conflicts", tags=["conflicts"])


@router.get("", response_model=Page[ConflictResponse])
def list_conflicts(
    review_status: Optional[str] = Query(default=None),
    event_id: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.CONFLICT_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = conflict_service.list_conflicts_query(current_user.organization_id, review_status=review_status, event_id=event_id)
    return paginate(db, stmt, page_params.page, page_params.page_size, ConflictResponse)


@router.post("/detect", response_model=DetectConflictsResponse)
def detect_conflicts(
    payload: DetectConflictsRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.CONFLICT_MANAGE)),
    db: Session = Depends(get_db),
) -> DetectConflictsResponse:
    """A standalone entry point for conflict detection, independent of
    `/fusion/run` -- useful to re-scan existing correlations (e.g. after
    changing `spatial_conflict_threshold_meters`) without also
    recomputing correlations."""
    result = conflict_service.detect_conflicts(
        db, current_user.organization_id,
        correlation_batch_id=payload.correlation_batch_id,
        spatial_conflict_threshold_meters=payload.spatial_conflict_threshold_meters,
    )
    audit_service.record(
        db, action="conflict.detect", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="conflict_batch", target_id=result["batch_id"], request_id=getattr(request.state, "request_id", None),
        context_metadata=result,
    )
    db.commit()
    return DetectConflictsResponse(**result)


@router.get("/{conflict_id}", response_model=ConflictResponse)
def get_conflict(
    conflict_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.CONFLICT_READ)),
    db: Session = Depends(get_db),
) -> ConflictResponse:
    conflict = conflict_service.get_conflict(db, current_user.organization_id, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conflict not found")
    return ConflictResponse.model_validate(conflict)


@router.post("/{conflict_id}/resolve", response_model=ConflictResponse)
def resolve_conflict(
    conflict_id: str,
    payload: ConflictResolveRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.CONFLICT_MANAGE)),
    db: Session = Depends(get_db),
) -> ConflictResponse:
    conflict = conflict_service.get_conflict(db, current_user.organization_id, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conflict not found")
    try:
        updated = conflict_service.resolve_conflict(
            db, conflict, review_status=payload.review_status, resolved_by_user_id=current_user.id, resolution_note=payload.resolution_note,
            request_id=getattr(request.state, "request_id", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ConflictResponse.model_validate(updated)


@router.get("/{conflict_id}/history", response_model=list[ReviewHistoryEntry])
def get_conflict_history(
    conflict_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.CONFLICT_READ)),
    db: Session = Depends(get_db),
) -> list[ReviewHistoryEntry]:
    conflict = conflict_service.get_conflict(db, current_user.organization_id, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conflict not found")
    history = conflict_service.get_review_history(db, current_user.organization_id, conflict_id)
    return [ReviewHistoryEntry.model_validate(h) for h in history]
