"""Event correlation. Deterministic, rule-based,
fully explainable candidate-relationship detection for analyst review --
this is explicitly NOT a certainty claim, a fusion engine, or a merge
of two events into one. Advanced probabilistic fusion is out of scope
here and belongs to Phase 3; this module only ever produces
EventCorrelation rows an analyst can inspect, confirm, or reject.

Every correlation this module creates:
  * names the exact reasons it fired (`reasons`, machine-readable codes)
  * is reproducible -- the same inputs + rule_version always produce
    the same correlation
  * is between two EXISTING, UNCHANGED events -- never a merge
  * is NEVER created between an event and itself, and is stored at
    most once per (event_a_id, event_b_id, rule_version) pair

`recompute()` is the one, explicit, auditable entry point -- there is
no background job silently creating correlations; see
docs/analytics/EVENT_CORRELATION.md for the full rule documentation.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.geo.distance import haversine_meters
from app.models.event import Event
from app.models.event_correlation import EventCorrelation

RULE_VERSION = "1.0"

# Configurable thresholds (Section 14 requires these be explicit and
# configurable -- these are the module's documented defaults; a future
# per-organization settings surface can override them without changing
# the rule logic itself).
DEFAULT_TIME_WINDOW_SECONDS = 30 * 60  # 30 minutes
DEFAULT_SPATIAL_THRESHOLD_METERS = 500.0

# Phase 7: the haversine implementation itself now lives in
# app/geo/distance.py as the one shared, public, documented, tested
# distance function for the whole codebase -- this module no longer
# defines its own copy (it used to, as a private `_haversine_meters`
# helper with an identical formula and the same EARTH_RADIUS_METERS
# constant). Zero behavior change; see app/geo/distance.py's module
# docstring.

# Reason code -> weight used ONLY to compute the documented, bounded
# match_strength figure below -- never exposed as a probability of
# truth. A same-source repeat is weighted low on purpose: Section 14
# explicitly forbids treating two reports from the SAME source as
# independent corroboration, so it alone should never push
# match_strength near 1.0.
REASON_WEIGHTS = {
    "shared_asset_reference": 0.40,
    "temporal_proximity": 0.25,
    "spatial_proximity": 0.25,
    "compatible_event_type": 0.15,
    "shared_source_id": 0.10,
}

# A candidate is only created when at least this many independent
# reasons fire -- a single weak signal (e.g. "happened on the same
# day") is not treated as a correlation candidate at all.
MIN_REASONS_FOR_CANDIDATE = 2


def _compatible_event_types(a: str, b: str) -> bool:
    """Equal types are trivially compatible; everything else is
    "not compatible" for now -- a documented, extensible mapping point
    ("explicit matching rules") rather than a fuzzy guess."""
    return a.strip().lower() == b.strip().lower()


def _find_reasons(a: Event, b: Event, *, time_window_seconds: int, spatial_threshold_meters: float) -> tuple[list[str], Optional[float], Optional[float]]:
    reasons: list[str] = []
    temporal_delta: Optional[float] = None
    spatial_delta: Optional[float] = None

    if a.source_id == b.source_id:
        reasons.append("shared_source_id")

    if a.asset_id and b.asset_id and a.asset_id == b.asset_id:
        reasons.append("shared_asset_reference")

    if _compatible_event_types(a.event_type, b.event_type):
        reasons.append("compatible_event_type")

    delta_seconds = abs((a.observed_at - b.observed_at).total_seconds())
    temporal_delta = delta_seconds
    if delta_seconds <= time_window_seconds:
        reasons.append("temporal_proximity")

    if a.latitude is not None and a.longitude is not None and b.latitude is not None and b.longitude is not None:
        distance = haversine_meters(a.latitude, a.longitude, b.latitude, b.longitude)
        spatial_delta = distance
        if distance <= spatial_threshold_meters:
            reasons.append("spatial_proximity")

    return reasons, temporal_delta, spatial_delta


def _match_strength(reasons: list[str]) -> float:
    return round(min(1.0, sum(REASON_WEIGHTS.get(r, 0.0) for r in reasons)), 4)


def recompute(
    db: Session,
    organization_id: str,
    *,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    time_window_seconds: int = DEFAULT_TIME_WINDOW_SECONDS,
    spatial_threshold_meters: float = DEFAULT_SPATIAL_THRESHOLD_METERS,
    max_events: int = 2000,
    time_window_seconds_by_type: Optional[dict[str, int]] = None,
) -> dict:
    """The one explicit, auditable "run the correlation rules" entry
    point ("recompute only via an authorized auditable
    operation"). Compares events within `time_window_seconds` of each
    other (events far apart in time are never compared at all, which
    bounds this from being an O(n^2) scan of the whole table) and
    inserts a new EventCorrelation candidate for every pair that
    clears MIN_REASONS_FOR_CANDIDATE and doesn't already have one for
    this rule_version. Returns a summary of what this run did -- never
    silently merges or mutates an existing event.

    `time_window_seconds_by_type` (Phase 3, `settings.
    fusion_time_window_seconds_by_type`) is an optional per-event-type
    override layered on top of `time_window_seconds`: when either side
    of a pair has a `event_type` listed in this mapping, the LARGER of
    the two sides' windows (falling back to `time_window_seconds` for a
    side with no override) is used for that pair's own
    `temporal_proximity` check -- e.g. a slow-to-report "sensor_offline"
    event type can be given a longer window than a fast-moving
    "intrusion" type without changing the global default. A type not
    listed here is completely unaffected."""
    batch_id = str(uuid.uuid4())
    overrides = time_window_seconds_by_type or {}
    # The early-break scan bound below must use the LARGEST window any
    # pair could legitimately need -- never just the global default --
    # or a longer per-type override would be missed by breaking the
    # inner loop too soon.
    max_possible_window = max([time_window_seconds, *overrides.values()]) if overrides else time_window_seconds

    stmt = select(Event).where(Event.organization_id == organization_id)
    if since:
        stmt = stmt.where(Event.observed_at >= since)
    if until:
        stmt = stmt.where(Event.observed_at <= until)
    stmt = stmt.order_by(Event.observed_at.asc()).limit(max_events)
    events = db.execute(stmt).scalars().all()

    # Existing pairs for this rule_version, so a re-run is idempotent
    # rather than erroring on the unique constraint or duplicating rows.
    existing_stmt = select(EventCorrelation.event_a_id, EventCorrelation.event_b_id).where(
        EventCorrelation.organization_id == organization_id, EventCorrelation.rule_version == RULE_VERSION
    )
    existing_pairs = {(a, b) for a, b in db.execute(existing_stmt).all()}

    created = 0
    skipped_existing = 0
    candidates_considered = 0

    for i, a in enumerate(events):
        for b in events[i + 1 :]:
            # Events are time-ordered, so once b is further than the
            # widest possible window from a, every later b is too --
            # stop this inner loop early rather than comparing the
            # whole remaining list.
            if (b.observed_at - a.observed_at).total_seconds() > max_possible_window:
                break
            if a.id == b.id:
                continue
            event_a_id, event_b_id = sorted((a.id, b.id))
            if (event_a_id, event_b_id) in existing_pairs:
                skipped_existing += 1
                continue

            candidates_considered += 1
            ordered_a, ordered_b = (a, b) if a.id == event_a_id else (b, a)
            pair_window = max(
                overrides.get(ordered_a.event_type, time_window_seconds),
                overrides.get(ordered_b.event_type, time_window_seconds),
            )
            reasons, temporal_delta, spatial_delta = _find_reasons(
                ordered_a, ordered_b, time_window_seconds=pair_window, spatial_threshold_meters=spatial_threshold_meters
            )
            if len(reasons) < MIN_REASONS_FOR_CANDIDATE:
                continue

            correlation = EventCorrelation(
                organization_id=organization_id,
                event_a_id=event_a_id,
                event_b_id=event_b_id,
                reasons=reasons,
                rule_version=RULE_VERSION,
                temporal_delta_seconds=temporal_delta,
                spatial_delta_meters=spatial_delta,
                match_strength=_match_strength(reasons),
                review_status="candidate",
                correlation_batch_id=batch_id,
            )
            db.add(correlation)
            existing_pairs.add((event_a_id, event_b_id))
            created += 1

    db.commit()
    return {
        "batch_id": batch_id,
        "events_considered": len(events),
        "pairs_considered": candidates_considered,
        "correlations_created": created,
        "already_existed": skipped_existing,
        "rule_version": RULE_VERSION,
        "time_window_seconds": time_window_seconds,
        "spatial_threshold_meters": spatial_threshold_meters,
    }


def list_correlations_for_event(db: Session, organization_id: str, event_id: str):
    stmt = (
        select(EventCorrelation)
        .where(
            EventCorrelation.organization_id == organization_id,
            (EventCorrelation.event_a_id == event_id) | (EventCorrelation.event_b_id == event_id),
        )
        .order_by(EventCorrelation.match_strength.desc())
    )
    return db.execute(stmt).scalars().all()


def list_correlations_query(organization_id: str, *, review_status: Optional[str] = None):
    stmt = select(EventCorrelation).where(EventCorrelation.organization_id == organization_id)
    if review_status:
        stmt = stmt.where(EventCorrelation.review_status == review_status)
    return stmt.order_by(EventCorrelation.created_at.desc())


def get_correlation(db: Session, organization_id: str, correlation_id: str) -> Optional[EventCorrelation]:
    stmt = select(EventCorrelation).where(EventCorrelation.id == correlation_id, EventCorrelation.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def review_correlation(db: Session, correlation: EventCorrelation, *, review_status: str, reviewed_by_user_id: Optional[str]) -> EventCorrelation:
    """An analyst's explicit confirm/reject decision -- this is the
    ONLY way review_status ever leaves "candidate"; nothing in this
    module promotes a candidate automatically."""
    from datetime import timezone

    correlation.review_status = review_status
    correlation.reviewed_by_user_id = reviewed_by_user_id
    correlation.reviewed_at = datetime.now(timezone.utc)
    db.add(correlation)
    db.commit()
    db.refresh(correlation)
    return correlation
