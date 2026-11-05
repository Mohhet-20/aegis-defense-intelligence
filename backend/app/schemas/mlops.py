"""Request/response schemas MLOps routes. Requests are strict
(unknown fields rejected, numbers must be finite); responses declare the shape
the frontend relies on."""
from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.schemas.common import Page

IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:\-]{8,100}$")
FEATURE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,63}$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ registry ---
class ModelVersionCreate(Strict):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=5, max_length=100)
    task_type: Literal["object_detection", "classification"]
    adapter_key: Optional[str] = Field(default=None, max_length=100)
    supported_media_types: list[Literal["image", "video"]] = Field(default_factory=list, max_length=2)
    artifact_reference: Optional[str] = Field(default=None, max_length=500)
    artifact_digest: Optional[str] = Field(default=None, max_length=64)
    input_schema_version: Optional[str] = Field(default=None, max_length=50)
    output_schema_version: Optional[str] = Field(default=None, max_length=50)
    framework_metadata: Optional[dict[str, Any]] = None
    release_notes: Optional[str] = Field(default=None, max_length=4000)
    documentation_ref: Optional[str] = Field(default=None, max_length=500)


class TransitionRequest(Strict):
    action: Literal["request_review", "reject_review", "approve", "revoke_approval", "deprecate", "reactivate", "archive"]
    reason: str = Field(min_length=3, max_length=1000)


# --------------------------------------------------------------- experiments ---
class DetectionConfig(Strict):
    fixture: Literal["synthetic_single_rectangle_fixture@1.0", "coco_val2017_subset"] = "synthetic_single_rectangle_fixture@1.0"
    sample_count: int = Field(default=20, ge=1, le=1000)
    iou_match_threshold: float = Field(default=0.5, gt=0.0, le=1.0)


class ClassificationSample(Strict):
    sample_ref: Optional[str] = Field(default=None, max_length=200)
    true_label: Optional[str] = Field(default=None, max_length=100)
    predicted_label: str = Field(min_length=1, max_length=100)
    positive_probability: Optional[float] = None

    @field_validator("positive_probability")
    @classmethod
    def _finite(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (not math.isfinite(v) or not 0.0 <= v <= 1.0):
            raise ValueError("positive_probability must be a finite number between 0 and 1")
        return v


class ClassificationConfig(Strict):
    dataset_name: str = Field(min_length=1, max_length=200)
    dataset_version: str = Field(min_length=1, max_length=50)
    is_synthetic: bool
    labels: Optional[list[str]] = Field(default=None, max_length=100)
    positive_label: Optional[str] = Field(default=None, max_length=100)
    samples: list[ClassificationSample] = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def _probabilities_need_positive_label(self) -> "ClassificationConfig":
        if any(s.positive_probability is not None for s in self.samples) and not self.positive_label:
            raise ValueError("positive_label is required when positive_probability values are supplied")
        return self


class ExperimentCreate(Strict):
    model_record_id: str = Field(min_length=1, max_length=36)
    experiment_name: str = Field(min_length=1, max_length=200)
    purpose: Optional[str] = Field(default=None, max_length=1000)
    idempotency_key: Optional[str] = Field(default=None, max_length=100)
    detection: Optional[DetectionConfig] = None
    classification: Optional[ClassificationConfig] = None

    @field_validator("idempotency_key")
    @classmethod
    def _key(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not IDEMPOTENCY_RE.match(v):
            raise ValueError("idempotency_key must be 8-100 characters of letters, digits, '.', '_', ':' or '-'")
        return v

    @model_validator(mode="after")
    def _exactly_one(self) -> "ExperimentCreate":
        if (self.detection is None) == (self.classification is None):
            raise ValueError("provide exactly one of 'detection' or 'classification'")
        return self


class BaselineSelect(Strict):
    run_id: str = Field(min_length=1, max_length=36)
    reason: Optional[str] = Field(default=None, max_length=1000)


# ---------------------------------------------------------------- monitoring ---
class MonitoringRecord(Strict):
    features: dict[str, Any] = Field(default_factory=dict)
    predicted_label: Optional[str] = Field(default=None, max_length=100)
    confidence: Optional[float] = None
    true_label: Optional[str] = Field(default=None, max_length=100)

    @field_validator("confidence")
    @classmethod
    def _conf(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (not math.isfinite(v) or not 0.0 <= v <= 1.0):
            raise ValueError("confidence must be a finite number between 0 and 1")
        return v

    @field_validator("features")
    @classmethod
    def _features(cls, v: dict) -> dict:
        if len(v) > 100:
            raise ValueError("a record may carry at most 100 features")
        for k, val in v.items():
            if not FEATURE_NAME_RE.match(k):
                raise ValueError(f"invalid feature name {k!r}")
            if isinstance(val, float) and not math.isfinite(val):
                raise ValueError(f"feature {k!r} must be finite")
            if isinstance(val, str) and len(val) > 100:
                raise ValueError(f"feature {k!r} is longer than 100 characters")
            if val is not None and not isinstance(val, (int, float, str, bool)):
                raise ValueError(f"feature {k!r} must be a number, string, boolean or null")
        return v


class SnapshotCreate(Strict):
    model_record_id: str = Field(min_length=1, max_length=36)
    kind: Literal["reference", "current"]
    reference_snapshot_id: Optional[str] = Field(default=None, max_length=36)
    window_start: datetime
    window_end: datetime
    expected_schema: Optional[dict[str, Literal["numeric", "categorical"]]] = None
    note: Optional[str] = Field(default=None, max_length=1000)
    records: list[MonitoringRecord] = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def _window(self) -> "SnapshotCreate":
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        if self.kind == "reference" and self.reference_snapshot_id:
            raise ValueError("a reference snapshot cannot itself reference another snapshot")
        if self.expected_schema is not None:
            if len(self.expected_schema) > 100:
                raise ValueError("expected_schema may declare at most 100 features")
            for k in self.expected_schema:
                if not FEATURE_NAME_RE.match(k):
                    raise ValueError(f"invalid feature name {k!r}")
        return self


# ------------------------------------------------------------------- signals ---
class SignalAcknowledge(Strict):
    assignee_user_id: Optional[str] = Field(default=None, max_length=36)


class SignalResolve(Strict):
    notes: str = Field(min_length=3, max_length=2000)


# ------------------------------------------------------------------ responses ---
class Loose(BaseModel):
    model_config = ConfigDict(extra="allow", from_attributes=True)


class VersionOut(Loose):
    id: str
    name: str
    version: str
    task_type: Optional[str]
    lifecycle_state: str
    legacy_status: str
    scope: str
    created_at: datetime
    evaluation: dict
    artifact: dict


class FamilyOut(Loose):
    name: str
    version_count: int
    latest_version: Optional[str]
    task_types: list[str]
    lifecycle_counts: dict[str, int]


class EventOut(Loose):
    id: str
    action: str
    from_state: Optional[str]
    to_state: str
    created_at: datetime


class RunOut(Loose):
    id: str
    model_record_id: str
    model_version: str
    task: str
    experiment_name: str
    status: str
    dataset_name: str
    dataset_version: str
    is_synthetic: bool
    started_at: datetime
    completed_at: Optional[datetime]
    duration_ms: Optional[float]
    metrics: Optional[dict]
    sample_count: Optional[int]
    error_category: Optional[str]
    error_message: Optional[str]


class SignalOut(Loose):
    id: str
    category: str
    severity: str
    status: str
    title: str
    summary: str
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime


class SnapshotOut(Loose):
    id: str
    model_record_id: str
    kind: str
    window_start: datetime
    window_end: datetime
    sample_count: int
    labelled_count: int
    schema_violation_count: int


class SignalPage(Page[SignalOut]):
    counts: dict = {}
