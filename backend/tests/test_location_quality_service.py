"""Tests for app/services/location_quality_service.py (Phase 7,
Section 17 "Provenance and uncertainty")."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.event import Event
from app.services import location_quality_service

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(db, org, source, *, title="E", lat=None, lon=None, crs="WGS84", uncertainty=None):
    e = Event(
        organization_id=org.id, source_id=source.id, external_id=f"ext-{title}",
        event_type="perimeter_motion", title=title, observed_at=NOW, ingested_at=NOW,
        latitude=lat, longitude=lon, data_origin="synthetic_demo",
        coordinate_reference_system=crs, location_uncertainty_m=uncertainty,
    )
    db.add(e)
    db.flush()
    return e


def test_missing_location_is_an_exact_count(db, org, source):
    _event(db, org, source, title="missing1")
    _event(db, org, source, title="missing2")
    _event(db, org, source, title="present", lat=38.9, lon=-77.0)
    db.commit()

    summary = location_quality_service.quality_summary(db, org.id, record_types=["event"])
    assert summary.missing_count == 2
    assert summary.valid_count == 1


def test_invalid_range_counted(db, org, source):
    _event(db, org, source, title="bad", lat=999.0, lon=-77.0)
    db.commit()
    summary = location_quality_service.quality_summary(db, org.id, record_types=["event"])
    assert summary.invalid_range_count == 1
    assert summary.valid_count == 0


def test_unsupported_crs_counted(db, org, source):
    _event(db, org, source, title="bad-crs", lat=38.9, lon=-77.0, crs="UTM43N")
    db.commit()
    summary = location_quality_service.quality_summary(db, org.id, record_types=["event"])
    assert summary.unsupported_crs_count == 1


def test_uncertainty_unavailable_counted_only_for_valid_rows(db, org, source):
    _event(db, org, source, title="no-uncertainty", lat=38.9, lon=-77.0, uncertainty=None)
    _event(db, org, source, title="has-uncertainty", lat=38.9, lon=-77.0, uncertainty=10.0)
    db.commit()
    summary = location_quality_service.quality_summary(db, org.id, record_types=["event"])
    assert summary.valid_count == 2
    assert summary.uncertainty_unavailable_count == 1


def test_stale_location_counted(db, org, source):
    old = NOW - timedelta(days=30)
    e = Event(
        organization_id=org.id, source_id=source.id, external_id="ext-stale",
        event_type="perimeter_motion", title="stale", observed_at=old, ingested_at=old,
        latitude=38.9, longitude=-77.0, data_origin="synthetic_demo", location_uncertainty_m=5.0,
    )
    db.add(e)
    db.commit()
    summary = location_quality_service.quality_summary(db, org.id, record_types=["event"])
    assert summary.stale_count == 1


def test_list_quality_issues_excludes_clean_records_by_default(db, org, source):
    # Use a recent, real wall-clock observed_at (not the fixed historical
    # `NOW` the other tests use) -- the service's staleness check always
    # compares against the real `datetime.now()`, so a "clean" record
    # must actually be recent, not just coordinate-valid.
    recent = datetime.now(timezone.utc) - timedelta(minutes=5)
    e = Event(
        organization_id=org.id, source_id=source.id, external_id="ext-clean",
        event_type="perimeter_motion", title="clean", observed_at=recent, ingested_at=recent,
        latitude=38.9, longitude=-77.0, data_origin="synthetic_demo", location_uncertainty_m=5.0,
    )
    db.add(e)
    _event(db, org, source, title="missing")
    db.commit()
    issues = location_quality_service.list_quality_issues(db, org.id, record_types=["event"])
    titles = {i.title for i in issues}
    assert "missing" in titles
    # "clean" still has an informational uncertainty_unavailable? No --
    # it was given uncertainty=5.0, so it's fully clean and excluded.
    assert "clean" not in titles


def test_list_quality_issues_includes_all_when_only_issues_false(db, org, source):
    _event(db, org, source, title="clean", lat=38.9, lon=-77.0, uncertainty=5.0)
    db.commit()
    issues = location_quality_service.list_quality_issues(db, org.id, record_types=["event"], only_issues=False)
    titles = {i.title for i in issues}
    assert "clean" in titles


def test_quality_summary_tenant_isolated(db, org, source):
    from app.models.organization import Organization

    other = Organization(name="Other")
    db.add(other)
    db.flush()
    _event(db, other, source, title="other-org", lat=38.9, lon=-77.0)
    db.commit()

    summary = location_quality_service.quality_summary(db, org.id, record_types=["event"])
    assert summary.total_records_checked == 0
