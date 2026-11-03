"""Tests for app/services/geo_export_service.py (Phase 7, Section 12
"GeoJSON/CSV export")."""
from __future__ import annotations

import csv
import io
import json

import pytest
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.models.event import Event
from app.services import geo_export_service

settings = get_settings()

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(db, org, source, *, title="E", offset_min=0, lat=38.9, lon=-77.0, injection_title=None):
    e = Event(
        organization_id=org.id, source_id=source.id, external_id=f"ext-{title}-{offset_min}",
        event_type="perimeter_motion", title=injection_title or title,
        observed_at=NOW + timedelta(minutes=offset_min), ingested_at=NOW,
        latitude=lat, longitude=lon, data_origin="synthetic_demo",
    )
    db.add(e)
    db.flush()
    return e


def test_export_geojson_basic_structure(db, org, source):
    e = _event(db, org, source, title="A")
    db.commit()

    result = geo_export_service.export_geojson(db, org.id, record_types=["event"])
    assert result.format == "geojson"
    assert result.content_type == "application/geo+json"
    assert result.feature_count == 1
    assert result.truncated is False

    doc = json.loads(result.content)
    assert doc["type"] == "FeatureCollection"
    feature = doc["features"][0]
    assert feature["type"] == "Feature"
    # GeoJSON coordinate order is [longitude, latitude] (RFC 7946), never [lat, lon].
    assert feature["geometry"]["coordinates"] == [-77.0, 38.9]
    assert feature["properties"]["record_id"] == e.id
    assert "latitude" not in feature["properties"]
    assert "longitude" not in feature["properties"]


def test_export_geojson_excludes_missing_or_invalid_locations(db, org, source):
    _event(db, org, source, title="good")
    bad = Event(
        organization_id=org.id, source_id=source.id, external_id="ext-missing",
        event_type="perimeter_motion", title="missing", observed_at=NOW, ingested_at=NOW,
        latitude=None, longitude=None, data_origin="synthetic_demo",
    )
    db.add(bad)
    db.commit()

    result = geo_export_service.export_geojson(db, org.id, record_types=["event"])
    assert result.feature_count == 1


def test_export_csv_basic_structure(db, org, source):
    e = _event(db, org, source, title="A")
    db.commit()

    result = geo_export_service.export_csv(db, org.id, record_types=["event"])
    assert result.format == "csv"
    assert result.content_type == "text/csv"
    rows = list(csv.reader(io.StringIO(result.content)))
    assert rows[0] == geo_export_service.CSV_FIELDS
    assert len(rows) == 2
    record_id_idx = geo_export_service.CSV_FIELDS.index("record_id")
    assert rows[1][record_id_idx] == e.id


def test_export_csv_guards_against_formula_injection(db, org, source):
    _event(db, org, source, title="A", injection_title="=cmd|' /C calc'!A0")
    db.commit()

    result = geo_export_service.export_csv(db, org.id, record_types=["event"])
    rows = list(csv.reader(io.StringIO(result.content)))
    title_idx = geo_export_service.CSV_FIELDS.index("title")
    # The dangerous leading character must be neutralized with a
    # leading single quote so no spreadsheet application treats this
    # cell as a formula.
    assert rows[1][title_idx].startswith("'=")


def test_export_respects_max_features_and_reports_truncated(db, org, source):
    for i in range(5):
        _event(db, org, source, title=f"e{i}", offset_min=i)
    db.commit()

    result = geo_export_service.export_geojson(db, org.id, record_types=["event"], max_features=3)
    assert result.feature_count == 3
    assert result.truncated is True


def test_export_never_exceeds_configured_hard_ceiling(db, org, source):
    for i in range(3):
        _event(db, org, source, title=f"e{i}", offset_min=i)
    db.commit()

    # Even asking for far more than the hard ceiling is clamped, never honored as-is.
    result = geo_export_service.export_geojson(db, org.id, record_types=["event"], max_features=10_000_000)
    assert result.feature_count <= settings.GEOSPATIAL_MAX_EXPORT_FEATURES


def test_export_filters_by_bbox(db, org, source):
    inside = _event(db, org, source, title="inside", lat=38.9, lon=-77.0)
    _event(db, org, source, title="outside", lat=10.0, lon=10.0)
    db.commit()

    result = geo_export_service.export_geojson(
        db, org.id, record_types=["event"],
        min_lat=38.0, max_lat=39.0, min_lon=-78.0, max_lon=-76.0,
    )
    assert result.feature_count == 1
    doc = json.loads(result.content)
    assert doc["features"][0]["properties"]["record_id"] == inside.id


def test_export_filters_by_time_range(db, org, source):
    inside = _event(db, org, source, title="inside", offset_min=10)
    _event(db, org, source, title="outside", offset_min=500)
    db.commit()

    result = geo_export_service.export_geojson(
        db, org.id, record_types=["event"], since=NOW, until=NOW + timedelta(hours=1),
    )
    assert result.feature_count == 1
    doc = json.loads(result.content)
    assert doc["features"][0]["properties"]["record_id"] == inside.id


def test_export_rejects_partial_bbox(db, org):
    with pytest.raises(ValueError):
        geo_export_service.export_geojson(db, org.id, record_types=["event"], min_lat=10.0)


def test_export_tenant_isolated(db, org, source):
    from app.models.organization import Organization

    other = Organization(name="Other")
    db.add(other)
    db.flush()
    other_source = source.__class__(organization_id=other.id, name="other-src", source_type="synthetic_generator")
    db.add(other_source)
    db.flush()
    _event(db, other, other_source, title="other-org")
    db.commit()

    result = geo_export_service.export_geojson(db, org.id, record_types=["event"])
    assert result.feature_count == 0
