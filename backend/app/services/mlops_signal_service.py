"""Review signals.

A signal says "a measured quantity crossed a configured threshold; a person
should look". It never asserts a real-world threat, never triggers an
automated operational action, and is created idempotently:

 * One OPEN/ACKNOWLEDGED row exists per (organization, dedup_key). Re-observing
   the same condition updates that row (occurrence_count, last_seen_at, latest
   observed value/evidence; severity can only ESCALATE) instead of inserting a
   duplicate, so a repeated scan cannot cause an alert storm.
 * A resolved signal stays resolved; if the condition recurs later a NEW row is
   created so the history shows each distinct episode (same convention as the
   Phase 9 fleet alerts).
 * Deduplication is enforced in the service layer, not by a DB unique
   constraint (a unique key would block recording a second episode). Two truly
   concurrent writers could still race; this is documented in KNOWN_RISKS.
 * Resolution is manual. Nothing auto-resolves a signal when a metric recovers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.errors import MlopsConflict, MlopsNotFound, MlopsValidationError, scrub
from app.core.obs_metrics import registry
from app.mlops.validation import bounded_evidence
from app.models.mlops import SIGNAL_CATEGORIES, SIGNAL_SEVERITIES, ExperimentRun, ReviewSignal
from app.models.model_record import ModelRecord
from app.models.user import User
from app.services import audit_service

SEVERITY_RANK = {s: i for i, s in enumerate(SIGNAL_SEVERITIES)}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def raise_signal(
    db: Session, *, organization_id: str, category: str, severity: str, dedup_key: str, title: str, summary: str,
    subsystem: str = "mlops", model_record_id: Optional[str] = None, experiment_run_id: Optional[str] = None,
    snapshot_id: Optional[str] = None, observed_value: Optional[float] = None, threshold_value: Optional[float] = None,
    evidence: Optional[dict] = None, limitations: Optional[str] = None, request_id: Optional[str] = None,
) -> tuple[ReviewSignal, bool]:
    """Creates or refreshes a signal. Returns (signal, created). Flush-only: the
    caller owns the transaction."""
    if category not in SIGNAL_CATEGORIES:
        raise ValueError(f"unknown signal category {category!r}")
    if severity not in SIGNAL_SEVERITIES:
        raise ValueError(f"unknown signal severity {severity!r}")
    now = _now()
    ev = bounded_evidence(evidence or {})
    existing = db.execute(
        select(ReviewSignal).where(
            ReviewSignal.organization_id == organization_id, ReviewSignal.dedup_key == dedup_key,
            ReviewSignal.status.in_(("open", "acknowledged")),
        ).order_by(ReviewSignal.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        existing.occurrence_count += 1
        existing.last_seen_at = now
        existing.observed_value = observed_value
        existing.threshold_value = threshold_value
        existing.evidence = ev
        existing.summary = scrub(summary, 2000)
        if SEVERITY_RANK[severity] > SEVERITY_RANK[existing.severity]:
            existing.severity = severity
        db.flush()
        return existing, False
    sig = ReviewSignal(
        organization_id=organization_id, category=category, severity=severity, status="open", dedup_key=dedup_key[:200],
        title=title[:300], summary=scrub(summary, 2000), subsystem=subsystem, model_record_id=model_record_id,
        experiment_run_id=experiment_run_id, snapshot_id=snapshot_id, observed_value=observed_value,
        threshold_value=threshold_value, evidence=ev, limitations=limitations[:1000] if limitations else None,
        occurrence_count=1, first_seen_at=now, last_seen_at=now,
    )
    db.add(sig)
    db.flush()
    registry.inc("mlops_review_signals_total", {"category": category, "severity": severity})
    audit_service.record(
        db, action="mlops.signal.raised", actor_user_id=None, organization_id=organization_id, target_type="review_signal",
        target_id=sig.id, request_id=request_id,
        context_metadata={"category": category, "severity": severity, "model_record_id": model_record_id, "experiment_run_id": experiment_run_id},
    )
    return sig, True


def get_signal(db: Session, organization_id: str, signal_id: str) -> ReviewSignal:
    sig = db.execute(select(ReviewSignal).where(ReviewSignal.id == signal_id, ReviewSignal.organization_id == organization_id)).scalar_one_or_none()
    if sig is None:
        raise MlopsNotFound("Review signal not found")
    return sig


def acknowledge(db: Session, *, organization_id: str, signal_id: str, user_id: str, assignee_user_id: Optional[str], request_id: Optional[str]) -> ReviewSignal:
    sig = get_signal(db, organization_id, signal_id)
    if sig.status != "open":
        raise MlopsConflict(f"Only an open signal can be acknowledged (current status: {sig.status})")
    assignee = assignee_user_id or user_id
    # Assignment must stay inside the organization; a foreign or inactive user id is rejected, not stored.
    ok = db.execute(select(User.id).where(User.id == assignee, User.organization_id == organization_id, User.is_active.is_(True))).scalar_one_or_none()
    if ok is None:
        raise MlopsValidationError("assignee must be an active user in this organization")
    sig.status = "acknowledged"
    sig.acknowledged_by_user_id = user_id
    sig.acknowledged_at = _now()
    sig.assigned_to_user_id = assignee
    audit_service.record(db, action="mlops.signal.acknowledge", actor_user_id=user_id, organization_id=organization_id,
                         target_type="review_signal", target_id=sig.id, request_id=request_id,
                         context_metadata={"from": "open", "to": "acknowledged", "assigned_to": assignee, "category": sig.category})
    db.flush()
    return sig


def resolve(db: Session, *, organization_id: str, signal_id: str, user_id: str, notes: str, request_id: Optional[str]) -> ReviewSignal:
    sig = get_signal(db, organization_id, signal_id)
    if sig.status == "resolved":
        raise MlopsConflict("Signal is already resolved")
    notes = (notes or "").strip()
    if len(notes) < 3:
        raise MlopsValidationError("resolution notes are required (at least 3 characters)")
    if len(notes) > 2000:
        raise MlopsValidationError("resolution notes are limited to 2000 characters")
    prev = sig.status
    sig.status = "resolved"
    sig.resolved_by_user_id = user_id
    sig.resolved_at = _now()
    sig.resolution_notes = notes
    audit_service.record(db, action="mlops.signal.resolve", actor_user_id=user_id, organization_id=organization_id,
                         target_type="review_signal", target_id=sig.id, request_id=request_id,
                         context_metadata={"from": prev, "to": "resolved", "category": sig.category})
    db.flush()
    return sig


def list_query(organization_id: str, *, status: Optional[str] = None, category: Optional[str] = None, severity: Optional[str] = None,
               model_record_id: Optional[str] = None, experiment_run_id: Optional[str] = None):
    stmt = select(ReviewSignal).where(ReviewSignal.organization_id == organization_id)
    if status:
        stmt = stmt.where(ReviewSignal.status == status)
    if category:
        stmt = stmt.where(ReviewSignal.category == category)
    if severity:
        stmt = stmt.where(ReviewSignal.severity == severity)
    if model_record_id:
        stmt = stmt.where(ReviewSignal.model_record_id == model_record_id)
    if experiment_run_id:
        stmt = stmt.where(ReviewSignal.experiment_run_id == experiment_run_id)
    rank = case(*[(ReviewSignal.severity == s, i) for s, i in SEVERITY_RANK.items()], else_=0)
    status_rank = case((ReviewSignal.status == "open", 0), (ReviewSignal.status == "acknowledged", 1), else_=2)
    return stmt.order_by(status_rank, rank.desc(), ReviewSignal.last_seen_at.desc())


def counts(db: Session, organization_id: str) -> dict:
    rows = db.execute(
        select(ReviewSignal.status, ReviewSignal.severity, func.count()).where(ReviewSignal.organization_id == organization_id)
        .group_by(ReviewSignal.status, ReviewSignal.severity)
    ).all()
    by_status: dict[str, int] = {}
    unresolved_by_severity: dict[str, int] = {}
    for st, sev, n in rows:
        by_status[st] = by_status.get(st, 0) + n
        if st != "resolved":
            unresolved_by_severity[sev] = unresolved_by_severity.get(sev, 0) + n
    return {"by_status": by_status, "unresolved_by_severity": unresolved_by_severity}


def serialize(db: Session, sig: ReviewSignal) -> dict:
    model = db.get(ModelRecord, sig.model_record_id) if sig.model_record_id else None
    run = db.get(ExperimentRun, sig.experiment_run_id) if sig.experiment_run_id else None
    return {
        "id": sig.id, "category": sig.category, "severity": sig.severity, "status": sig.status, "title": sig.title, "summary": sig.summary,
        "subsystem": sig.subsystem, "model_record_id": sig.model_record_id,
        "model_name": model.name if model else None, "model_version": model.version if model else None,
        "experiment_run_id": sig.experiment_run_id, "experiment_name": run.experiment_name if run else None, "snapshot_id": sig.snapshot_id,
        "observed_value": sig.observed_value, "threshold_value": sig.threshold_value, "evidence": sig.evidence or {},
        "limitations": sig.limitations, "occurrence_count": sig.occurrence_count, "first_seen_at": sig.first_seen_at, "last_seen_at": sig.last_seen_at,
        "assigned_to_user_id": sig.assigned_to_user_id, "acknowledged_by_user_id": sig.acknowledged_by_user_id, "acknowledged_at": sig.acknowledged_at,
        "resolved_by_user_id": sig.resolved_by_user_id, "resolved_at": sig.resolved_at, "resolution_notes": sig.resolution_notes,
        "advisory_notice": "Review signal: a measured value crossed a configured threshold. It is not evidence of a real-world condition and triggers no automatic action.",
    }
