"""Tests for app/services/geo_timeline_service.py (Section 17
"Temporal queries")."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.event import Event
from app.services import geo_timeline_service

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(db, org, source, *, title="E", offset_min=0, lat=38.9, lon=-77.0):
    e = Event(
        organization_id=org.id, source_id=source.id, external_id=f"ext-{title}-{offset_min}",
        event_type="perimeter_motion", title=title, observed_at=NOW + timedelta(minutes=offset_min),
        ingested_at=NOW, latitude=lat, longitude=lon, data_origin="synthetic_demo",
    )
    db.add(e)
    db.flush()
    return e


def test_query_timeline_filters_by_range(db, org, source):
    inside = _event(db, org, source, title="in", offset_min=10)
    outside = _event(db, org, source, title="out", offset_min=200)
    db.commit()

    result = geo_timeline_service.query_timeline(db, org.id, since=NOW, until=NOW + timedelta(hours=1), record_types=["event"])
    ids = {i.record_id for i in result.items}
    assert inside.id in ids
    assert outside.id not in ids


def test_query_timeline_ascending_vs_descending(db, org, source):
    first = _event(db, org, source, title="first", offset_min=0)
    second = _event(db, org, source, title="second", offset_min=30)
    db.commit()

    asc = geo_timeline_service.query_timeline(db, org.id, since=NOW, until=NOW + timedelta(hours=1), record_types=["event"], ascending=True)
    desc = geo_timeline_service.query_timeline(db, org.id, since=NOW, until=NOW + timedelta(hours=1), record_types=["event"], ascending=False)
    assert [i.record_id for i in asc.items] == [first.id, second.id]
    assert [i.record_id for i in desc.items] == [second.id, first.id]


def test_query_timeline_rejects_since_after_until(db, org):
    with pytest.raises(ValueError):
        geo_timeline_service.query_timeline(db, org.id, since=NOW, until=NOW - timedelta(hours=1))


def test_query_timeline_rejects_excessive_range(db, org):
    with pytest.raises(geo_timeline_service.TimeRangeTooLargeError):
        geo_timeline_service.query_timeline(db, org.id, since=NOW, until=NOW + timedelta(days=5000))


def test_time_bucket_counts_basic(db, org, source):
    _event(db, org, source, title="a", offset_min=0)
    _event(db, org, source, title="b", offset_min=5)
    _event(db, org, source, title="c", offset_min=65)
    db.commit()

    buckets, is_approximate = geo_timeline_service.time_bucket_counts(
        db, org.id, since=NOW, until=NOW + timedelta(hours=2), bucket_seconds=3600, record_types=["event"],
    )
    assert is_approximate is False
    assert len(buckets) == 2
    assert buckets[0].count == 2
    assert buckets[1].count == 1


def test_time_bucket_counts_rejects_non_positive_bucket(db, org):
    with pytest.raises(ValueError):
        geo_timeline_service.time_bucket_counts(db, org.id, since=NOW, until=NOW + timedelta(hours=1), bucket_seconds=0)


def test_temporal_gaps_detects_gap_above_threshold(db, org, source):
    _event(db, org, source, title="a", offset_min=0)
    _event(db, org, source, title="b", offset_min=5)
    _event(db, org, source, title="c", offset_min=65)  # 60-minute gap from b
    db.commit()

    gaps, is_approximate = geo_timeline_service.temporal_gaps(
        db, org.id, record_type="event", since=NOW, until=NOW + timedelta(hours=2), min_gap_seconds=1800,
    )
    assert is_approximate is False
    assert len(gaps) == 1
    assert gaps[0].gap_seconds == pytest.approx(3600, rel=0.01)


def test_temporal_gaps_no_gap_below_threshold(db, org, source):
    _event(db, org, source, title="a", offset_min=0)
    _event(db, org, source, title="b", offset_min=5)
    db.commit()

    gaps, _ = geo_timeline_service.temporal_gaps(
        db, org.id, record_type="event", since=NOW, until=NOW + timedelta(hours=1), min_gap_seconds=1800,
    )
    assert gaps == []


def test_temporal_gaps_rejects_unknown_record_type(db, org):
    with pytest.raises(ValueError):
        geo_timeline_service.temporal_gaps(db, org.id, record_type="not_a_type", since=NOW, until=NOW + timedelta(hours=1), min_gap_seconds=10)
