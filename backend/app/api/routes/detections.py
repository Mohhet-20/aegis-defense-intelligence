from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.models.detection_result import DetectionResult
from app.schemas.detection import DetectionResultResponse, DetectionReviewRequest, PromoteToEvidenceRequest
from app.schemas.evidence import EvidenceResponse
from app.services import audit_service, detection_review_service

router = APIRouter(prefix="/detections", tags=["detections"])


def _get_detection(db: Session, organization_id: str, detection_id: str) -> DetectionResult:
    stmt = select(DetectionResult).where(DetectionResult.id == detection_id, DetectionResult.organization_id == organization_id)
    detection = db.execute(stmt).scalar_one_or_none()
    if detection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection result not found")
    return detection


@router.post("/{detection_id}/review", response_model=DetectionResultResponse)
def review_detection(
    detection_id: str,
    payload: DetectionReviewRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DETECTION_REVIEW)),
    db: Session = Depends(get_db),
) -> DetectionResultResponse:
    detection = _get_detection(db, current_user.organization_id, detection_id)
    updated = detection_review_service.review_detection(
        db, detection, review_status=payload.review_status, reviewed_by_user_id=current_user.id, review_note=payload.review_note,
    )
    audit_service.record(
        db, action="detection.review", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="detection_result", target_id=updated.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"review_status": updated.review_status},
    )
    db.commit()
    return DetectionResultResponse.model_validate(updated)


@router.post("/{detection_id}/promote-to-evidence", response_model=EvidenceResponse, status_code=status.HTTP_201_CREATED)
def promote_to_evidence(
    detection_id: str,
    payload: PromoteToEvidenceRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DETECTION_REVIEW)),
    db: Session = Depends(get_db),
) -> EvidenceResponse:
    detection = _get_detection(db, current_user.organization_id, detection_id)
    try:
        evidence = detection_review_service.promote_to_evidence(
            db, detection, title=payload.title, summary=payload.summary, created_by_user_id=current_user.id,
        )
    except detection_review_service.ReviewError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    audit_service.record(
        db, action="detection.promote_to_evidence", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="evidence", target_id=evidence.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"detection_result_id": detection.id},
    )
    db.commit()
    return EvidenceResponse.model_validate(evidence)
