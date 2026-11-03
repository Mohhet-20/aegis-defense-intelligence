"""Measured query/endpoint timings on a disposable synthetic SQLite database.

    python scripts/benchmark_queries.py [--events 20000] [--runs 5]

Builds an in-memory database (never touches the configured DATABASE_URL),
bulk-loads synthetic events, then times representative read endpoints and a
report build through the real HTTP stack. Prints hardware, dataset size and
min/median/max milliseconds. Numbers describe THIS machine and THIS dataset
on SQLite only; they are not a production-scale or PostgreSQL claim.
"""
from __future__ import annotations

import argparse
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, insert  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.data_source import DataSource  # noqa: E402
from app.models.event import Event  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.user import User  # noqa: E402

PASSWORD = "BenchPassword123!"


def build(n_events: int):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    with Session() as db:
        org = Organization(name="Bench", status="active")
        db.add(org)
        db.flush()
        db.add(User(organization_id=org.id, username="bench", email="b@example.com", display_name="B",
                    password_hash=hash_password(PASSWORD), role="administrator", is_active=True))
        sources = [DataSource(organization_id=org.id, name=f"S{i}", source_type="file_upload") for i in range(5)]
        db.add_all(sources)
        db.flush()
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = [dict(
            id=f"bench-{i:08d}", organization_id=org.id, source_id=sources[i % 5].id,
            event_type=("alert", "movement", "sensor_offline")[i % 3], title=f"E{i}",
            observed_at=t0 + timedelta(minutes=i), ingested_at=t0 + timedelta(minutes=i, seconds=30),
            data_origin="user_upload", processing_status="ingested",
            latitude=10 + (i % 100) / 100, longitude=20 + (i % 100) / 100, location_validation_status="valid", confidence=0.5,
        ) for i in range(n_events)]
        for k in range(0, len(rows), 2000):
            db.execute(insert(Event), rows[k:k + 2000])
        db.commit()
    return Session, t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=int, default=20000)
    ap.add_argument("--runs", type=int, default=5)
    a = ap.parse_args()
    Session, t0 = build(a.events)

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    end = t0 + timedelta(minutes=a.events + 5)
    win = {"start": t0.isoformat().replace("+00:00", "Z"), "end": end.isoformat().replace("+00:00", "Z")}
    with TestClient(app) as c:
        tok = c.post("/api/v1/auth/login", json={"username_or_email": "bench", "password": PASSWORD}).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        cases = [
            ("GET /events?page_size=50", lambda: c.get("/api/v1/events?page_size=50", headers=h)),
            ("GET /events?event_type=alert", lambda: c.get("/api/v1/events?event_type=alert&page_size=50", headers=h)),
            ("GET /reporting/analytics/events", lambda: c.get("/api/v1/reporting/analytics/events", params=win, headers=h)),
            ("GET /reporting/dashboards/executive", lambda: c.get("/api/v1/reporting/dashboards/executive", params=win, headers=h)),
            ("POST /reporting/reports (json)", lambda: c.post("/api/v1/reporting/reports", headers=h, json={"template_key": "platform_activity", "format": "json", **win})),
        ]
        print(f"hardware: {platform.platform()} | cpus={os.cpu_count()} | python={platform.python_version()}")
        print(f"dataset: {a.events} events, 5 sources, 1 org, SQLite in-memory; runs={a.runs}")
        print(f"{'case':44} {'status':>6} {'min ms':>8} {'median':>8} {'max':>8}")
        for name, fn in cases:
            times, status = [], None
            for _ in range(a.runs):
                s = time.perf_counter()
                r = fn()
                times.append((time.perf_counter() - s) * 1000)
                status = r.status_code
            print(f"{name:44} {status:>6} {min(times):8.1f} {statistics.median(times):8.1f} {max(times):8.1f}")
    app.dependency_overrides.clear()


if __name__ == "__main__":
    main()
