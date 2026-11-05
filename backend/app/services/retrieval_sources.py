"""Per-record-type text adapters, live-record loading and the
record-level access decision used by BOTH indexing and search.

The index is derived data. `can_view` is evaluated against the LIVE record at
query time, so a revoked membership, a record reclassified as restricted, or a
deleted record takes effect immediately without waiting for a re-index."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, has_permission
from app.models.assessment import Assessment
from app.models.assessment_review import AssessmentReview
from app.models.data_source import DataSource
from app.models.event import Event
from app.models.evidence import Evidence
from app.models.investigation import Investigation
from app.models.investigation_workspace import InvestigationNote
from app.models.media_asset import MediaAsset
from app.models.observation import Observation
from app.models.retrieval import INDEXABLE_RECORD_TYPES
from app.models.scenario import Scenario
from app.services import evidence_registry_service, investigation_service

MODELS = {
    "investigation": Investigation, "investigation_note": InvestigationNote, "event": Event,
    "observation": Observation, "assessment": Assessment, "assessment_review": AssessmentReview,
    "evidence": Evidence, "data_source": DataSource, "media_asset": MediaAsset, "scenario": Scenario,
}
assert set(MODELS) == set(INDEXABLE_RECORD_TYPES)

# Per-type read permission. Retrieval never grants more than the record's own API.
READ_PERMISSION = {
    "investigation": Permission.INVESTIGATION_READ, "investigation_note": Permission.INVESTIGATION_READ,
    "event": Permission.EVENT_READ, "observation": Permission.OBSERVATION_READ,
    "assessment": Permission.ASSESSMENT_READ, "assessment_review": Permission.ASSESSMENT_READ,
    "evidence": Permission.EVIDENCE_READ, "data_source": Permission.SOURCE_READ,
    "media_asset": Permission.EVIDENCE_READ, "scenario": Permission.SCENARIO_READ,
}

# Frontend detail routes. Record types without a dedicated page link to the
# nearest page that itself enforces authorization.
DETAIL_ROUTE = {
    "investigation": "/investigations/{id}", "investigation_note": "/investigations/{parent}",
    "event": "/events/{id}", "assessment": "/fusion/assessments/{id}",
    "assessment_review": "/fusion/assessments/{parent}", "data_source": "/sources",
    "evidence": "/investigations", "observation": "/events", "media_asset": "/investigations",
    "scenario": "/scenarios/{id}",
}


def has_read(user, record_type: str) -> bool:
    return has_permission(user.role, READ_PERMISSION[record_type])


def allowed_record_types(user: AuthenticatedUser) -> list[str]:
    return [t for t in INDEXABLE_RECORD_TYPES if has_permission(user.role, READ_PERMISSION[t])]


def load_live(db: Session, organization_id: str, record_type: str, record_id: str):
    model = MODELS.get(record_type)
    if model is None or not record_id or len(record_id) > 36:
        return None
    return db.execute(select(model).where(model.id == record_id, model.organization_id == organization_id)).scalar_one_or_none()


def parent_id(record_type: str, row) -> Optional[str]:
    if record_type == "investigation_note":
        return row.investigation_id
    if record_type == "assessment_review":
        return row.assessment_id
    return None


def detail_link(record_type: str, row_id: str, parent: Optional[str] = None) -> Optional[str]:
    tpl = DETAIL_ROUTE.get(record_type)
    if tpl is None:
        return None
    return tpl.format(id=row_id, parent=parent or row_id)


def can_view(db: Session, user: AuthenticatedUser, record_type: str, row) -> bool:
    """Record-level decision. Missing record => False (caller drops the hit)."""
    if row is None or row.organization_id != user.organization_id:
        return False
    perm = READ_PERMISSION.get(record_type)
    if perm is None or not has_permission(user.role, perm):
        return False
    if record_type == "investigation":
        return investigation_service.user_can_access(db, user, row)
    if record_type == "investigation_note":
        inv = db.get(Investigation, row.investigation_id)
        if inv is None or not investigation_service.user_can_access(db, user, inv):
            return False
        if row.evidence_id:
            ev = db.get(Evidence, row.evidence_id)
            if ev is not None and not evidence_registry_service.evidence_visible(user, ev):
                return False
        return True
    if record_type == "evidence":
        return evidence_registry_service.evidence_visible(user, row)
    if record_type == "assessment_review":
        a = db.get(Assessment, row.assessment_id)
        return a is not None and a.organization_id == user.organization_id
    if record_type == "scenario":
        if not row.investigation_id:
            return True
        inv = db.get(Investigation, row.investigation_id)
        return inv is not None and investigation_service.user_can_access(db, user, inv)
    return True


@dataclass
class DocSpec:
    title: str
    text: str
    source_ref: str
    extraction_method: str
    investigation_id: Optional[str] = None
    source_id: Optional[str] = None
    review_status: Optional[str] = None
    source_time: Optional[datetime] = None
    source_updated_at: Optional[datetime] = None
    status: str = "indexed"  # indexed | unsupported
    note: Optional[str] = None


def _sec(heading: str, body) -> str:
    if body is None:
        return ""
    if isinstance(body, (list, tuple)):
        body = "\n".join(f"- {b}" for b in body if b)
    body = str(body).strip()
    return f"## {heading}\n{body}\n\n" if body else ""


def _payload_text(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    parts = []
    for k, v in list(payload.items())[:40]:
        if isinstance(v, (str, int, float, bool)):
            parts.append(f"{k}: {v}")
    return "\n".join(parts)


def build_doc(db: Session, record_type: str, row) -> DocSpec:
    """Text + metadata for one record. Only fields already stored on the record
    are used; nothing is generated or inferred."""
    rid = row.id
    ref = f"{record_type}:{rid}"
    upd = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
    if record_type == "investigation":
        text = (_sec("Description", row.description) + _sec("Purpose", row.purpose) + _sec("Scope", row.scope)
                + _sec("Resolution notes", row.resolution_notes) + _sec("Closure reason", row.closure_reason)
                + _sec("Tags", row.tags))
        return DocSpec(row.title, f"# {row.title}\n{text}", ref, "record_fields", investigation_id=rid,
                       review_status=row.status, source_time=row.created_at, source_updated_at=upd)
    if record_type == "investigation_note":
        title = f"{(row.note_kind or 'note').replace('_', ' ')} note"
        text = f"# {title}\n" + _sec("Note", row.body) + _sec("Tags", row.tags)
        return DocSpec(title, text, ref, "record_fields", investigation_id=row.investigation_id,
                       review_status=row.resolution_status, source_time=row.created_at, source_updated_at=upd)
    if record_type == "event":
        text = (f"# {row.title}\n" + _sec("Description", row.description) + _sec("Event type", row.event_type)
                + _sec("Source severity", row.source_severity) + _sec("Attributes", _payload_text(row.attributes)))
        return DocSpec(row.title, text, ref, "record_fields", source_id=row.source_id,
                       review_status=row.processing_status, source_time=row.observed_at, source_updated_at=upd)
    if record_type == "observation":
        title = f"{row.observation_type} observation"
        meas = f"{row.measurement_value} {row.unit or ''}".strip() if row.measurement_value is not None else None
        text = (f"# {title}\n" + _sec("Measurement", meas) + _sec("Payload", _payload_text(row.payload))
                + _sec("Quality flags", row.quality_flags) + _sec("Validation status", row.validation_status))
        return DocSpec(title, text, ref, "record_fields", source_id=row.source_id,
                       review_status=row.validation_status, source_time=row.observed_at, source_updated_at=upd)
    if record_type == "assessment":
        text = (f"# {row.title}\n" + _sec("Question", row.question) + _sec("Scope", row.scope_description)
                + _sec("Summary", row.summary) + _sec("Assumptions", row.assumptions)
                + _sec("Information gaps", row.information_gaps) + _sec("Confidence rationale", row.confidence_rationale))
        return DocSpec(row.title, text, ref, "record_fields", review_status=row.status,
                       source_time=row.created_at, source_updated_at=upd)
    if record_type == "assessment_review":
        title = f"Review ({row.decision})"
        text = f"# {title}\n" + _sec("Notes", row.notes) + _sec("Change reason", row.change_reason) + _sec("Information flags", row.information_flags)
        return DocSpec(title, text, ref, "record_fields", review_status=row.decision,
                       source_time=row.created_at, source_updated_at=upd)
    if record_type == "evidence":
        text = (f"# {row.title}\n" + _sec("Summary", row.summary) + _sec("Content", row.content)
                + _sec("Evidence type", row.evidence_type))
        method = "approved_report_document" if row.evidence_type == "report" else "record_fields"
        return DocSpec(row.title, text, ref, method, source_id=row.source_id, review_status=row.review_status,
                       source_time=row.captured_at or row.created_at, source_updated_at=upd)
    if record_type == "data_source":
        text = (f"# {row.name}\n" + _sec("Description", row.description) + _sec("Source type", row.source_type)
                + _sec("Owner team", row.owner_team) + _sec("Status", row.status))
        return DocSpec(row.name, text, ref, "record_fields", source_id=row.id, review_status=row.status,
                       source_time=row.created_at, source_updated_at=upd)
    if record_type == "media_asset":
        # Metadata only: no OCR / transcription exists, and binary bytes are never indexed.
        text = f"# {row.declared_filename}\n" + _sec("Media", f"{row.media_type} {row.detected_mime_type}")
        return DocSpec(row.declared_filename, text, ref, "metadata_only", status="unsupported",
                       review_status=row.status, source_time=row.created_at, source_updated_at=upd,
                       note="Binary media is not text-searchable; only filename and type are known.")
    if record_type == "scenario":
        # Everything here is hypothetical. The title and first lines say so, so
        # every excerpt and citation carries the label.
        title = f"[SIMULATED] {row.title}"
        summ = None
        if row.latest_summary and row.latest_summary.get("metrics"):
            summ = [f"{k}: {v}" for k, v in sorted(row.latest_summary["metrics"].items())][:40]
        text = (f"# {title}\n> SIMULATED - hypothetical scenario on synthetic data; not an observation and not evidence.\n\n"
                + _sec("Question", row.question) + _sec("Description", row.description)
                + _sec("Simulator", f"{row.simulator_id} v{row.simulator_version}, seed {row.seed}, scenario version {row.version}")
                + _sec("Parameters", [f"{k} = {v}" for k, v in sorted((row.params or {}).items())])
                + _sec("Assumptions", row.assumptions) + _sec("Limitations", row.limitations)
                + _sec("Latest simulated metrics", summ))
        return DocSpec(title, text, ref, "record_fields", investigation_id=row.investigation_id, review_status=row.status,
                       source_time=row.created_at, source_updated_at=upd)
    raise ValueError(f"unsupported record_type {record_type}")


def iter_rows(db: Session, organization_id: str, record_type: str, limit: int) -> Iterable:
    model = MODELS[record_type]
    return db.execute(select(model).where(model.organization_id == organization_id).limit(limit)).scalars().all()
