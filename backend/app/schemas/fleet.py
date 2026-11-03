"""Enterprise fleet management shapes. See
app/models/fleet_site.py, device_capability.py, device_config_baseline.py,
infrastructure_alert.py, and the corresponding fleet_*_service.py
modules.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# --- Fleet sites / groups ---------------------------------------------

class FleetSiteCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class FleetSiteResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}


class FleetSiteSummaryResponse(BaseModel):
    site_id: str
    site_name: str
    device_count: int
    presence_counts: dict[str, int]
    administrative_status_counts: dict[str, int]
    open_alert_count: int


# --- Capability discovery ---------------------------------------------

class DeviceCapabilityResponse(BaseModel):
    capability_key: str
    supported: bool
    installed: bool
    available_and_ready: bool
    healthy: Optional[bool]
    last_verified_at: Optional[datetime]
    last_reported_at: Optional[datetime]

    model_config = {"from_attributes": True}


class FleetCapabilitySummaryEntry(BaseModel):
    capability_key: str
    device_count: int
    supported_count: int
    installed_count: int
    available_and_ready_count: int
    healthy_count: int
    recently_verified_count: int


# --- Config / baselines / drift ----------------------------------------

class DeviceConfigBaselineCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    expected_config: dict = Field(default_factory=dict)
    description: Optional[str] = Field(default=None, max_length=1000)
    version: int = 1


class DeviceConfigBaselineResponse(BaseModel):
    id: str
    name: str
    version: int
    expected_config: dict
    description: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class DeviceConfigAssignBaselineRequest(BaseModel):
    baseline_id: str


class DeviceConfigUpdateRequest(BaseModel):
    new_config: dict
    expected_revision: int


class DeviceConfigDriftResponse(BaseModel):
    evaluated: bool
    has_drift: Optional[bool]
    baseline_id: Optional[str]
    baseline_version: Optional[int] = None
    differences: list[dict]


class DeviceConfigStateResponse(BaseModel):
    current_config: dict
    config_revision: int
    config_baseline_id: Optional[str]
    drift: DeviceConfigDriftResponse


# --- Heartbeat / presence ----------------------------------------------

class HeartbeatRequest(BaseModel):
    protocol_version: str
    reported_at: Optional[datetime] = None


class HeartbeatResponse(BaseModel):
    device_id: str
    server_time: datetime
    presence_state: str


# --- Infrastructure alerts ----------------------------------------------

class InfrastructureAlertResponse(BaseModel):
    id: str
    device_id: Optional[str]
    alert_type: str
    severity: str
    status: str
    dedup_key: str
    title: str
    evidence: dict
    explanation: Optional[str]
    occurrence_count: int
    first_detected_at: datetime
    last_evaluated_at: datetime
    acknowledged_at: Optional[datetime]
    acknowledged_by_user_id: Optional[str]
    resolved_at: Optional[datetime]
    resolved_by_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertActionRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)


# --- Fleet analytics -----------------------------------------------------

class FleetOverviewResponse(BaseModel):
    as_of: datetime
    total_devices: int
    presence_counts: dict[str, int]
    administrative_status_counts: dict[str, int]
    devices_with_assigned_baseline: int
    baseline_assignment_pct: Optional[float]
    open_alerts_by_severity: dict[str, int]
    total_open_alerts: int
    unresolved_sync_conflicts: int


# --- Lifecycle preview -----------------------------------------------------

class LifecyclePreviewResponse(BaseModel):
    current_status: str
    target_status: str
    is_legal: bool
    is_consequential: bool
    impact_notes: list[str]
