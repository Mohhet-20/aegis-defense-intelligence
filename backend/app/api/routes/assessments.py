from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.assessment import (
    AssessmentCreateRequest,
    AssessmentEvidenceLinkRequest,
    AssessmentEvidenceLinkResponse,
    AssessmentResponse,
    AssessmentRevisionResponse,
    AssessmentUpdateRequest,
)
from app.schemas.common import Page, PageParams
from app.services import assessment_service, audit_service

router = APIRouter(prefix="/assessments", tags=["assessments"])


@router.get("", response_model=Page[AssessmentResponse])
def list_assessments(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSESSMENT_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = assessment_service.list_assessments_query(current_user.organization_id, status=status_filter)
    return paginate(db, stmt, page_params.page, page_params.page_size, AssessmentResponse)


@router.post("", response_model=AssessmentResponse, status_code=status.HTTP_201_CREATED)
def create_assessment(
    payload: AssessmentCreateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSESSMENT_MANAGE)),
    db: Session = Depends(get_db),
) -> AssessmentResponse:
    try:
        assessment = assessment_service.create_assessment(
            db, organization_id=current_user.organization_id, author_user_id=current_user.id, **payload.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    audit_service.record(
        db, action="assessment.create", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="assessment", target_id=assessment.id, request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return AssessmentResponse.model_validate(assessment)


def _get_or_404(db: Session, organization_id: str, assessment_id: str):
    assessment = assessment_service.get_assessment(db, organization_id, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return assessment


@router.get("/{assessment_id}", response_model=AssessmentResponse)
def get_assessment(
    assessment_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSESSMENT_READ)),
    db: Session = Depends(get_db),
) -> AssessmentResponse:
    return AssessmentResponse.model_validate(_get_or_404(db, current_user.organization_id, assessment_id))


@router.patch("/{assessment_id}", response_model=AssessmentResponse)
def update_assessment(
    assessment_id: str,
    payload: AssessmentUpdateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSESSMENT_MANAGE)),
    db: Session = Depends(get_db),
) -> AssessmentResponse:
    assessment = _get_or_404(db, current_user.organization_id, assessment_id)
    fields = payload.model_dump(exclude_unset=True)
    change_note = fields.pop("change_note", None)
    try:
        updated = assessment_service.update_assessment(
            db, assessment, actor_user_id=current_user.id, change_note=change_note,
            request_id=getattr(request.state, "request_id", None), **fields,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return AssessmentResponse.model_validate(updated)


@router.get("/{assessment_id}/revisions", response_model=list[AssessmentRevisionResponse])
def list_revisions(
    assessment_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSESSMENT_READ)),
    db: Session = Depends(get_db),
) -> list[AssessmentRevisionResponse]:
    _get_or_404(db, current_user.organization_id, assessment_id)
    revisions = assessment_service.list_revisions(db, current_user.organization_id, assessment_id)
    return [AssessmentRevisionResponse.model_validate(r) for r in revisions]


@router.post("/{assessment_id}/evidence", response_model=AssessmentEvidenceLinkResponse, status_code=status.HTTP_201_CREATED)
def link_evidence(
    assessment_id: str,
    payload: AssessmentEvidenceLinkRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSESSMENT_MANAGE)),
    db: Session = Depends(get_db),
) -> AssessmentEvidenceLinkResponse:
    assessment = _get_or_404(db, current_user.organization_id, assessment_id)
    try:
        link, _created = assessment_service.link_evidence(
            db, organization_id=current_user.organization_id, assessment=assessment, role=payload.role,
            event_id=payload.event_id, evidence_id=payload.evidence_id, note=payload.note,
            actor_user_id=current_user.id, request_id=getattr(request.state, "request_id", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return AssessmentEvidenceLinkResponse.model_validate(link)


@router.get("/{assessment_id}/evidence", response_model=list[AssessmentEvidenceLinkResponse])
def list_evidence_links(
    assessment_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSESSMENT_READ)),
    db: Session = Depends(get_db),
) -> list[AssessmentEvidenceLinkResponse]:
    _get_or_404(db, current_user.organization_id, assessment_id)
    links = assessment_service.list_evidence_links(db, current_user.organization_id, assessment_id)
    return [AssessmentEvidenceLinkResponse.model_validate(l) for l in links]
