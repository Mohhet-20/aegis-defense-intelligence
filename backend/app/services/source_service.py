from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.registry import get_connector_class, is_connector_driven
from app.models.data_source import DataSource


def create_source(
    db: Session,
    *,
    organization_id: str,
    name: str,
    source_type: str,
    description: Optional[str],
    reliability_weight: float,
    config_metadata: dict,
    owner_team: Optional[str] = None,
    connection_mode: str = "file_upload",
    enabled: bool = True,
) -> DataSource:
    source = DataSource(
        organization_id=organization_id,
        name=name,
        source_type=source_type,
        description=description,
        reliability_weight=reliability_weight,
        config_metadata=config_metadata,
        owner_team=owner_team,
        connection_mode=connection_mode,
        enabled=enabled,
        status="active",
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def get_source(db: Session, organization_id: str, source_id: str) -> Optional[DataSource]:
    stmt = select(DataSource).where(DataSource.id == source_id, DataSource.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_sources_query(organization_id: str):
    return select(DataSource).where(DataSource.organization_id == organization_id).order_by(DataSource.created_at.desc())


def update_source(db: Session, source: DataSource, **fields) -> DataSource:
    """Generic field update. `config_metadata` changes bump
    config_revision ("config revision" lets provenance say
    which version of a source's configuration produced a given batch).
    A reliability_weight change is NOT accepted here -- see
    set_reliability_weight(), which requires a documented reason."""
    fields.pop("reliability_weight", None)
    for key, value in fields.items():
        if value is not None:
            setattr(source, key, value)
            if key == "config_metadata":
                source.config_revision += 1
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def set_reliability_weight(db: Session, source: DataSource, *, weight: float, reason: str) -> DataSource:
    """Reliability weight is a configured ASSUMPTION about how much to
    trust a source's reports -- Section 16's explicit rule that a
    significant manual change needs a documented reason, and that this
    number is never auto-derived from correlation/duplication counts.
    The caller (the API route) is responsible for writing the audit
    record that actually stores `reason`; this function only validates
    and applies the new value."""
    if not reason or not reason.strip():
        raise ValueError("a documented reason is required to change a source's reliability weight")
    source.reliability_weight = weight
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def enable_source(db: Session, source: DataSource) -> DataSource:
    source.enabled = True
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def disable_source(db: Session, source: DataSource) -> DataSource:
    source.enabled = False
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def validate_configuration(source: DataSource) -> list[str]:
    """Returns human-readable configuration problems, or an empty list
    if the configuration is valid. A source type with no connector
    (file_upload-only sources like "manual") has nothing to validate --
    its "configuration" IS the uploaded file, not stored config."""
    connector_cls = get_connector_class(source.source_type)
    if connector_cls is None:
        return []
    connector = connector_cls(source.config_metadata or {})
    try:
        return connector.validate_config()
    finally:
        connector.close()


def check_connectivity(source: DataSource) -> tuple[bool, Optional[str]]:
    """Best-effort reachability probe. A non-connector-driven source
    (file upload only) has no endpoint to probe -- (True, None) means
    "not applicable," never "confirmed live," and the API layer must
    say so explicitly rather than implying a live connection exists."""
    if not is_connector_driven(source.source_type):
        return True, None
    connector_cls = get_connector_class(source.source_type)
    connector = connector_cls(source.config_metadata or {})
    try:
        return connector.check_connectivity()
    finally:
        connector.close()


def record_connectivity_result(db: Session, source: DataSource, *, ok: bool, error_category: Optional[str] = None) -> DataSource:
    source.last_ingestion_attempt_at = datetime.now(timezone.utc)
    source.last_error_category = None if ok else (error_category or "unknown")
    db.add(source)
    db.commit()
    db.refresh(source)
    return source
