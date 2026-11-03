"""MLOps model registry.

Extends the existing `ModelRecord` registry -- it does not create a second one.

 * Visibility: rows registered through this API are owned by one organization
   (`owner_organization_id`) and are invisible to others (404, same as any
   other-organization record). Rows with a NULL owner (seed data, the Phase 4
   CV registrations) remain platform-level and visible to everyone, exactly as
   before. A governance transition on a platform-level row is therefore a
   platform-wide change; this is recorded in docs/security/KNOWN_RISKS.md.
 * Immutability: identifying fields cannot change after registration (ORM guard
   in app/models/model_record.py). A correction is a new version.
 * Lifecycle: registered -> review_required -> approved -> deprecated ->
   archived (see TRANSITIONS). Every transition is validated here, requires a
   reason, records an append-only event and an audit row. Approval is never
   automatic and is not inferred from metrics.
 * "Approved" is registry metadata. There is NO serving/activation environment
   in this application, so approval does not deploy anything. The only legacy
   effect is that deprecate/archive set the Phase 4 `status` to deprecated/
   retired, which already stops NEW CV inference jobs (inference_service checks
   `status in (registered, active)`); historical jobs and results are untouched.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import (
    MlopsConflict,
    MlopsNotFound,
    MlopsValidationError,
)
from app.core.obs_metrics import registry as metrics_registry
from app.core.security import Permission
from app.mlops import artifacts
from app.mlops.validation import validate_json_blob
from app.models.mlops import ExperimentRun, ModelLifecycleEvent, ReviewSignal
from app.models.model_record import (
    MLOPS_TASK_TYPES,
    ModelRecord,
)
from app.services import audit_service, mlops_signal_service
from app.services.timeutil import ensure_utc

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\- ]{0,198}$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.\-]+)?(\+[0-9A-Za-z.\-]+)?$")
SCHEMA_VERSION_RE = re.compile(r"^[A-Za-z0-9._\-]{1,50}$")
MEDIA_TYPES = ("image", "video")

# (current state, action) -> new state
TRANSITIONS: dict[tuple[str, str], str] = {
    ("registered", "request_review"): "review_required",
    ("review_required", "reject_review"): "registered",
    ("registered", "approve"): "approved",
    ("review_required", "approve"): "approved",
    ("approved", "revoke_approval"): "review_required",
    ("registered", "deprecate"): "deprecated",
    ("review_required", "deprecate"): "deprecated",
    ("approved", "deprecate"): "deprecated",
    ("deprecated", "reactivate"): "approved",
    ("deprecated", "archive"): "archived",
}
ACTIONS = tuple(sorted({a for _, a in TRANSITIONS}))
# Permission needed to PERFORM an action. Everything except requesting a review
# is an approval-authority decision (administrator-only by default).
ACTION_PERMISSION = {
    "request_review": Permission.MLOPS_REVIEW,
    "reject_review": Permission.MLOPS_APPROVE,
    "approve": Permission.MLOPS_APPROVE,
    "revoke_approval": Permission.MLOPS_APPROVE,
    "deprecate": Permission.MLOPS_APPROVE,
    "reactivate": Permission.MLOPS_APPROVE,
    "archive": Permission.MLOPS_APPROVE,
}
EVIDENCE_ACTIONS = ("approve", "reactivate")
LEGACY_STATUS_AFTER = {"deprecate": "deprecated", "archive": "retired", "reactivate": "active"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- visibility ---
def visible_clause(organization_id: str):
    return or_(ModelRecord.owner_organization_id.is_(None), ModelRecord.owner_organization_id == organization_id)


def get_visible(db: Session, organization_id: str, model_record_id: str) -> Optional[ModelRecord]:
    return db.execute(select(ModelRecord).where(ModelRecord.id == model_record_id, visible_clause(organization_id))).scalar_one_or_none()


def require_visible(db: Session, organization_id: str, model_record_id: str) -> ModelRecord:
    model = get_visible(db, organization_id, model_record_id)
    if model is None:
        raise MlopsNotFound("Model version not found")
    return model


# ---------------------------------------------------------------- register -----
def register_version(db: Session, *, organization_id: str, user_id: str, data: dict, request_id: Optional[str] = None) -> ModelRecord:
    settings = get_settings()
    name = (data.get("name") or "").strip()
    version = (data.get("version") or "").strip()
    task = data.get("task_type")
    if not NAME_RE.match(name):
        raise MlopsValidationError("name must start with a letter or digit and use only letters, digits, space, '.', '_' or '-' (max 200)")
    if not SEMVER_RE.match(version):
        raise MlopsValidationError("version must be a semantic version such as 1.2.0 or 1.2.0-rc.1")
    if task not in MLOPS_TASK_TYPES:
        raise MlopsValidationError(f"task_type must be one of {MLOPS_TASK_TYPES}")
    for key in ("input_schema_version", "output_schema_version"):
        if data.get(key) is not None and not SCHEMA_VERSION_RE.match(data[key]):
            raise MlopsValidationError(f"{key} must be 1-50 characters of letters, digits, '.', '_' or '-'")
    notes = data.get("release_notes")
    if notes is not None and len(notes) > 4000:
        raise MlopsValidationError("release_notes are limited to 4000 characters")
    doc_ref = data.get("documentation_ref")
    if doc_ref is not None and (len(doc_ref) > 500 or "\n" in doc_ref):
        raise MlopsValidationError("documentation_ref must be a single line of at most 500 characters")
    framework = validate_json_blob(data.get("framework_metadata"), field="framework_metadata", max_bytes=settings.MLOPS_MAX_METADATA_BYTES)

    adapter_key = data.get("adapter_key")
    media_types = list(data.get("supported_media_types") or [])
    if task == "object_detection":
        from app.cv.adapters.registry import available_adapter_keys

        if not adapter_key:
            raise MlopsValidationError("adapter_key is required for object_detection models")
        if adapter_key not in available_adapter_keys():
            raise MlopsValidationError(f"adapter_key is not a registered adapter (available: {available_adapter_keys()})")
        media_types = media_types or ["image"]
        if any(m not in MEDIA_TYPES for m in media_types):
            raise MlopsValidationError(f"supported_media_types must be a subset of {MEDIA_TYPES}")
        model_type = "computer_vision"
    else:
        if adapter_key:
            raise MlopsValidationError("adapter_key applies only to object_detection models (the closed CV adapter allow-list)")
        media_types = []
        model_type = "classifier"

    reference = data.get("artifact_reference") or (f"adapter:{adapter_key}" if adapter_key else None)
    digest = (data.get("artifact_digest") or None)
    if digest is not None:
        digest = digest.lower()
        if not artifacts.SHA256_RE.match(digest):
            raise MlopsValidationError("artifact_digest must be a 64-character lowercase hex SHA-256")
    if reference:
        kind, _ = artifacts.validate_reference(reference)
        if kind == "adapter":
            if digest:
                raise MlopsValidationError("artifact_digest applies to artifact files; an adapter reference has no file to hash")
            if adapter_key and reference != f"adapter:{adapter_key}":
                raise MlopsValidationError("artifact_reference must match adapter_key")
        else:
            status = artifacts.check_artifact(reference, None, None, verify_digest=False)
            if status.available:
                actual = artifacts.sha256_file(artifacts._resolve_file(reference.split(":", 1)[1]), settings.MLOPS_MAX_ARTIFACT_HASH_BYTES)  # type: ignore[arg-type]
                if digest and digest != actual:
                    raise MlopsValidationError("artifact_digest does not match the artifact file content")
                digest = digest or actual
    elif digest:
        raise MlopsValidationError("artifact_digest requires an artifact_reference")

    dup = db.execute(select(ModelRecord.id).where(ModelRecord.name == name, ModelRecord.version == version).limit(1)).first()
    if dup is not None:
        raise MlopsConflict("A model version with this name and version already exists; registered versions are immutable, register a new version instead")

    model = ModelRecord(
        name=name, version=version, model_type=model_type, task_type=task, adapter_key=adapter_key, supported_media_types=media_types,
        artifact_reference=reference, artifact_digest=digest, status="registered", evaluation_metadata={},
        owner_organization_id=organization_id, created_by_user_id=user_id, lifecycle_state="registered",
        input_schema_version=data.get("input_schema_version"), output_schema_version=data.get("output_schema_version"),
        framework_metadata=framework, release_notes=notes, documentation_ref=doc_ref,
    )
    db.add(model)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise MlopsConflict("A model version with this name and version already exists") from exc
    _event(db, model, action="register", from_state=None, to_state="registered", user_id=user_id, org_id=organization_id,
           reason="Version registered", evidence={"artifact_kind": artifacts.check_artifact(reference, adapter_key, digest, verify_digest=False).kind})
    audit_service.record(
        db, action="mlops.model.register", actor_user_id=user_id, organization_id=organization_id, target_type="model_record",
        target_id=model.id, request_id=request_id,
        context_metadata={"name": name, "version": version, "task_type": task, "has_digest": bool(digest), "artifact_kind": artifacts.check_artifact(reference, adapter_key, digest, verify_digest=False).kind},
    )
    return model


def _event(db: Session, model: ModelRecord, *, action: str, from_state: Optional[str], to_state: str, user_id: Optional[str],
           org_id: Optional[str], reason: Optional[str], evidence: Optional[dict] = None) -> ModelLifecycleEvent:
    ev = ModelLifecycleEvent(model_record_id=model.id, action=action, from_state=from_state, to_state=to_state, actor_user_id=user_id,
                             actor_organization_id=org_id, reason=reason, evidence=evidence or {}, created_at=_now())
    db.add(ev)
    db.flush()
    return ev


# ---------------------------------------------------------------- evaluation ---
def approval_evidence(db: Session, organization_id: str, model: ModelRecord) -> dict:
    """Facts an approver is shown (and that are stored on the transition event)."""
    s = get_settings()
    runs = db.execute(
        select(ExperimentRun).where(ExperimentRun.organization_id == organization_id, ExperimentRun.model_record_id == model.id,
                                    ExperimentRun.status == "succeeded").order_by(ExperimentRun.completed_at.desc()).limit(10)
    ).scalars().all()
    latest = ensure_utc(runs[0].completed_at or runs[0].started_at) if runs else None
    open_serious = db.scalar(
        select(func.count()).select_from(ReviewSignal).where(
            ReviewSignal.organization_id == organization_id, ReviewSignal.model_record_id == model.id,
            ReviewSignal.status != "resolved", ReviewSignal.severity.in_(("serious", "critical")))
    ) or 0
    return {
        "succeeded_runs": len(runs), "run_ids": [r.id for r in runs],
        "latest_succeeded_at": latest.isoformat() if latest else None,
        "evidence_is_synthetic_only": bool(runs) and all(r.is_synthetic for r in runs),
        "max_evaluation_age_days": s.MLOPS_APPROVAL_MAX_EVAL_AGE_DAYS,
        "unresolved_serious_or_critical_signals": open_serious,
        "evidence_fresh": bool(latest and latest >= _now() - timedelta(days=s.MLOPS_APPROVAL_MAX_EVAL_AGE_DAYS)),
    }


def transition(db: Session, *, organization_id: str, user_id: str, model: ModelRecord, action: str, reason: str, request_id: Optional[str] = None) -> ModelLifecycleEvent:
    settings = get_settings()
    reason = (reason or "").strip()
    if len(reason) < 3 or len(reason) > 1000:
        raise MlopsValidationError("a reason of 3-1000 characters is required for every lifecycle transition")
    key = (model.lifecycle_state, action)
    if action not in ACTIONS:
        raise MlopsValidationError(f"unknown action {action!r}; expected one of {ACTIONS}")
    if key not in TRANSITIONS:
        raise MlopsConflict(f"Action '{action}' is not allowed from state '{model.lifecycle_state}'")
    evidence: dict = {}
    if action in EVIDENCE_ACTIONS:
        evidence = approval_evidence(db, organization_id, model)
        if settings.MLOPS_REQUIRE_SEPARATE_APPROVER and model.created_by_user_id and model.created_by_user_id == user_id:
            raise MlopsConflict("The user who registered this version cannot also approve it")
        if evidence["succeeded_runs"] == 0:
            raise MlopsConflict("Approval requires at least one succeeded evaluation run for this version in your organization")
        if not evidence["evidence_fresh"]:
            raise MlopsConflict(f"The newest succeeded evaluation is older than {settings.MLOPS_APPROVAL_MAX_EVAL_AGE_DAYS} days; run a new evaluation first")
        if evidence["unresolved_serious_or_critical_signals"]:
            raise MlopsConflict("Resolve or review the open serious/critical review signals for this version before approval")
    prev = model.lifecycle_state
    model.lifecycle_state = TRANSITIONS[key]
    if action in LEGACY_STATUS_AFTER:
        model.status = LEGACY_STATUS_AFTER[action]
    event = _event(db, model, action=action, from_state=prev, to_state=model.lifecycle_state, user_id=user_id, org_id=organization_id,
                   reason=reason, evidence=evidence)
    audit_service.record(
        db, action=f"mlops.model.{action}", actor_user_id=user_id, organization_id=organization_id, target_type="model_record",
        target_id=model.id, request_id=request_id,
        context_metadata={"from": prev, "to": model.lifecycle_state, "reason": reason, "legacy_status": model.status,
                          "platform_level_record": model.owner_organization_id is None, **({"evidence": evidence} if evidence else {})},
    )
    db.flush()
    return event


def history_query(model_record_id: str):
    return select(ModelLifecycleEvent).where(ModelLifecycleEvent.model_record_id == model_record_id).order_by(ModelLifecycleEvent.created_at.desc())


def serialize_event(ev: ModelLifecycleEvent, viewer_org: str) -> dict:
    same_org = ev.actor_organization_id == viewer_org
    return {
        "id": ev.id, "action": ev.action, "from_state": ev.from_state, "to_state": ev.to_state,
        # Another organization's actor id is not disclosed (registry rows can be platform-level).
        "actor_user_id": ev.actor_user_id if same_org else None, "actor_scope": "your_organization" if same_org else ("system" if ev.actor_organization_id is None else "other_organization"),
        "reason": ev.reason if same_org or ev.actor_organization_id is None else ev.reason,
        "evidence": ev.evidence if same_org else {}, "created_at": ev.created_at,
    }


# ---------------------------------------------------------------- listing ------
def evaluation_status(db: Session, organization_id: str, model_ids: list[str]) -> dict[str, dict]:
    """Derived (never stored) evaluation status per model. States: none, running,
    failed, stale, review_needed, passed. "passed" means: the latest run succeeded,
    is not stale, and no unresolved metric_regression/metric_below_floor signal
    exists. It is NOT a quality claim about the model."""
    if not model_ids:
        return {}
    s = get_settings()
    stale_before = _now() - timedelta(days=s.MLOPS_EVALUATION_STALE_DAYS)
    out = {m: {"status": "none", "latest_run_id": None, "latest_run_at": None, "latest_succeeded_run_id": None, "latest_succeeded_at": None, "run_count": 0, "metrics": {}} for m in model_ids}
    for model_id, n in db.execute(select(ExperimentRun.model_record_id, func.count()).where(
            ExperimentRun.organization_id == organization_id, ExperimentRun.model_record_id.in_(model_ids)).group_by(ExperimentRun.model_record_id)).all():
        out[model_id]["run_count"] = n

    def latest(extra):
        rn = func.row_number().over(partition_by=ExperimentRun.model_record_id, order_by=ExperimentRun.started_at.desc()).label("rn")
        sub = select(ExperimentRun, rn).where(ExperimentRun.organization_id == organization_id, ExperimentRun.model_record_id.in_(model_ids), *extra).subquery()
        from sqlalchemy.orm import aliased

        alias = aliased(ExperimentRun, sub)
        return db.execute(select(alias).where(sub.c.rn == 1)).scalars().all()

    latest_any = {r.model_record_id: r for r in latest([])}
    latest_ok = {r.model_record_id: r for r in latest([ExperimentRun.status == "succeeded"])}
    flagged = {mid for (mid,) in db.execute(select(ReviewSignal.model_record_id).where(
        ReviewSignal.organization_id == organization_id, ReviewSignal.model_record_id.in_(model_ids), ReviewSignal.status != "resolved",
        ReviewSignal.category.in_(("metric_regression", "metric_below_floor")))).all()}
    for mid in model_ids:
        a, ok = latest_any.get(mid), latest_ok.get(mid)
        row = out[mid]
        if a is not None:
            row["latest_run_id"], row["latest_run_at"] = a.id, a.started_at
        if ok is not None:
            row["latest_succeeded_run_id"], row["latest_succeeded_at"] = ok.id, ok.completed_at or ok.started_at
            row["metrics"] = {k: v.get("value") for k, v in (ok.metrics or {}).items() if v.get("defined")}
        if a is None:
            continue
        if a.status == "running":
            row["status"] = "running"
        elif a.status == "failed":
            row["status"] = "failed"
        elif ensure_utc(a.completed_at or a.started_at) < stale_before:
            row["status"] = "stale"
        elif mid in flagged:
            row["status"] = "review_needed"
        else:
            row["status"] = "passed"
    return out


def _artifact_brief(model: ModelRecord) -> dict:
    return artifacts.check_artifact(model.artifact_reference, model.adapter_key, model.artifact_digest, verify_digest=False).as_dict()


def serialize_version(model: ModelRecord, ev: Optional[dict] = None, *, viewer_org: str, include_detail: bool = False) -> dict:
    d = {
        "id": model.id, "name": model.name, "version": model.version, "task_type": model.task_type, "model_type": model.model_type,
        "lifecycle_state": model.lifecycle_state, "legacy_status": model.status, "adapter_key": model.adapter_key,
        "supported_media_types": model.supported_media_types or [], "artifact_reference": model.artifact_reference,
        "artifact_digest": model.artifact_digest, "artifact": _artifact_brief(model),
        "scope": "platform" if model.owner_organization_id is None else "organization",
        "owned_by_your_organization": model.owner_organization_id == viewer_org,
        "created_at": model.created_at, "evaluation": ev or {"status": "none"},
    }
    if include_detail:
        d.update(
            input_schema_version=model.input_schema_version, output_schema_version=model.output_schema_version,
            framework_metadata=model.framework_metadata or {}, release_notes=model.release_notes, documentation_ref=model.documentation_ref,
            created_by_user_id=model.created_by_user_id if model.owner_organization_id == viewer_org else None,
            serving_note="Approval is registry metadata only. This application has no model serving/activation environment; nothing is deployed by approving a version.",
        )
    return d


def versions_query(organization_id: str, *, q: Optional[str] = None, task: Optional[str] = None, lifecycle_state: Optional[str] = None,
                   family: Optional[str] = None, sort: str = "created_at", order: str = "desc"):
    stmt = select(ModelRecord).where(visible_clause(organization_id))
    if q:
        like = f"%{q.strip()[:100]}%"
        stmt = stmt.where(or_(ModelRecord.name.ilike(like), ModelRecord.version.ilike(like)))
    if task:
        stmt = stmt.where(ModelRecord.task_type == task)
    if lifecycle_state:
        stmt = stmt.where(ModelRecord.lifecycle_state == lifecycle_state)
    if family:
        stmt = stmt.where(ModelRecord.name == family)
    col = {"created_at": ModelRecord.created_at, "name": ModelRecord.name, "version": ModelRecord.version, "lifecycle_state": ModelRecord.lifecycle_state}.get(sort, ModelRecord.created_at)
    return stmt.order_by(col.asc() if order == "asc" else col.desc(), ModelRecord.id)


def list_families(db: Session, organization_id: str, *, q: Optional[str], page: int, page_size: int) -> dict:
    base = select(ModelRecord.name, func.count().label("n"), func.max(ModelRecord.created_at).label("latest")).where(visible_clause(organization_id)).group_by(ModelRecord.name)
    if q:
        base = base.where(ModelRecord.name.ilike(f"%{q.strip()[:100]}%"))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    names = db.execute(base.order_by(func.max(ModelRecord.created_at).desc(), ModelRecord.name).limit(page_size).offset((page - 1) * page_size)).all()
    rows = db.execute(select(ModelRecord).where(visible_clause(organization_id), ModelRecord.name.in_([n for n, _, _ in names]))).scalars().all() if names else []
    by_name: dict[str, list[ModelRecord]] = {}
    for r in rows:
        by_name.setdefault(r.name, []).append(r)
    items = []
    for name, n, latest in names:
        versions = by_name.get(name, [])
        states: dict[str, int] = {}
        for v in versions:
            states[v.lifecycle_state] = states.get(v.lifecycle_state, 0) + 1
        newest = max(versions, key=lambda v: v.created_at) if versions else None
        items.append({"name": name, "version_count": n, "latest_version": newest.version if newest else None,
                      "task_types": sorted({v.task_type for v in versions if v.task_type}), "lifecycle_counts": states, "latest_registered_at": latest})
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ---------------------------------------------------------------- artifacts ----
def verify_artifact(db: Session, *, organization_id: str, user_id: str, model: ModelRecord, request_id: Optional[str]) -> dict:
    try:
        st = artifacts.check_artifact(model.artifact_reference, model.adapter_key, model.artifact_digest, verify_digest=True)
    except MlopsValidationError as exc:
        st = artifacts.ArtifactStatus(kind="file", available=False, reason=str(exc), digest_checked=True)
    ok = st.available and (st.digest_match is not False)
    metrics_registry.inc("mlops_artifact_verifications_total", {"outcome": "ok" if ok else "unavailable"})
    audit_service.record(db, action="mlops.model.verify_artifact", actor_user_id=user_id, organization_id=organization_id,
                         target_type="model_record", target_id=model.id, outcome="success" if ok else "failure", request_id=request_id,
                         context_metadata={"kind": st.kind, "available": st.available, "digest_match": st.digest_match})
    signal = None
    if not ok:
        sig, _ = mlops_signal_service.raise_signal(
            db, organization_id=organization_id, category="artifact_unavailable", severity="serious" if st.digest_match is False else "warning",
            dedup_key=f"artifact_unavailable:{model.id}", title=f"Model artifact unavailable: {model.name} {model.version}",
            summary=f"Artifact verification failed: {st.reason or 'unavailable'}.", model_record_id=model.id, subsystem="model_registry",
            evidence=st.as_dict(), limitations="Reflects the state of artifact storage at verification time only.", request_id=request_id)
        signal = sig.id
    out = st.as_dict()
    out["review_signal_id"] = signal
    return out
