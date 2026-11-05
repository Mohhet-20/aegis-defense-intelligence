"""Security governance: token version, lifecycle requests, audit triggers

Revision ID: a14c0de5ec01
Revises: 980f1f55cbaa
Create Date: 2026-10-16 10:00:00

Non-destructive: adds two nullable/defaulted user columns, one new table and
(optionally) database triggers that reject UPDATE/DELETE on audit_records.
No existing row is modified or removed. Downgrade drops exactly what this
revision added.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a14c0de5ec01"
down_revision: Union[str, None] = "980f1f55cbaa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_triggers_up(dialect: str) -> None:
    if dialect == "sqlite":
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS trg_audit_records_no_update BEFORE UPDATE ON audit_records "
            "BEGIN SELECT RAISE(ABORT, 'audit_records is append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS trg_audit_records_no_delete BEFORE DELETE ON audit_records "
            "BEGIN SELECT RAISE(ABORT, 'audit_records is append-only'); END"
        )
    elif dialect == "postgresql":
        op.execute(
            "CREATE OR REPLACE FUNCTION aegis_audit_append_only() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'audit_records is append-only'; END; $$ LANGUAGE plpgsql"
        )
        op.execute("DROP TRIGGER IF EXISTS trg_audit_records_append_only ON audit_records")
        op.execute(
            "CREATE TRIGGER trg_audit_records_append_only BEFORE UPDATE OR DELETE ON audit_records "
            "FOR EACH ROW EXECUTE FUNCTION aegis_audit_append_only()"
        )


def _audit_triggers_down(dialect: str) -> None:
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_records_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_records_no_delete")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_records_append_only ON audit_records")
        op.execute("DROP FUNCTION IF EXISTS aegis_audit_append_only()")


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "lifecycle_requests",
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by_user_id", sa.String(36), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(500), nullable=True),
        sa.Column("executed_by_user_id", sa.String(36), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("impact", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action in ('archive','delete')", name="ck_lifecycle_action"),
        sa.CheckConstraint(
            "status in ('pending','approved','rejected','executed','cleanup_pending','failed','cancelled')",
            name="ck_lifecycle_status",
        ),
    )
    op.create_index("ix_lifecycle_requests_organization_id", "lifecycle_requests", ["organization_id"])
    op.create_index("ix_lifecycle_requests_org_status", "lifecycle_requests", ["organization_id", "status", "created_at"])
    op.create_index("ix_lifecycle_requests_target", "lifecycle_requests", ["organization_id", "resource_type", "resource_id"])
    _audit_triggers_up(dialect)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    _audit_triggers_down(dialect)
    op.drop_index("ix_lifecycle_requests_target", table_name="lifecycle_requests")
    op.drop_index("ix_lifecycle_requests_org_status", table_name="lifecycle_requests")
    op.drop_index("ix_lifecycle_requests_organization_id", table_name="lifecycle_requests")
    op.drop_table("lifecycle_requests")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("password_changed_at")
        batch.drop_column("token_version")
