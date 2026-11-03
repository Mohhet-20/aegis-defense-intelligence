from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.cv import coco_eval
from app.cv.adapters.registry import UnsupportedRuntimeError
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.evaluation import ModelEvaluationRunResponse, RunEvaluationRequest
from app.services import audit_service, evaluation_service, model_registry_service

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.post("/runs", response_model=ModelEvaluationRunResponse, status_code=status.HTTP_201_CREATED)
def run_evaluation(
    payload: RunEvaluationRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EVALUATION_RUN)),
    db: Session = Depends(get_db),
) -> ModelEvaluationRunResponse:
    model_record = model_registry_service.get_cv_model(db, payload.model_record_id, current_user.organization_id)
    if model_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV model not found")
    try:
        run = evaluation_service.run_evaluation(
            db, organization_id=current_user.organization_id, model_record=model_record,
            sample_count=payload.sample_count, iou_match_threshold=payload.iou_match_threshold,
            evaluated_by_user_id=current_user.id, dataset=payload.dataset,
        )
    except (UnsupportedRuntimeError, coco_eval.DatasetUnavailable) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    audit_service.record(
        db, action="evaluation.run", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="model_evaluation_run", target_id=run.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"model_record_id": model_record.id, "precision": run.precision, "recall": run.recall, "f1_score": run.f1_score},
    )
    db.commit()
    return ModelEvaluationRunResponse.model_validate(run)


@router.get("/runs", response_model=Page[ModelEvaluationRunResponse])
def list_evaluation_runs(
    model_record_id: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EVALUATION_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = evaluation_service.list_runs_query(current_user.organization_id, model_record_id=model_record_id)
    return paginate(db, stmt, page_params.page, page_params.page_size, ModelEvaluationRunResponse)


@router.get("/runs/{run_id}", response_model=ModelEvaluationRunResponse)
def get_evaluation_run(
    run_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EVALUATION_READ)),
    db: Session = Depends(get_db),
) -> ModelEvaluationRunResponse:
    run = evaluation_service.get_run(db, current_user.organization_id, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found")
    return ModelEvaluationRunResponse.model_validate(run)
