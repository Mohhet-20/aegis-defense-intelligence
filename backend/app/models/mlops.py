"""The MLOps layer MLOps tables: lifecycle history, experiment runs, baselines,
monitoring snapshots and review signals.

Design notes
 * `ModelRecord` remains THE model-version registry; nothing here
   duplicates it. A "model family" is the set of ModelRecord rows sharing a
   `name`, exposed as a view -- there is no second registry table.
 * `ExperimentRun` is the unified tracking ledger. It links to the underlying
   computer-vision / explainable-AI evaluation rows (`source_run_type` / `source_run_id`)
   instead of replacing them.
 * `ReviewSignal` is deliberately separate from `InfrastructureAlert` (fleet
   health, the fleet layer) and from intelligence Events: it is about MODEL quality and
   MLOps subsystem health, and never about a real-world condition.
 * Everything except `ModelLifecycleEvent` is organization-scoped.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

EXPERIMENT_STATUSES = ("running", "succeeded", "failed")
EXPERIMENT_TASKS = ("object_detection", "classification")
SNAPSHOT_KINDS = ("reference", "current")
SIGNAL_STATUSES = ("open", "acknowledged", "resolved")
SIGNAL_SEVERITIES = ("info", "warning", "serious", "critical")
SIGNAL_CATEGORIES = (
    "evaluation_failed", "metric_regression", "metric_below_floor", "artifact_unavailable", "evaluation_stale",
    "job_failure_rate", "input_schema_violations", "insufficient_data", "data_drift", "prediction_drift",
    "performance_degradation",
)


class AppendOnlyError(RuntimeError):
    pass


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class ModelLifecycleEvent(Base, UUIDPrimaryKeyMixin):
    """Append-only history of a model version's governance transitions.
    Platform-level (ModelRecord is global), so it carries the actor's
    organization id and readers only see actor identity for their own org."""

    __tablename__ = "model_lifecycle_events"
    __table_args__ = (Index("ix_model_lifecycle_events_model_created", "model_record_id", "created_at"),)

    model_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("model_records.id", ondelete="CASCADE"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    from_state: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    actor_organization_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    reason: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


@event.listens_for(ModelLifecycleEvent, "before_update")
@event.listens_for(ModelLifecycleEvent, "before_delete")
def _lifecycle_event_append_only(mapper, connection, target) -> None:  # noqa: ARG001
    raise AppendOnlyError("model_lifecycle_events is append-only")


class ExperimentRun(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "experiment_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_experiment_runs_org_idempotency_key"),
        CheckConstraint(f"status IN ({_in(EXPERIMENT_STATUSES)})", name="ck_experiment_runs_status"),
        CheckConstraint(f"task IN ({_in(EXPERIMENT_TASKS)})", name="ck_experiment_runs_task"),
        Index("ix_experiment_runs_org_model_started", "organization_id", "model_record_id", "started_at"),
        Index("ix_experiment_runs_org_task_dataset", "organization_id", "task", "dataset_name", "dataset_version"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    model_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("model_records.id", ondelete="RESTRICT"), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    task: Mapped[str] = mapped_column(String(30), nullable=False)
    experiment_name: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    execution_mode: Mapped[str] = mapped_column(String(40), nullable=False)  # adapter_inference_on_fixture | scored_submitted_predictions
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    dataset_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(50), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(nullable=False, default=True)
    dataset_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    run_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Full validated configuration. Classification sample payloads are NOT stored
    # here (only their count + fingerprint); the scored detail lives in the linked
    # source run, which is subject to the existing size limits.
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # only for status == succeeded
    sample_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    methodology: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    reproducibility: Mapped[dict] = mapped_column(JSON, default=dict)

    source_run_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    source_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    error_category: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    initiated_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class ExperimentBaseline(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """The explicitly selected baseline run for one (task, dataset name+version)
    within an organization. Never inferred from 'best' or 'latest'."""

    __tablename__ = "experiment_baselines"
    __table_args__ = (
        UniqueConstraint("organization_id", "task", "dataset_name", "dataset_version", name="uq_experiment_baselines_scope"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    task: Mapped[str] = mapped_column(String(30), nullable=False)
    dataset_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(50), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("experiment_runs.id", ondelete="RESTRICT"), nullable=False)
    selected_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    selected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class MonitoringSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """A bounded summary of one monitoring window for a model version. Only the
    summary is stored -- never the submitted rows."""

    __tablename__ = "monitoring_snapshots"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_in(SNAPSHOT_KINDS)})", name="ck_monitoring_snapshots_kind"),
        Index("ix_monitoring_snapshots_org_model_end", "organization_id", "model_record_id", "window_end"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    model_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("model_records.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    reference_snapshot_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("monitoring_snapshots.id", ondelete="SET NULL"), nullable=True)
    window_start: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    window_end: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    labelled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schema_violation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class ReviewSignal(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "review_signals"
    __table_args__ = (
        CheckConstraint(f"status IN ({_in(SIGNAL_STATUSES)})", name="ck_review_signals_status"),
        CheckConstraint(f"severity IN ({_in(SIGNAL_SEVERITIES)})", name="ck_review_signals_severity"),
        CheckConstraint(f"category IN ({_in(SIGNAL_CATEGORIES)})", name="ck_review_signals_category"),
        Index("ix_review_signals_org_dedup", "organization_id", "dedup_key"),
        Index("ix_review_signals_org_status_sev", "organization_id", "status", "severity"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(String(2000), nullable=False)
    subsystem: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    model_record_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("model_records.id", ondelete="CASCADE"), nullable=True, index=True)
    experiment_run_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=True, index=True)
    snapshot_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("monitoring_snapshots.id", ondelete="SET NULL"), nullable=True)
    observed_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    threshold_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    limitations: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    assigned_to_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    acknowledged_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    resolved_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
