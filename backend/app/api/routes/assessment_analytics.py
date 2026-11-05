"""Advisory scoring and human review of assessments (Sections 5-6). Extends the assessment routes without touching
them."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.analytics import scoring
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.analytics import ReviewRequest, ReviewResponse, ReviewSummaryResponse, ScoreRequest, ScoreSnapshotResponse
from app.services import assessment_review_service as reviews, assessment_scoring_service as scoring_svc, assessment_service

router = APIRouter(tags=["assessment-analytics"])


def _assessment_or_404(db: Session, organization_id: str, assessment_id: str):
    a = assessment_service.get_assessment(db, organization_id, assessment_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return a


def _score_response(snap) -> ScoreSnapshotResponse:
    return ScoreSnapshotResponse.model_validate(snap)


@router.get("/assessment-scoring-rules")
def list_scoring_rules(current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSESSMENT_READ))) -> dict:
    return {"score_scale": scoring.SCORE_SCALE, "bands": [{"band": b, "min_score": t} for b, t in scoring.BANDS],
            "allowed_inputs": list(scoring.ALLOWED_INPUTS), "advisory_notice": scoring.ADVISORY_NOTICE,
            "rules": {k: {"version": v["version"], "description": v["description"], "config": v["config"]} for k, v in scoring.RULES.items()}}


@router.post("/assessments/{assessment_id}/score", response_model=ScoreSnapshotResponse, status_code=status.HTTP_201_CREATED)
def compute_score(
    assessment_id: str, payload: ScoreRequest, request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSESSMENT_REVIEW)),
    db: Session = Depends(get_db),
) -> ScoreSnapshotResponse:
    assessment = _assessment_or_404(db, current_user.organization_id, assessment_id)
    try:
        snap = scoring_svc.compute_score(db, assessment, actor_user_id=current_user.id, rule_key=payload.rule_key,
                                         config_overrides=payload.config_overrides, request_id=getattr(request.state, "request_id", None))
    except scoring.ScoringConfigError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return _score_response(snap)


@router.get("/assessments/{assessment_id}/scores", response_model=list[ScoreSnapshotResponse])
def list_scores(
    assessment_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSESSMENT_READ)),
    db: Session = Depends(get_db),
) -> list[ScoreSnapshotResponse]:
    _assessment_or_404(db, current_user.organization_id, assessment_id)
    return [_score_response(s) for s in scoring_svc.list_snapshots(db, current_user.organization_id, assessment_id)]


@router.post("/assessments/{assessment_id}/reviews", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
def submit_review(
    assessment_id: str, payload: ReviewRequest, request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSESSMENT_REVIEW)),
    db: Session = Depends(get_db),
) -> ReviewResponse:
    assessment = _assessment_or_404(db, current_user.organization_id, assessment_id)
    try:
        review = reviews.submit_review(
            db, assessment, reviewer_user_id=current_user.id, decision=payload.decision, notes=payload.notes,
            change_reason=payload.change_reason, information_flags=payload.information_flags,
            score_snapshot_id=payload.score_snapshot_id, request_id=getattr(request.state, "request_id", None))
    except reviews.ReviewError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ReviewResponse.model_validate(review)


@router.get("/assessments/{assessment_id}/reviews", response_model=ReviewSummaryResponse)
def review_summary(
    assessment_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSESSMENT_READ)),
    db: Session = Depends(get_db),
) -> ReviewSummaryResponse:
    org = current_user.organization_id
    assessment = _assessment_or_404(db, org, assessment_id)
    history = reviews.list_reviews(db, org, assessment_id)
    latest = history[-1] if history else None
    snaps = scoring_svc.list_snapshots(db, org, assessment_id)
    return ReviewSummaryResponse(
        assessment_id=assessment_id, current_assessment_version=assessment.version, review_status=reviews.review_status(history),
        latest_review=ReviewResponse.model_validate(latest) if latest else None,
        latest_score=_score_response(snaps[0]) if snaps else None,
        comparison=reviews.comparison(latest, assessment), history=[ReviewResponse.model_validate(r) for r in history],
    )
