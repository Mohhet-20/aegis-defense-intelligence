"""Regression tests for scripts/seed.py against real, disposable SQLite files.

seed.py previously called Base.metadata.create_all(), which on an empty or
not-yet-upgraded database created tables behind Alembic's back so the next
`alembic upgrade head` failed with "table already exists".
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def _run(args: list[str], db_path: Path, media: Path) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        "ENVIRONMENT": "development",
        "CV_MEDIA_STORAGE_ROOT": str(media),
    }
    return subprocess.run([sys.executable, *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=300)


def test_seed_refuses_an_unmigrated_database_and_creates_no_tables(tmp_path):
    db = tmp_path / "empty.db"
    result = _run(["scripts/seed.py"], db, tmp_path / "media")
    assert result.returncode != 0
    assert "alembic upgrade head" in (result.stdout + result.stderr)
    tables = sqlite3.connect(db).execute("select name from sqlite_master where type='table'").fetchall() if db.exists() else []
    assert tables == []
    # The database is still a clean target for the supported path.
    assert _run(["-m", "alembic", "upgrade", "head"], db, tmp_path / "media").returncode == 0


def test_seed_after_migration_is_idempotent(tmp_path):
    db = tmp_path / "demo.db"
    media = tmp_path / "media"
    assert _run(["-m", "alembic", "upgrade", "head"], db, media).returncode == 0
    first = _run(["scripts/seed.py"], db, media)
    assert first.returncode == 0, first.stderr[-2000:]
    second = _run(["scripts/seed.py"], db, media)
    assert second.returncode == 0, second.stderr[-2000:]
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from users").fetchone()[0] == 4
    assert con.execute("select count(*) from organizations").fetchone()[0] == 1
    # Seeding must not have moved the schema off the migration head.
    check = _run(["-m", "alembic", "check"], db, media)
    assert check.returncode == 0, check.stdout + check.stderr
