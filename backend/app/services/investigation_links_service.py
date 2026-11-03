"""Link existing records to an investigation (references only, never copies).

Every link target is resolved with an organization filter, so a record
from another organization is indistinguishable from a missing one.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assessment import Assessment
from app.models.data_source import DataSource
from app.models.detection_result import DetectionResult
from app.models.event import Event
from app.models.evidence import Evidence
from app.models.investigation import Investigation
from app.models.investigation_workspace import LINK_RECORD_TYPES, InvestigationLink
from app.models.media_asset import MediaAsset
from app.models.observation import Observation
from app.models.sensor import Sensor
from app.models.track import Track
from app.services import audit_service
from app.services.investigation_service import assert_mutable
from app.services.timeutil import iso
from app.services.workspace_errors import conflict, invalid, not_found

MODELS: dict[str, Any] = {
    "event": Event,
    "observation": Observation,
    "assessment": Assessment,
    "data_source": DataSource,
    "sensor": Sensor,
    "media_asset": MediaAsset,
    "evidence": Evidence,
    "detection_result": DetectionResult,
    "track": Track,
}
assert set(MODELS) == set(LINK_RECORD_TYPES)


def resolve_record(db: Session, organization_id: str, record_type: str, record_id: str):
    model = MODELS.get(record_type)
    if model is None:
        raise invalid(f"record_type must be one of {LINK_RECORD_TYPES}")
    if not record_id or len(record_id) > 36:
        raise invalid("record_id is malformed")
    return db.execute(select(model).where(model.id == record_id, model.organization_id == organization_id)).scalar_one_or_none()


def describe(record_type: str, row) -> dict:
    """Uniform, read-only summary of a linked record. Nothing is invented:
    attributes a record type does not have are None."""
    d = {
        "record_type": record_type, "record_id": row.id, "title": None, "summary": None,
        "source_id": None, "review_status": None, "data_quality": "unknown",
        "primary_time": None, "primary_time_kind": None,
    }
    if record_type == "event":
        d.update(title=row.title, summary=row.description, source_id=row.source_id, primary_time=iso(row.observed_at), primary_time_kind="event_time")
    elif record_type == "observation":
        flags = list(row.quality_flags or [])
        d.update(
            title=f"{row.observation_type} observation", source_id=row.source_id,
            primary_time=iso(row.observed_at), primary_time_kind="observation_time",
            data_quality=("flagged" if flags or row.validation_status != "valid" else "clean"),
            summary=f"validation_status={row.validation_status}" + (f"; flags={flags}" if flags else ""),
        )
    elif record_type == "assessment":
        d.update(title=row.title, summary=row.summary, review_status=row.status, primary_time=iso(row.created_at), primary_time_kind="record_created")
    elif record_type == "data_source":
        d.update(title=row.name, summary=row.description, source_id=row.id)
    elif record_type == "sensor":
        d.update(title=row.name, summary=row.description, source_id=row.source_id)
    elif record_type == "media_asset":
        d.update(title=row.declared_filename, summary=f"{row.media_type} {row.detected_mime_type}, {row.byte_size} bytes", primary_time=iso(row.created_at), primary_time_kind="registration_time")
    elif record_type == "evidence":
        d.update(title=row.title, summary=row.summary, source_id=row.source_id, review_status=row.review_status, primary_time=iso(row.created_at), primary_time_kind="registration_time")
    elif record_type == "detection_result":
        d.update(title=f"{row.class_label} detection", review_status=row.review_status, primary_time=iso(row.created_at), primary_time_kind="processing_time", summary=f"confidence={row.confidence:.3f} (model-reported)")
    elif record_type == "track":
        d.update(title=f"Track {row.sequence_track_id}", summary=f"state={row.state}", primary_time=iso(row.created_at), primary_time_kind="processing_time")
    return d


def link_record(
    db: Session, investigation: Investigation, *, record_type: str, record_id: str,
    note: Optional[str], actor_user_id: str, request_id: Optional[str] = None,
) -> InvestigationLink:
    assert_mutable(investigation)
    row = resolve_record(db, investigation.organization_id, record_type, record_id)
    if row is None:
        raise not_found(f"{record_type}")
    dup = db.execute(
        select(InvestigationLink.id).where(
            InvestigationLink.investigation_id == investigation.id,
            InvestigationLink.record_type == record_type, InvestigationLink.record_id == record_id,
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise conflict(f"That {record_type} is already linked to this investigation")
    link = InvestigationLink(
        organization_id=investigation.organization_id, investigation_id=investigation.id,
        record_type=record_type, record_id=record_id, note=note, linked_by_user_id=actor_user_id,
    )
    db.add(link)
    audit_service.record(
        db, action="investigation.link_add", actor_user_id=actor_user_id, organization_id=investigation.organization_id,
        target_type="investigation", target_id=investigation.id, request_id=request_id,
        context_metadata={"record_type": record_type, "record_id": record_id},
    )
    db.flush()
    return link


def unlink_record(db: Session, investigation: Investigation, *, link_id: str, actor_user_id: str, request_id: Optional[str] = None) -> None:
    assert_mutable(investigation)
    link = db.execute(
        select(InvestigationLink).where(InvestigationLink.id == link_id, InvestigationLink.investigation_id == investigation.id)
    ).scalar_one_or_none()
    if link is None:
        raise not_found("Link")
    meta = {"record_type": link.record_type, "record_id": link.record_id}
    db.delete(link)
    audit_service.record(
        db, action="investigation.link_remove", actor_user_id=actor_user_id, organization_id=investigation.organization_id,
        target_type="investigation", target_id=investigation.id, request_id=request_id, context_metadata=meta,
    )
    db.flush()


def list_links(db: Session, investigation: Investigation) -> list[InvestigationLink]:
    return list(
        db.execute(
            select(InvestigationLink).where(InvestigationLink.investigation_id == investigation.id)
            .order_by(InvestigationLink.created_at.asc(), InvestigationLink.id.asc())
        ).scalars()
    )


def effective_records(db: Session, investigation: Investigation) -> list[dict]:
    """All records tied to the investigation: explicit links plus the legacy
    JSON id lists (Phase 1-3 `linked_event_ids` / `evidence_refs`). Legacy
    ids that do not resolve in this org are skipped (and counted by callers
    via `unresolved_legacy_refs`). Each item: {link, row, record_type, origin}."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for link in list_links(db, investigation):
        row = resolve_record(db, investigation.organization_id, link.record_type, link.record_id)
        key = (link.record_type, link.record_id)
        seen.add(key)
        out.append({"link": link, "row": row, "record_type": link.record_type, "record_id": link.record_id, "origin": "link"})
    for rtype, ids in (("event", investigation.linked_event_ids or []), ("evidence", investigation.evidence_refs or [])):
        for rid in ids:
            if not isinstance(rid, str) or (rtype, rid) in seen:
                continue
            row = resolve_record(db, investigation.organization_id, rtype, rid) if len(rid) <= 36 else None
            if row is None:
                continue
            seen.add((rtype, rid))
            out.append({"link": None, "row": row, "record_type": rtype, "record_id": rid, "origin": "legacy_list"})
    return out


def unresolved_legacy_refs(db: Session, investigation: Investigation) -> list[str]:
    resolved = {(r["record_type"], r["record_id"]) for r in effective_records(db, investigation) if r["origin"] == "legacy_list"}
    missing = []
    for rtype, ids in (("event", investigation.linked_event_ids or []), ("evidence", investigation.evidence_refs or [])):
        for rid in ids:
            if (rtype, rid) not in resolved and not any(l.record_type == rtype and l.record_id == rid for l in list_links(db, investigation)):
                missing.append(f"{rtype}:{rid}")
    return missing
