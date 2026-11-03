from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.tenancy import require_in_org
from app.models.event import Event
from app.models.observation import Observation
from app.models.raw_record import RawRecord
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.evidence import EvidenceCreateRequest, EvidenceResponse, EvidenceUpdateRequest
from app.services import audit_service, evidence_service

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("", response_model=Page[EvidenceResponse])
def list_evidence(
    evidence_type: Optional[str] = Query(default=None),
    event_id: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EVIDENCE_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = evidence_service.list_evidence_query(current_user.organization_id, evidence_type=evidence_type, event_id=event_id)
    return paginate(db, stmt, page_params.page, page_params.page_size, EvidenceResponse)


@router.post("", response_model=EvidenceResponse, status_code=status.HTTP_201_CREATED)
def create_evidence(
    payload: EvidenceCreateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EVIDENCE_MANAGE)),
    db: Session = Depends(get_db),
) -> EvidenceResponse:
    org = current_user.organization_id
    require_in_org(db, Event, org, payload.event_id, "Event")
    require_in_org(db, RawRecord, org, payload.raw_record_id, "Raw record")
    require_in_org(db, Observation, org, payload.observation_id, "Observation")
    try:
        evidence = evidence_service.create_evidence(
            db, organization_id=current_user.organization_id, created_by_user_id=current_user.id, **payload.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    audit_service.record(
        db, action="evidence.create", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="evidence", target_id=evidence.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"evidence_type": evidence.evidence_type},
    )
    db.commit()
    return EvidenceResponse.model_validate(evidence)


def _get_or_404(db: Session, organization_id: str, evidence_id: str):
    evidence = evidence_service.get_evidence(db, organization_id, evidence_id)
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence item not found")
    return evidence


@router.get("/{evidence_id}", response_model=EvidenceResponse)
def get_evidence(
    evidence_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EVIDENCE_READ)),
    db: Session = Depends(get_db),
) -> EvidenceResponse:
    return EvidenceResponse.model_validate(_get_or_404(db, current_user.organization_id, evidence_id))


@router.patch("/{evidence_id}", response_model=EvidenceResponse)
def update_evidence(
    evidence_id: str,
    payload: EvidenceUpdateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EVIDENCE_MANAGE)),
    db: Session = Depends(get_db),
) -> EvidenceResponse:
    evidence = _get_or_404(db, current_user.organization_id, evidence_id)
    try:
        updated = evidence_service.update_evidence_content(db, evidence, **payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    audit_service.record(
        db, action="evidence.update", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="evidence", target_id=evidence.id, request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return EvidenceResponse.model_validate(updated)
