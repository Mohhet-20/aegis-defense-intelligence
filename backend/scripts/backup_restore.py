"""Consistent backup / verify / restore for an AEGIS deployment.

    python scripts/backup_restore.py backup  --dest /backups/aegis-2026-10-17
    python scripts/backup_restore.py verify  --backup /backups/aegis-2026-10-17
    python scripts/backup_restore.py restore --backup /backups/aegis-2026-10-17 \\
        --target-db-url sqlite:////srv/restore/aegis.db --target-files /srv/restore/media

What is captured (one directory, one manifest):
  * the database: SQLite via the sqlite3 online-backup API, PostgreSQL via
    `pg_dump -Fc` (needs pg_dump / pg_restore on PATH);
  * every file under the private storage root (CV_MEDIA_STORAGE_ROOT: uploaded
    media, the `reports/` artifacts, any model artifacts kept there), each
    with its SHA-256;
  * manifest.json: alembic revision, engine, per-table row counts, file list.
NOT captured: .env / secrets (back those up through your secret manager), the
frontend build, logs, the edge devices' local stores.

Consistency: database and files reference each other, so run backup while
writes are paused (stop the API or put it in maintenance) -- the script
re-hashes the files after the database copy and FAILS if any changed meanwhile.

Restore never overwrites: the target database must be empty (no tables / SQLite
file absent) and the target files directory must be empty or absent. After
restoring it re-verifies every file hash and row count against the manifest.
A backup is only trusted once a restore has been tested somewhere disposable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

MANIFEST = "manifest.json"
DB_SQLITE = "database.sqlite3"
DB_PG = "database.pgdump"
FILES_DIR = "files"


class BackupError(Exception):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _scan(root: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise BackupError(f"refusing to follow symlink inside storage root: {p}")
        if p.is_file() and not any(part.startswith("__healthcheck") for part in p.relative_to(root).parts):
            out[p.relative_to(root).as_posix()] = {"sha256": _sha256(p), "bytes": p.stat().st_size}
    return out


def _row_counts(url: str) -> dict[str, int]:
    engine = create_engine(url)
    try:
        with engine.connect() as c:
            names = sorted(inspect(c).get_table_names())
            return {n: c.execute(text(f'SELECT COUNT(*) FROM "{n}"')).scalar() for n in names}
    finally:
        engine.dispose()


def _alembic_revision(url: str) -> str | None:
    engine = create_engine(url)
    try:
        with engine.connect() as c:
            if "alembic_version" not in inspect(c).get_table_names():
                return None
            return c.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise BackupError(f"{name} not found on PATH (needed for PostgreSQL backups)")
    return path


def _pg_args(url):
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    args = ["-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres"]
    return args, env


def backup(db_url: str, storage_root: Path, dest: Path) -> dict:
    url = make_url(db_url)
    if dest.exists() and any(dest.iterdir()):
        raise BackupError(f"destination {dest} is not empty; refusing to mix backups")
    dest.mkdir(parents=True, exist_ok=True)
    before = _scan(storage_root)
    if url.get_backend_name() == "sqlite":
        src = sqlite3.connect(f"file:{url.database}?mode=ro", uri=True)
        dst = sqlite3.connect(dest / DB_SQLITE)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        db_file, engine_name = DB_SQLITE, "sqlite"
    elif url.get_backend_name() == "postgresql":
        args, env = _pg_args(url)
        subprocess.run([_require_tool("pg_dump"), "-Fc", "-f", str(dest / DB_PG), *args, url.database], check=True, env=env)
        db_file, engine_name = DB_PG, "postgresql"
    else:
        raise BackupError(f"unsupported database engine: {url.get_backend_name()}")
    counts = _row_counts(db_url)
    revision = _alembic_revision(db_url)
    after = _scan(storage_root)
    if before != after:
        raise BackupError("files under the storage root changed while the backup ran; pause writes and retry")
    for rel in before:
        target = dest / FILES_DIR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(storage_root / rel, target)
    manifest = {
        "format": 1, "created_at": datetime.now(timezone.utc).isoformat(), "engine": engine_name, "database_file": db_file,
        "alembic_revision": revision, "row_counts": counts, "files": before,
    }
    (dest / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def verify(backup_dir: Path) -> dict:
    mf = backup_dir / MANIFEST
    if not mf.exists():
        raise BackupError("manifest.json missing")
    manifest = json.loads(mf.read_text())
    if not (backup_dir / manifest["database_file"]).exists():
        raise BackupError("database file missing from backup")
    problems = []
    for rel, meta in manifest["files"].items():
        p = backup_dir / FILES_DIR / rel
        if not p.exists():
            problems.append(f"missing: {rel}")
        elif _sha256(p) != meta["sha256"]:
            problems.append(f"hash mismatch: {rel}")
    extra = set(_scan(backup_dir / FILES_DIR)) - set(manifest["files"])
    problems += [f"unexpected file: {e}" for e in sorted(extra)]
    if problems:
        raise BackupError("backup failed verification: " + "; ".join(problems[:10]))
    return manifest


def restore(backup_dir: Path, target_db_url: str, target_files: Path) -> dict:
    manifest = verify(backup_dir)
    url = make_url(target_db_url)
    if target_files.exists() and any(target_files.iterdir()):
        raise BackupError(f"target files directory {target_files} is not empty; refusing to overwrite")
    if manifest["engine"] != url.get_backend_name():
        raise BackupError(f"backup is {manifest['engine']} but target is {url.get_backend_name()}; cross-engine restore is not supported")
    if url.get_backend_name() == "sqlite":
        if url.database and Path(url.database).exists():
            raise BackupError(f"target database file {url.database} already exists; refusing to overwrite")
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_dir / manifest["database_file"], url.database)
    else:
        engine = create_engine(target_db_url)
        try:
            with engine.connect() as c:
                if inspect(c).get_table_names():
                    raise BackupError("target PostgreSQL database is not empty; refusing to restore into it")
        finally:
            engine.dispose()
        args, env = _pg_args(url)
        subprocess.run([_require_tool("pg_restore"), "--no-owner", "-d", url.database, *args, str(backup_dir / manifest["database_file"])], check=True, env=env)
    target_files.mkdir(parents=True, exist_ok=True)
    for rel in manifest["files"]:
        dst = target_files / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_dir / FILES_DIR / rel, dst)
    # Post-restore verification against the manifest
    restored_files = _scan(target_files)
    if restored_files != manifest["files"]:
        raise BackupError("restored files do not match the manifest")
    counts = _row_counts(target_db_url)
    if counts != manifest["row_counts"]:
        diff = {k: (manifest["row_counts"].get(k), counts.get(k)) for k in set(counts) | set(manifest["row_counts"]) if counts.get(k) != manifest["row_counts"].get(k)}
        raise BackupError(f"restored row counts differ from the manifest: {diff}")
    if _alembic_revision(target_db_url) != manifest["alembic_revision"]:
        raise BackupError("restored alembic revision differs from the manifest")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--dest", required=True)
    b.add_argument("--db-url", default=None, help="default: DATABASE_URL from the environment/settings")
    b.add_argument("--storage-root", default=None, help="default: CV_MEDIA_STORAGE_ROOT")
    v = sub.add_parser("verify")
    v.add_argument("--backup", required=True)
    r = sub.add_parser("restore")
    r.add_argument("--backup", required=True)
    r.add_argument("--target-db-url", required=True)
    r.add_argument("--target-files", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "backup":
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            from app.core.config import get_settings

            s = get_settings()
            root = Path(a.storage_root or s.CV_MEDIA_STORAGE_ROOT)
            if s.REPORT_STORAGE_ROOT and not Path(s.REPORT_STORAGE_ROOT).resolve().is_relative_to(root.resolve()):
                raise BackupError("REPORT_STORAGE_ROOT points outside the storage root, so report artifacts would be missing from the backup; "
                                  "leave it unset (default <storage root>/reports) or back that directory up separately")
            m = backup(a.db_url or s.DATABASE_URL, root, Path(a.dest))
            print(f"backup ok: {len(m['files'])} files, {sum(m['row_counts'].values())} rows, revision {m['alembic_revision']}")
        elif a.cmd == "verify":
            m = verify(Path(a.backup))
            print(f"verify ok: {len(m['files'])} files match the manifest")
        else:
            m = restore(Path(a.backup), a.target_db_url, Path(a.target_files))
            print(f"restore ok: {len(m['files'])} files, {sum(m['row_counts'].values())} rows verified against the manifest")
    except BackupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
