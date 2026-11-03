from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.relationship import (
    EvidenceRelationshipResponse,
    RelationshipCreateRequest,
    RelationshipReverseRequest,
    RelationshipReviewRequest,
    ReviewHistoryEntry,
)
from app.services import audit_service, relationship_service
from app.services.relationship_service import InvalidReferenceError

router = APIRouter(prefix="/relationships", tags=["relationships"])


@router.get("", response_model=Page[EvidenceRelationshipResponse])
def list_relationships(
    relationship_type: Optional[str] = Query(default=None),
    origin: Optional[str] = Query(default=None),
    review_status: Optional[str] = Query(default=None),
    ref_type: Optional[str] = Query(default=None),
    ref_id: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.RELATIONSHIP_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = relationship_service.list_relationships_query(
        current_user.organization_id, relationship_type=relationship_type, origin=origin, review_status=review_status, ref_type=ref_type, ref_id=ref_id,
    )
    return paginate(db, stmt, page_params.page, page_params.page_size, EvidenceRelationshipResponse)


@router.post("", response_model=EvidenceRelationshipResponse, status_code=status.HTTP_201_CREATED)
def create_relationship(
    payload: RelationshipCreateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.RELATIONSHIP_MANAGE)),
    db: Session = Depends(get_db),
) -> EvidenceRelationshipResponse:
    """Every relationship submitted through this route is
    `origin="analyst_created"` -- a rule_based relationship is only
    ever written by fusion_service.py, never by a human filling out
    this form (Section 3D: distinguish rule-based from analyst-drawn
    links)."""
    try:
        relationship, created = relationship_service.create_relationship(
            db,
            organization_id=current_user.organization_id,
            source_ref_type=payload.source_ref_type,
            source_ref_id=payload.source_ref_id,
            target_ref_type=payload.target_ref_type,
            target_ref_id=payload.target_ref_id,
            relationship_type=payload.relationship_type,
            origin="analyst_created",
            explanation=payload.explanation,
            supporting_metadata=payload.supporting_metadata,
            created_by_user_id=current_user.id,
        )
    except InvalidReferenceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if created:
        audit_service.record(
            db, action="evidence_relationship.create", actor_user_id=current_user.id, organization_id=current_user.organization_id,
            target_type="evidence_relationship", target_id=relationship.id, request_id=getattr(request.state, "request_id", None),
            context_metadata={"relationship_type": relationship.relationship_type},
        )
        db.commit()
    return EvidenceRelationshipResponse.model_validate(relationship)


def _get_or_404(db: Session, organization_id: str, relationship_id: str):
    relationship = relationship_service.get_relationship(db, organization_id, relationship_id)
    if relationship is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found")
    return relationship


@router.get("/{relationship_id}", response_model=EvidenceRelationshipResponse)
def get_relationship(
    relationship_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.RELATIONSHIP_READ)),
    db: Session = Depends(get_db),
) -> EvidenceRelationshipResponse:
    return EvidenceRelationshipResponse.model_validate(_get_or_404(db, current_user.organization_id, relationship_id))


@router.get("/{relationship_id}/history", response_model=list[ReviewHistoryEntry])
def get_relationship_history(
    relationship_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.RELATIONSHIP_READ)),
    db: Session = Depends(get_db),
) -> list[ReviewHistoryEntry]:
    _get_or_404(db, current_user.organization_id, relationship_id)
    history = relationship_service.get_review_history(db, current_user.organization_id, relationship_id)
    return [ReviewHistoryEntry.model_validate(h) for h in history]


@router.post("/{relationship_id}/review", response_model=EvidenceRelationshipResponse)
def review_relationship(
    relationship_id: str,
    payload: RelationshipReviewRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.RELATIONSHIP_MANAGE)),
    db: Session = Depends(get_db),
) -> EvidenceRelationshipResponse:
    relationship = _get_or_404(db, current_user.organization_id, relationship_id)
    try:
        updated = relationship_service.review_relationship(
            db, relationship, review_status=payload.review_status, reviewed_by_user_id=current_user.id,
            review_note=payload.review_note, request_id=getattr(request.state, "request_id", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return EvidenceRelationshipResponse.model_validate(updated)


@router.post("/{relationship_id}/reverse", response_model=EvidenceRelationshipResponse)
def reverse_relationship(
    relationship_id: str,
    payload: RelationshipReverseRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.RELATIONSHIP_MANAGE)),
    db: Session = Depends(get_db),
) -> EvidenceRelationshipResponse:
    relationship = _get_or_404(db, current_user.organization_id, relationship_id)
    try:
        updated = relationship_service.reverse_relationship(
            db, relationship, actor_user_id=current_user.id, note=payload.note, request_id=getattr(request.state, "request_id", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return EvidenceRelationshipResponse.model_validate(updated)
