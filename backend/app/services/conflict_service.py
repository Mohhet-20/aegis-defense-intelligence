"""Conflict detection. Deliberately scoped to
pairs of events ALREADY flagged related by `correlation_service.py` --
this is never an independent all-pairs scan, and it never treats a
field one side simply didn't report as a contradiction (missing
information is not negative evidence).

A conflict fires only for an ACTUAL, comparable disagreement:
  * `incompatible_event_type` -- correlated via a strong non-type
    signal (shared asset or shared source), but the two event_type
    values differ.
  * `conflicting_severity` -- both sides report a source_severity, and
    they differ.
  * `conflicting_location` -- correlated, but NOT via spatial_proximity
    (i.e. either one side had no coordinates, or they were further
    apart than the correlation threshold), and both sides DO have
    coordinates that are further apart than
    `FUSION_SPATIAL_CONFLICT_THRESHOLD_METERS` -- a materially different
    reported location for what other signals say is probably the same
    thing.
  * Any `identifier_service.compare_events()` result with outcome
    "conflict" (a shared attribute key with disagreeing values).

Conflicts are idempotent per (event_a_id, event_b_id,
conflict_rule_version) -- a rerun never duplicates an existing row, and
updates its `conflicting_fields` in place if the underlying events or
rule version changed (events are otherwise immutable, so in practice
this only differs on a genuine rule_version bump).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.conflict import Conflict
from app.models.event import Event
from app.models.event_correlation import EventCorrelation
from app.services import identifier_service

settings = get_settings()

CONFLICT_RULE_VERSION = "1.0"


def _spatial_conflict(a: Event, b: Event, correlation: EventCorrelation, *, spatial_conflict_threshold_meters: float) -> Optional[dict]:
    if "spatial_proximity" in (correlation.reasons or []):
        return None  # already agree closely enough to have fired as a match signal
    if a.latitude is None or a.longitude is None or b.latitude is None or b.longitude is None:
        return None  # missing coordinates on either side is unknown, not a conflict
    if correlation.spatial_delta_meters is None:
        return None
    if correlation.spatial_delta_meters <= spatial_conflict_threshold_meters:
        return None
    return {
        "field": "location",
        "value_a": {"latitude": a.latitude, "longitude": a.longitude},
        "value_b": {"latitude": b.latitude, "longitude": b.longitude},
        "rule": f"distance {correlation.spatial_delta_meters:.1f}m exceeds conflict threshold {spatial_conflict_threshold_meters:.1f}m",
    }


def _find_conflicting_fields(a: Event, b: Event, correlation: EventCorrelation, *, spatial_conflict_threshold_meters: float) -> list[dict]:
    fields: list[dict] = []

    strong_non_type_signal = any(r in (correlation.reasons or []) for r in ("shared_asset_reference", "shared_source_id"))
    if strong_non_type_signal and a.event_type.strip().lower() != b.event_type.strip().lower():
        fields.append({"field": "event_type", "value_a": a.event_type, "value_b": b.event_type, "rule": "incompatible_event_type"})

    if a.source_severity and b.source_severity and a.source_severity.strip().lower() != b.source_severity.strip().lower():
        fields.append({"field": "source_severity", "value_a": a.source_severity, "value_b": b.source_severity, "rule": "conflicting_severity"})

    spatial = _spatial_conflict(a, b, correlation, spatial_conflict_threshold_meters=spatial_conflict_threshold_meters)
    if spatial:
        fields.append(spatial)

    for cmp in identifier_service.compare_events(a, b):
        if cmp.outcome == "conflict":
            fields.append({"field": cmp.field, "value_a": cmp.value_a, "value_b": cmp.value_b, "rule": "conflicting_attribute_value"})

    return fields


def detect_conflicts(
    db: Session,
    organization_id: str,
    *,
    correlation_batch_id: Optional[str] = None,
    spatial_conflict_threshold_meters: Optional[float] = None,
    max_pairs: int = 2000,
) -> dict:
    """The one explicit entry point that produces `Conflict` rows --
    always run over existing `EventCorrelation` candidates (optionally
    narrowed to one batch), never a fresh pairwise scan. Safe to call
    repeatedly: an unchanged pair+rule_version is skipped, not
    duplicated."""
    threshold = spatial_conflict_threshold_meters if spatial_conflict_threshold_meters is not None else settings.FUSION_SPATIAL_CONFLICT_THRESHOLD_METERS
    batch_id = str(uuid.uuid4())

    corr_stmt = select(EventCorrelation).where(
        EventCorrelation.organization_id == organization_id,
        EventCorrelation.review_status != "rejected",
    )
    if correlation_batch_id:
        corr_stmt = corr_stmt.where(EventCorrelation.correlation_batch_id == correlation_batch_id)
    corr_stmt = corr_stmt.limit(max_pairs)
    correlations = db.execute(corr_stmt).scalars().all()

    existing_stmt = select(Conflict.event_a_id, Conflict.event_b_id).where(
        Conflict.organization_id == organization_id, Conflict.conflict_rule_version == CONFLICT_RULE_VERSION
    )
    existing_pairs = {(a, b) for a, b in db.execute(existing_stmt).all()}

    created = 0
    updated = 0
    pairs_considered = 0

    for correlation in correlations:
        event_a = db.get(Event, correlation.event_a_id)
        event_b = db.get(Event, correlation.event_b_id)
        if event_a is None or event_b is None:
            continue
        pairs_considered += 1

        fields = _find_conflicting_fields(event_a, event_b, correlation, spatial_conflict_threshold_meters=threshold)
        pair_key = (correlation.event_a_id, correlation.event_b_id)

        if not fields:
            continue

        if pair_key in existing_pairs:
            existing_conflict = db.execute(
                select(Conflict).where(
                    Conflict.organization_id == organization_id,
                    Conflict.event_a_id == correlation.event_a_id,
                    Conflict.event_b_id == correlation.event_b_id,
                    Conflict.conflict_rule_version == CONFLICT_RULE_VERSION,
                )
            ).scalar_one_or_none()
            if existing_conflict and existing_conflict.conflicting_fields != fields:
                existing_conflict.conflicting_fields = fields
                db.add(existing_conflict)
                updated += 1
            continue

        conflict = Conflict(
            organization_id=organization_id,
            event_a_id=correlation.event_a_id,
            event_b_id=correlation.event_b_id,
            correlation_id=correlation.id,
            conflicting_fields=fields,
            conflict_rule_version=CONFLICT_RULE_VERSION,
            review_status="unresolved",
            fusion_batch_id=batch_id,
        )
        db.add(conflict)
        existing_pairs.add(pair_key)
        created += 1

    db.commit()
    return {
        "batch_id": batch_id,
        "pairs_considered": pairs_considered,
        "conflicts_created": created,
        "conflicts_updated": updated,
        "rule_version": CONFLICT_RULE_VERSION,
    }


def list_conflicts_query(organization_id: str, *, review_status: Optional[str] = None, event_id: Optional[str] = None):
    stmt = select(Conflict).where(Conflict.organization_id == organization_id)
    if review_status:
        stmt = stmt.where(Conflict.review_status == review_status)
    if event_id:
        stmt = stmt.where((Conflict.event_a_id == event_id) | (Conflict.event_b_id == event_id))
    return stmt.order_by(Conflict.created_at.desc())


def get_conflict(db: Session, organization_id: str, conflict_id: str) -> Optional[Conflict]:
    stmt = select(Conflict).where(Conflict.id == conflict_id, Conflict.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def resolve_conflict(
    db: Session, conflict: Conflict, *, review_status: str, resolved_by_user_id: Optional[str], resolution_note: Optional[str], request_id: Optional[str] = None,
) -> Conflict:
    """The only way a conflict's review_status ever changes. Never
    rewrites `conflicting_fields` or either underlying Event -- see the
    module docstring and docs/analytics/CONFLICT_DETECTION.md for what
    "corrected" and "superseded" do and do NOT mean here. Writes its
    own audit record in the SAME transaction as the state change, so
    the two can never disagree."""
    from app.models.conflict import CONFLICT_REVIEW_STATUSES
    from app.services import audit_service

    if review_status not in CONFLICT_REVIEW_STATUSES:
        raise ValueError(f"'{review_status}' is not a valid conflict review_status (must be one of {CONFLICT_REVIEW_STATUSES})")

    prior_status = conflict.review_status
    conflict.review_status = review_status
    conflict.resolved_by_user_id = resolved_by_user_id
    conflict.resolved_at = datetime.now(timezone.utc)
    conflict.resolution_note = resolution_note
    db.add(conflict)

    audit_service.record(
        db, action="conflict.resolve", actor_user_id=resolved_by_user_id, organization_id=conflict.organization_id,
        target_type="conflict", target_id=conflict.id, request_id=request_id,
        context_metadata={"prior_status": prior_status, "new_status": review_status, "resolution_note": resolution_note},
    )
    db.commit()
    db.refresh(conflict)
    return conflict


def get_review_history(db: Session, organization_id: str, conflict_id: str):
    from app.services import audit_service

    return audit_service.list_for_target(db, organization_id, target_type="conflict", target_id=conflict_id)
