from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class LifecycleRequestCreate(BaseModel):
    resource_type: str = Field(min_length=1, max_length=40)
    resource_id: str = Field(min_length=1, max_length=36)
    action: str = Field(pattern="^(archive|delete)$")
    reason: str = Field(min_length=5, max_length=1000)


class LifecycleReviewBody(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)


class LifecycleRequestResponse(BaseModel):
    id: str
    resource_type: str
    resource_id: str
    action: str
    status: str
    reason: str
    requested_by_user_id: str
    reviewed_by_user_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    executed_by_user_id: Optional[str] = None
    executed_at: Optional[datetime] = None
    impact: dict[str, Any]
    result: Optional[dict[str, Any]] = None
    failure_reason: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
