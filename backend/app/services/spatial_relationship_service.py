"""Automated spatial-relationship candidate generation (Phase 7,
Section 11). Produces "spatially_associated" EvidenceRelationship rows
between Event/Observation pairs that are BOTH close in space (<=
a configurable distance threshold) AND close in time (<= a configurable
time window) -- never auto-merges them, never claims they describe the
same real-world thing, and never fabricates a location: only records
whose coordinates are already classified "valid" by app/geo/validation.py
are ever compared.

`EvidenceRelationship.RELATIONSHIP_TYPES` has reserved the
"spatially_associated" value since Phase 3, unused until now -- this
module is what finally produces it, rather than inventing a new string.

Deliberately out of scope (documented here, not silently dropped):
  * Determining whether two spatially/temporally close records
    describe the SAME real-world event/object ("location conflict
    requiring review", "spatially inconsistent duplicate") is Phase
    3's app/services/conflict_service.py's job. generate_candidates()
    below creates an EXPLAINABLE ASSOCIATION, never a merge and never a
    conflict finding, and never calls into conflict_service. An
    analyst who reviews a candidate and judges the two records to be
    the same real-world thing uses conflict_service's own workflow for
    that -- this module does not attempt it.
  * Attaching a threat level, intent, or priority to a candidate based
    on geographic proximity or density (Section 20's prohibited-scope
    list) -- never done anywhere in this module. A candidate is a
    reviewable fact ("these two things were close"), never a
    conclusion ("this is suspicious").
  * Sensor<->Sensor and Asset<->* spatial pairs. Section 11's own
    framing is "two independently-sourced records reporting activity
    near the same place/time," which maps onto Event and Observation
    (the two record types that represent an OCCURRENCE), not
    Sensor/Asset (fixed infrastructure, whose mutual proximity is a
    deployment fact already visible on the map, not a new
    intelligence finding).

Bounding the comparison (Section 15 -- "avoid unbounded pairwise
spatial comparisons"): records are fetched oldest-first up to
settings.GEOSPATIAL_RELATIONSHIP_MAX_CANDIDATES (a hard ceiling on N),
sorted by timestamp, and compared with a SLIDING WINDOW -- for each
record, the inner loop only considers records that follow it within
the time window and stops (via `break`, since the list is
time-sorted) as soon as that window is exceeded. Actual distance
comparisons are therefore bounded by how many records fall within the
time window of each other, never by N^2.

Review workflow: this module does NOT implement confirm/reject/
uncertain logic of its own. A generated candidate is an ordinary
EvidenceRelationship row with review_status="candidate", reviewed the
same way any other relationship is -- via
app/services/relationship_service.review_relationship().
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.geo.distance import haversine_meters
from app.geo.validation import classify_validation_status
from app.models.event import Event
from app.models.evidence import Evidence
from app.models.observation import Observation
from app.schemas.geospatial import SpatialRelationshipCandidateResponse, SpatialRelationshipRunResponse
from app.services import evidence_service, relationship_service

settings = get_settings()

RULE_VERSION = "spatial_relationship_v1"

# The only two record types this module compares -- see the module
# docstring's "Deliberately out of scope" section for why Sensor/Asset
# are excluded.
_CANDIDATE_RECORD_TYPES = ("event", "observation")

_RECORD_TYPE_MODELS = {"event": Event, "observation": Observation}


@dataclass
class _Candidate:
    record_type: str
    record_id: str
    latitude: float
    longitude: float
    timestamp: datetime
    row: object  # the actual Event or Observation ORM row, for Evidence-wrapping


def _usable_rows(
    db: Session, organization_id: str, record_type: str, *,
    since: Optional[datetime], until: Optional[datetime], limit: int,
) -> list[_Candidate]:
    """Every row of `record_type` with a currently-valid location,
    oldest observed_at first, capped at `limit` -- this is where N
    gets bounded."""
    model = _RECORD_TYPE_MODELS[record_type]
    stmt = select(model).where(
        model.organization_id == organization_id,
        model.latitude.is_not(None),
        model.longitude.is_not(None),
    )
    if since is not None:
        stmt = stmt.where(model.observed_at >= since)
    if until is not None:
        stmt = stmt.where(model.observed_at < until)  # half-open interval
    stmt = stmt.order_by(model.observed_at.asc()).limit(limit)
    rows = db.execute(stmt).scalars().all()

    out: list[_Candidate] = []
    for row in rows:
        status = classify_validation_status(row.latitude, row.longitude, coordinate_reference_system=row.coordinate_reference_system)
        if status != "valid":
            continue  # never compares an unusable location
        out.append(_Candidate(record_type=record_type, record_id=row.id, latitude=row.latitude, longitude=row.longitude, timestamp=row.observed_at, row=row))
    return out


def _as_relationship_ref(db: Session, organization_id: str, candidate: _Candidate, *, created_by_user_id: Optional[str]) -> tuple[str, str]:
    """Returns (ref_type, ref_id) suitable for
    relationship_service.create_relationship(). An Event is directly
    referenceable; an Observation is not
    (app/models/evidence_relationship.py's REFERENCEABLE_TYPES is only
    `("event", "evidence")`) so it is wrapped as a "sensor_observation"
    Evidence item first -- the exact pattern
    app/services/cross_source_comparison_service.py established in
    Phase 6, now shared via evidence_service.get_or_create_observation_evidence."""
    if candidate.record_type == "event":
        return "event", candidate.record_id
    evidence = evidence_service.get_or_create_observation_evidence(db, organization_id, candidate.row, created_by_user_id=created_by_user_id)
    return "evidence", evidence.id


def generate_candidates(
    db: Session, organization_id: str, *,
    since: Optional[datetime] = None, until: Optional[datetime] = None,
    distance_threshold_m: Optional[float] = None,
    time_window_seconds: Optional[int] = None,
    created_by_user_id: Optional[str] = None,
) -> SpatialRelationshipRunResponse:
    """Bounded pairwise comparison across Event+Observation records
    with a usable location. Creates (or, for an identical pair that
    already exists, idempotently reuses -- see
    relationship_service.create_relationship's own dedup) a
    "spatially_associated" EvidenceRelationship for every pair within
    BOTH thresholds. Never deletes or modifies an existing
    relationship, and never generates a second relationship_type for
    the same pair."""
    distance_m = distance_threshold_m if distance_threshold_m is not None else settings.GEOSPATIAL_RELATIONSHIP_DISTANCE_METERS
    window_s = time_window_seconds if time_window_seconds is not None else settings.GEOSPATIAL_RELATIONSHIP_TIME_WINDOW_SECONDS
    if distance_m <= 0:
        raise ValueError("distance_threshold_m must be positive")
    if window_s <= 0:
        raise ValueError("time_window_seconds must be positive")

    max_candidates = settings.GEOSPATIAL_RELATIONSHIP_MAX_CANDIDATES
    candidates: list[_Candidate] = []
    for rt in _CANDIDATE_RECORD_TYPES:
        # max+1 per type so that overflow is detectable (a LIMIT of exactly max hides truncation)
        candidates.extend(_usable_rows(db, organization_id, rt, since=since, until=until, limit=max_candidates + 1))
    candidates.sort(key=lambda c: c.timestamp)
    truncated_to_max = len(candidates) > max_candidates
    candidates = candidates[:max_candidates]

    pairs_considered = 0
    created_count = 0
    already_known_count = 0

    n = len(candidates)
    for i in range(n):
        a = candidates[i]
        for j in range(i + 1, n):
            b = candidates[j]
            time_diff = (b.timestamp - a.timestamp).total_seconds()
            if time_diff > window_s:
                break  # list is time-sorted ascending -- nothing further can be in range
            if a.record_type == b.record_type and a.record_id == b.record_id:
                continue  # same underlying record fetched twice cannot happen today (disjoint
                # record types) but guarded defensively
            pairs_considered += 1
            distance = haversine_meters(a.latitude, a.longitude, b.latitude, b.longitude)
            if distance > distance_m:
                continue

            source_ref_type, source_ref_id = _as_relationship_ref(db, organization_id, a, created_by_user_id=created_by_user_id)
            target_ref_type, target_ref_id = _as_relationship_ref(db, organization_id, b, created_by_user_id=created_by_user_id)
            explanation = (
                f"{a.record_type} '{a.record_id}' and {b.record_type} '{b.record_id}' are "
                f"{distance:.1f}m apart and {time_diff:.0f}s apart by observed_at -- both within "
                f"the configured spatial ({distance_m:.0f}m) and temporal ({window_s}s) thresholds "
                f"(rule {RULE_VERSION}). This is an explainable proximity association only -- it is "
                "NOT a determination that the two records describe the same real-world event; that "
                "judgment belongs to app/services/conflict_service.py, which this module never calls."
            )
            _relationship, created = relationship_service.create_relationship(
                db, organization_id=organization_id,
                source_ref_type=source_ref_type, source_ref_id=source_ref_id,
                target_ref_type=target_ref_type, target_ref_id=target_ref_id,
                relationship_type="spatially_associated", origin="rule_based",
                explanation=explanation,
                supporting_metadata={
                    "distance_m": round(distance, 2),
                    "time_difference_seconds": time_diff,
                    "rule_version": RULE_VERSION,
                    # Always True by construction -- a candidate is only ever created when
                    # BOTH the spatial and temporal thresholds are met (see module docstring).
                    "temporally_associated": True,
                    "source_record_type": a.record_type, "source_record_id": a.record_id,
                    "target_record_type": b.record_type, "target_record_id": b.record_id,
                    "distance_threshold_m": distance_m, "time_window_seconds": window_s,
                },
                created_by_user_id=created_by_user_id,
            )
            if created:
                created_count += 1
            else:
                already_known_count += 1

    return SpatialRelationshipRunResponse(
        candidates_created=created_count,
        candidates_already_known=already_known_count,
        pairs_considered=pairs_considered,
        candidates_considered=n,
        candidates_truncated=truncated_to_max,
        rule_version=RULE_VERSION,
        distance_threshold_m=distance_m,
        time_window_seconds=window_s,
    )


def _resolve_underlying_record(db: Session, ref_type: str, ref_id: str) -> tuple[str, str]:
    """A relationship's source/target ref is "event" or "evidence"
    (REFERENCEABLE_TYPES) -- but an "evidence" ref wrapping an
    Observation should be reported to the caller as the Observation it
    actually represents, not as an opaque Evidence id. Falls back to
    reporting the Evidence item itself if it does not wrap an
    Observation (e.g. a future "spatially_associated" row created by
    some other path)."""
    if ref_type == "event":
        return "event", ref_id
    evidence = db.execute(select(Evidence).where(Evidence.id == ref_id)).scalar_one_or_none()
    if evidence is not None and evidence.observation_id:
        return "observation", evidence.observation_id
    return "evidence", ref_id


def _location_quality(db: Session, record_type: str, record_id: str) -> Optional[str]:
    model = _RECORD_TYPE_MODELS.get(record_type)
    if model is None:
        return None
    row = db.execute(select(model).where(model.id == record_id)).scalar_one_or_none()
    if row is None:
        return None
    return classify_validation_status(row.latitude, row.longitude, coordinate_reference_system=row.coordinate_reference_system)


def list_candidates(
    db: Session, organization_id: str, *,
    review_status: Optional[str] = None, limit: int = 200,
) -> list[SpatialRelationshipCandidateResponse]:
    """Read-only listing of "spatially_associated" relationships for
    this organization -- reviewing one (confirm/reject/uncertain) is
    done directly via relationship_service.review_relationship(), not
    through this module."""
    stmt = relationship_service.list_relationships_query(
        organization_id, relationship_type="spatially_associated", review_status=review_status,
    ).limit(limit)
    rows = db.execute(stmt).scalars().all()

    out: list[SpatialRelationshipCandidateResponse] = []
    for r in rows:
        source_ref_type = "event" if r.source_event_id else "evidence"
        source_ref_id = r.source_event_id or r.source_evidence_id
        target_ref_type = "event" if r.target_event_id else "evidence"
        target_ref_id = r.target_event_id or r.target_evidence_id
        source_record_type, source_record_id = _resolve_underlying_record(db, source_ref_type, source_ref_id)
        target_record_type, target_record_id = _resolve_underlying_record(db, target_ref_type, target_ref_id)
        meta = r.supporting_metadata or {}
        out.append(SpatialRelationshipCandidateResponse(
            relationship_id=r.id,
            source_ref_type=source_ref_type, source_ref_id=source_ref_id,
            source_record_type=source_record_type, source_record_id=source_record_id,
            target_ref_type=target_ref_type, target_ref_id=target_ref_id,
            target_record_type=target_record_type, target_record_id=target_record_id,
            relationship_type=r.relationship_type,
            distance_m=meta.get("distance_m"),
            time_difference_seconds=meta.get("time_difference_seconds"),
            rule_version=meta.get("rule_version", RULE_VERSION),
            explanation=r.explanation,
            review_status=r.review_status,
            origin=r.origin,
            source_location_quality=_location_quality(db, source_record_type, source_record_id),
            target_location_quality=_location_quality(db, target_record_type, target_record_id),
            created_at=r.created_at,
        ))
    return out
