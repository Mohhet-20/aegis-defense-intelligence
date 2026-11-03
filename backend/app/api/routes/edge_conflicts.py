"""Conflict review queue API -- JWT-authenticated.
List/inspect/resolve, fully audited. See
app/services/edge_conflict_service.py for the resolution rules (never
unconditional last-write-wins)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.edge_sync import SyncConflictResolveRequest, SyncConflictResponse
from app.services import edge_conflict_service

router = APIRouter(prefix="/edge/conflicts", tags=["edge-conflicts"])


def _get_conflict_or_404(db: Session, organization_id: str, conflict_id: str):
    conflict = edge_conflict_service.get_conflict(db, organization_id, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conflict not found")
    return conflict


@router.get("", response_model=Page[SyncConflictResponse])
def list_conflicts(
    resolution_status: Optional[str] = Query(default=None),
    device_id: Optional[str] = Query(default=None),
    record_type: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EDGE_CONFLICT_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = edge_conflict_service.list_conflicts_query(
        current_user.organization_id, resolution_status=resolution_status, device_id=device_id, record_type=record_type,
    )
    return paginate(db, stmt, page_params.page, page_params.page_size, SyncConflictResponse)


@router.get("/{conflict_id}", response_model=SyncConflictResponse)
def get_conflict(
    conflict_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EDGE_CONFLICT_READ)),
    db: Session = Depends(get_db),
) -> SyncConflictResponse:
    conflict = _get_conflict_or_404(db, current_user.organization_id, conflict_id)
    return SyncConflictResponse.model_validate(conflict)


@router.post("/{conflict_id}/resolve", response_model=SyncConflictResponse)
def resolve_conflict(
    conflict_id: str,
    payload: SyncConflictResolveRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EDGE_CONFLICT_MANAGE)),
    db: Session = Depends(get_db),
) -> SyncConflictResponse:
    conflict = _get_conflict_or_404(db, current_user.organization_id, conflict_id)
    try:
        conflict = edge_conflict_service.resolve_conflict(
            db, conflict, resolution_strategy=payload.resolution_strategy, actor_user_id=current_user.id, resolution_note=payload.resolution_note,
        )
    except (edge_conflict_service.InvalidConflictResolutionError, edge_conflict_service.ConflictAlreadyResolvedError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SyncConflictResponse.model_validate(conflict)
