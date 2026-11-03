"""Data retention and lifecycle (Phase 14, Phase G).

Design rules (documented in docs/security/DATA_LIFECYCLE.md):

* Only the record types listed in RESOURCE_POLICIES can be archived or
  deleted through this module. Evidence, investigations, assessments,
  events, raw records and audit rows are deliberately NOT deletable here:
  they carry provenance and are retained / superseded, never silently
  removed.
* Every consequential operation is a two-step workflow: REQUEST (with a
  dry-run impact snapshot) -> APPROVE (a different administrator unless
  LIFECYCLE_REQUIRE_SEPARATE_APPROVER=false) -> EXECUTE. Nothing is
  cascaded implicitly: a record that is still referenced produces a
  *blocker* and the request is refused.
* Database changes happen in ONE transaction. Filesystem removal happens
  only AFTER the commit succeeded; if it fails the request ends in
  `cleanup_pending` (never reported as plain success) and can be retried.
* Derived data (retrieval index entries) is invalidated / removed in the
  same transaction as the source record.
* Audit rows are never deleted by the application; AUDIT_RETENTION_DAYS only
  drives an eligibility *report*.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import AuthenticatedUser
from app.cv import storage
from app.models.audit import AuditRecord
from app.models.lifecycle import LifecycleRequest
from app.models.media_asset import MediaAsset
from app.models.retrieval import CopilotConversation, CopilotMessage, RetrievalChunk, RetrievalDocument
from app.models.scenario import Scenario, ScenarioRun, SyntheticDataset
from app.services import audit_service, retrieval_index_service

logger = logging.getLogger("aegis.lifecycle")
settings = get_settings()


class LifecycleError(Exception):
    """Base class; `status_code` is the HTTP status the route should use."""

    status_code = 400


class LifecycleNotFound(LifecycleError):
    status_code = 404


class LifecycleConflict(LifecycleError):
    status_code = 409

    def __init__(self, message: str, blockers: Optional[list[str]] = None):
        super().__init__(message)
        self.blockers = blockers or []


class LifecycleInvalid(LifecycleError):
    status_code = 422


# classification vocabulary: public | internal | confidential | sensitive_source | secret
RESOURCE_POLICIES: dict[str, dict[str, Any]] = {
    "scenario": {
        "label": "Scenario definition", "classification": "internal", "actions": ["archive"],
        "retention_days_setting": None,
        "semantics": "Archived, never deleted. Ready/archived scenarios are immutable; changes create a new version.",
    },
    "scenario_run": {
        "label": "Scenario run (simulated output)", "classification": "internal", "actions": ["delete"],
        "retention_days_setting": "LIFECYCLE_SCENARIO_RUN_RETENTION_DAYS",
        "semantics": "Derived, reproducible from the scenario snapshot + seed. Deletable once finished.",
    },
    "synthetic_dataset": {
        "label": "Synthetic dataset", "classification": "internal", "actions": ["delete"],
        "retention_days_setting": "LIFECYCLE_SYNTHETIC_DATASET_RETENTION_DAYS",
        "semantics": "Synthetic only. Deletion is blocked while a run still references it.",
    },
    "copilot_conversation": {
        "label": "Copilot conversation", "classification": "confidential", "actions": ["delete"],
        "retention_days_setting": "COPILOT_CONVERSATION_RETENTION_DAYS",
        "semantics": "History of questions/answers, not evidence. Messages are removed with the conversation.",
    },
    "media_asset": {
        "label": "Media file", "classification": "sensitive_source", "actions": ["delete"],
        "retention_days_setting": "LIFECYCLE_MEDIA_RETENTION_DAYS",
        "semantics": "Deletable ONLY while nothing references it (evidence, detections, inference/tracking jobs). The stored file is removed after the database commit.",
    },
}

# Types that exist in the platform but are NOT deletable through lifecycle.
PROTECTED_TYPES: dict[str, dict[str, str]] = {
    "evidence": {"label": "Evidence item", "classification": "confidential", "handling": "retain; supersede with a new version, never delete"},
    "investigation": {"label": "Investigation", "classification": "confidential", "handling": "retain; close/archive through the investigation workflow"},
    "assessment": {"label": "Assessment & review history", "classification": "confidential", "handling": "retain; supersede with a revision"},
    "event": {"label": "Event / observation", "classification": "internal", "handling": "retain; provenance for derived records"},
    "raw_record": {"label": "Raw source record", "classification": "sensitive_source", "handling": "retain; access gated by raw_record:read"},
    "audit_record": {"label": "Audit record", "classification": "confidential", "handling": "append-only; never deleted by the application"},
    "user_credentials": {"label": "Credentials / API keys", "classification": "secret", "handling": "hashed at rest; never exported, logged or returned"},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def retention_days(resource_type: str) -> int:
    name = RESOURCE_POLICIES[resource_type]["retention_days_setting"]
    return int(getattr(settings, name)) if name else 0


def policies() -> dict:
    items = []
    for rtype, pol in RESOURCE_POLICIES.items():
        items.append({
            "resource_type": rtype, "label": pol["label"], "classification": pol["classification"],
            "actions": pol["actions"], "retention_days": retention_days(rtype) or None,
            "retention_setting": pol["retention_days_setting"], "semantics": pol["semantics"], "managed": True,
        })
    for rtype, pol in PROTECTED_TYPES.items():
        items.append({
            "resource_type": rtype, "label": pol["label"], "classification": pol["classification"],
            "actions": [], "retention_days": None, "retention_setting": None, "semantics": pol["handling"], "managed": False,
        })
    return {
        "items": items,
        "audit_retention_days": settings.AUDIT_RETENTION_DAYS or None,
        "audit_note": "Audit records are never deleted by the application. AUDIT_RETENTION_DAYS only drives an eligibility report.",
        "require_separate_approver": settings.LIFECYCLE_REQUIRE_SEPARATE_APPROVER,
    }


_MODELS = {
    "scenario": Scenario, "scenario_run": ScenarioRun, "synthetic_dataset": SyntheticDataset,
    "copilot_conversation": CopilotConversation, "media_asset": MediaAsset,
}


def _load(db: Session, organization_id: str, resource_type: str, resource_id: str):
    model = _MODELS.get(resource_type)
    if model is None:
        return None
    return db.scalar(select(model).where(model.id == resource_id, model.organization_id == organization_id))


def _media_reference_counts(db: Session, media_id: str) -> dict[str, int]:
    from app.models.detection_result import DetectionResult
    from app.models.evidence import Evidence
    from app.models.inference_job import InferenceJob
    from app.models.track_observation import TrackObservation
    from app.models.tracking_job import TrackingJob

    out = {}
    for label, model in (("evidence", Evidence), ("detections", DetectionResult), ("inference_jobs", InferenceJob),
                         ("tracking_jobs", TrackingJob), ("track_observations", TrackObservation)):
        n = db.scalar(select(func.count()).select_from(model).where(model.media_asset_id == media_id)) or 0
        if n:
            out[label] = int(n)
    return out


def impact(db: Session, organization_id: str, resource_type: str, obj, action: str) -> dict:
    """Dry-run: what would this operation touch, and what blocks it?"""
    blockers: list[str] = []
    affected: dict[str, Any] = {}
    if resource_type == "scenario":
        if obj.status == "archived":
            blockers.append("already archived")
        affected["runs"] = db.scalar(select(func.count()).select_from(ScenarioRun).where(ScenarioRun.scenario_id == obj.id)) or 0
        affected["retrieval_index"] = "invalidated (derived)"
    elif resource_type == "scenario_run":
        if obj.status == "running":
            blockers.append("run is still in progress")
        affected["results_bytes"] = len(json.dumps(obj.results or {}))
    elif resource_type == "synthetic_dataset":
        refs = 0
        for (ref,) in db.execute(select(ScenarioRun.dataset_ref).where(
                ScenarioRun.organization_id == organization_id, ScenarioRun.dataset_ref.is_not(None)).limit(5000)).all():
            if obj.id in json.dumps(ref):
                refs += 1
        if refs:
            blockers.append(f"referenced by {refs} scenario run(s); delete those runs first")
        affected["records_stored"] = obj.stored_record_count
    elif resource_type == "copilot_conversation":
        affected["messages"] = db.scalar(select(func.count()).select_from(CopilotMessage).where(CopilotMessage.conversation_id == obj.id)) or 0
    elif resource_type == "media_asset":
        refs = _media_reference_counts(db, obj.id)
        if refs:
            blockers.append("still referenced by: " + ", ".join(f"{v} {k}" for k, v in refs.items()))
        affected["files"] = 1
        affected["byte_size"] = obj.byte_size
    return {"action": action, "blockers": blockers, "affected": affected, "executable": not blockers}


def preview(db: Session, organization_id: str, resource_type: str, *, older_than_days: Optional[int] = None) -> dict:
    """Bulk dry-run: records older than the retention window (or an explicit
    `older_than_days`), each with its blockers. Changes NOTHING."""
    pol = RESOURCE_POLICIES.get(resource_type)
    if pol is None:
        raise LifecycleInvalid(f"resource_type '{resource_type}' is not lifecycle-managed")
    days = older_than_days if older_than_days is not None else retention_days(resource_type)
    if not days or days <= 0:
        return {"resource_type": resource_type, "retention_days": None, "cutoff": None, "items": [], "total_eligible": 0,
                "note": "No retention window configured for this type; nothing is automatically eligible."}
    cutoff = _now() - timedelta(days=days)
    model = _MODELS[resource_type]
    rows = db.execute(select(model).where(model.organization_id == organization_id, model.created_at < cutoff)
                      .order_by(model.created_at).limit(settings.LIFECYCLE_MAX_BATCH)).scalars().all()
    total = db.scalar(select(func.count()).select_from(model).where(model.organization_id == organization_id, model.created_at < cutoff)) or 0
    action = pol["actions"][0]
    items = [{"resource_id": r.id, "created_at": r.created_at, "label": _label(resource_type, r),
              "impact": impact(db, organization_id, resource_type, r, action)} for r in rows]
    return {"resource_type": resource_type, "retention_days": days, "cutoff": cutoff, "action": action, "items": items,
            "total_eligible": int(total), "truncated": total > len(rows)}


def audit_retention_report(db: Session, organization_id: str) -> dict:
    days = settings.AUDIT_RETENTION_DAYS
    total = db.scalar(select(func.count()).select_from(AuditRecord).where(AuditRecord.organization_id == organization_id)) or 0
    if not days:
        return {"retention_days": None, "total": int(total), "eligible_for_external_archival": 0,
                "note": "AUDIT_RETENTION_DAYS is 0: audit history is kept indefinitely."}
    cutoff = _now() - timedelta(days=days)
    n = db.scalar(select(func.count()).select_from(AuditRecord).where(
        AuditRecord.organization_id == organization_id, AuditRecord.created_at < cutoff)) or 0
    return {"retention_days": days, "total": int(total), "eligible_for_external_archival": int(n), "cutoff": cutoff,
            "note": "Report only. The application never deletes audit rows; export/archive and purge must be done by a DBA under your own procedure."}


def _label(resource_type: str, obj) -> str:
    for attr in ("title", "name", "declared_filename"):
        v = getattr(obj, attr, None)
        if v:
            return str(v)[:120]
    return f"{resource_type} {obj.id[:8]}"


# ---- workflow -------------------------------------------------------------

def get_request(db: Session, organization_id: str, request_id: str) -> LifecycleRequest:
    req = db.scalar(select(LifecycleRequest).where(LifecycleRequest.id == request_id, LifecycleRequest.organization_id == organization_id))
    if req is None:
        raise LifecycleNotFound("Lifecycle request not found")
    return req


def list_requests_query(organization_id: str, *, status: Optional[str] = None, resource_type: Optional[str] = None):
    stmt = select(LifecycleRequest).where(LifecycleRequest.organization_id == organization_id)
    if status:
        stmt = stmt.where(LifecycleRequest.status == status)
    if resource_type:
        stmt = stmt.where(LifecycleRequest.resource_type == resource_type)
    return stmt.order_by(LifecycleRequest.created_at.desc())


def create_request(db: Session, user: AuthenticatedUser, *, resource_type: str, resource_id: str, action: str, reason: str,
                   request_id: Optional[str] = None) -> LifecycleRequest:
    if resource_type in PROTECTED_TYPES:
        raise LifecycleInvalid(f"'{resource_type}' is protected and cannot be archived or deleted through lifecycle: {PROTECTED_TYPES[resource_type]['handling']}")
    pol = RESOURCE_POLICIES.get(resource_type)
    if pol is None:
        raise LifecycleInvalid(f"resource_type '{resource_type}' is not lifecycle-managed")
    if action not in pol["actions"]:
        raise LifecycleInvalid(f"'{action}' is not permitted for {resource_type}; allowed: {pol['actions']}")
    obj = _load(db, user.organization_id, resource_type, resource_id)
    if obj is None:
        raise LifecycleNotFound(f"{resource_type} not found")
    imp = impact(db, user.organization_id, resource_type, obj, action)
    if imp["blockers"]:
        audit_service.record(
            db, action="lifecycle.request", actor_user_id=user.id, organization_id=user.organization_id,
            target_type=resource_type, target_id=resource_id, outcome="denied", request_id=request_id,
            context_metadata={"lifecycle_action": action, "blockers": imp["blockers"]},
        )
        db.commit()
        raise LifecycleConflict("Operation blocked: " + "; ".join(imp["blockers"]), imp["blockers"])
    dup = db.scalar(select(LifecycleRequest.id).where(
        LifecycleRequest.organization_id == user.organization_id, LifecycleRequest.resource_type == resource_type,
        LifecycleRequest.resource_id == resource_id, LifecycleRequest.status.in_(("pending", "approved", "cleanup_pending"))))
    if dup:
        raise LifecycleConflict("An open lifecycle request already exists for this record")
    req = LifecycleRequest(
        organization_id=user.organization_id, resource_type=resource_type, resource_id=resource_id, action=action,
        status="pending", reason=reason, requested_by_user_id=user.id, impact={**imp, "label": _label(resource_type, obj)},
    )
    db.add(req)
    db.flush()
    audit_service.record(
        db, action="lifecycle.request", actor_user_id=user.id, organization_id=user.organization_id,
        target_type=resource_type, target_id=resource_id, request_id=request_id,
        context_metadata={"lifecycle_request_id": req.id, "lifecycle_action": action, "affected": imp["affected"]},
    )
    return req


def review(db: Session, user: AuthenticatedUser, req: LifecycleRequest, *, approve: bool, note: Optional[str],
           request_id: Optional[str] = None) -> LifecycleRequest:
    if req.status != "pending":
        raise LifecycleConflict(f"Request is {req.status}, not pending")
    if approve and settings.LIFECYCLE_REQUIRE_SEPARATE_APPROVER and req.requested_by_user_id == user.id:
        audit_service.record(
            db, action="lifecycle.approve", actor_user_id=user.id, organization_id=user.organization_id,
            target_type=req.resource_type, target_id=req.resource_id, outcome="denied", request_id=request_id,
            context_metadata={"lifecycle_request_id": req.id, "reason": "self-approval not permitted"},
        )
        db.commit()
        raise LifecycleConflict("A different administrator must approve this request")
    req.status = "approved" if approve else "rejected"
    req.reviewed_by_user_id, req.reviewed_at, req.review_note = user.id, _now(), (note or None)
    db.add(req)
    audit_service.record(
        db, action="lifecycle.approve" if approve else "lifecycle.reject", actor_user_id=user.id, organization_id=user.organization_id,
        target_type=req.resource_type, target_id=req.resource_id, request_id=request_id,
        context_metadata={"lifecycle_request_id": req.id, "lifecycle_action": req.action},
    )
    return req


def cancel(db: Session, user: AuthenticatedUser, req: LifecycleRequest, *, request_id: Optional[str] = None) -> LifecycleRequest:
    if req.status not in ("pending", "approved"):
        raise LifecycleConflict(f"Request is {req.status} and cannot be cancelled")
    req.status = "cancelled"
    db.add(req)
    audit_service.record(
        db, action="lifecycle.cancel", actor_user_id=user.id, organization_id=user.organization_id,
        target_type=req.resource_type, target_id=req.resource_id, request_id=request_id,
        context_metadata={"lifecycle_request_id": req.id},
    )
    return req


def _drop_index_rows(db: Session, organization_id: str, record_type: str, record_id: str) -> int:
    n = db.execute(delete(RetrievalChunk).where(
        RetrievalChunk.organization_id == organization_id, RetrievalChunk.record_type == record_type,
        RetrievalChunk.record_id == record_id)).rowcount or 0
    db.execute(delete(RetrievalDocument).where(
        RetrievalDocument.organization_id == organization_id, RetrievalDocument.record_type == record_type,
        RetrievalDocument.record_id == record_id))
    return int(n)


def execute(db: Session, user: AuthenticatedUser, req: LifecycleRequest, *, request_id: Optional[str] = None) -> LifecycleRequest:
    """Runs an APPROVED request (or retries file cleanup of a
    `cleanup_pending` one). Commits internally so the DB outcome is durable
    BEFORE any file is touched; returns the request in its final status."""
    org = user.organization_id
    if req.status == "cleanup_pending":
        return _retry_cleanup(db, user, req, request_id)
    if req.status != "approved":
        raise LifecycleConflict(f"Request is {req.status}; only approved requests can be executed")

    obj = _load(db, org, req.resource_type, req.resource_id)
    if obj is None:
        return _fail(db, user, req, "target record no longer exists", request_id)
    imp = impact(db, org, req.resource_type, obj, req.action)
    if imp["blockers"]:  # state changed since the request was approved
        return _fail(db, user, req, "blocked at execution: " + "; ".join(imp["blockers"]), request_id)

    file_key: Optional[str] = None
    result: dict[str, Any] = {"affected": imp["affected"]}
    try:
        rtype = req.resource_type
        if rtype == "scenario":
            obj.status = "archived"
            db.add(obj)
            retrieval_index_service.invalidate_record(db, org, "scenario", obj.id, "lifecycle_archived")
        elif rtype == "scenario_run":
            db.delete(obj)
        elif rtype == "synthetic_dataset":
            db.delete(obj)
        elif rtype == "copilot_conversation":
            result["messages_deleted"] = db.execute(delete(CopilotMessage).where(CopilotMessage.conversation_id == obj.id)).rowcount or 0
            db.delete(obj)
        elif rtype == "media_asset":
            file_key = obj.storage_key
            result["index_chunks_removed"] = _drop_index_rows(db, org, "media_asset", obj.id)
            db.delete(obj)
        db.flush()
        req.status = "executed"
        req.executed_by_user_id, req.executed_at, req.result = user.id, _now(), result
        db.add(req)
        audit_service.record(
            db, action=f"lifecycle.{req.action}", actor_user_id=user.id, organization_id=org,
            target_type=req.resource_type, target_id=req.resource_id, request_id=request_id,
            context_metadata={"lifecycle_request_id": req.id, **result},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("lifecycle execute failed")
        return _fail(db, user, get_request(db, org, req.id), f"database operation failed: {type(exc).__name__}", request_id)

    if file_key:
        _remove_file(db, user, req, file_key, request_id)
    return req


def _remove_file(db: Session, user: AuthenticatedUser, req: LifecycleRequest, file_key: str, request_id: Optional[str]) -> None:
    try:
        storage.delete(file_key)
        req.result = {**(req.result or {}), "file_removed": True}
        db.add(req)
        db.commit()
    except Exception as exc:
        logger.exception("lifecycle file cleanup failed")
        db.rollback()
        req = get_request(db, user.organization_id, req.id)
        req.status = "cleanup_pending"
        req.failure_reason = f"file removal failed: {type(exc).__name__}"
        req.result = {**(req.result or {}), "file_removed": False, "file_key": file_key}
        db.add(req)
        audit_service.record(
            db, action="lifecycle.cleanup_failed", actor_user_id=user.id, organization_id=user.organization_id,
            target_type=req.resource_type, target_id=req.resource_id, outcome="failure", request_id=request_id,
            context_metadata={"lifecycle_request_id": req.id},
        )
        db.commit()


def _retry_cleanup(db: Session, user: AuthenticatedUser, req: LifecycleRequest, request_id: Optional[str]) -> LifecycleRequest:
    key = (req.result or {}).get("file_key")
    if not key:
        raise LifecycleConflict("No pending file cleanup is recorded for this request")
    try:
        storage.delete(key)
    except Exception as exc:
        raise LifecycleConflict(f"File cleanup still failing: {type(exc).__name__}") from exc
    req.status, req.failure_reason = "executed", None
    req.result = {**(req.result or {}), "file_removed": True}
    req.result.pop("file_key", None)
    db.add(req)
    audit_service.record(
        db, action="lifecycle.cleanup_completed", actor_user_id=user.id, organization_id=user.organization_id,
        target_type=req.resource_type, target_id=req.resource_id, request_id=request_id,
        context_metadata={"lifecycle_request_id": req.id},
    )
    db.commit()
    return req


def _fail(db: Session, user: AuthenticatedUser, req: LifecycleRequest, reason: str, request_id: Optional[str]) -> LifecycleRequest:
    req.status, req.failure_reason = "failed", reason[:500]
    db.add(req)
    audit_service.record(
        db, action=f"lifecycle.{req.action}", actor_user_id=user.id, organization_id=user.organization_id,
        target_type=req.resource_type, target_id=req.resource_id, outcome="failure", request_id=request_id,
        context_metadata={"lifecycle_request_id": req.id, "reason": reason[:300]},
    )
    db.commit()
    return req
