from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AuditRecordResponse(BaseModel):
    id: str
    organization_id: Optional[str]
    actor_user_id: Optional[str]
    action: str
    target_type: Optional[str]
    target_id: Optional[str]
    outcome: str
    request_id: Optional[str]
    context_metadata: dict
    created_at: datetime

    model_config = {"from_attributes": True}
