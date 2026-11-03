"""Request/response schemas for Phase 10 analytics routes."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.analytics.metrics import MAX_SAMPLES
from app.analytics.scoring import ADVISORY_NOTICE
from app.models.assessment_review import INFORMATION_FLAGS, REVIEW_DECISIONS


# ------------------------------ evaluation ------------------------------
class EvaluationSample(BaseModel):
    sample_ref: Optional[str] = Field(default=None, max_length=200)
    true_label: Optional[str] = Field(default=None, max_length=100)  # None = unlabelled; excluded and counted
    predicted_label: str = Field(min_length=1, max_length=100)
    positive_probability: Optional[float] = None  # model-provided P(positive_label); never invented

    @field_validator("positive_probability")
    @classmethod
    def _prob(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (not math.isfinite(v) or not 0.0 <= v <= 1.0):
            raise ValueError("positive_probability must be a finite number between 0 and 1")
        return v


class ClassificationEvaluationRequest(BaseModel):
    model_record_id: str
    model_version: Optional[str] = Field(default=None, max_length=50)  # if given, must equal the registry version
    dataset_name: str = Field(min_length=1, max_length=200)
    dataset_version: str = Field(min_length=1, max_length=50)
    dataset_reference: Optional[str] = Field(default=None, max_length=500)
    is_synthetic: bool  # required: the submitter must declare it
    labels: Optional[list[str]] = Field(default=None, max_length=100)
    positive_label: Optional[str] = Field(default=None, max_length=100)
    samples: list[EvaluationSample] = Field(max_length=MAX_SAMPLES)

    @model_validator(mode="after")
    def _probabilities_need_positive_label(self) -> "ClassificationEvaluationRequest":
        if any(s.positive_probability is not None for s in self.samples) and not self.positive_label:
            raise ValueError("positive_label is required when positive_probability values are supplied")
        return self


class ClassificationEvaluationResponse(BaseModel):
    id: str
    model_record_id: str
    model_version: str
    dataset_name: str
    dataset_version: str
    dataset_reference: Optional[str]
    is_synthetic: bool
    performance_claim: str
    sample_count: int
    excluded_missing_label: int
    evaluation_config: dict
    metric_definitions: dict
    results: Optional[dict]
    warnings: list
    status: str
    error_message: Optional[str]
    evaluated_by_user_id: Optional[str]
    evaluated_at: datetime


class EvaluationOverviewRow(BaseModel):
    kind: str  # classification | detection | tracking
    id: str
    model_record_id: Optional[str]
    model_name: Optional[str]
    model_version: Optional[str]
    dataset_name: str
    dataset_version: str
    is_synthetic: Optional[bool]
    status: str
    headline_metrics: dict
    evaluated_at: datetime


# ----------------------------- explanations -----------------------------
class ExplanationMethodInfo(BaseModel):
    method_key: str
    label: str
    explanation_kind: str
    supported: bool
    limitation: Optional[str]


class ExplanationResponse(BaseModel):
    output_type: str
    output_id: str
    supported: bool
    method_key: Optional[str]
    label: Optional[str] = None
    explanation_kind: Optional[str] = None
    items: list[dict] = Field(default_factory=list)
    method_detail: Optional[str] = None
    interpretation_note: Optional[str] = None
    limitation: Optional[str] = None
    available_methods: list[ExplanationMethodInfo]
    data_quality: list[dict] = Field(default_factory=list)


# -------------------------------- scoring -------------------------------
class ScoreRequest(BaseModel):
    rule_key: str = Field(default="review_priority_v1", max_length=60)
    config_overrides: Optional[dict[str, Any]] = None


class ScoreSnapshotResponse(BaseModel):
    id: str
    assessment_id: str
    assessment_version: int
    rule_key: str
    rule_version: str
    rule_config: dict
    score: float
    score_scale: str
    priority_band: str
    factors: list
    distinct_concepts: dict
    evidence_considered: list
    data_quality_limitations: list
    conflicts: list
    missing_information: list
    computed_at: datetime
    computed_by_user_id: Optional[str]
    advisory_notice: str = ADVISORY_NOTICE

    model_config = {"from_attributes": True}


# -------------------------------- review --------------------------------
class ReviewRequest(BaseModel):
    decision: str
    notes: str = Field(min_length=1, max_length=2000)
    change_reason: Optional[str] = Field(default=None, max_length=1000)
    information_flags: list[str] = Field(default_factory=list)
    score_snapshot_id: Optional[str] = None

    @field_validator("decision")
    @classmethod
    def _decision(cls, v: str) -> str:
        if v not in REVIEW_DECISIONS:
            raise ValueError(f"decision must be one of {REVIEW_DECISIONS}")
        return v

    @field_validator("information_flags")
    @classmethod
    def _flags(cls, v: list[str]) -> list[str]:
        bad = [f for f in v if f not in INFORMATION_FLAGS]
        if bad:
            raise ValueError(f"information_flags must be within {INFORMATION_FLAGS}; got {bad}")
        return sorted(set(v))

    @field_validator("notes")
    @classmethod
    def _notes_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("notes must not be blank")
        return v


class ReviewResponse(BaseModel):
    id: str
    assessment_id: str
    assessment_version: int
    score_snapshot_id: Optional[str]
    decision: str
    notes: str
    change_reason: Optional[str]
    information_flags: list
    advisory_score_at_review: Optional[float]
    advisory_band_at_review: Optional[str]
    reviewer_user_id: Optional[str]
    supersedes_review_id: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ReviewSummaryResponse(BaseModel):
    assessment_id: str
    current_assessment_version: int
    review_status: str  # unreviewed | accepted | rejected | further_review_requested
    latest_review: Optional[ReviewResponse]
    latest_score: Optional[ScoreSnapshotResponse]
    comparison: dict  # advisory vs human
    history: list[ReviewResponse]
