"""Tests for app/services/spatial_relationship_service.py (Section 11 "Spatial relationships")."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.event import Event
from app.models.observation import Observation
from app.models.sensor import Sensor
from app.services import spatial_relationship_service

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Washington DC-ish coordinates, offset by small amounts for "near" vs "far".
BASE_LAT, BASE_LON = 38.9, -77.0


def _event(db, org, source, *, title, offset_min=0, lat=BASE_LAT, lon=BASE_LON):
    e = Event(
        organization_id=org.id, source_id=source.id, external_id=f"ext-{title}",
        event_type="perimeter_motion", title=title, observed_at=NOW + timedelta(minutes=offset_min),
        ingested_at=NOW, latitude=lat, longitude=lon, data_origin="synthetic_demo",
    )
    db.add(e)
    db.flush()
    return e


def _sensor(db, org, source, *, name="S1"):
    s = Sensor(organization_id=org.id, source_id=source.id, name=name, sensor_type="environmental", status="active")
    db.add(s)
    db.flush()
    return s


def _observation(db, org, sensor, source, *, offset_min=0, lat=BASE_LAT, lon=BASE_LON, obs_type="motion_detected"):
    o = Observation(
        organization_id=org.id, sensor_id=sensor.id, source_id=source.id,
        observed_at=NOW + timedelta(minutes=offset_min), observation_type=obs_type, payload={},
        validation_status="valid", data_origin="synthetic_demo", latitude=lat, longitude=lon,
    )
    db.add(o)
    db.flush()
    return o


def test_generate_candidates_creates_relationship_for_close_pair(db, org, source):
    a = _event(db, org, source, title="a", offset_min=0)
    b = _event(db, org, source, title="b", offset_min=5, lat=BASE_LAT + 0.001, lon=BASE_LON)  # ~111m north
    db.commit()

    result = spatial_relationship_service.generate_candidates(
        db, org.id, distance_threshold_m=500.0, time_window_seconds=1800,
    )
    assert result.candidates_created == 1
    assert result.candidates_already_known == 0

    candidates = spatial_relationship_service.list_candidates(db, org.id)
    assert len(candidates) == 1
    c = candidates[0]
    assert {c.source_record_id, c.target_record_id} == {a.id, b.id}
    assert c.relationship_type == "spatially_associated"
    assert c.review_status == "candidate"
    assert c.distance_m is not None and c.distance_m < 200
    assert c.source_location_quality == "valid"
    assert c.target_location_quality == "valid"


def test_generate_candidates_excludes_pair_outside_distance_threshold(db, org, source):
    _event(db, org, source, title="a", offset_min=0, lat=BASE_LAT, lon=BASE_LON)
    _event(db, org, source, title="b", offset_min=5, lat=BASE_LAT + 1.0, lon=BASE_LON)  # ~111km away
    db.commit()

    result = spatial_relationship_service.generate_candidates(db, org.id, distance_threshold_m=500.0, time_window_seconds=1800)
    assert result.candidates_created == 0
    assert spatial_relationship_service.list_candidates(db, org.id) == []


def test_generate_candidates_excludes_pair_outside_time_window(db, org, source):
    _event(db, org, source, title="a", offset_min=0)
    _event(db, org, source, title="b", offset_min=120)  # same place, far apart in time
    db.commit()

    result = spatial_relationship_service.generate_candidates(db, org.id, distance_threshold_m=500.0, time_window_seconds=1800)
    assert result.candidates_created == 0


def test_generate_candidates_is_idempotent(db, org, source):
    _event(db, org, source, title="a", offset_min=0)
    _event(db, org, source, title="b", offset_min=1)
    db.commit()

    first = spatial_relationship_service.generate_candidates(db, org.id, distance_threshold_m=500.0, time_window_seconds=1800)
    second = spatial_relationship_service.generate_candidates(db, org.id, distance_threshold_m=500.0, time_window_seconds=1800)
    assert first.candidates_created == 1
    assert second.candidates_created == 0
    assert second.candidates_already_known == 1
    assert len(spatial_relationship_service.list_candidates(db, org.id)) == 1


def test_generate_candidates_wraps_observation_as_evidence(db, org, source):
    sensor = _sensor(db, org, source)
    event = _event(db, org, source, title="e", offset_min=0)
    obs = _observation(db, org, sensor, source, offset_min=2)
    db.commit()

    result = spatial_relationship_service.generate_candidates(db, org.id, distance_threshold_m=500.0, time_window_seconds=1800)
    assert result.candidates_created == 1

    candidates = spatial_relationship_service.list_candidates(db, org.id)
    assert len(candidates) == 1
    c = candidates[0]
    types = {c.source_record_type, c.target_record_type}
    ids = {c.source_record_id, c.target_record_id}
    assert types == {"event", "observation"}
    assert ids == {event.id, obs.id}
    # Underlying ref for the observation side must be "evidence" (wrapped),
    # never a direct, unsupported reference to an Observation row.
    ref_types = {c.source_ref_type, c.target_ref_type}
    assert ref_types == {"event", "evidence"}


def test_generate_candidates_skips_records_with_missing_or_invalid_location(db, org, source):
    _event(db, org, source, title="no-location", offset_min=0, lat=None, lon=None)
    _event(db, org, source, title="has-location", offset_min=1)
    db.commit()

    result = spatial_relationship_service.generate_candidates(db, org.id, distance_threshold_m=500.0, time_window_seconds=1800)
    # Only one usable record exists -- nothing to pair it with.
    assert result.candidates_created == 0
    assert result.pairs_considered == 0


def test_generate_candidates_respects_since_until(db, org, source):
    inside_a = _event(db, org, source, title="in-a", offset_min=10)
    inside_b = _event(db, org, source, title="in-b", offset_min=11)
    _event(db, org, source, title="outside", offset_min=500)
    db.commit()

    result = spatial_relationship_service.generate_candidates(
        db, org.id, since=NOW, until=NOW + timedelta(hours=1),
        distance_threshold_m=500.0, time_window_seconds=1800,
    )
    assert result.candidates_created == 1
    candidates = spatial_relationship_service.list_candidates(db, org.id)
    assert {candidates[0].source_record_id, candidates[0].target_record_id} == {inside_a.id, inside_b.id}


def test_generate_candidates_rejects_non_positive_thresholds(db, org):
    import pytest
    with pytest.raises(ValueError):
        spatial_relationship_service.generate_candidates(db, org.id, distance_threshold_m=0.0)
    with pytest.raises(ValueError):
        spatial_relationship_service.generate_candidates(db, org.id, time_window_seconds=0)


def test_list_candidates_filters_by_review_status(db, org, source):
    _event(db, org, source, title="a", offset_min=0)
    _event(db, org, source, title="b", offset_min=1)
    db.commit()
    spatial_relationship_service.generate_candidates(db, org.id, distance_threshold_m=500.0, time_window_seconds=1800)

    candidates_only = spatial_relationship_service.list_candidates(db, org.id, review_status="candidate")
    confirmed_only = spatial_relationship_service.list_candidates(db, org.id, review_status="confirmed")
    assert len(candidates_only) == 1
    assert confirmed_only == []


def test_candidate_can_be_reviewed_via_existing_relationship_service(db, org, source, seeded_users):
    from app.services import relationship_service

    _event(db, org, source, title="a", offset_min=0)
    _event(db, org, source, title="b", offset_min=1)
    db.commit()
    spatial_relationship_service.generate_candidates(db, org.id, distance_threshold_m=500.0, time_window_seconds=1800)

    candidate = spatial_relationship_service.list_candidates(db, org.id)[0]
    relationship = relationship_service.get_relationship(db, org.id, candidate.relationship_id)
    analyst = seeded_users["analyst"]
    reviewed = relationship_service.review_relationship(
        db, relationship, review_status="confirmed", reviewed_by_user_id=analyst.id,
    )
    assert reviewed.review_status == "confirmed"
    assert spatial_relationship_service.list_candidates(db, org.id, review_status="confirmed")[0].relationship_id == candidate.relationship_id


def test_generate_candidates_tenant_isolated(db, org, source):
    from app.models.organization import Organization

    other = Organization(name="Other")
    db.add(other)
    db.flush()
    other_source = source.__class__(organization_id=other.id, name="other-src", source_type="synthetic_generator")
    db.add(other_source)
    db.flush()
    _event(db, other, other_source, title="other-a", offset_min=0)
    _event(db, other, other_source, title="other-b", offset_min=1)
    db.commit()

    result = spatial_relationship_service.generate_candidates(db, org.id, distance_threshold_m=500.0, time_window_seconds=1800)
    assert result.candidates_created == 0
    assert spatial_relationship_service.list_candidates(db, org.id) == []
