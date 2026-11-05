"""Schemas. Unknown fields are rejected; sizes are bounded."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Short = Field(min_length=1, max_length=300)


class ScenarioCreate(_Strict):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    question: Optional[str] = Field(default=None, max_length=1000)
    category: Optional[str] = Field(default=None, min_length=1, max_length=60)
    template_id: Optional[str] = Field(default=None, max_length=60)
    simulator_id: Optional[str] = Field(default=None, max_length=60)
    params: dict[str, Any] = Field(default_factory=dict, max_length=64)
    assumptions: list[str] = Field(default_factory=list, max_length=30)
    limitations: list[str] = Field(default_factory=list, max_length=30)
    seed: int = Field(default=1, ge=0, le=2_147_483_647)
    execution_config: dict[str, Any] = Field(default_factory=dict, max_length=8)
    investigation_id: Optional[str] = Field(default=None, max_length=36)


class ScenarioUpdate(_Strict):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    question: Optional[str] = Field(default=None, max_length=1000)
    category: Optional[str] = Field(default=None, min_length=1, max_length=60)
    params: Optional[dict[str, Any]] = Field(default=None, max_length=64)
    assumptions: Optional[list[str]] = Field(default=None, max_length=30)
    limitations: Optional[list[str]] = Field(default=None, max_length=30)
    seed: Optional[int] = Field(default=None, ge=0, le=2_147_483_647)
    execution_config: Optional[dict[str, Any]] = Field(default=None, max_length=8)
    investigation_id: Optional[str] = Field(default=None, max_length=36)


class ScenarioDuplicate(_Strict):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    params: dict[str, Any] = Field(default_factory=dict, max_length=64)
    seed: Optional[int] = Field(default=None, ge=0, le=2_147_483_647)


class ValidateRequest(_Strict):
    simulator_id: str = Field(max_length=60)
    params: dict[str, Any] = Field(default_factory=dict, max_length=64)
    execution_config: dict[str, Any] = Field(default_factory=dict, max_length=8)


class RunRequest(_Strict):
    seed: Optional[int] = Field(default=None, ge=0, le=2_147_483_647)


class SweepEntry(_Strict):
    param: str = Field(max_length=60)
    values: Optional[list[float]] = Field(default=None, min_length=2, max_length=9)
    min: Optional[float] = None
    max: Optional[float] = None
    steps: Optional[int] = Field(default=None, ge=2, le=9)


class SensitivityRequest(_Strict):
    sweep: list[SweepEntry] = Field(min_length=1, max_length=4)
    repetitions: int = Field(default=5, ge=1, le=20)
    metric: str = Field(max_length=60)
    seed: Optional[int] = Field(default=None, ge=0, le=2_147_483_647)


class CompareRequest(_Strict):
    baseline_run_id: str = Field(max_length=36)
    alternative_run_ids: list[str] = Field(min_length=1, max_length=3)
    scenario_id: Optional[str] = Field(default=None, max_length=36)


class DatasetRequest(_Strict):
    name: str = Field(min_length=1, max_length=200)
    params: dict[str, Any] = Field(default_factory=dict, max_length=64)
    seed: int = Field(default=1, ge=0, le=2_147_483_647)


class ScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    lineage_id: str
    version: int
    parent_scenario_id: Optional[str]
    title: str
    description: Optional[str]
    question: Optional[str]
    category: str
    template_id: Optional[str]
    simulator_id: str
    simulator_version: str
    params: dict
    assumptions: list
    limitations: list
    seed: int
    execution_config: dict
    status: str
    investigation_id: Optional[str]
    owner_user_id: str
    latest_summary: Optional[dict]
    created_at: datetime
    updated_at: datetime
    synthetic: Literal[True] = True
    label: str = "SIMULATED - hypothetical scenario; not evidence"


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    scenario_id: str
    scenario_version: int
    run_kind: str
    status: str
    simulator_id: str
    simulator_version: str
    seed: int
    error_code: Optional[str]
    error_message: Optional[str]
    retry_of_run_id: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]
    runtime_ms: Optional[int]
    result_sha256: Optional[str]
    synthetic: Literal[True] = True


class RunDetail(RunSummary):
    config_snapshot: dict
    dataset_ref: Optional[dict]
    results: Optional[dict]
    idempotency_key: Optional[str]
    requested_by_user_id: str
    idempotent_replay: bool = False
    label: str = "SIMULATED - hypothetical results; not evidence"


class DatasetSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    generator: str
    generator_version: str
    params: dict
    seed: int
    record_count: int
    stored_record_count: int
    records_truncated: bool
    content_sha256: str
    is_synthetic: bool
    generated_at: datetime
    synthetic: Literal[True] = True
    label: str = "SYNTHETIC dataset - not an observation of the real world"
