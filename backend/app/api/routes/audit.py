from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.models.audit import AuditRecord
from app.schemas.audit import AuditRecordResponse
from app.schemas.common import Page, PageParams
from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditRecordResponse])
def list_audit_records(
    actor_user_id: Optional[str] = Query(default=None, max_length=36),
    action: Optional[str] = Query(default=None, max_length=100),
    action_prefix: Optional[str] = Query(default=None, max_length=100),
    target_type: Optional[str] = Query(default=None, max_length=50),
    target_id: Optional[str] = Query(default=None, max_length=36),
    outcome: Optional[str] = Query(default=None, pattern="^(success|failure|denied)$"),
    request_id: Optional[str] = Query(default=None, max_length=64),
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.AUDIT_READ)),
    db: Session = Depends(get_db),
) -> Page:
    """Restricted to AUDIT_READ (administrator by default). Strictly scoped
    to THIS organization: system-level rows (organization_id NULL) and other
    organizations' rows are never returned (Phase 14 fixed a defect where
    NULL-org rows were visible to every organization's administrator). The
    API is read-only -- there is no update or delete route for audit rows."""
    stmt = audit_service.build_query(
        current_user.organization_id, actor_user_id=actor_user_id, action=action, action_prefix=action_prefix,
        target_type=target_type, target_id=target_id, outcome=outcome, request_id=request_id,
        created_from=created_from, created_to=created_to,
    )
    return paginate(db, stmt, page_params.page, page_params.page_size, AuditRecordResponse)


@router.get("/actions", response_model=list[str])
def list_audit_actions(
    current_user: AuthenticatedUser = Depends(require_permission(Permission.AUDIT_READ)),
    db: Session = Depends(get_db),
) -> list[str]:
    return audit_service.distinct_actions(db, current_user.organization_id)


@router.get("/{audit_id}", response_model=AuditRecordResponse)
def get_audit_record(
    audit_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.AUDIT_READ)),
    db: Session = Depends(get_db),
) -> AuditRecordResponse:
    row = db.execute(
        select(AuditRecord).where(AuditRecord.id == audit_id, AuditRecord.organization_id == current_user.organization_id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit record not found")
    return AuditRecordResponse.model_validate(row)
