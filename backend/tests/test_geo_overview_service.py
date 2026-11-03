"""Tests for app/services/geo_overview_service.py (Phase 7, Section 6
"Overview")."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.conflict import Conflict
from app.models.event import Event
from app.services import geo_overview_service, spatial_relationship_service

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(db, org, source, *, title="E", offset_min=0, lat=38.9, lon=-77.0):
    e = Event(
        organization_id=org.id, source_id=source.id, external_id=f"ext-{title}",
        event_type="perimeter_motion", title=title, observed_at=NOW + timedelta(minutes=offset_min),
        ingested_at=NOW, latitude=lat, longitude=lon, data_origin="synthetic_demo",
    )
    db.add(e)
    db.flush()
    return e


def test_overview_basic_counts(db, org, source):
    _event(db, org, source, title="a", offset_min=0)
    _event(db, org, source, title="b", offset_min=5)
    # A row with coordinates PRESENT but invalid -- this is what
    # missing_or_invalid_location_total actually counts (mirrors
    # geo_query_service.fetch_record_type's own convention: a row with
    # NULL coordinates is never fetched into this query at all -- it is
    # reported separately via data_quality_summary.missing_count below
    # -- so it is not "excluded," it was simply never a candidate).
    bad = Event(
        organization_id=org.id, source_id=source.id, external_id="ext-bad",
        event_type="perimeter_motion", title="bad-range", observed_at=NOW, ingested_at=NOW,
        latitude=999.0, longitude=-77.0, data_origin="synthetic_demo",
    )
    truly_missing = Event(
        organization_id=org.id, source_id=source.id, external_id="ext-missing",
        event_type="perimeter_motion", title="missing", observed_at=NOW, ingested_at=NOW,
        latitude=None, longitude=None, data_origin="synthetic_demo",
    )
    db.add_all([bad, truly_missing])
    db.commit()

    overview = geo_overview_service.build_overview(db, org.id, record_types=["event"])
    assert overview.located_records_by_type["event"] == 2
    assert overview.located_records_total == 2
    assert overview.missing_or_invalid_location_total == 1
    assert len(overview.recent_located_records) == 2
    assert overview.temporal_coverage_earliest is not None
    assert overview.temporal_coverage_latest is not None
    assert overview.data_quality_summary.missing_count == 1
    assert overview.data_quality_summary.invalid_range_count == 1


def test_overview_counts_unreviewed_spatial_relationship_candidates(db, org, source):
    _event(db, org, source, title="a", offset_min=0)
    _event(db, org, source, title="b", offset_min=1)
    db.commit()

    before = geo_overview_service.build_overview(db, org.id, record_types=["event"])
    assert before.spatial_relationship_candidates_unreviewed == 0

    spatial_relationship_service.generate_candidates(db, org.id, distance_threshold_m=500.0, time_window_seconds=1800)
    after = geo_overview_service.build_overview(db, org.id, record_types=["event"])
    assert after.spatial_relationship_candidates_unreviewed == 1


def test_overview_counts_unreviewed_location_conflicts(db, org, source):
    a = _event(db, org, source, title="a", offset_min=0)
    b = _event(db, org, source, title="b", offset_min=1)
    db.commit()

    conflict = Conflict(
        organization_id=org.id, event_a_id=a.id, event_b_id=b.id,
        conflicting_fields=[{"field": "location", "value_a": {}, "value_b": {}, "rule": "far_apart"}],
        conflict_rule_version="1.0", review_status="unresolved",
    )
    non_location_conflict = Conflict(
        organization_id=org.id, event_a_id=a.id, event_b_id=b.id,
        conflicting_fields=[{"field": "event_type", "value_a": "x", "value_b": "y", "rule": "incompatible_event_type"}],
        conflict_rule_version="2.0", review_status="unresolved",
    )
    resolved_location_conflict = Conflict(
        organization_id=org.id, event_a_id=a.id, event_b_id=b.id,
        conflicting_fields=[{"field": "location", "value_a": {}, "value_b": {}, "rule": "far_apart"}],
        conflict_rule_version="3.0", review_status="explained",
    )
    db.add_all([conflict, non_location_conflict, resolved_location_conflict])
    db.commit()

    overview = geo_overview_service.build_overview(db, org.id, record_types=["event"])
    assert overview.location_conflicts_unreviewed == 1


def test_overview_tenant_isolated(db, org, source):
    from app.models.organization import Organization

    other = Organization(name="Other")
    db.add(other)
    db.flush()
    other_source = source.__class__(organization_id=other.id, name="other-src", source_type="synthetic_generator")
    db.add(other_source)
    db.flush()
    _event(db, other, other_source, title="other-event")
    db.commit()

    overview = geo_overview_service.build_overview(db, org.id, record_types=["event"])
    assert overview.located_records_total == 0
