"""Event correlation tests. Covers the
service-level rule engine directly and the API's authorized-recompute
/ review workflow."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.data_source import DataSource
from app.models.event import Event
from app.services import correlation_service as corr


def _make_event(db, org, source, *, title, offset_minutes=0, lat=None, lon=None, event_type="perimeter_motion", asset_id=None):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    event = Event(
        organization_id=org.id, source_id=source.id, external_id=title, event_type=event_type, title=title,
        observed_at=now + timedelta(minutes=offset_minutes), ingested_at=now, latitude=lat, longitude=lon,
        data_origin="user_upload", asset_id=asset_id,
    )
    db.add(event)
    db.flush()
    return event


def test_nearby_compatible_events_are_flagged_as_candidates(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    e1 = _make_event(db, org, source, title="E1", offset_minutes=0, lat=38.9, lon=-77.0)
    e2 = _make_event(db, org, source, title="E2", offset_minutes=5, lat=38.9001, lon=-77.0001)
    db.commit()

    result = corr.recompute(db, org.id)
    assert result["correlations_created"] == 1

    correlations = corr.list_correlations_for_event(db, org.id, e1.id)
    assert len(correlations) == 1
    assert "temporal_proximity" in correlations[0].reasons
    assert "spatial_proximity" in correlations[0].reasons
    assert correlations[0].review_status == "candidate"


def test_distant_events_are_never_correlated(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    _make_event(db, org, source, title="Near", offset_minutes=0, lat=38.9, lon=-77.0, event_type="perimeter_motion")
    _make_event(db, org, source, title="FarInTime", offset_minutes=600, lat=38.9, lon=-77.0, event_type="perimeter_motion")
    db.commit()

    result = corr.recompute(db, org.id)
    assert result["correlations_created"] == 0


def test_temporal_proximity_alone_is_not_enough_for_a_candidate(db, org):
    """Two events close in time but from DIFFERENT sources, with
    DIFFERENT event types, no shared asset, and no coordinates share
    only "temporal_proximity" -- Section 14 requires at least one
    additional independent reason before flagging a candidate, so this
    pair must never be created."""
    source_a = DataSource(organization_id=org.id, name="SA", source_type="manual")
    source_b = DataSource(organization_id=org.id, name="SB", source_type="manual")
    db.add_all([source_a, source_b])
    db.flush()
    _make_event(db, org, source_a, title="A", offset_minutes=0, event_type="perimeter_motion")
    _make_event(db, org, source_b, title="B", offset_minutes=1, event_type="sensor_offline")
    db.commit()

    result = corr.recompute(db, org.id)
    assert result["correlations_created"] == 0


def test_two_independent_reasons_together_do_produce_a_candidate(db, org):
    """The same shape as above, but now the two events share a source
    too (shared_source_id + temporal_proximity = 2 reasons) -- that
    clears MIN_REASONS_FOR_CANDIDATE."""
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    _make_event(db, org, source, title="A", offset_minutes=0, event_type="perimeter_motion")
    _make_event(db, org, source, title="B", offset_minutes=1, event_type="sensor_offline")
    db.commit()

    result = corr.recompute(db, org.id)
    assert result["correlations_created"] == 1


def test_recompute_is_idempotent(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    _make_event(db, org, source, title="E1", lat=38.9, lon=-77.0)
    _make_event(db, org, source, title="E2", offset_minutes=1, lat=38.9, lon=-77.0)
    db.commit()

    first = corr.recompute(db, org.id)
    second = corr.recompute(db, org.id)
    assert first["correlations_created"] == 1
    assert second["correlations_created"] == 0
    assert second["already_existed"] == 1


def test_correlation_never_merges_or_mutates_the_original_events(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    e1 = _make_event(db, org, source, title="E1", lat=38.9, lon=-77.0)
    e2 = _make_event(db, org, source, title="E2", offset_minutes=1, lat=38.9, lon=-77.0)
    db.commit()
    e1_title, e2_title = e1.title, e2.title

    corr.recompute(db, org.id)

    db.refresh(e1)
    db.refresh(e2)
    assert e1.title == e1_title
    assert e2.title == e2_title
    assert e1.id != e2.id  # both events independently still exist


def test_review_requires_an_explicit_analyst_decision(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    _make_event(db, org, source, title="E1", lat=38.9, lon=-77.0)
    _make_event(db, org, source, title="E2", offset_minutes=1, lat=38.9, lon=-77.0)
    db.commit()
    corr.recompute(db, org.id)

    correlation = corr.list_correlations_query(org.id).limit(1)
    row = db.execute(correlation).scalars().first()
    assert row.review_status == "candidate"

    updated = corr.review_correlation(db, row, review_status="confirmed", reviewed_by_user_id=None)
    assert updated.review_status == "confirmed"
    assert updated.reviewed_at is not None


# --- API-level: authorization + the auditable recompute endpoint ----------


def test_recompute_endpoint_requires_correlation_manage_permission(client, seeded_users, tokens, auth_header):
    response = client.post("/api/v1/correlation/recompute", json={}, headers=auth_header(tokens, "viewer"))
    assert response.status_code == 403


def test_review_endpoint_rejects_setting_status_back_to_candidate(client, seeded_users, tokens, auth_header):
    response = client.post(
        "/api/v1/correlation/does-not-matter/review", json={"review_status": "candidate"}, headers=auth_header(tokens, "analyst")
    )
    assert response.status_code == 422  # schema validation rejects it before any lookup
