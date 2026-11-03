from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.risk_assessment import RiskAssessment


def get_assessment(db: Session, organization_id: str, assessment_id: str) -> Optional[RiskAssessment]:
    stmt = select(RiskAssessment).where(RiskAssessment.id == assessment_id, RiskAssessment.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_assessments_query(organization_id: str, *, human_review_status: Optional[str] = None):
    stmt = select(RiskAssessment).where(RiskAssessment.organization_id == organization_id)
    if human_review_status:
        stmt = stmt.where(RiskAssessment.human_review_status == human_review_status)
    return stmt.order_by(RiskAssessment.assessed_at.desc())


def review_assessment(db: Session, assessment: RiskAssessment, *, reviewer_user_id: str, human_review_status: str, reviewer_notes: Optional[str]) -> RiskAssessment:
    assessment.human_review_status = human_review_status
    assessment.reviewer_user_id = reviewer_user_id
    assessment.reviewed_at = datetime.now(timezone.utc)
    assessment.reviewer_notes = reviewer_notes
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment
