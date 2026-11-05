"""Migration: report_runs + analytics indexes; ORM parity; round trip with existing data."""
from __future__ import annotations

import sqlite3

from alembic import command
from alembic.config import Config

from app.core.config import get_settings
from app.db.base import Base
import app.models  # noqa: F401
from app.models.analytics_indexes import ANALYTICS_INDEXES


def _cfg(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def test_report_migration_round_trip_and_parity(tmp_path):
    cfg = _cfg(tmp_path)
    settings = get_settings()
    old = settings.DATABASE_URL
    path = tmp_path / "p16.db"
    settings.DATABASE_URL = f"sqlite:///{path}"
    try:
        command.upgrade(cfg, "b15e0ps0001")
        con = sqlite3.connect(path)
        con.execute("insert into organizations(id,name,status,created_at,updated_at) values('o1','Org','active','2026-01-01','2026-01-01')")
        con.commit()
        assert not con.execute("select name from sqlite_master where name='report_runs'").fetchall()
        con.close()
        command.upgrade(cfg, "head")
        con = sqlite3.connect(path)
        cols = {r[1] for r in con.execute("pragma table_info(report_runs)")}
        assert {c.name for c in Base.metadata.tables["report_runs"].columns} == cols
        idx = {r[1] for r in con.execute("select * from sqlite_master where type='index'")} if False else {r[0] for r in con.execute("select name from sqlite_master where type='index'")}
        for name in ("ix_events_org_observed_at", "ix_events_org_ingested_at", "ix_observations_org_observed_at", "ix_ingestion_jobs_org_started_at", "ix_raw_records_org_received_at", "ix_investigations_org_created_at"):
            assert name in idx, name
        assert con.execute("select count(*) from organizations").fetchone()[0] == 1   # existing data untouched
        con.close()
        command.downgrade(cfg, "b15e0ps0001")
        con = sqlite3.connect(path)
        assert not con.execute("select name from sqlite_master where name='report_runs'").fetchall()
        assert "ix_events_org_observed_at" not in {r[0] for r in con.execute("select name from sqlite_master where type='index'")}
        assert con.execute("select count(*) from organizations").fetchone()[0] == 1
        con.close()
        command.upgrade(cfg, "head")
    finally:
        settings.DATABASE_URL = old


def test_orm_declares_the_same_analytics_indexes():
    names = {i.name for t in Base.metadata.tables.values() for i in t.indexes}
    assert {i.name for i in ANALYTICS_INDEXES} <= names
