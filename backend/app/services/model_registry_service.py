"""CV model registry. Thin CRUD/listing over the
existing, Phase-1 `ModelRecord` table -- extended, not duplicated, with
the `task_type`/`adapter_key`/`supported_media_types` columns Phase 4
added (see app/models/model_record.py). A non-CV ModelRecord (NULL
task_type, like the seeded "demo-risk-scorer" row) is simply never
returned by `list_cv_models_query()`.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.cv.adapters.registry import available_adapter_keys
from app.models.model_record import MODEL_TASK_TYPES, ModelRecord

VALID_MEDIA_TYPES = ("image", "video")


def register_cv_model(
    db: Session,
    *,
    name: str,
    version: str,
    adapter_key: str,
    supported_media_types: list[str],
    status: str = "active",
) -> ModelRecord:
    if adapter_key not in available_adapter_keys():
        raise ValueError(f"adapter_key '{adapter_key}' is not a registered adapter -- available: {available_adapter_keys()}")
    for media_type in supported_media_types:
        if media_type not in VALID_MEDIA_TYPES:
            raise ValueError(f"'{media_type}' is not a supported media type (must be one of {VALID_MEDIA_TYPES})")

    existing_stmt = select(ModelRecord).where(ModelRecord.name == name, ModelRecord.version == version)
    existing = db.execute(existing_stmt).scalar_one_or_none()
    if existing is not None:
        return existing

    model_record = ModelRecord(
        name=name,
        version=version,
        model_type="computer_vision",
        task_type="object_detection",
        adapter_key=adapter_key,
        supported_media_types=list(supported_media_types),
        status=status,
        evaluation_metadata={},
    )
    db.add(model_record)
    db.commit()
    db.refresh(model_record)
    return model_record


def get_cv_model(db: Session, model_record_id: str, organization_id: Optional[str] = None) -> Optional[ModelRecord]:
    """`organization_id`: when given, a version registered by a
    DIFFERENT organization through the MLOps API is treated as not found.
    Platform-level rows (owner NULL, i.e. everything registered before Phase 15)
    stay visible to every organization, exactly as before."""
    model_record = db.get(ModelRecord, model_record_id)
    if model_record is None or model_record.task_type not in MODEL_TASK_TYPES:
        return None
    if organization_id is not None and model_record.owner_organization_id not in (None, organization_id):
        return None
    return model_record


def list_cv_models_query(*, media_type: Optional[str] = None, organization_id: Optional[str] = None):
    stmt = select(ModelRecord).where(ModelRecord.task_type.in_(MODEL_TASK_TYPES))
    if organization_id is not None:
        stmt = stmt.where(or_(ModelRecord.owner_organization_id.is_(None), ModelRecord.owner_organization_id == organization_id))
    if media_type:
        # supported_media_types is a JSON list -- filtered in Python
        # after the query rather than a dialect-specific JSON
        # containment operator, so this works identically on SQLite
        # (tests, local dev) and Postgres (production).
        pass
    return stmt.order_by(ModelRecord.created_at.desc())


def model_supports_media_type(model_record: ModelRecord, media_type: str) -> bool:
    return media_type in (model_record.supported_media_types or [])
