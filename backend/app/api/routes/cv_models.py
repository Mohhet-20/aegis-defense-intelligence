from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.cv_model import CVModelRegisterRequest, CVModelResponse
from app.services import audit_service, model_registry_service

router = APIRouter(prefix="/cv/models", tags=["cv-models"])


@router.post("", response_model=CVModelResponse, status_code=status.HTTP_201_CREATED)
def register_cv_model(
    payload: CVModelRegisterRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.MODEL_MANAGE)),
    db: Session = Depends(get_db),
) -> CVModelResponse:
    try:
        model_record = model_registry_service.register_cv_model(
            db, name=payload.name, version=payload.version, adapter_key=payload.adapter_key,
            supported_media_types=payload.supported_media_types, status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    audit_service.record(
        db, action="cv_model.register", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="model_record", target_id=model_record.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"adapter_key": model_record.adapter_key, "name": model_record.name, "version": model_record.version},
    )
    db.commit()
    return CVModelResponse.model_validate(model_record)


@router.get("", response_model=Page[CVModelResponse])
def list_cv_models(
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.MODEL_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = model_registry_service.list_cv_models_query(organization_id=current_user.organization_id)
    return paginate(db, stmt, page_params.page, page_params.page_size, CVModelResponse)


@router.get("/{model_record_id}", response_model=CVModelResponse)
def get_cv_model(
    model_record_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.MODEL_READ)),
    db: Session = Depends(get_db),
) -> CVModelResponse:
    model_record = model_registry_service.get_cv_model(db, model_record_id, current_user.organization_id)
    if model_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV model not found")
    return CVModelResponse.model_validate(model_record)
