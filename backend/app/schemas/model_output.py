"""Shared model-output schema.

One normalized, validated view over the outputs the platform already
stores (detection results, risk assessments). It is a READ model:
nothing here is persisted separately, so there is no second copy of a
model's output to drift out of sync with the source row.

Rules enforced by the validators:
 * `confidence` is optional and, when present, a finite number in [0, 1].
   When the source model provided none, it stays None and
   `confidence_provided` is False -- a confidence is never manufactured.
 * `processed_at` must be timezone-aware and not in the future.
 * `model.version` must be non-empty. An output whose recorded model
   version disagrees with the registry row is reported as a
   `version_mismatch` data-quality indicator (see
   model_output_service), not silently accepted.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

MODEL_OUTPUT_SCHEMA_VERSION = "1.0"
OUTPUT_TYPES = ("detection_result", "risk_assessment")
EXECUTION_STATUSES = ("completed", "failed", "unknown")
Severity = Literal["info", "warning", "error"]


class DataQualityIndicator(BaseModel):
    code: str
    severity: Severity
    message: str


class ModelRef(BaseModel):
    model_record_id: Optional[str] = None
    name: str
    version: str = Field(min_length=1)
    adapter_key: Optional[str] = None
    evaluation_metadata: dict = Field(default_factory=dict)


class RecordRef(BaseModel):
    type: str
    id: str
    label: Optional[str] = None


class ModelOutput(BaseModel):
    schema_version: str = MODEL_OUTPUT_SCHEMA_VERSION
    output_type: Literal["detection_result", "risk_assessment"]
    output_id: str
    organization_id: str
    model: ModelRef
    input_refs: list[RecordRef] = Field(default_factory=list)
    source_refs: list[RecordRef] = Field(default_factory=list)
    prediction: dict[str, Any]
    confidence: Optional[float] = None
    confidence_provided: bool = False
    confidence_note: Optional[str] = None
    processed_at: datetime
    execution_status: Literal["completed", "failed", "unknown"] = "unknown"
    data_quality: list[DataQualityIndicator] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    explanation_metadata: dict[str, Any] = Field(default_factory=dict)
    supporting_records: list[RecordRef] = Field(default_factory=list)
    review_status: Optional[str] = None

    @field_validator("confidence")
    @classmethod
    def _confidence_in_range(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if isinstance(v, bool) or not math.isfinite(v) or not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be a finite number between 0 and 1")
        return v

    @field_validator("processed_at")
    @classmethod
    def _processed_at_valid(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("processed_at must be timezone-aware")
        if v > datetime.now(timezone.utc):
            raise ValueError("processed_at must not be in the future")
        return v

    @model_validator(mode="after")
    def _confidence_flag_consistent(self) -> "ModelOutput":
        if self.confidence is None and self.confidence_provided:
            raise ValueError("confidence_provided cannot be true when confidence is missing")
        if self.confidence is not None and not self.confidence_provided:
            self.confidence_provided = True
        return self
