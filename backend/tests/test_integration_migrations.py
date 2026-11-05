"""The migration chain builds a database that matches the
ORM. Uses a throwaway SQLite file under tmp_path; the configured DATABASE_URL
is restored afterwards and no existing database is touched."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

import app.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base

ROOT = Path(__file__).resolve().parents[1]


def _cfg():
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    return cfg


def test_there_is_exactly_one_migration_head():
    assert len(ScriptDirectory.from_config(_cfg()).get_heads()) == 1


def test_fresh_upgrade_to_head_matches_the_orm_schema(tmp_path):
    settings = get_settings()
    old = settings.DATABASE_URL
    path = tmp_path / "fresh.db"
    settings.DATABASE_URL = f"sqlite:///{path}"
    try:
        command.upgrade(_cfg(), "head")
        con = sqlite3.connect(path)
        have = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        missing_tables = sorted(set(Base.metadata.tables) - have)
        assert missing_tables == [], f"ORM tables absent after migrating: {missing_tables}"
        missing_cols = []
        for name, table in Base.metadata.tables.items():
            cols = {r[1] for r in con.execute(f"pragma table_info({name})")}
            missing_cols += [f"{name}.{c.name}" for c in table.columns if c.name not in cols]
        con.close()
        assert missing_cols == [], f"ORM columns absent after migrating: {missing_cols}"
    finally:
        settings.DATABASE_URL = old
