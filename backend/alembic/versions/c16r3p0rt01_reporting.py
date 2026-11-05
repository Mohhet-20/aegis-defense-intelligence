"""Analytics and reporting: report_runs table and windowed-query indexes

Revision ID: c16r3p0rt01
Revises: b15e0ps0001
Create Date: 2026-10-17 18:00:00

Non-destructive: one new table and seven composite indexes on existing tables
(no column or data changes). Downgrade drops exactly those.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c16r3p0rt01"
down_revision: Union[str, None] = "b15e0ps0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = [
    ("ix_events_org_observed_at", "events", ["organization_id", "observed_at"]),
    ("ix_events_org_ingested_at", "events", ["organization_id", "ingested_at"]),
    ("ix_observations_org_observed_at", "observations", ["organization_id", "observed_at"]),
    ("ix_observations_org_ingested_at", "observations", ["organization_id", "ingested_at"]),
    ("ix_ingestion_jobs_org_started_at", "ingestion_jobs", ["organization_id", "started_at"]),
    ("ix_raw_records_org_received_at", "raw_records", ["organization_id", "received_at"]),
    ("ix_investigations_org_created_at", "investigations", ["organization_id", "created_at"]),
]


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "report_runs",
        sa.Column("id", sa.String(36), primary_key=True), _ts("created_at"), _ts("updated_at"),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("template_key", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("visibility", sa.String(20), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("required_permissions", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("definition_version", sa.String(10), nullable=False),
        _ts("started_at"), _ts("completed_at", True), _ts("expires_at", True),
        sa.Column("sample_summary", sa.JSON(), nullable=False),
        sa.Column("section_status", sa.JSON(), nullable=False),
        sa.Column("artifact_name", sa.String(120), nullable=True),
        sa.Column("artifact_bytes", sa.Integer(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_category", sa.String(40), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_report_runs_org_idempotency_key"),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed', 'expired')", name="ck_report_runs_status"),
        sa.CheckConstraint("format IN ('json', 'csv', 'html')", name="ck_report_runs_format"),
        sa.CheckConstraint("visibility IN ('private', 'organization')", name="ck_report_runs_visibility"),
    )
    op.create_index("ix_report_runs_organization_id", "report_runs", ["organization_id"])
    op.create_index("ix_report_runs_org_created", "report_runs", ["organization_id", "created_at"])
    op.create_index("ix_report_runs_org_status", "report_runs", ["organization_id", "status"])
    for name, table, cols in INDEXES:
        op.create_index(name, table, cols)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
    op.drop_table("report_runs")
