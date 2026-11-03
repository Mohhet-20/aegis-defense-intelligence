"""Cross-source observation comparison. Read-only
comparison is a pure function over two already-fetched Observation
rows; persisting a reviewable LINK between them reuses Phase 3's
Evidence + EvidenceRelationship models exactly as Section 11 asks
("link related observations using existing evidence-relationship
models") -- there is no new comparison table.

Nothing here ever merges two observations into one authoritative value,
and a correlated timestamp is never treated as proof of causation or
of describing the same real-world event -- this module only ever
REPORTS what it found; the review workflow (confirmed/rejected/
uncertain) on the resulting EvidenceRelationship is where an analyst's
own judgment gets recorded.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.observation import Observation
from app.sensors import units as unit_lib
from app.services import evidence_service, relationship_service

COMPARISON_METHOD_VERSION = "1.0"


class IncomparableObservationsError(ValueError):
    pass


def find_candidate_observations(
    db: Session, organization_id: str, *, sensor_ids: list[str], measurement_type: Optional[str], since: datetime, until: datetime,
):
    stmt = select(Observation).where(
        Observation.organization_id == organization_id,
        Observation.sensor_id.in_(sensor_ids),
        Observation.observed_at >= since,
        Observation.observed_at <= until,
    )
    if measurement_type:
        stmt = stmt.where(Observation.observation_type == measurement_type)
    return list(db.execute(stmt.order_by(Observation.observed_at.asc())).scalars().all())


def compare(observation_a: Observation, observation_b: Observation, *, tolerance: Optional[float] = None) -> dict:
    """Returns a dict describing the comparison -- never a merged
    value. `conflicting` is only ever set when BOTH observations carry
    a real numeric value, a compatible unit, AND a caller-supplied
    tolerance is exceeded; with no tolerance given, `conflicting` stays
    None ("not assessed"), never defaulting to False (which would
    falsely imply agreement was checked)."""
    same_measurement_type = observation_a.observation_type == observation_b.observation_type
    unit_a, unit_b = observation_a.unit, observation_b.unit
    units_compatible = bool(unit_a and unit_b and unit_lib.units_compatible(unit_a, unit_b))

    delta = None
    converted_b_value = None
    if (
        same_measurement_type and observation_a.measurement_value is not None and observation_b.measurement_value is not None
        and unit_a and unit_b and units_compatible
    ):
        try:
            conversion = unit_lib.convert_unit(observation_b.measurement_value, unit_b, unit_a)
            converted_b_value = conversion.converted_value
            delta = round(observation_a.measurement_value - converted_b_value, 6)
        except unit_lib.IncompatibleUnitError:
            pass

    conflicting = None
    if delta is not None and tolerance is not None:
        conflicting = abs(delta) > tolerance

    missing_a = observation_a.measurement_value is None
    missing_b = observation_b.measurement_value is None

    time_gap_seconds = abs((observation_a.observed_at - observation_b.observed_at).total_seconds())

    return {
        "method_version": COMPARISON_METHOD_VERSION,
        "observation_a_id": observation_a.id,
        "observation_b_id": observation_b.id,
        "sensor_a_id": observation_a.sensor_id,
        "sensor_b_id": observation_b.sensor_id,
        "measurement_type_a": observation_a.observation_type,
        "measurement_type_b": observation_b.observation_type,
        "same_measurement_type": same_measurement_type,
        "unit_a": unit_a,
        "unit_b": unit_b,
        "units_compatible": units_compatible,
        "value_a": observation_a.measurement_value,
        "value_b": observation_b.measurement_value,
        "value_b_converted_to_unit_a": converted_b_value,
        "delta": delta,
        "tolerance": tolerance,
        "conflicting": conflicting,
        "missing_a": missing_a,
        "missing_b": missing_b,
        "time_gap_seconds": round(time_gap_seconds, 3),
        # Stored as ISO strings (not raw datetime objects) because this
        # dict is also persisted verbatim into EvidenceRelationship.
        # supporting_metadata, a JSON column -- CrossSourceComparisonResponse
        # still declares these fields as `datetime` and pydantic parses
        # the ISO string back automatically.
        "observed_at_a": observation_a.observed_at.isoformat(),
        "observed_at_b": observation_b.observed_at.isoformat(),
        "provenance_a": observation_a.provenance,
        "provenance_b": observation_b.provenance,
        "explanation": _explain(same_measurement_type, units_compatible, delta, conflicting, missing_a, missing_b),
    }


def _explain(same_measurement_type: bool, units_compatible: bool, delta: Optional[float], conflicting: Optional[bool], missing_a: bool, missing_b: bool) -> str:
    if missing_a or missing_b:
        return "one or both observations have no numeric measurement value -- only timestamps/metadata are comparable"
    if not same_measurement_type:
        return "the two observations report different measurement types -- values are not directly comparable"
    if not units_compatible:
        return "the two observations report incompatible units -- no conversion was attempted"
    if conflicting is True:
        return f"values differ by {delta} after unit conversion, exceeding the configured tolerance -- this is a disagreement between sources, not evidence either one is wrong"
    if conflicting is False:
        return f"values differ by {delta} after unit conversion, within the configured tolerance"
    return f"values differ by {delta} after unit conversion; no tolerance was supplied, so agreement was not assessed"


def create_comparison_link(
    db: Session, organization_id: str, observation_a: Observation, observation_b: Observation,
    *, comparison: dict, origin: str = "rule_based", created_by_user_id: Optional[str] = None,
):
    if observation_a.id == observation_b.id:
        raise IncomparableObservationsError("cannot compare an observation to itself")
    # Observation-wrapping now lives in evidence_service.get_or_create_observation_evidence --
    # promoted there when spatial_relationship_service.py
    # needed the identical logic for spatially-close Observation pairs.
    # This call site is unchanged in behavior.
    evidence_a = evidence_service.get_or_create_observation_evidence(db, organization_id, observation_a, created_by_user_id=created_by_user_id)
    evidence_b = evidence_service.get_or_create_observation_evidence(db, organization_id, observation_b, created_by_user_id=created_by_user_id)
    return relationship_service.create_relationship(
        db, organization_id=organization_id,
        source_ref_type="evidence", source_ref_id=evidence_a.id,
        target_ref_type="evidence", target_ref_id=evidence_b.id,
        relationship_type="cross_source_comparison", origin=origin,
        explanation=comparison["explanation"], supporting_metadata=comparison,
        created_by_user_id=created_by_user_id,
    )
