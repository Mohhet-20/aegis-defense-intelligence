from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.risk_assessment import RiskAssessmentResponse, RiskAssessmentReviewRequest
from app.services import audit_service, risk_service

router = APIRouter(prefix="/risk-assessments", tags=["risk-assessments"])


@router.get("", response_model=Page[RiskAssessmentResponse])
def list_risk_assessments(
    human_review_status: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.RISK_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = risk_service.list_assessments_query(current_user.organization_id, human_review_status=human_review_status)
    return paginate(db, stmt, page_params.page, page_params.page_size, RiskAssessmentResponse)


@router.get("/{assessment_id}", response_model=RiskAssessmentResponse)
def get_risk_assessment(
    assessment_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.RISK_READ)),
    db: Session = Depends(get_db),
) -> RiskAssessmentResponse:
    assessment = risk_service.get_assessment(db, current_user.organization_id, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk assessment not found")
    return RiskAssessmentResponse.model_validate(assessment)


@router.post("/{assessment_id}/review", response_model=RiskAssessmentResponse)
def review_risk_assessment(
    assessment_id: str,
    payload: RiskAssessmentReviewRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.RISK_REVIEW)),
    db: Session = Depends(get_db),
) -> RiskAssessmentResponse:
    assessment = risk_service.get_assessment(db, current_user.organization_id, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk assessment not found")
    updated = risk_service.review_assessment(
        db, assessment, reviewer_user_id=current_user.id,
        human_review_status=payload.human_review_status, reviewer_notes=payload.reviewer_notes,
    )
    audit_service.record(
        db, action="risk_assessment.review", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="risk_assessment", target_id=assessment.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"human_review_status": payload.human_review_status},
    )
    db.commit()
    return RiskAssessmentResponse.model_validate(updated)
