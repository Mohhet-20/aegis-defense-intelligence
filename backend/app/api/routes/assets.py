from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.asset import AssetCreateRequest, AssetResponse, AssetUpdateRequest
from app.schemas.common import Page, PageParams
from app.services import asset_service, audit_service

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=Page[AssetResponse])
def list_assets(
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSET_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = asset_service.list_assets_query(current_user.organization_id)
    return paginate(db, stmt, page_params.page, page_params.page_size, AssetResponse)


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
def create_asset(
    payload: AssetCreateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSET_MANAGE)),
    db: Session = Depends(get_db),
) -> AssetResponse:
    asset = asset_service.create_asset(db, organization_id=current_user.organization_id, **payload.model_dump())
    audit_service.record(
        db, action="asset.create", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="asset", target_id=asset.id, request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return AssetResponse.model_validate(asset)


@router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(
    asset_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSET_READ)),
    db: Session = Depends(get_db),
) -> AssetResponse:
    asset = asset_service.get_asset(db, current_user.organization_id, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return AssetResponse.model_validate(asset)


@router.patch("/{asset_id}", response_model=AssetResponse)
def update_asset(
    asset_id: str,
    payload: AssetUpdateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ASSET_MANAGE)),
    db: Session = Depends(get_db),
) -> AssetResponse:
    asset = asset_service.get_asset(db, current_user.organization_id, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    updated = asset_service.update_asset(db, asset, **payload.model_dump(exclude_unset=True))
    audit_service.record(
        db, action="asset.update", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="asset", target_id=asset.id, request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return AssetResponse.model_validate(updated)
