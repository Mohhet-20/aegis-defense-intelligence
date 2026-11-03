"""Compare the ORM metadata with the schema produced by `alembic upgrade head` on a database.

    DATABASE_URL=postgresql+psycopg2://... python scripts/check_schema_drift.py

Run it against a disposable database that has just been migrated. Exit 0 = the
ORM and the migrated schema agree; any difference fails. (KNOWN_RISKS item 39's
two accepted differences were resolved by declaring them in the ORM.)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402


def main() -> int:
    engine = create_engine(get_settings().DATABASE_URL)
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    flat = []
    for d in diffs:
        flat.extend(d if isinstance(d, list) else [d])
    print(f"{len(flat)} difference(s) between the ORM and the migrated schema")
    for d in flat:
        print("DRIFT:", str(d)[:300])
    return 1 if flat else 0


if __name__ == "__main__":
    raise SystemExit(main())
