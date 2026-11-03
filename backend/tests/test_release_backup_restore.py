"""Phase 18: backup -> verify -> restore into an isolated location, then prove
the application can read the restored records AND their private files.
Everything lives under tmp_path; no real database or media is touched."""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from scripts import backup_restore as br
from scripts.bootstrap_admin import bootstrap

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "Str0ng-Restore-Pass!"
API = "/api/v1"


def _migrate(url: str):
    s = get_settings()
    old = s.DATABASE_URL
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    s.DATABASE_URL = url
    try:
        command.upgrade(cfg, "head")
    finally:
        s.DATABASE_URL = old


class _Env:
    """Points the shared FastAPI app at one database + one storage root."""

    def __init__(self, db_url: str, storage: Path):
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False})
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.storage = storage

    def __enter__(self):
        self.old_root = get_settings().CV_MEDIA_STORAGE_ROOT
        get_settings().CV_MEDIA_STORAGE_ROOT = str(self.storage)

        def _db():
            s = self.Session()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db] = _db
        self.client = TestClient(app)
        return self

    def __exit__(self, *exc):
        app.dependency_overrides.clear()
        get_settings().CV_MEDIA_STORAGE_ROOT = self.old_root
        self.engine.dispose()

    def login(self):
        r = self.client.post(f"{API}/auth/login", json={"username_or_email": "root", "password": PASSWORD})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def populated(tmp_path, png_bytes):
    src_db = tmp_path / "src.db"
    storage = tmp_path / "src_media"
    storage.mkdir()
    url = f"sqlite:///{src_db}"
    _migrate(url)
    facts = {}
    with _Env(url, storage) as env:
        with env.Session() as db:
            bootstrap(db, organization="Backup Org", username="root", email="root@backup.example.org", display_name="Root", password=PASSWORD)
        h = env.login()
        src = env.client.post(f"{API}/sources", headers=h, json={"name": "Feed", "source_type": "manual"})
        assert src.status_code == 201, src.text
        recs = [{"event_type": "perimeter_motion", "title": f"E{i}", "observed_at": "2026-01-01T00:0%d:00Z" % i, "external_id": f"b{i}"} for i in range(3)]
        up = env.client.post(f"{API}/ingestion/jobs", headers=h, data={"source_id": src.json()["id"]},
                             files={"file": ("a.json", io.BytesIO(json.dumps(recs).encode()), "application/json")})
        assert up.json()["accepted_count"] == 3
        content = png_bytes(64, 48)
        media = env.client.post(f"{API}/media", headers=h, files={"file": ("m.png", content, "image/png")}).json()
        inv = env.client.post(f"{API}/investigations", headers=h, json={"title": "Case", "priority": "normal", "purpose": "t", "scope": "t"})
        assert inv.status_code == 201, inv.text
        rep = env.client.post(f"{API}/reporting/reports", headers=h, json={
            "template_key": "platform_activity", "format": "json", "start": "2025-12-01T00:00:00Z", "end": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}).json()
        assert rep.get("status") == "completed", rep
        facts.update(media_id=media["id"], media_sha=hashlib.sha256(content).hexdigest(), report_id=rep["id"], report_sha=rep["content_sha256"],
                     inv_id=inv.json()["id"])
    return url, storage, facts, tmp_path


def test_backup_verify_restore_roundtrip_is_readable_by_the_application(populated):
    url, storage, facts, tmp = populated
    dest = tmp / "backup"
    m = br.backup(url, storage, dest)
    assert m["alembic_revision"] and m["row_counts"]["events"] == 3
    assert any(k.startswith("reports/") for k in m["files"]), "report artifact missing from backup"
    assert len(m["files"]) >= 2  # media + report
    br.verify(dest)

    r_db, r_files = tmp / "restored" / "aegis.db", tmp / "restored" / "media"
    br.restore(dest, f"sqlite:///{r_db}", r_files)

    with _Env(f"sqlite:///{r_db}", r_files) as env:
        h = env.login()  # the restored user table carries the bootstrap administrator
        assert env.client.get(f"{API}/events", headers=h).json()["total"] == 3
        assert env.client.get(f"{API}/investigations/{facts['inv_id']}", headers=h).status_code == 200
        got = env.client.get(f"{API}/media/{facts['media_id']}/content", headers=h)
        assert got.status_code == 200 and hashlib.sha256(got.content).hexdigest() == facts["media_sha"]
        rep = env.client.get(f"{API}/reporting/reports/{facts['report_id']}/download", headers=h)
        assert rep.status_code == 200 and hashlib.sha256(rep.content).hexdigest() == facts["report_sha"]


def test_restore_refuses_to_overwrite_existing_data(populated):
    url, storage, _, tmp = populated
    dest = tmp / "backup"
    br.backup(url, storage, dest)
    existing_db = tmp / "existing.db"
    existing_db.write_bytes(b"precious")
    with pytest.raises(br.BackupError, match="already exists"):
        br.restore(dest, f"sqlite:///{existing_db}", tmp / "fresh_files")
    assert existing_db.read_bytes() == b"precious"
    busy = tmp / "busy"
    busy.mkdir()
    (busy / "keep.txt").write_text("keep")
    with pytest.raises(br.BackupError, match="not empty"):
        br.restore(dest, f"sqlite:///{tmp / 'new.db'}", busy)
    assert (busy / "keep.txt").read_text() == "keep"


def test_verify_detects_a_tampered_or_missing_backup_file(populated):
    url, storage, _, tmp = populated
    dest = tmp / "backup"
    m = br.backup(url, storage, dest)
    victim = dest / "files" / next(iter(m["files"]))
    victim.write_bytes(victim.read_bytes() + b"x")
    with pytest.raises(br.BackupError, match="hash mismatch"):
        br.verify(dest)
    victim.unlink()
    with pytest.raises(br.BackupError, match="missing"):
        br.verify(dest)


def test_backup_fails_if_files_change_during_the_run_and_refuses_a_nonempty_destination(populated, monkeypatch):
    url, storage, _, tmp = populated
    dest = tmp / "backup2"
    real = br._row_counts

    def racing(u):
        (storage / "late_upload.bin").write_bytes(b"arrived mid-backup")
        return real(u)

    monkeypatch.setattr(br, "_row_counts", racing)
    with pytest.raises(br.BackupError, match="changed while the backup ran"):
        br.backup(url, storage, dest)
    monkeypatch.undo()
    (storage / "late_upload.bin").unlink()
    good = tmp / "backup3"
    br.backup(url, storage, good)
    with pytest.raises(br.BackupError, match="not empty"):
        br.backup(url, storage, good)


def test_backup_manifest_contains_no_secrets(populated):
    url, storage, _, tmp = populated
    br.backup(url, storage, tmp / "b")
    text = (tmp / "b" / "manifest.json").read_text()
    assert PASSWORD not in text and get_settings().SECRET_KEY not in text
