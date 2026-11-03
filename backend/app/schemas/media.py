from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class MediaAssetResponse(BaseModel):
    id: str
    organization_id: str
    media_type: str
    status: str
    rejection_reason: Optional[str]
    declared_filename: str
    detected_mime_type: str
    content_hash: str
    byte_size: int
    width_px: Optional[int]
    height_px: Optional[int]
    duration_seconds: Optional[float]
    frame_count: Optional[int]
    fps: Optional[float]
    uploaded_by_user_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
