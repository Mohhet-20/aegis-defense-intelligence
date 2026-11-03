"""Normalized model outputs and their explanations (Phase 10,
Sections 2 and 4). Read-only."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.analytics import ExplanationResponse
from app.schemas.common import Page, PageParams
from app.schemas.model_output import OUTPUT_TYPES, ModelOutput
from app.services import explanation_service, model_output_service

router = APIRouter(prefix="/model-outputs", tags=["model-outputs"])


class ModelOutputPage(Page[ModelOutput]):
    skipped_invalid: int = 0


def _check_type(output_type: str) -> None:
    if output_type not in OUTPUT_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"output_type must be one of {OUTPUT_TYPES}")


@router.get("", response_model=ModelOutputPage)
def list_model_outputs(
    output_type: str = Query(...),
    model_record_id: Optional[str] = Query(default=None, max_length=36),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ANALYTICS_READ)),
    db: Session = Depends(get_db),
) -> ModelOutputPage:
    _check_type(output_type)
    data = model_output_service.list_outputs(db, current_user.organization_id, output_type, model_record_id=model_record_id,
                                             page=page_params.page, page_size=page_params.page_size)
    return ModelOutputPage(**data)


@router.get("/{output_type}/{output_id}", response_model=ModelOutput)
def get_model_output(
    output_type: str, output_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ANALYTICS_READ)),
    db: Session = Depends(get_db),
) -> ModelOutput:
    _check_type(output_type)
    try:
        output = model_output_service.get_output(db, current_user.organization_id, output_type, output_id)
    except model_output_service.ModelOutputInvalid as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if output is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model output not found")
    return output


@router.get("/{output_type}/{output_id}/explanation", response_model=ExplanationResponse)
def get_explanation(
    output_type: str, output_id: str,
    method: Optional[str] = Query(default=None, max_length=60),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ANALYTICS_READ)),
    db: Session = Depends(get_db),
) -> ExplanationResponse:
    _check_type(output_type)
    try:
        result = explanation_service.explain_output(db, current_user.organization_id, output_type, output_id, method)
    except explanation_service.UnknownExplanationMethod as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except model_output_service.ModelOutputInvalid as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model output not found")
    return ExplanationResponse(**result)
