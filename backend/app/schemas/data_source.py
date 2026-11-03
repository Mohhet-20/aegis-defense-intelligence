from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.data_source import DATA_SOURCE_CONNECTION_MODES, DATA_SOURCE_STATUSES


class DataSourceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_type: str = Field(min_length=1, max_length=50)
    description: Optional[str] = Field(default=None, max_length=2000)
    reliability_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    config_metadata: dict = Field(default_factory=dict)
    owner_team: Optional[str] = Field(default=None, max_length=200)
    connection_mode: str = Field(default="file_upload", max_length=30)
    enabled: bool = Field(default=True)

    @field_validator("connection_mode")
    @classmethod
    def _check_connection_mode(cls, v: str) -> str:
        if v not in DATA_SOURCE_CONNECTION_MODES:
            raise ValueError(f"connection_mode must be one of {DATA_SOURCE_CONNECTION_MODES}")
        return v


class DataSourceUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[str] = None
    config_metadata: Optional[dict] = None
    owner_team: Optional[str] = Field(default=None, max_length=200)
    connection_mode: Optional[str] = Field(default=None, max_length=30)

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in DATA_SOURCE_STATUSES:
            raise ValueError(f"status must be one of {DATA_SOURCE_STATUSES}")
        return v

    @field_validator("connection_mode")
    @classmethod
    def _check_connection_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in DATA_SOURCE_CONNECTION_MODES:
            raise ValueError(f"connection_mode must be one of {DATA_SOURCE_CONNECTION_MODES}")
        return v


class ReliabilityWeightRequest(BaseModel):
    """A significant manual reliability change requires a documented
    reason -- this is never derived automatically from
    correlation or duplication counts."""

    weight: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=1000)


class DataSourceResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    source_type: str
    description: Optional[str]
    status: str
    reliability_weight: float
    owner_team: Optional[str]
    connection_mode: str
    enabled: bool
    last_error_category: Optional[str]
    config_revision: int
    last_ingestion_attempt_at: Optional[datetime]
    last_ingestion_success_at: Optional[datetime]
    last_checkpoint_cursor: Optional[str]
    last_checkpoint_at: Optional[datetime]
    # config_metadata is intentionally still exposed here -- Section 3
    # requires it carry NO secret values (the HTTP connector's
    # auth_env_var names an environment variable, never a credential),
    # so returning it is safe by construction, not by filtering.
    config_metadata: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConnectivityCheckResponse(BaseModel):
    ok: bool
    detail: Optional[str]
    applicable: bool  # False for a file-upload-only source -- there is nothing to probe


class ConfigValidationResponse(BaseModel):
    valid: bool
    errors: list[str]
