from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.tenancy import reject_foreign_ids
from app.models.event import Event
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.investigation import (
    InvestigationCreateRequest,
    InvestigationResponse,
    InvestigationUpdateRequest,
)
from app.services import audit_service, investigation_service


router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.get("", response_model=Page[InvestigationResponse])
def list_investigations(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    priority: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=200),
    tag: Optional[str] = Query(default=None, max_length=50),
    assigned_user_id: Optional[str] = Query(default=None, max_length=36),
    reviewer_user_id: Optional[str] = Query(default=None, max_length=36),
    include_archived: bool = Query(default=False),
    sort_by: str = Query(default="created_at", pattern="^(created_at|updated_at|title|priority|status)$"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INVESTIGATION_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = investigation_service.list_investigations_query(
        current_user.organization_id, status=status_filter, user=current_user, priority=priority, q=q, tag=tag,
        assigned_user_id=assigned_user_id, reviewer_user_id=reviewer_user_id, include_archived=include_archived,
        sort_by=sort_by, sort_dir=sort_dir,
    )
    return paginate(db, stmt, page_params.page, page_params.page_size, InvestigationResponse)


@router.post("", response_model=InvestigationResponse, status_code=status.HTTP_201_CREATED)
def create_investigation(
    payload: InvestigationCreateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INVESTIGATION_MANAGE)),
    db: Session = Depends(get_db),
) -> InvestigationResponse:
    data = payload.model_dump()
    reject_foreign_ids(db, Event, current_user.organization_id, data.get("linked_event_ids") or [], "Event")
    if data.get("is_restricted") and not data.get("assigned_user_id"):
        data["assigned_user_id"] = current_user.id  # a restricted case must not lock out its creator
    investigation = investigation_service.create_investigation(
        db, organization_id=current_user.organization_id, actor_user_id=current_user.id, **data
    )
    audit_service.record(
        db, action="investigation.create", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="investigation", target_id=investigation.id, request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    db.refresh(investigation)
    return InvestigationResponse.model_validate(investigation)


@router.get("/{investigation_id}", response_model=InvestigationResponse)
def get_investigation(
    investigation_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INVESTIGATION_READ)),
    db: Session = Depends(get_db),
) -> InvestigationResponse:
    investigation = investigation_service.get_accessible(db, current_user, investigation_id)
    return InvestigationResponse.model_validate(investigation)


@router.patch("/{investigation_id}", response_model=InvestigationResponse)
def update_investigation(
    investigation_id: str,
    payload: InvestigationUpdateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INVESTIGATION_MANAGE)),
    db: Session = Depends(get_db),
) -> InvestigationResponse:
    investigation = investigation_service.get_accessible(db, current_user, investigation_id)
    request_id = getattr(request.state, "request_id", None)
    reject_foreign_ids(db, Event, current_user.organization_id, payload.model_dump(exclude_unset=True).get("linked_event_ids") or [], "Event")
    updated = investigation_service.update_investigation(
        db, investigation, actor_user_id=current_user.id, request_id=request_id, **payload.model_dump(exclude_unset=True)
    )
    audit_service.record(
        db, action="investigation.update", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="investigation", target_id=investigation.id, request_id=request_id,
        context_metadata=payload.model_dump(exclude_none=True),
    )
    db.commit()
    db.refresh(updated)
    return InvestigationResponse.model_validate(updated)
