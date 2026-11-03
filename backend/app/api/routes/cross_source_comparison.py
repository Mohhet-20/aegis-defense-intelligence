from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.cross_source import CrossSourceComparisonResponse, CrossSourceCompareRequest, CrossSourceLinkRequest
from app.schemas.relationship import EvidenceRelationshipResponse
from app.services import audit_service, cross_source_comparison_service, observation_service

router = APIRouter(prefix="/cross-source-comparison", tags=["cross-source-comparison"])


def _resolve_observation(db: Session, organization_id: str, observation_id: str):
    observation = observation_service.get_observation(db, organization_id, observation_id)
    if observation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Observation '{observation_id}' not found")
    return observation


@router.post("/compare", response_model=CrossSourceComparisonResponse)
def compare_observations(
    payload: CrossSourceCompareRequest,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVATION_READ)),
    db: Session = Depends(get_db),
) -> CrossSourceComparisonResponse:
    observation_a = _resolve_observation(db, current_user.organization_id, payload.observation_a_id)
    observation_b = _resolve_observation(db, current_user.organization_id, payload.observation_b_id)
    comparison = cross_source_comparison_service.compare(observation_a, observation_b, tolerance=payload.tolerance)
    return CrossSourceComparisonResponse(**comparison)


@router.post("/links", response_model=EvidenceRelationshipResponse, status_code=status.HTTP_201_CREATED)
def create_comparison_link(
    payload: CrossSourceLinkRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.RELATIONSHIP_MANAGE)),
    db: Session = Depends(get_db),
) -> EvidenceRelationshipResponse:
    observation_a = _resolve_observation(db, current_user.organization_id, payload.observation_a_id)
    observation_b = _resolve_observation(db, current_user.organization_id, payload.observation_b_id)
    comparison = cross_source_comparison_service.compare(observation_a, observation_b, tolerance=payload.tolerance)
    try:
        relationship, created = cross_source_comparison_service.create_comparison_link(
            db, current_user.organization_id, observation_a, observation_b,
            comparison=comparison, origin="analyst_created", created_by_user_id=current_user.id,
        )
    except cross_source_comparison_service.IncomparableObservationsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if created:
        audit_service.record(
            db, action="cross_source_comparison.link", actor_user_id=current_user.id, organization_id=current_user.organization_id,
            target_type="evidence_relationship", target_id=relationship.id, request_id=getattr(request.state, "request_id", None),
        )
        db.commit()
    return EvidenceRelationshipResponse.model_validate(relationship)
