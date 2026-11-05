from __future__ import annotations

from typing import Optional

from sqlalchemy import JSON, Index, String, Text, event, inspect
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MODEL_RECORD_STATUSES = ("registered", "active", "deprecated", "retired")

# which task a registered model actually performs.
# NULL (the default, unchanged for the seeded "demo-risk-scorer"
# row) means "not a task this registry has a real pipeline for yet" --
# exactly the placeholder the row already was. Only
# "object_detection" rows are ever offered to the CV inference pipeline
# (app/cv/registry.py); nothing here assumes every ModelRecord is a CV
# model.
MODEL_TASK_TYPES = ("object_detection",)

# Tasks the MLOps registry can track. "object_detection" is the only
# task the CV inference pipeline runs; "classification" is registry/evaluation
# only (AEGIS scores predictions a caller supplies; it does not execute the model).
MLOPS_TASK_TYPES = ("object_detection", "classification")

# Governance lifecycle. Evaluation status ("none/running/passed/failed/
# stale") is DERIVED from experiment runs at read time, never stored, so it
# cannot drift from the evidence. The legacy `status` column still decides CV
# inference eligibility; see model_registry_lifecycle for the mapping.
MODEL_LIFECYCLE_STATES = ("registered", "review_required", "approved", "deprecated", "archived")

# Columns that identify what a registered version IS. After registration they can
# never change (a correction is a new version). Guarded below at the ORM layer.
MODEL_IMMUTABLE_COLUMNS = (
    "name", "version", "model_type", "task_type", "adapter_key", "supported_media_types", "artifact_reference",
    "artifact_digest", "input_schema_version", "output_schema_version", "framework_metadata", "release_notes",
    "documentation_ref", "owner_organization_id", "created_by_user_id",
)


class ModelImmutableError(RuntimeError):
    """A registered model version's identifying fields cannot be modified."""


class ModelRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Platform-level model registry row -- see
    docs/architecture/AI_ANALYTICS_CONTRACTS.md (the eventual
    owner for non-CV models) and docs/ml/MODEL_REGISTRY.md (this
    layer's real consumer). Not organization-scoped: a model version is
    a platform-level artifact, referenced by (not owned by) any
    organization's RiskAssessment/InferenceJob/DetectionResult rows.

    Shipped this as an inert placeholder (`adapter_key`/
    `task_type`/`supported_media_types` did not exist; nothing read
    `evaluation_metadata`). The computer-vision layer extends it -- rather than building a
    parallel `CVModel` table -- with exactly the columns the real CV
    inference pipeline needs to resolve a row to a runnable adapter. All
    three additions are nullable with no backfill required: the existing
    seeded `demo-risk-scorer` row keeps `task_type IS NULL` and is simply
    invisible to the CV model registry list, unchanged in every other
    respect.
    """

    __tablename__ = "model_records"
    # Mirrors migration b15e0ps0001, which creates this index (it skips it, with a
    # warning, only if legacy duplicate pairs exist). The registry service enforces
    # the same rule; declaring it keeps `alembic check` / create_all in step.
    __table_args__ = (Index("uq_model_records_name_version", "name", "version", unique=True),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    model_type: Mapped[str] = mapped_column(String(50), nullable=False)
    artifact_reference: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    evaluation_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="registered")

    # --- computer vision infrastructure ----------
    # Which task this model performs -- see MODEL_TASK_TYPES above.
    task_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    # Key into app/cv/registry.py's ADAPTERS map -- the one thing that
    # actually decides which Python code runs inference for this row.
    # Never a free-form class path or a remote URL: always one of a
    # small, explicitly-registered set, so a model_record can never
    # cause this platform to import or execute arbitrary code.
    adapter_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # JSON list of "image" / "video" -- which media types this
    # model/adapter is able to run against. Checked before an inference
    # job is ever submitted.
    supported_media_types: Mapped[list] = mapped_column(JSON, default=list)

    # --- MLOps registry. All nullable / defaulted, so every
    # pre-existing row is valid unchanged. ---------------------------------------
    # Organization that registered this version through the MLOps API. NULL = a
    # platform-level pre-original row, visible to every organization (as before).
    # Non-NULL rows are visible only to the owning organization.
    owner_organization_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    lifecycle_state: Mapped[str] = mapped_column(String(20), nullable=False, default="registered", server_default="registered", index=True)
    artifact_digest: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # sha256 hex of the artifact, when one exists
    input_schema_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    output_schema_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    framework_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)  # framework / runtime compatibility notes (bounded, validated)
    release_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    documentation_ref: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


@event.listens_for(ModelRecord, "before_update")
def _guard_immutable_columns(mapper, connection, target) -> None:  # noqa: ARG001
    # Applies to versions registered through the MLOps API (they carry an owner
    # organization). Pre-original platform-level rows (owner NULL) keep their
    # original behaviour: existing code and tests legitimately edit them,
    # so immutability is NOT enforced for those rows (documented limitation).
    if target.owner_organization_id is None:
        return
    state = inspect(target)
    for column in MODEL_IMMUTABLE_COLUMNS:
        history = state.attrs[column].history
        if history.has_changes() and history.deleted:
            # `deleted` holds the previous value. Owned rows are fully immutable:
            # even filling a previously-NULL field is refused.
            old = history.deleted[0]
            new = history.added[0] if history.added else None
            if old != new:
                raise ModelImmutableError(f"model version field '{column}' is immutable after registration; register a new version instead")
