"""Identifier/attribute comparison and conflict
detection. Section 17 requires: matching source-local IDs,
same local ID in different namespaces, missing identifiers, conflicting
attributes, actual contradictory values, missing values, legitimate
differences, and conflict resolution + audit history.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.conflict import Conflict
from app.models.data_source import DataSource
from app.models.event import Event
from app.services import conflict_service, correlation_service, identifier_service

pytestmark = pytest.mark.usefixtures("referenced_rows")  # real rows for the ids these tests reference (PostgreSQL enforces FKs)


def _event(**overrides) -> Event:
    base = dict(
        organization_id="org-1", source_id="src-1", event_type="perimeter_motion", title="E",
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        data_origin="user_upload", attributes={},
    )
    base.update(overrides)
    return Event(**base)


# --- identifier_service: unit-level, no DB needed ------------------------


def test_matching_source_local_identifiers_within_the_same_source():
    a = _event(source_id="src-1", external_id="TAG-1")
    b = _event(source_id="src-1", external_id="tag-1")  # case-insensitive match
    cmp = identifier_service.compare_source_local_identifiers(a, b)
    assert cmp is not None
    assert cmp.outcome == "match"
    assert cmp.namespace == "src-1"


def test_same_local_id_in_different_namespaces_is_never_compared():
    """Section 7: 'never assume identical local IDs from different
    sources identify the same object' -- a shared external_id across
    two DIFFERENT sources must not even be evaluated as a match OR a
    conflict; it's simply not comparable."""
    a = _event(source_id="src-1", external_id="TAG-1")
    b = _event(source_id="src-2", external_id="TAG-1")
    cmp = identifier_service.compare_source_local_identifiers(a, b)
    assert cmp is None


def test_missing_identifier_on_either_side_is_unknown_not_a_conflict():
    a = _event(source_id="src-1", external_id=None)
    b = _event(source_id="src-1", external_id="TAG-1")
    assert identifier_service.compare_source_local_identifiers(a, b) is None

    a2 = _event(attributes={"serial_number": "SN-1"})
    b2 = _event(attributes={})  # the other side never reported it
    assert identifier_service.compare_attributes(a2, b2) == []


def test_conflicting_attribute_value_is_flagged():
    a = _event(attributes={"serial_number": "SN-1"})
    b = _event(attributes={"serial_number": "SN-2"})
    results = identifier_service.compare_attributes(a, b)
    assert len(results) == 1
    assert results[0].outcome == "conflict"
    assert results[0].field == "attributes.serial_number"


def test_only_documented_identifier_keys_are_compared():
    """An arbitrary JSON key outside the configured allow-list is never
    blindly diffed ('schema-aware comparisons ... never
    blindly comparing arbitrary JSON')."""
    a = _event(attributes={"favorite_color": "red"})
    b = _event(attributes={"favorite_color": "blue"})
    assert identifier_service.compare_attributes(a, b) == []


def test_shared_asset_reference_match_and_conflict():
    a = _event(asset_id="asset-1")
    b = _event(asset_id="asset-1")
    assert identifier_service.compare_asset_reference(a, b).outcome == "match"

    c = _event(asset_id="asset-2")
    assert identifier_service.compare_asset_reference(a, c).outcome == "conflict"


# --- conflict_service: DB-level, via correlation candidates -------------


def _make_event(db, org, source, **overrides):
    defaults = dict(
        organization_id=org.id, source_id=source.id, event_type="perimeter_motion", title="E",
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        data_origin="user_upload", attributes={},
    )
    defaults.update(overrides)
    event = Event(**defaults)
    db.add(event)
    db.flush()
    return event


def test_conflict_detection_requires_an_existing_correlation(db, org):
    """No EventCorrelation row at all -> no conflict is ever evaluated,
    even if the two events' fields genuinely disagree -- conflict
    detection is scoped to already-related pairs (Section 9's module
    docstring), never an independent all-pairs scan."""
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    _make_event(db, org, source, title="A", asset_id="asset-1", event_type="intrusion")
    _make_event(db, org, source, title="B", asset_id="asset-1", event_type="sensor_offline",
                observed_at=datetime(2026, 1, 1, 5, tzinfo=timezone.utc))  # 5 hours later, outside the correlation window
    db.commit()

    result = conflict_service.detect_conflicts(db, org.id)
    assert result["pairs_considered"] == 0
    assert result["conflicts_created"] == 0


def test_incompatible_event_type_is_a_real_conflict():
    """Two events correlated via a strong non-type signal
    (shared_asset_reference) but reporting DIFFERENT event_type values
    -- an actual, comparable disagreement, not missing information."""
    pass  # covered end-to-end below; kept as a documentation anchor.


def test_full_conflict_detection_and_resolution_workflow(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    e1 = _make_event(db, org, source, title="A", asset_id="asset-1", event_type="intrusion", source_severity="high")
    e2 = _make_event(db, org, source, title="B", asset_id="asset-1", event_type="sensor_offline", source_severity="low",
                      observed_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc))
    db.commit()

    corr_result = correlation_service.recompute(db, org.id)
    assert corr_result["correlations_created"] == 1  # shared_asset_reference + temporal_proximity + shared_source_id

    conflict_result = conflict_service.detect_conflicts(db, org.id)
    assert conflict_result["conflicts_created"] == 1

    conflicts = list(db.execute(select(Conflict).where(Conflict.organization_id == org.id)).scalars())
    assert len(conflicts) == 1
    conflict = conflicts[0]
    fields_by_name = {f["field"]: f for f in conflict.conflicting_fields}
    assert "event_type" in fields_by_name
    assert fields_by_name["event_type"]["rule"] == "incompatible_event_type"
    assert "source_severity" in fields_by_name
    assert conflict.review_status == "unresolved"

    # Legitimate-difference path: an analyst can accept the
    # disagreement rather than treat it as unresolved forever.
    resolved = conflict_service.resolve_conflict(
        db, conflict, review_status="accepted", resolved_by_user_id="user-1", resolution_note="Different sensors genuinely saw different things.",
    )
    assert resolved.review_status == "accepted"
    assert resolved.resolved_at is not None

    history = conflict_service.get_review_history(db, org.id, conflict.id)
    assert len(history) == 1
    assert history[0].action == "conflict.resolve"
    assert history[0].context_metadata["prior_status"] == "unresolved"
    assert history[0].context_metadata["new_status"] == "accepted"


def test_conflict_detection_is_idempotent(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    _make_event(db, org, source, title="A", asset_id="asset-1", event_type="intrusion")
    _make_event(db, org, source, title="B", asset_id="asset-1", event_type="sensor_offline",
                observed_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc))
    db.commit()
    correlation_service.recompute(db, org.id)

    first = conflict_service.detect_conflicts(db, org.id)
    second = conflict_service.detect_conflicts(db, org.id)
    assert first["conflicts_created"] == 1
    assert second["conflicts_created"] == 0  # rerun never duplicates


def test_no_coordinates_on_either_side_is_never_a_spatial_conflict(db, org):
    """Missing coordinates is unknown, never flagged as disagreeing
    locations ('missing information is not negative
    evidence')."""
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    _make_event(db, org, source, title="A", asset_id="asset-1")
    _make_event(db, org, source, title="B", asset_id="asset-1", observed_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc))
    db.commit()
    correlation_service.recompute(db, org.id)
    result = conflict_service.detect_conflicts(db, org.id)
    assert result["conflicts_created"] == 0


def test_invalid_resolution_status_is_rejected(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    e1 = _make_event(db, org, source, title="A", asset_id="asset-1", event_type="intrusion")
    e2 = _make_event(db, org, source, title="B", asset_id="asset-1", event_type="sensor_offline",
                      observed_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc))
    db.commit()
    correlation_service.recompute(db, org.id)
    conflict_service.detect_conflicts(db, org.id)
    conflict = db.execute(select(Conflict).where(Conflict.organization_id == org.id)).scalar_one()

    import pytest
    with pytest.raises(ValueError):
        conflict_service.resolve_conflict(db, conflict, review_status="not-a-real-status", resolved_by_user_id="u1", resolution_note=None)
