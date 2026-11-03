"""UTCDateTime (app/db/types.py): every stored timestamp is UTC and comes back
timezone-aware, on SQLite and PostgreSQL alike.

Regression: on SQLite, timestamps were returned naive and serialized without an
offset ("2026-10-18T14:22:29"), so browsers outside UTC displayed them shifted
(by +05:30 in India); and an aware non-UTC value was stored as its local wall
time because SQLite drops offsets.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.event import Event

IST = timezone(timedelta(hours=5, minutes=30))
OFFSET = re.compile(r"(Z|[+-]\d\d:\d\d)$")


def _event(db, org, source, when):
    e = Event(organization_id=org.id, source_id=source.id, event_type="perimeter_motion", title="tz",
              observed_at=when, ingested_at=when, data_origin="user_upload")
    db.add(e)
    db.commit()
    db.expire_all()
    return db.get(Event, e.id)


def test_non_utc_input_is_stored_as_utc_and_returned_aware(db, org, source):
    local = datetime(2026, 1, 12, 23, 30, tzinfo=IST)          # = 18:00 UTC
    e = _event(db, org, source, local)
    assert e.observed_at.tzinfo is not None
    assert e.observed_at.utcoffset() == timedelta(0)
    assert e.observed_at == local                                 # same instant
    assert (e.observed_at.hour, e.observed_at.minute) == (18, 0)  # stored as UTC, not IST wall time


def test_naive_input_is_taken_as_utc(db, org, source):
    e = _event(db, org, source, datetime(2026, 1, 12, 9, 0))
    assert e.observed_at == datetime(2026, 1, 12, 9, 0, tzinfo=timezone.utc)


def test_query_comparisons_use_the_same_conversion(db, org, source):
    _event(db, org, source, datetime(2026, 1, 12, 18, 0, tzinfo=timezone.utc))
    # 23:29 IST is 17:59 UTC -- before the event; 23:31 IST is after it.
    before = datetime(2026, 1, 12, 23, 29, tzinfo=IST)
    after = datetime(2026, 1, 12, 23, 31, tzinfo=IST)
    hits = db.execute(select(Event).where(Event.observed_at > before, Event.observed_at < after)).scalars().all()
    assert len(hits) == 1


def test_api_timestamps_always_carry_an_offset(client, db, org, source, seeded_users, tokens, auth_header):
    _event(db, org, source, datetime(2026, 1, 12, 18, 0, tzinfo=timezone.utc))
    body = client.get("/api/v1/events", headers=auth_header(tokens, "analyst")).json()
    item = body["items"][0]
    for key in ("observed_at", "created_at", "updated_at"):
        assert OFFSET.search(item[key]), f"{key}={item[key]!r} has no UTC offset"
    assert datetime.fromisoformat(item["observed_at"].replace("Z", "+00:00")) == datetime(2026, 1, 12, 18, 0, tzinfo=timezone.utc)


def test_to_utc_flags_only_naive_input():
    from app.services.timeutil import ensure_utc, iso, to_utc

    assert to_utc(None) == (None, False)
    assert to_utc(datetime(2026, 1, 1, 12, 0)) == (datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc), True)
    aware, assumed = to_utc(datetime(2026, 1, 1, 17, 30, tzinfo=IST))
    assert (aware, assumed) == (datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc), False)
    assert aware.utcoffset() == timedelta(0)
    assert ensure_utc(None) is None
    assert iso(datetime(2026, 1, 1, 17, 30, tzinfo=IST)) == "2026-01-01T12:00:00Z"
