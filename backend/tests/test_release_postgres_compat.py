"""Phase 18: statements that SQLite accepts but PostgreSQL rejects.

The unit suite runs on SQLite, which is lenient (LIKE on a JSON column, no
foreign-key enforcement). These tests compile the production queries against
the PostgreSQL dialect so that class of defect is caught without a server.
The full suite can also be run against a real PostgreSQL with
TEST_DATABASE_URL (see docs/testing/INTEGRATION_TESTING.md)."""
from __future__ import annotations

from sqlalchemy.dialects import postgresql

from app.services import sensor_service


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_sensor_measurement_type_filter_casts_the_json_column_for_postgresql():
    sql = _sql(sensor_service.list_sensors_query("org-1", measurement_type="temperature"))
    assert "CAST(sensors.measurement_types AS VARCHAR) LIKE" in sql, sql
    assert "sensors.measurement_types LIKE" not in sql


def test_analytics_buckets_are_labelled_in_utc_whatever_the_server_timezone():
    """Regression: to_char() formats a timestamptz in the session TimeZone (taken from
    postgresql.conf, which initdb copies from the OS). On a non-UTC server every hourly
    bucket was shifted and late events fell outside the window's labels."""
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.models.event import Event
    from app.services.analytics_service import bucket_expr

    fake_db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    for bucket in ("hour", "day"):
        sql = _sql(select(bucket_expr(Event.observed_at, bucket, fake_db)))
        assert "to_char(timezone('UTC', events.observed_at)" in sql, sql


def test_analytics_bucket_labels_on_a_real_non_utc_postgresql_session(db):
    """Runs only with TEST_DATABASE_URL: forces an unusual session zone (+12:45)."""
    import pytest
    from datetime import datetime, timezone

    from sqlalchemy import literal, select, text
    from sqlalchemy.types import DateTime

    from app.services.analytics_service import bucket_expr

    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("needs PostgreSQL (set TEST_DATABASE_URL)")
    db.execute(text("SET TIME ZONE 'Pacific/Chatham'"))
    try:
        ts = literal(datetime(2026, 1, 12, 23, 30, tzinfo=timezone.utc), DateTime(timezone=True))
        assert db.execute(select(bucket_expr(ts, "hour", db))).scalar() == "2026-01-12T23:00:00Z"
        assert db.execute(select(bucket_expr(ts, "day", db))).scalar() == "2026-01-12"
    finally:
        db.execute(text("SET TIME ZONE 'UTC'"))
