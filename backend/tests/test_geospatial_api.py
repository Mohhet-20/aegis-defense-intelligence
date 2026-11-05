"""API tests for /geospatial, /geospatial/timeline, /geospatial/analytics,
/geospatial/export (Section 13/16: auth, RBAC, tenant
isolation, and bounded results at the route layer)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.event import Event

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(db, org, source, *, title="E", offset_min=0, lat=38.9, lon=-77.0):
    e = Event(
        organization_id=org.id, source_id=source.id, external_id=f"ext-{title}",
        event_type="perimeter_motion", title=title, observed_at=NOW + timedelta(minutes=offset_min),
        ingested_at=NOW, latitude=lat, longitude=lon, data_origin="synthetic_demo",
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def test_viewport_requires_authentication(client):
    response = client.get("/api/v1/geospatial/viewport", params={"min_lat": -90, "max_lat": 90, "min_lon": -180, "max_lon": 180})
    assert response.status_code == 401


def test_viewport_readable_by_every_role(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="a")
    for role in ("viewer", "investigator", "analyst", "admin"):
        response = client.get(
            "/api/v1/geospatial/viewport",
            params={"min_lat": -90, "max_lat": 90, "min_lon": -180, "max_lon": 180, "record_types": ["event"]},
            headers=auth_header(tokens, role),
        )
        assert response.status_code == 200, response.text
        assert response.json()["returned_count"] == 1


def test_viewport_rejects_invalid_bounds(client, tokens, auth_header):
    response = client.get(
        "/api/v1/geospatial/viewport",
        params={"min_lat": 200, "max_lat": 90, "min_lon": -180, "max_lon": 180},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 400


def test_radius_endpoint(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="a")
    response = client.get(
        "/api/v1/geospatial/radius",
        params={"center_latitude": 38.9, "center_longitude": -77.0, "radius_km": 10.0, "record_types": ["event"]},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["returned_count"] == 1


def test_overview_endpoint(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="a")
    response = client.get("/api/v1/geospatial/overview", params={"record_types": ["event"]}, headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["located_records_by_type"]["event"] == 1


def test_quality_summary_endpoint(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="a")
    response = client.get("/api/v1/geospatial/quality/summary", params={"record_types": ["event"]}, headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200, response.text
    assert response.json()["valid_count"] == 1


def test_quality_issues_endpoint(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="missing", lat=None, lon=None)
    response = client.get("/api/v1/geospatial/quality/issues", params={"record_types": ["event"]}, headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1


def test_generate_relationships_requires_geospatial_manage(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="a", offset_min=0)
    _event(db, org, source, title="b", offset_min=1)

    forbidden = client.post(
        "/api/v1/geospatial/relationships/generate", json={"distance_threshold_m": 500.0, "time_window_seconds": 1800},
        headers=auth_header(tokens, "viewer"),
    )
    assert forbidden.status_code == 403

    forbidden_investigator = client.post(
        "/api/v1/geospatial/relationships/generate", json={"distance_threshold_m": 500.0, "time_window_seconds": 1800},
        headers=auth_header(tokens, "investigator"),
    )
    assert forbidden_investigator.status_code == 403

    allowed = client.post(
        "/api/v1/geospatial/relationships/generate", json={"distance_threshold_m": 500.0, "time_window_seconds": 1800},
        headers=auth_header(tokens, "analyst"),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["candidates_created"] == 1


def test_list_relationships_endpoint(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="a", offset_min=0)
    _event(db, org, source, title="b", offset_min=1)
    client.post(
        "/api/v1/geospatial/relationships/generate", json={"distance_threshold_m": 500.0, "time_window_seconds": 1800},
        headers=auth_header(tokens, "analyst"),
    )
    response = client.get("/api/v1/geospatial/relationships", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1


def test_generated_relationship_is_reviewable_via_existing_relationships_endpoint(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="a", offset_min=0)
    _event(db, org, source, title="b", offset_min=1)
    client.post(
        "/api/v1/geospatial/relationships/generate", json={"distance_threshold_m": 500.0, "time_window_seconds": 1800},
        headers=auth_header(tokens, "analyst"),
    )
    candidates = client.get("/api/v1/geospatial/relationships", headers=auth_header(tokens, "viewer")).json()
    relationship_id = candidates[0]["relationship_id"]

    review = client.post(
        f"/api/v1/relationships/{relationship_id}/review", json={"review_status": "confirmed"},
        headers=auth_header(tokens, "analyst"),
    )
    assert review.status_code == 200, review.text
    assert review.json()["review_status"] == "confirmed"


def test_timeline_endpoint(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="a", offset_min=10)
    response = client.get(
        "/api/v1/geospatial/timeline",
        params={"since": NOW.isoformat(), "until": (NOW + timedelta(hours=1)).isoformat(), "record_types": ["event"]},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["returned_count"] == 1


def test_timeline_rejects_excessive_range(client, tokens, auth_header):
    response = client.get(
        "/api/v1/geospatial/timeline",
        params={"since": NOW.isoformat(), "until": (NOW + timedelta(days=5000)).isoformat()},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 400


def test_time_bucket_endpoint(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="a", offset_min=0)
    response = client.get(
        "/api/v1/geospatial/timeline/buckets",
        params={"since": NOW.isoformat(), "until": (NOW + timedelta(hours=2)).isoformat(), "bucket_seconds": 3600, "record_types": ["event"]},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_approximate"] is False
    assert len(body["buckets"]) == 2


def test_temporal_gaps_endpoint(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="a", offset_min=0)
    _event(db, org, source, title="b", offset_min=65)
    response = client.get(
        "/api/v1/geospatial/analytics/temporal-gaps",
        params={"record_type": "event", "since": NOW.isoformat(), "until": (NOW + timedelta(hours=2)).isoformat(), "min_gap_seconds": 1800},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["gaps"]) == 1


def test_spatial_grid_endpoint(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="a", lat=38.9, lon=-77.0)
    response = client.get(
        "/api/v1/geospatial/analytics/spatial-grid",
        params={"record_types": ["event"], "grid_resolution_degrees": 1.0},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert sum(c["count"] for c in body["cells"]) == 1


def test_export_requires_geospatial_export_permission(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="a")

    forbidden_viewer = client.get(
        "/api/v1/geospatial/export/geojson", params={"record_types": ["event"]}, headers=auth_header(tokens, "viewer"),
    )
    assert forbidden_viewer.status_code == 403

    forbidden_investigator = client.get(
        "/api/v1/geospatial/export/geojson", params={"record_types": ["event"]}, headers=auth_header(tokens, "investigator"),
    )
    assert forbidden_investigator.status_code == 403

    allowed = client.get(
        "/api/v1/geospatial/export/geojson", params={"record_types": ["event"]}, headers=auth_header(tokens, "analyst"),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.headers["content-type"].startswith("application/geo+json")
    doc = allowed.json()
    assert doc["feature_count"] == 1


def test_export_csv(client, tokens, auth_header, db, org, source):
    _event(db, org, source, title="a")
    response = client.get(
        "/api/v1/geospatial/export/csv", params={"record_types": ["event"]}, headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "record_id" in response.text


def test_tenant_isolation_across_geospatial_endpoints(client, tokens, auth_header, db, org, source):
    from app.models.organization import Organization

    other = Organization(name="Other")
    db.add(other)
    db.flush()
    other_source = source.__class__(organization_id=other.id, name="other-src", source_type="synthetic_generator")
    db.add(other_source)
    db.flush()
    _event(db, other, other_source, title="other-event")
    db.commit()

    response = client.get(
        "/api/v1/geospatial/viewport",
        params={"min_lat": -90, "max_lat": 90, "min_lon": -180, "max_lon": 180, "record_types": ["event"]},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["returned_count"] == 0


def test_generate_relationships_discloses_truncation(client, tokens, auth_header, db, org, source, monkeypatch):
    """Regression: when the located records exceeded the per-run cap, only the
    earliest ones were compared and the response did not say so."""
    from app.core.config import get_settings

    for i in range(4):
        _event(db, org, source, title=f"e{i}", offset_min=i)
    h = auth_header(tokens, "analyst")
    body = {"distance_threshold_m": 500.0, "time_window_seconds": 1800}
    full = client.post("/api/v1/geospatial/relationships/generate", json=body, headers=h).json()
    assert (full["candidates_considered"], full["candidates_truncated"]) == (4, False)

    monkeypatch.setattr(get_settings(), "GEOSPATIAL_RELATIONSHIP_MAX_CANDIDATES", 2)
    capped = client.post("/api/v1/geospatial/relationships/generate", json=body, headers=h).json()
    assert (capped["candidates_considered"], capped["candidates_truncated"]) == (2, True)
    assert capped["pairs_considered"] == 1
