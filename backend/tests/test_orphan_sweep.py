"""scripts/sweep_orphan_files.py (KNOWN_RISKS 46): unreferenced storage files are reported,
never touched when young, and deleted only on request."""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

from app.core.config import get_settings
from app.cv import storage
from app.services import media_service


def _sweeper():
    path = Path(__file__).resolve().parent.parent / "scripts" / "sweep_orphan_files.py"
    spec = importlib.util.spec_from_file_location("sweep_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


def test_reports_only_unreferenced_old_files(db, org, png_bytes, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "CV_MEDIA_STORAGE_ROOT", str(tmp_path))
    asset = media_service.ingest_media(db, organization_id=org.id, declared_filename="a.png", content=png_bytes(), uploaded_by_user_id=None)
    kept = tmp_path / asset.storage_key
    orphan = tmp_path / org.id / ("f" * 64 + ".png")
    fresh = tmp_path / org.id / ("e" * 64 + ".png")
    for p in (orphan, fresh):
        p.write_bytes(b"left behind by a crash")
    (tmp_path / "__healthcheck__").write_bytes(b"probe")
    old = time.time() - 48 * 3600
    os.utime(orphan, (old, old))
    os.utime(kept, (old, old))

    orphans, too_new = _sweeper().find_orphans(db, min_age_hours=24)
    assert [o.path for o in orphans] == [f"{org.id}/{'f' * 64}.png"]
    assert too_new == 1                                   # the fresh file is left alone
    assert kept.exists() and storage.read_bytes(asset.storage_key) == png_bytes()


def test_report_artifacts_are_recognised_as_referenced(db, org, tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from app.models.report import ReportRun
    from app.services import report_service

    monkeypatch.setattr(get_settings(), "CV_MEDIA_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(get_settings(), "REPORT_STORAGE_ROOT", "")
    run = ReportRun(organization_id=org.id, template_key="platform_activity", title="t", format="json", status="completed",
                    request_fingerprint="0" * 64, definition_version="1", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    db.add(run)
    db.commit()
    path = report_service._artifact_path(run)
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    old = time.time() - 48 * 3600
    os.utime(path, (old, old))
    assert _sweeper().find_orphans(db, min_age_hours=24) == ([], 0)
