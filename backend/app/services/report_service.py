"""Report generation, storage, retrieval and retention.

Guarantees (each covered by tests):
* Authorization precedes data access: the caller needs REPORT_GENERATE and every
  permission the chosen sections require, else 403 with no data touched.
* Generation is synchronous and bounded. The run row is "running" while work
  happens; it becomes "completed" ONLY after the artifact has been written to a
  temp file, hashed and atomically renamed. Any failure leaves status "failed",
  no artifact, and a sanitised error.
* Artifacts live in private storage (never statically served); the on-disk name is
  derived from the run id and format, never from user input.
* Retention: `purge_expired` deletes the file and marks the run "expired"; the row is kept.
* The sha256 is an integrity check of the stored bytes. It says nothing about authenticity.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import MlopsConflict, MlopsForbidden, MlopsNotFound, ArtifactUnavailable, scrub
from app.core.security import AuthenticatedUser, Permission, Role, has_permission
from app.models.report import ReportRun
from app.reporting import definitions as defs
from app.reporting import render, summaries
from app.reporting.envelope import Ctx
from app.reporting.templates import SECTION_PERMISSIONS, TEMPLATES, required_permissions
from app.reporting.window import AnalyticsInputError, as_utc, build_filters, build_window, now_utc
from app.schemas.reporting import ReportRequest
from app.services import analytics_service as an
from app.services import audit_service

INTEGRITY_NOTE = "content_sha256 is an integrity check of the stored file's bytes only; it does not establish who created the report or that its source data is authentic."
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class Plan:
    template_key: str
    title: str
    sections: list[str]
    window: object
    filters: object
    required: list[str]
    notes: Optional[str]
    format: str
    visibility: str
    raw: dict


def storage_root() -> Path:
    s = get_settings()
    return Path(s.REPORT_STORAGE_ROOT) if s.REPORT_STORAGE_ROOT else Path(s.CV_MEDIA_STORAGE_ROOT) / "reports"


def _artifact_path(run: ReportRun) -> Path:
    ext = render.EXTENSIONS[run.format]
    if not re.fullmatch(r"[0-9a-f\-]{36}", run.id) or not re.fullmatch(r"[0-9a-f\-]{36}", run.organization_id):
        raise ArtifactUnavailable("report storage location is invalid")
    return storage_root() / run.organization_id / f"{run.id}.{ext}"


def safe_filename(template_key: str, run_id: str, fmt: str, when: datetime) -> str:
    t = re.sub(r"[^a-z0-9_]", "", template_key.lower())[:30] or "report"
    return f"aegis-{t}-{when.strftime('%Y%m%d')}-{run_id[:8]}.{render.EXTENSIONS[fmt]}"


def clean_notes(notes: Optional[str]) -> Optional[str]:
    if notes is None:
        return None
    text = _CTRL.sub("", notes.replace("\r\n", "\n")).strip()
    if len(text) > get_settings().REPORT_MAX_NOTES_CHARS:
        raise AnalyticsInputError(f"notes may be at most {get_settings().REPORT_MAX_NOTES_CHARS} characters")
    return text or None


# ------------------------------------------------------------------ catalog ---
def templates_for(user: AuthenticatedUser) -> list[dict]:
    out = []
    for key, t in TEMPLATES.items():
        secs = list(t["sections"]) if key != "custom" else sorted(SECTION_PERMISSIONS)
        req = required_permissions(secs) if key != "custom" else []
        ok = all(has_permission(user.role, Permission(p)) for p in req)
        out.append({"key": key, "title": t["title"], "description": t["description"], "sections": secs, "custom_sections": key == "custom",
                    "required_permissions": req, "available": ok and has_permission(user.role, Permission.REPORT_GENERATE),
                    "formats": list(render.RENDERERS)})
    return out


# --------------------------------------------------------------- validation ---
def validate(user: AuthenticatedUser, req: ReportRequest) -> Plan:
    if req.template_key not in TEMPLATES:
        raise AnalyticsInputError("unknown report template")
    tpl = TEMPLATES[req.template_key]
    if req.template_key == "custom":
        if not req.sections:
            raise AnalyticsInputError("a custom report needs at least one section")
        bad = [s for s in req.sections if s not in SECTION_PERMISSIONS]
        if bad:
            raise AnalyticsInputError("unknown section(s) requested")
        sections = list(dict.fromkeys(req.sections))
    else:
        if req.sections:
            raise AnalyticsInputError("sections can only be chosen for the custom template")
        sections = list(tpl["sections"])
    window = build_window(req.start, req.end, req.days, req.bucket, req.time_basis)
    filters = build_filters(req.source_id, req.category, req.include_archived)
    notes = clean_notes(req.notes)
    required = required_permissions(sections)
    if not has_permission(user.role, Permission.REPORT_GENERATE):
        raise MlopsForbidden("you do not have permission to generate reports")
    missing = [p for p in required if not has_permission(user.role, Permission(p))]
    if missing:
        raise MlopsForbidden("you lack permission for data this report would include")
    title = (req.title or tpl["title"]).strip()
    return Plan(req.template_key, title, sections, window, filters, required, notes, req.format, req.visibility, req.model_dump(mode="json"))


def _fingerprint(plan: Plan) -> str:
    raw = {k: v for k, v in plan.raw.items() if k != "idempotency_key"}
    return hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()


# --------------------------------------------------------------- visibility ---
def can_read(user: AuthenticatedUser, run: ReportRun) -> bool:
    if run.organization_id != user.organization_id or not has_permission(user.role, Permission.REPORTING_READ):
        return False
    if user.role != Role.ADMINISTRATOR and run.visibility == "private" and run.created_by_user_id != user.id:
        return False
    return all(has_permission(user.role, Permission(p)) for p in (run.required_permissions or []))


def get_for_user(db: Session, user: AuthenticatedUser, report_id: str) -> ReportRun:
    run = db.get(ReportRun, report_id) if re.fullmatch(r"[0-9a-fA-F\-]{1,36}", report_id or "") else None
    if run is None or not can_read(user, run):
        raise MlopsNotFound("report not found")
    return run


def list_query(user: AuthenticatedUser, *, status: Optional[str], template_key: Optional[str]):
    stmt = select(ReportRun).where(ReportRun.organization_id == user.organization_id)
    if user.role != Role.ADMINISTRATOR:
        stmt = stmt.where((ReportRun.visibility == "organization") | (ReportRun.created_by_user_id == user.id))
    if status:
        stmt = stmt.where(ReportRun.status == status)
    if template_key:
        stmt = stmt.where(ReportRun.template_key == template_key)
    return stmt.order_by(ReportRun.created_at.desc(), ReportRun.id)


def permitted(user: AuthenticatedUser, runs: list[ReportRun]) -> list[ReportRun]:
    return [r for r in runs if can_read(user, r)]


def serialize(run: ReportRun, *, replayed: bool = False) -> dict:
    return {
        "id": run.id, "template_key": run.template_key, "title": run.title, "status": run.status, "format": run.format, "visibility": run.visibility, "parameters": run.parameters or {},
        "has_commentary": bool(run.notes), "required_permissions": run.required_permissions or [], "definition_version": run.definition_version, "created_by_user_id": run.created_by_user_id,
        "created_at": run.created_at, "started_at": run.started_at, "completed_at": run.completed_at, "expires_at": run.expires_at, "sample_summary": run.sample_summary or {},
        "section_status": run.section_status or {}, "artifact_name": run.artifact_name, "artifact_bytes": run.artifact_bytes, "content_sha256": run.content_sha256,
        "integrity_note": INTEGRITY_NOTE, "download_count": run.download_count, "error_category": run.error_category, "error_message": run.error_message, "replayed": replayed,
        "downloadable": run.status == "completed",
    }


# --------------------------------------------------------------- generation ---
def build_document(ctx: Ctx, plan: Plan, run_id: str, generated_at: datetime) -> dict:
    sections = {sid: an.build_section(ctx, sid) for sid in plan.sections}
    used = {mid for env in sections.values() for mid in list(env["values"]) + [m for t in env["tables"].values() for m in t["metric_ids"]]}
    return {
        "report": {"id": run_id, "title": plan.title, "template": plan.template_key, "template_title": TEMPLATES[plan.template_key]["title"], "generated_at": generated_at.isoformat(),
                   "generated_by_user_id": ctx.user.id, "definition_version": defs.DEFINITION_VERSION, "window": plan.window.describe(), "filters": plan.filters.describe(),
                   "sections": plan.sections},
        "automatic_findings_label": summaries.LABEL,
        "automatic_findings": {sid: summaries.section_findings(env) for sid, env in sections.items()},
        "analyst_commentary": {"text": plan.notes, "author_user_id": ctx.user.id if plan.notes else None,
                               "note": "Written by the report's author. AEGIS has not verified it and it is not part of the automatic findings."},
        "ai_generated_text": None,
        "sections": sections,
        "metric_definitions": {mid: defs.CATALOG[mid] for mid in sorted(used)},
        "limitations": ["Counts describe records stored in AEGIS, not necessarily everything that occurred.",
                        "Figures are not threat scores or judgements about intent; unusual volumes or values are prompts for human review.",
                        "No PDF output and no AI-written summary are produced by this version.",
                        INTEGRITY_NOTE],
    }


def generate(db: Session, user: AuthenticatedUser, req: ReportRequest, *, request_id: Optional[str] = None) -> tuple[ReportRun, bool]:
    plan = validate(user, req)
    fp = _fingerprint(plan)
    key = req.idempotency_key
    if key:
        existing = db.scalar(select(ReportRun).where(ReportRun.organization_id == user.organization_id, ReportRun.idempotency_key == key))
        if existing is not None:
            if existing.request_fingerprint != fp or existing.created_by_user_id != user.id:
                raise MlopsConflict("this idempotency key was already used with different parameters")
            return existing, True
    now = now_utc()
    s = get_settings()
    run = ReportRun(organization_id=user.organization_id, created_by_user_id=user.id, template_key=plan.template_key, title=plan.title, status="running", format=plan.format,
                    visibility=plan.visibility, parameters={"window": plan.window.describe(), "filters": plan.filters.describe(), "sections": plan.sections},
                    notes=plan.notes, required_permissions=plan.required, idempotency_key=key, request_fingerprint=fp, definition_version=defs.DEFINITION_VERSION,
                    started_at=now, sample_summary={}, section_status={}, download_count=0)
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise MlopsConflict("a report with this idempotency key already exists")
    tmp: Optional[Path] = None
    try:
        ctx = Ctx(db=db, user=user, window=plan.window, filters=plan.filters, now=now)
        doc = build_document(ctx, plan, run.id, now)
        data = render.RENDERERS[plan.format](doc)
        if len(data) > s.REPORT_MAX_ARTIFACT_BYTES:
            run.error_category = "too_large"
            raise ValueError("artifact exceeds the size limit; narrow the window, filters or sections")
        path = _artifact_path(run)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".tmp-{uuid.uuid4().hex}")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        digest = hashlib.sha256(data).hexdigest()
        os.replace(tmp, path)
        tmp = None
        run.artifact_name = safe_filename(plan.template_key, run.id, plan.format, now)
        run.artifact_bytes = len(data)
        run.content_sha256 = digest
        run.sample_summary = {sid: env["sample_counts"] for sid, env in doc["sections"].items()}
        run.section_status = {sid: env["status"] for sid, env in doc["sections"].items()}
        run.completed_at = now_utc()
        run.expires_at = run.completed_at + timedelta(days=s.REPORT_RETENTION_DAYS)
        run.status = "completed"  # last: only after the file exists, is hashed and renamed
        audit_service.record(db, action="report.generated", actor_user_id=user.id, organization_id=user.organization_id, target_type="report", target_id=run.id,
                             request_id=request_id, context_metadata={"template": plan.template_key, "format": plan.format, "sections": plan.sections, "bytes": len(data),
                                                                      "sha256": digest, "visibility": plan.visibility})
    except Exception as exc:  # noqa: BLE001 - recorded, sanitised, never reported as complete
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        run.status = "failed"
        run.completed_at = None
        run.expires_at = None
        run.artifact_name = run.artifact_bytes = run.content_sha256 = None
        run.error_category = run.error_category or ("validation" if isinstance(exc, AnalyticsInputError) else "generation_failed")
        run.error_message = scrub(str(exc) if isinstance(exc, (ValueError, AnalyticsInputError)) else "report generation failed; see server logs")[:500]
        audit_service.record(db, action="report.generation_failed", actor_user_id=user.id, organization_id=user.organization_id, target_type="report", target_id=run.id,
                             outcome="failure", request_id=request_id, context_metadata={"template": plan.template_key, "category": run.error_category})
    return run, False


# ----------------------------------------------------------------- retrieval ---
def read_artifact(db: Session, user: AuthenticatedUser, report_id: str, *, request_id: Optional[str]) -> tuple[ReportRun, bytes]:
    run = get_for_user(db, user, report_id)
    if run.status != "completed":
        raise ArtifactUnavailable(f"this report is {run.status}; there is no file to download")
    if run.expires_at is not None and as_utc(run.expires_at) <= now_utc():
        _expire(db, run, user.id, request_id)
        db.commit()  # the route raises next, so persist the expiry and its audit row here
        raise ArtifactUnavailable("this report has expired and its file was deleted")
    path = _artifact_path(run)
    if not path.is_file():
        raise ArtifactUnavailable("the report file is missing from storage")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != run.content_sha256:
        audit_service.record(db, action="report.integrity_mismatch", actor_user_id=user.id, organization_id=user.organization_id, target_type="report", target_id=run.id,
                             outcome="failure", request_id=request_id)
        db.commit()  # persist the audit row; the route raises next
        raise ArtifactUnavailable("the stored report file no longer matches its recorded hash and was not served")
    run.download_count = (run.download_count or 0) + 1
    audit_service.record(db, action="report.downloaded", actor_user_id=user.id, organization_id=user.organization_id, target_type="report", target_id=run.id,
                         request_id=request_id, context_metadata={"format": run.format, "bytes": len(data)})
    return run, data


def _expire(db: Session, run: ReportRun, actor: Optional[str], request_id: Optional[str]) -> None:
    try:
        _artifact_path(run).unlink(missing_ok=True)
    except (OSError, ArtifactUnavailable):
        pass
    run.status = "expired"
    audit_service.record(db, action="report.expired", actor_user_id=actor, organization_id=run.organization_id, target_type="report", target_id=run.id, request_id=request_id)


def purge_expired(db: Session, organization_id: Optional[str] = None, *, request_id: Optional[str] = None) -> int:
    stmt = select(ReportRun).where(ReportRun.status == "completed", ReportRun.expires_at.isnot(None), ReportRun.expires_at <= now_utc())
    if organization_id:
        stmt = stmt.where(ReportRun.organization_id == organization_id)
    n = 0
    for run in db.execute(stmt.limit(500)).scalars():
        _expire(db, run, None, request_id)
        n += 1
    return n
