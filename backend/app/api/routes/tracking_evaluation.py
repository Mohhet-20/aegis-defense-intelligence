from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.config import get_settings
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.tracking_evaluation import RunTrackingEvaluationRequest, TrackingEvaluationRunResponse
from app.services import audit_service, tracking_evaluation_service
from app.tracking.trackers.registry import UnsupportedTrackerError

router = APIRouter(prefix="/tracking/evaluation", tags=["tracking-evaluation"])
settings = get_settings()


@router.post("/runs", response_model=TrackingEvaluationRunResponse, status_code=status.HTTP_201_CREATED)
def run_tracking_evaluation(
    payload: RunTrackingEvaluationRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_EVALUATION_RUN)),
    db: Session = Depends(get_db),
) -> TrackingEvaluationRunResponse:
    tracker_key = payload.tracker_key or settings.TRACKING_DEFAULT_TRACKER_KEY
    try:
        run = tracking_evaluation_service.run_evaluation(
            db, organization_id=current_user.organization_id, tracker_key=tracker_key,
            min_iou_threshold=payload.min_iou_threshold, max_missed_frames=payload.max_missed_frames,
            min_hits_to_confirm=payload.min_hits_to_confirm, require_class_match=payload.require_class_match,
            evaluated_by_user_id=current_user.id,
        )
    except UnsupportedTrackerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    audit_service.record(
        db, action="tracking_evaluation.run", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="tracking_evaluation_run", target_id=run.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"tracker_key": run.tracker_key, "track_precision": run.track_precision, "track_recall": run.track_recall},
    )
    db.commit()
    return TrackingEvaluationRunResponse.model_validate(run)


@router.get("/runs", response_model=Page[TrackingEvaluationRunResponse])
def list_tracking_evaluation_runs(
    tracker_key: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_EVALUATION_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = tracking_evaluation_service.list_runs_query(current_user.organization_id, tracker_key=tracker_key)
    return paginate(db, stmt, page_params.page, page_params.page_size, TrackingEvaluationRunResponse)


@router.get("/runs/{run_id}", response_model=TrackingEvaluationRunResponse)
def get_tracking_evaluation_run(
    run_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_EVALUATION_READ)),
    db: Session = Depends(get_db),
) -> TrackingEvaluationRunResponse:
    run = tracking_evaluation_service.get_run(db, current_user.organization_id, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracking evaluation run not found")
    return TrackingEvaluationRunResponse.model_validate(run)
