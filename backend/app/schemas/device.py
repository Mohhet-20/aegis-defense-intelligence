"""Device registry/lifecycle shapes. See
app/models/device.py and app/services/device_service.py."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

DEVICE_TYPES_EXAMPLE_NOTE = "device_type is a free-text operator label (e.g. 'field_sensor_node', 'handheld'), not a closed enum -- deployments vary too much to enumerate here."


class DeviceRegisterRequest(BaseModel):
    device_identifier: str = Field(min_length=1, max_length=100)
    device_name: str = Field(min_length=1, max_length=200)
    device_type: str = Field(min_length=1, max_length=50)
    deployment_label: Optional[str] = None
    capabilities: list[str] = Field(default_factory=list)
    inference_backends: list[str] = Field(default_factory=list)
    model_manifest: dict = Field(default_factory=dict)
    metadata_note: Optional[str] = Field(default=None, max_length=300)
    site_id: Optional[str] = None


class DeviceResponse(BaseModel):
    id: str
    device_identifier: str
    device_name: str
    device_type: str
    deployment_label: Optional[str]
    software_version: Optional[str]
    protocol_version: Optional[str]
    api_key_prefix: Optional[str]
    capabilities: list[str]
    inference_backends: list[str]
    model_manifest: dict
    connectivity_state: str
    local_storage_status: Optional[dict]
    last_seen_at: Optional[datetime]
    last_sync_at: Optional[datetime]
    last_health_report_at: Optional[datetime]
    config_version: Optional[str]
    sync_status: str
    administrative_status: str
    revoked_at: Optional[datetime]
    revoked_reason: Optional[str]
    metadata_note: Optional[str]
    created_at: datetime

    # Live-computed, never read off a stale column (same discipline
    # Established for location validation) -- how many
    # SyncRecord rows for this device are currently queued, syncing, or
    # retryable_failure right now.
    pending_sync_count: int = 0
    unresolved_conflict_count: int = 0

    # --- -------------------------------------------
    site_id: Optional[str] = None
    config_revision: int = 0
    config_baseline_id: Optional[str] = None
    current_config: dict = Field(default_factory=dict)
    last_resource_metrics: Optional[dict] = None
    # Live-computed server-authoritative presence (never the device's
    # own self-reported connectivity_state -- see
    # app/services/fleet_presence_service.py's module docstring for why
    # the two are kept genuinely separate).
    presence_state: str = "unknown"

    model_config = {"from_attributes": True}


class DeviceRegistrationResult(BaseModel):
    """Returned exactly once, at registration or key-rotation time --
    `api_key` is never retrievable again afterward (no
    secret is stored in recoverable form)."""

    device: DeviceResponse
    api_key: str


class DeviceLifecycleActionRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)


class DeviceSiteAssignRequest(BaseModel):
    site_id: Optional[str] = None


class DeviceHealthReportResponse(BaseModel):
    id: str
    device_id: str
    reported_at: datetime
    connectivity_state: str
    resource_metrics: Optional[dict]
    queue_depth: Optional[int]
    pending_sync_count: Optional[int]
    model_status: Optional[dict]
    software_version: Optional[str]
    runtime_capabilities: Optional[list[str]]
    created_at: datetime

    model_config = {"from_attributes": True}
