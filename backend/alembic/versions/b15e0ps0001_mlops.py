"""Mlops: model lifecycle columns, experiment runs, baselines, monitoring snapshots, review signals

Revision ID: b15e0ps0001
Revises: a14c0de5ec01
Create Date: 2026-10-17 12:00:00

Non-destructive. Adds nullable/defaulted columns to model_records (every existing
row stays valid), back-fills lifecycle_state from the legacy status column, adds
five new tables, and creates a UNIQUE (name, version) index on model_records only
when no duplicate pairs already exist (duplicates are never deleted to make the
index fit; the migration leaves them alone and logs why). Downgrade drops exactly
what this revision added.
"""
from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b15e0ps0001"
down_revision: Union[str, None] = "a14c0de5ec01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

log = logging.getLogger("alembic.runtime.migration")
UNIQUE_INDEX = "uq_model_records_name_version"


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _base_cols() -> list[sa.Column]:
    return [sa.Column("id", sa.String(36), primary_key=True), _ts("created_at"), _ts("updated_at")]


def upgrade() -> None:
    with op.batch_alter_table("model_records") as batch:
        batch.add_column(sa.Column("owner_organization_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("created_by_user_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("lifecycle_state", sa.String(20), nullable=False, server_default="registered"))
        batch.add_column(sa.Column("artifact_digest", sa.String(64), nullable=True))
        batch.add_column(sa.Column("input_schema_version", sa.String(50), nullable=True))
        batch.add_column(sa.Column("output_schema_version", sa.String(50), nullable=True))
        batch.add_column(sa.Column("framework_metadata", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("release_notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("documentation_ref", sa.String(500), nullable=True))
    op.create_index("ix_model_records_owner_organization_id", "model_records", ["owner_organization_id"])
    op.create_index("ix_model_records_lifecycle_state", "model_records", ["lifecycle_state"])
    op.execute("UPDATE model_records SET lifecycle_state = 'deprecated' WHERE status = 'deprecated'")
    op.execute("UPDATE model_records SET lifecycle_state = 'archived' WHERE status = 'retired'")

    duplicates = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM (SELECT name, version FROM model_records GROUP BY name, version HAVING COUNT(*) > 1) d")).scalar()
    if duplicates:
        log.warning("mlops migration: %s duplicate (name, version) pair(s) exist in model_records; %s NOT created. "
                    "The registry service still rejects new duplicates.", duplicates, UNIQUE_INDEX)
    else:
        op.create_index(UNIQUE_INDEX, "model_records", ["name", "version"], unique=True)

    op.create_table(
        "model_lifecycle_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_record_id", sa.String(36), sa.ForeignKey("model_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("from_state", sa.String(20), nullable=True),
        sa.Column("to_state", sa.String(20), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("actor_organization_id", sa.String(36), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_model_lifecycle_events_model_record_id", "model_lifecycle_events", ["model_record_id"])
    op.create_index("ix_model_lifecycle_events_actor_organization_id", "model_lifecycle_events", ["actor_organization_id"])
    op.create_index("ix_model_lifecycle_events_model_created", "model_lifecycle_events", ["model_record_id", "created_at"])

    op.create_table(
        "experiment_runs",
        *_base_cols(),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_record_id", sa.String(36), sa.ForeignKey("model_records.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("task", sa.String(30), nullable=False),
        sa.Column("experiment_name", sa.String(200), nullable=False),
        sa.Column("purpose", sa.String(1000), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("execution_mode", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column("dataset_name", sa.String(200), nullable=False),
        sa.Column("dataset_version", sa.String(50), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("dataset_fingerprint", sa.String(64), nullable=False),
        sa.Column("config_fingerprint", sa.String(64), nullable=False),
        sa.Column("run_fingerprint", sa.String(64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.Column("methodology", sa.Text(), nullable=True),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("reproducibility", sa.JSON(), nullable=False),
        sa.Column("source_run_type", sa.String(40), nullable=True),
        sa.Column("source_run_id", sa.String(36), nullable=True),
        sa.Column("error_category", sa.String(40), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("initiated_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        _ts("started_at"),
        _ts("completed_at", True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_experiment_runs_org_idempotency_key"),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="ck_experiment_runs_status"),
        sa.CheckConstraint("task IN ('object_detection', 'classification')", name="ck_experiment_runs_task"),
    )
    for col in ("organization_id", "model_record_id", "status", "run_fingerprint"):
        op.create_index(f"ix_experiment_runs_{col}", "experiment_runs", [col])
    op.create_index("ix_experiment_runs_org_model_started", "experiment_runs", ["organization_id", "model_record_id", "started_at"])
    op.create_index("ix_experiment_runs_org_task_dataset", "experiment_runs", ["organization_id", "task", "dataset_name", "dataset_version"])

    op.create_table(
        "experiment_baselines",
        *_base_cols(),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task", sa.String(30), nullable=False),
        sa.Column("dataset_name", sa.String(200), nullable=False),
        sa.Column("dataset_version", sa.String(50), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("experiment_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("selected_by_user_id", sa.String(36), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=True),
        _ts("selected_at"),
        sa.UniqueConstraint("organization_id", "task", "dataset_name", "dataset_version", name="uq_experiment_baselines_scope"),
    )
    op.create_index("ix_experiment_baselines_organization_id", "experiment_baselines", ["organization_id"])

    op.create_table(
        "monitoring_snapshots",
        *_base_cols(),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_record_id", sa.String(36), sa.ForeignKey("model_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("reference_snapshot_id", sa.String(36), sa.ForeignKey("monitoring_snapshots.id", ondelete="SET NULL"), nullable=True),
        _ts("window_start"),
        _ts("window_end"),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("labelled_count", sa.Integer(), nullable=False),
        sa.Column("schema_violation_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=True),
        sa.CheckConstraint("kind IN ('reference', 'current')", name="ck_monitoring_snapshots_kind"),
    )
    op.create_index("ix_monitoring_snapshots_organization_id", "monitoring_snapshots", ["organization_id"])
    op.create_index("ix_monitoring_snapshots_model_record_id", "monitoring_snapshots", ["model_record_id"])
    op.create_index("ix_monitoring_snapshots_org_model_end", "monitoring_snapshots", ["organization_id", "model_record_id", "window_end"])

    op.create_table(
        "review_signals",
        *_base_cols(),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("dedup_key", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("summary", sa.String(2000), nullable=False),
        sa.Column("subsystem", sa.String(60), nullable=True),
        sa.Column("model_record_id", sa.String(36), sa.ForeignKey("model_records.id", ondelete="CASCADE"), nullable=True),
        sa.Column("experiment_run_id", sa.String(36), sa.ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("monitoring_snapshots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("observed_value", sa.Float(), nullable=True),
        sa.Column("threshold_value", sa.Float(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.String(1000), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        _ts("first_seen_at"),
        _ts("last_seen_at"),
        sa.Column("assigned_to_user_id", sa.String(36), nullable=True),
        sa.Column("acknowledged_by_user_id", sa.String(36), nullable=True),
        _ts("acknowledged_at", True),
        sa.Column("resolved_by_user_id", sa.String(36), nullable=True),
        _ts("resolved_at", True),
        sa.Column("resolution_notes", sa.String(2000), nullable=True),
        sa.CheckConstraint("status IN ('open', 'acknowledged', 'resolved')", name="ck_review_signals_status"),
        sa.CheckConstraint("severity IN ('info', 'warning', 'serious', 'critical')", name="ck_review_signals_severity"),
        sa.CheckConstraint(
            "category IN ('evaluation_failed', 'metric_regression', 'metric_below_floor', 'artifact_unavailable', 'evaluation_stale', "
            "'job_failure_rate', 'input_schema_violations', 'insufficient_data', 'data_drift', 'prediction_drift', 'performance_degradation')",
            name="ck_review_signals_category",
        ),
    )
    for col in ("organization_id", "category", "model_record_id", "experiment_run_id"):
        op.create_index(f"ix_review_signals_{col}", "review_signals", [col])
    op.create_index("ix_review_signals_org_dedup", "review_signals", ["organization_id", "dedup_key"])
    op.create_index("ix_review_signals_org_status_sev", "review_signals", ["organization_id", "status", "severity"])


def downgrade() -> None:
    op.drop_table("review_signals")
    op.drop_table("monitoring_snapshots")
    op.drop_table("experiment_baselines")
    op.drop_table("experiment_runs")
    op.drop_table("model_lifecycle_events")
    bind = op.get_bind()
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes("model_records")}
    if UNIQUE_INDEX in existing:
        op.drop_index(UNIQUE_INDEX, table_name="model_records")
    op.drop_index("ix_model_records_lifecycle_state", table_name="model_records")
    op.drop_index("ix_model_records_owner_organization_id", table_name="model_records")
    with op.batch_alter_table("model_records") as batch:
        for col in ("documentation_ref", "release_notes", "framework_metadata", "output_schema_version", "input_schema_version",
                    "artifact_digest", "lifecycle_state", "created_by_user_id", "owner_organization_id"):
            batch.drop_column(col)
