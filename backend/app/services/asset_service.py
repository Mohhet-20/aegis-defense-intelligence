from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset


def create_asset(db: Session, *, organization_id: str, **fields) -> Asset:
    asset = Asset(organization_id=organization_id, status="active", **fields)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def get_asset(db: Session, organization_id: str, asset_id: str) -> Optional[Asset]:
    stmt = select(Asset).where(Asset.id == asset_id, Asset.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_assets_query(organization_id: str):
    return select(Asset).where(Asset.organization_id == organization_id).order_by(Asset.created_at.desc())


def update_asset(db: Session, asset: Asset, **fields) -> Asset:
    for key, value in fields.items():
        if value is not None:
            setattr(asset, key, value)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset
