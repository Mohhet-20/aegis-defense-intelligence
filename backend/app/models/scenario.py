"""Phase 13: scenario definitions, runs and synthetic datasets.

Definitions (Scenario) are kept apart from execution results (ScenarioRun);
a run stores an immutable config snapshot so history is never overwritten.
Everything here is SIMULATED: these tables are never read by operational
observation/event/evidence code and nothing in them is evidence."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

SCENARIO_STATUSES = ("draft", "ready", "archived")
RUN_STATUSES = ("running", "completed", "failed")
RUN_KINDS = ("simulation", "sensitivity")


class Scenario(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "scenarios"
    __table_args__ = (
        UniqueConstraint("organization_id", "lineage_id", "version", name="uq_scenario_lineage_version"),
        Index("ix_scenarios_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    lineage_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_scenario_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    question: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    category: Mapped[str] = mapped_column(String(60), nullable=False, default="general")
    template_id: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    simulator_id: Mapped[str] = mapped_column(String(60), nullable=False)
    simulator_version: Mapped[str] = mapped_column(String(20), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    assumptions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    limitations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    seed: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    execution_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    investigation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    latest_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class ScenarioRun(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "scenario_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "scenario_id", "idempotency_key", name="uq_scenario_run_idem"),
        Index("ix_scenario_runs_history", "organization_id", "scenario_id", "created_at"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False)
    run_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="simulation")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    simulator_id: Mapped[str] = mapped_column(String(60), nullable=False)
    simulator_version: Mapped[str] = mapped_column(String(20), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    dataset_ref: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    results: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    retry_of_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    runtime_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    requested_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)


class SyntheticDataset(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """Isolated synthetic records. `is_synthetic` is always true and has a
    CHECK-like guard in the service; no operational table is ever written."""
    __tablename__ = "synthetic_datasets"
    __table_args__ = (Index("ix_synthetic_datasets_org", "organization_id", "created_at"),)

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    generator: Mapped[str] = mapped_column(String(80), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(20), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    stored_record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    records_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    records: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    header: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
