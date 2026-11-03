"""Tests for app/services/geo_query_service.py (Phase 7, Section 17
"Spatial queries" and "Temporal queries")."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.asset import Asset
from app.models.event import Event
from app.models.observation import Observation
from app.models.sensor import Sensor
from app.services import geo_query_service

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(db, org, source, *, title="E", lat=None, lon=None, offset_min=0, crs="WGS84"):
    e = Event(
        organization_id=org.id, source_id=source.id, external_id=f"ext-{title}-{lat}-{lon}-{offset_min}",
        event_type="perimeter_motion", title=title, observed_at=NOW + timedelta(minutes=offset_min),
        ingested_at=NOW, latitude=lat, longitude=lon, data_origin="synthetic_demo",
        coordinate_reference_system=crs,
    )
    db.add(e)
    db.flush()
    return e


def _sensor(db, org, *, name="S", lat=None, lon=None):
    s = Sensor(organization_id=org.id, name=name, sensor_type="environmental", latitude=lat, longitude=lon)
    db.add(s)
    db.flush()
    return s


def _observation(db, org, sensor, *, lat=None, lon=None, offset_min=0):
    o = Observation(
        organization_id=org.id, sensor_id=sensor.id, observed_at=NOW + timedelta(minutes=offset_min),
        observation_type="temperature_c", data_origin="synthetic_demo", latitude=lat, longitude=lon,
    )
    db.add(o)
    db.flush()
    return o


def _asset(db, org, *, name="A", lat=None, lon=None):
    a = Asset(organization_id=org.id, name=name, entity_type="vehicle", latitude=lat, longitude=lon)
    db.add(a)
    db.flush()
    return a


def test_viewport_returns_only_records_inside_bounds(db, org, source):
    inside = _event(db, org, source, title="inside", lat=38.9, lon=-77.0)
    outside = _event(db, org, source, title="outside", lat=10.0, lon=10.0)
    db.commit()

    result = geo_query_service.query_viewport(
        db, org.id, min_lat=38.0, max_lat=39.0, min_lon=-78.0, max_lon=-76.0, record_types=["event"],
    )
    ids = {i.record_id for i in result.items}
    assert inside.id in ids
    assert outside.id not in ids


def test_viewport_excludes_missing_coordinates(db, org, source):
    _event(db, org, source, title="no-loc", lat=None, lon=None)
    db.commit()
    result = geo_query_service.query_viewport(db, org.id, min_lat=-90, max_lat=90, min_lon=-180, max_lon=180, record_types=["event"])
    assert result.items == []
    assert result.total_matched == 0


def test_viewport_excludes_invalid_range_or_unsupported_crs(db, org, source):
    _event(db, org, source, title="bad-crs", lat=38.9, lon=-77.0, crs="UTM43N")
    db.commit()
    result = geo_query_service.query_viewport(db, org.id, min_lat=-90, max_lat=90, min_lon=-180, max_lon=180, record_types=["event"])
    assert result.items == []
    assert result.missing_or_invalid_location_count == 1


def test_viewport_rejects_invalid_bounds():
    class FakeDb:
        pass

    with pytest.raises(ValueError):
        geo_query_service.query_viewport(FakeDb(), "org", min_lat=100.0, max_lat=200.0, min_lon=0, max_lon=10)


def test_viewport_combines_multiple_record_types(db, org, source):
    e = _event(db, org, source, title="e", lat=38.9, lon=-77.0)
    s = _sensor(db, org, name="s", lat=38.9, lon=-77.0)
    sens2 = _sensor(db, org, name="s2", lat=38.9, lon=-77.0)
    o = _observation(db, org, sens2, lat=38.9, lon=-77.0)
    a = _asset(db, org, name="a", lat=38.9, lon=-77.0)
    db.commit()

    result = geo_query_service.query_viewport(db, org.id, min_lat=38.0, max_lat=39.0, min_lon=-78.0, max_lon=-76.0)
    record_types = {i.record_type for i in result.items}
    assert record_types == {"event", "sensor", "observation", "asset"}
    assert result.record_types_searched == list(geo_query_service.GEO_RECORD_TYPES)


def test_viewport_result_is_tenant_isolated(db, org, source):
    from app.models.organization import Organization

    other_org = Organization(name="Other Org")
    db.add(other_org)
    db.flush()
    _event(db, other_org, source, title="other-org-event", lat=38.9, lon=-77.0)
    db.commit()

    result = geo_query_service.query_viewport(db, org.id, min_lat=38.0, max_lat=39.0, min_lon=-78.0, max_lon=-76.0, record_types=["event"])
    assert result.items == []


def test_viewport_antimeridian_crossing_bbox(db, org, source):
    east = _event(db, org, source, title="east", lat=10.0, lon=179.5)
    west = _event(db, org, source, title="west", lat=10.0, lon=-179.5)
    far = _event(db, org, source, title="far", lat=10.0, lon=0.0)
    db.commit()

    result = geo_query_service.query_viewport(db, org.id, min_lat=0, max_lat=20, min_lon=170.0, max_lon=-170.0, record_types=["event"])
    ids = {i.record_id for i in result.items}
    assert east.id in ids
    assert west.id in ids
    assert far.id not in ids


def test_viewport_truncates_and_reports_total_matched(db, org, source):
    for i in range(10):
        _event(db, org, source, title=f"e{i}", lat=38.9, lon=-77.0)
    db.commit()

    result = geo_query_service.query_viewport(db, org.id, min_lat=38.0, max_lat=39.0, min_lon=-78.0, max_lon=-76.0, record_types=["event"], max_results=3)
    assert result.returned_count == 3
    assert result.total_matched == 10
    assert result.truncated is True


def test_viewport_time_filter_uses_observed_at_by_default(db, org, source):
    in_range = _event(db, org, source, title="in", lat=38.9, lon=-77.0, offset_min=0)
    out_of_range = _event(db, org, source, title="out", lat=38.9, lon=-77.0, offset_min=120)
    db.commit()

    result = geo_query_service.query_viewport(
        db, org.id, min_lat=38.0, max_lat=39.0, min_lon=-78.0, max_lon=-76.0, record_types=["event"],
        since=NOW, until=NOW + timedelta(minutes=60),
    )
    ids = {i.record_id for i in result.items}
    assert in_range.id in ids
    assert out_of_range.id not in ids


def test_viewport_time_filter_half_open_interval_excludes_until_boundary(db, org, source):
    boundary = _event(db, org, source, title="boundary", lat=38.9, lon=-77.0, offset_min=60)
    db.commit()

    result = geo_query_service.query_viewport(
        db, org.id, min_lat=38.0, max_lat=39.0, min_lon=-78.0, max_lon=-76.0, record_types=["event"],
        since=NOW, until=NOW + timedelta(minutes=60),
    )
    ids = {i.record_id for i in result.items}
    assert boundary.id not in ids  # until is exclusive


def test_viewport_sensor_and_asset_use_registered_at_timestamp(db, org):
    s = _sensor(db, org, name="s", lat=38.9, lon=-77.0)
    db.commit()
    result = geo_query_service.query_viewport(db, org.id, min_lat=38.0, max_lat=39.0, min_lon=-78.0, max_lon=-76.0, record_types=["sensor"])
    assert result.items[0].timestamp_type == "registered_at"


def test_radius_query_finds_nearby_and_excludes_far(db, org, source):
    near = _event(db, org, source, title="near", lat=38.9, lon=-77.0)
    far = _event(db, org, source, title="far", lat=10.0, lon=10.0)
    db.commit()

    result = geo_query_service.query_radius(db, org.id, center_latitude=38.9, center_longitude=-77.0, radius_km=10.0, record_types=["event"])
    ids = {i.record_id for i in result.items}
    assert near.id in ids
    assert far.id not in ids
    assert result.items[0].distance_m is not None
    assert result.items[0].distance_m < 100  # same point, near-zero distance


def test_radius_query_returns_sorted_by_distance(db, org, source):
    closer = _event(db, org, source, title="closer", lat=38.91, lon=-77.0)
    farther = _event(db, org, source, title="farther", lat=38.95, lon=-77.0)
    db.commit()

    result = geo_query_service.query_radius(db, org.id, center_latitude=38.9, center_longitude=-77.0, radius_km=20.0, record_types=["event"])
    assert [i.record_id for i in result.items] == [closer.id, farther.id]


def test_radius_query_rejects_excessive_radius(db, org):
    with pytest.raises(ValueError):
        geo_query_service.query_radius(db, org.id, center_latitude=0, center_longitude=0, radius_km=999999.0)


def test_radius_query_rejects_invalid_center(db, org):
    with pytest.raises(ValueError):
        geo_query_service.query_radius(db, org.id, center_latitude=200.0, center_longitude=0, radius_km=10.0)
    with pytest.raises(ValueError):
        geo_query_service.query_radius(db, org.id, center_latitude=0, center_longitude=0, radius_km=-5.0)


def test_radius_query_near_pole_does_not_crash(db, org, source):
    _event(db, org, source, title="pole", lat=89.9, lon=0.0)
    db.commit()
    result = geo_query_service.query_radius(db, org.id, center_latitude=89.95, center_longitude=0.0, radius_km=50.0, record_types=["event"])
    assert len(result.items) == 1


def test_spatial_grid_counts_buckets_nearby_records_into_one_cell(db, org, source):
    _event(db, org, source, title="a", lat=38.91, lon=-77.01)
    _event(db, org, source, title="b", lat=38.92, lon=-77.02)
    _event(db, org, source, title="far", lat=10.0, lon=10.0)
    db.commit()

    cells, is_approximate = geo_query_service.spatial_grid_counts(db, org.id, record_types=["event"], grid_resolution_degrees=1.0)
    assert is_approximate is False
    by_count = sorted(cells, key=lambda c: c.count, reverse=True)
    assert by_count[0].count == 2
    assert by_count[0].record_types == {"event": 2}
    assert sum(c.count for c in cells) == 3


def test_spatial_grid_counts_excludes_missing_or_invalid_locations(db, org, source):
    _event(db, org, source, title="good", lat=38.9, lon=-77.0)
    _event(db, org, source, title="missing")
    db.commit()

    cells, _ = geo_query_service.spatial_grid_counts(db, org.id, record_types=["event"], grid_resolution_degrees=1.0)
    assert sum(c.count for c in cells) == 1


def test_spatial_grid_counts_rejects_non_positive_resolution(db, org):
    with pytest.raises(ValueError):
        geo_query_service.spatial_grid_counts(db, org.id, grid_resolution_degrees=0.0)


def test_spatial_grid_counts_respects_time_range(db, org, source):
    _event(db, org, source, title="inside", lat=38.9, lon=-77.0, offset_min=10)
    _event(db, org, source, title="outside", lat=38.9, lon=-77.0, offset_min=500)
    db.commit()

    cells, _ = geo_query_service.spatial_grid_counts(
        db, org.id, record_types=["event"], grid_resolution_degrees=1.0, since=NOW, until=NOW + timedelta(hours=1),
    )
    assert sum(c.count for c in cells) == 1
