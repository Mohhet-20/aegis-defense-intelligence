from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.model_record import MODEL_RECORD_STATUSES


class CVModelRegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=50)
    adapter_key: str = Field(min_length=1, max_length=100)
    supported_media_types: list[str] = Field(min_length=1)
    status: str = "active"

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in MODEL_RECORD_STATUSES:
            raise ValueError(f"status must be one of {MODEL_RECORD_STATUSES}")
        return v


class CVModelResponse(BaseModel):
    id: str
    name: str
    version: str
    model_type: str
    task_type: Optional[str]
    adapter_key: Optional[str]
    supported_media_types: list[str]
    status: str
    evaluation_metadata: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
