"""Find (and optionally remove) files in the private storage root that no database row references.

    python scripts/sweep_orphan_files.py                       # report only (default)
    python scripts/sweep_orphan_files.py --delete              # remove orphans older than 24 h
    python scripts/sweep_orphan_files.py --delete --min-age-hours 72 --json orphans.json

An orphan is left behind when a process stops between writing an upload or report
artifact to disk and committing its database row (KNOWN_RISKS 46). Media files are
referenced by media_assets.storage_key, report artifacts by report_runs (id + format).
Files younger than --min-age-hours are never touched (an upload may be in flight), and
nothing is deleted without --delete. Run it against the same DATABASE_URL and
CV_MEDIA_STORAGE_ROOT as the application, ideally after a backup.
Exit status 0 = no orphans found (or all requested deletions done).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.config import get_settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.media_asset import MediaAsset  # noqa: E402
from app.models.report import ReportRun  # noqa: E402
from app.reporting import render  # noqa: E402
from app.services import report_service  # noqa: E402

IGNORED_NAMES = {"__healthcheck__"}  # readiness-probe scratch files


@dataclass
class Orphan:
    path: str      # relative to the storage root
    bytes: int
    age_hours: float


def referenced_paths(db) -> set[Path]:
    root = Path(get_settings().CV_MEDIA_STORAGE_ROOT).resolve()
    refs = {(root / key).resolve() for key in db.execute(select(MediaAsset.storage_key)).scalars()}
    reports = report_service.storage_root().resolve()
    for run_id, org_id, fmt in db.execute(select(ReportRun.id, ReportRun.organization_id, ReportRun.format)):
        ext = render.EXTENSIONS.get(fmt)
        if ext:
            refs.add((reports / org_id / f"{run_id}.{ext}").resolve())
    return refs


def find_orphans(db, *, min_age_hours: float, now: float | None = None) -> tuple[list[Orphan], int]:
    """Returns (orphans old enough to act on, number of unreferenced files skipped as too new)."""
    root = Path(get_settings().CV_MEDIA_STORAGE_ROOT).resolve()
    if not root.is_dir():
        return [], 0
    refs = referenced_paths(db)
    now = time.time() if now is None else now
    orphans, too_new = [], 0
    for p in root.rglob("*"):
        if not p.is_file() or p.name in IGNORED_NAMES or p.name.endswith((".partial", ".tmp")):
            continue
        if p.resolve() in refs:
            continue
        age = (now - p.stat().st_mtime) / 3600
        if age < min_age_hours:
            too_new += 1
            continue
        orphans.append(Orphan(str(p.relative_to(root)).replace("\\", "/"), p.stat().st_size, round(age, 1)))
    return sorted(orphans, key=lambda o: o.path), too_new


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--delete", action="store_true", help="remove the orphans found (default: report only)")
    ap.add_argument("--min-age-hours", type=float, default=24.0)
    ap.add_argument("--json", type=Path, default=None, help="also write the list to this file")
    args = ap.parse_args()
    if args.min_age_hours < 1:
        raise SystemExit("--min-age-hours must be at least 1 (uploads may be in flight)")
    root = Path(get_settings().CV_MEDIA_STORAGE_ROOT).resolve()
    with SessionLocal() as db:
        orphans, too_new = find_orphans(db, min_age_hours=args.min_age_hours)
    total = sum(o.bytes for o in orphans)
    print(f"storage root: {root}")
    print(f"{len(orphans)} orphan file(s), {total:,} bytes; {too_new} unreferenced file(s) younger than {args.min_age_hours} h left alone")
    for o in orphans:
        print(f"  {o.path}  {o.bytes:,} B  {o.age_hours} h old")
    if args.json:
        args.json.write_text(json.dumps([asdict(o) for o in orphans], indent=2), encoding="utf-8")
    if args.delete:
        for o in orphans:
            (root / o.path).unlink(missing_ok=True)
        print(f"deleted {len(orphans)} file(s)")
        return 0
    return 1 if orphans else 0


if __name__ == "__main__":
    raise SystemExit(main())
