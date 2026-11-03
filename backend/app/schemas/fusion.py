from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RunFusionJobRequest(BaseModel):
    time_window_seconds: Optional[int] = Field(default=None, ge=1, le=7 * 24 * 3600)
    spatial_threshold_meters: Optional[float] = Field(default=None, ge=0.0, le=100_000.0)
    spatial_conflict_threshold_meters: Optional[float] = Field(default=None, ge=0.0, le=200_000.0)


class FusionJobResponse(BaseModel):
    id: str
    organization_id: str
    status: str
    triggered_by_user_id: Optional[str]
    rule_version: str
    parameters: dict
    events_considered: int
    correlations_created: int
    conflicts_created: int
    started_at: datetime
    finished_at: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    data: dict


class GraphEdge(BaseModel):
    id: str
    type: str
    origin: Optional[str] = None
    source: dict
    target: dict
    reasons: Optional[list[str]] = None
    relationship_type: Optional[str] = None
    conflicting_fields: Optional[list] = None
    role: Optional[str] = None
    explanation: Optional[str] = None
    match_strength: Optional[float] = None
    review_status: Optional[str] = None


class GraphResponse(BaseModel):
    seed: dict
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
    max_depth: int
    max_nodes: int
