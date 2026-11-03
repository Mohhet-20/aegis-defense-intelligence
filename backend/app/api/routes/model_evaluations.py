"""Labelled-dataset model evaluation + a unified evaluation overview."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.analytics import ClassificationEvaluationRequest, ClassificationEvaluationResponse, EvaluationOverviewRow
from app.schemas.common import Page, PageParams
from app.services import audit_service, classification_evaluation_service as svc

router = APIRouter(prefix="/model-evaluations", tags=["model-evaluations"])
log = logging.getLogger("aegis.analytics.evaluation")


def _to_response(run) -> ClassificationEvaluationResponse:
    return ClassificationEvaluationResponse(
        id=run.id, model_record_id=run.model_record_id, model_version=run.model_version, dataset_name=run.dataset_name,
        dataset_version=run.dataset_version, dataset_reference=run.dataset_reference, is_synthetic=run.is_synthetic,
        performance_claim=svc.performance_claim(run.is_synthetic, run.dataset_name, run.dataset_version),
        sample_count=run.sample_count, excluded_missing_label=run.excluded_missing_label, evaluation_config=run.evaluation_config,
        metric_definitions=run.metric_definitions, results=run.results, warnings=run.warnings, status=run.status,
        error_message=run.error_message, evaluated_by_user_id=run.evaluated_by_user_id, evaluated_at=run.evaluated_at,
    )


@router.post("", response_model=ClassificationEvaluationResponse, status_code=status.HTTP_201_CREATED)
def run_evaluation(
    payload: ClassificationEvaluationRequest, request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ANALYTICS_EVALUATE)),
    db: Session = Depends(get_db),
) -> ClassificationEvaluationResponse:
    rid = getattr(request.state, "request_id", None)
    try:
        run = svc.run_classification_evaluation(db, organization_id=current_user.organization_id, req=payload, user_id=current_user.id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    except svc.EvaluationInputError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except svc.EvaluationFailed as exc:
        audit_service.record(db, action="model_evaluation.failed", actor_user_id=current_user.id, organization_id=current_user.organization_id,
                             target_type="classification_evaluation_run", target_id=exc.run.id, outcome="failure", request_id=rid)
        db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Evaluation failed and was recorded as failed (run {exc.run.id}); no metrics were stored.")
    audit_service.record(db, action="model_evaluation.run", actor_user_id=current_user.id, organization_id=current_user.organization_id,
                         target_type="classification_evaluation_run", target_id=run.id, request_id=rid,
                         context_metadata={"model_record_id": run.model_record_id, "model_version": run.model_version,
                                           "dataset": f"{run.dataset_name}@{run.dataset_version}", "is_synthetic": run.is_synthetic,
                                           "sample_count": run.sample_count})
    db.commit()
    db.refresh(run)
    log.info("classification evaluation %s completed (samples=%s synthetic=%s)", run.id, run.sample_count, run.is_synthetic)
    return _to_response(run)


@router.get("", response_model=Page[EvaluationOverviewRow])
def evaluation_overview(
    model_record_id: Optional[str] = Query(default=None, max_length=36),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ANALYTICS_READ)),
    db: Session = Depends(get_db),
) -> Page:
    data = svc.overview(db, current_user.organization_id, model_record_id=model_record_id, page=page_params.page, page_size=page_params.page_size)
    return Page(**data)


@router.get("/{run_id}", response_model=ClassificationEvaluationResponse)
def get_evaluation(
    run_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ANALYTICS_READ)),
    db: Session = Depends(get_db),
) -> ClassificationEvaluationResponse:
    run = svc.get_run(db, current_user.organization_id, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found")
    return _to_response(run)
