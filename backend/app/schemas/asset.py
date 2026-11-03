from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.asset import ASSET_STATUSES
from app.schemas.common import GeoLocationFields


class AssetCreateRequest(GeoLocationFields):
    name: str = Field(min_length=1, max_length=200)
    entity_type: str = Field(min_length=1, max_length=50)
    description: Optional[str] = Field(default=None, max_length=2000)
    extra_metadata: dict = Field(default_factory=dict)


class AssetUpdateRequest(GeoLocationFields):
    name: Optional[str] = Field(default=None, max_length=200)
    entity_type: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[str] = None
    extra_metadata: Optional[dict] = None

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ASSET_STATUSES:
            raise ValueError(f"status must be one of {ASSET_STATUSES}")
        return v


class AssetResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    entity_type: str
    description: Optional[str]
    status: str
    latitude: Optional[float]
    longitude: Optional[float]
    extra_metadata: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
