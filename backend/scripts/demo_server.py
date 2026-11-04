"""Run AEGIS as a self-contained public demo (the root Dockerfile's entrypoint).

    DEMO_MODE=true python scripts/demo_server.py

Each cycle: fresh SQLite database and media folder -> `alembic upgrade head` ->
scripts/seed.py -> start uvicorn -> load the demo walkthrough through the public API
-> (if the real detector and the COCO sample are installed) run the real detector on
a few CC BY-licensed COCO photos and evaluate it on the full sample. With
DEMO_RESET_HOURS > 0 the server is restarted on a fresh database after that many
hours, so visitors always find a clean demo; otherwise it runs until stopped.

Refuses to run without DEMO_MODE=true, and refuses to reset a non-SQLite database:
it deletes its database file on every cycle, so it is only for throwaway demo data.
SECRET_KEY is generated per container start when not provided (sessions then end on
restart, which a demo with resetting data does not mind).
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.core.demo import DEMO_PASSWORD  # noqa: E402
from app.core.security_config import DEFAULT_SECRET  # noqa: E402

SHOWCASE_PHOTOS = 3


def log(msg: str) -> None:
    print(f"[demo] {msg}", flush=True)


def sqlite_path(url: str) -> Path:
    if not url.startswith("sqlite:///"):
        raise SystemExit("Refusing: demo_server.py resets its database every cycle and only accepts a SQLite DATABASE_URL.")
    raw = url[len("sqlite:///"):]
    if not raw or raw == ":memory:":
        raise SystemExit("Refusing: DATABASE_URL must name a SQLite file.")
    return (BACKEND / raw).resolve() if not Path(raw).is_absolute() else Path(raw)


def in_backend(path: str) -> Path:
    """Relative paths in settings are relative to backend/ (where the server runs)."""
    p = Path(path)
    return p if p.is_absolute() else (BACKEND / p).resolve()


def reset_state(db_file: Path, media_root: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(str(db_file) + suffix).unlink(missing_ok=True)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    if media_root.exists():
        shutil.rmtree(media_root)
    media_root.mkdir(parents=True, exist_ok=True)


def run(cmd: list[str], env: dict) -> None:
    subprocess.run(cmd, cwd=BACKEND, env=env, check=True)


def wait_ready(base: str, proc: subprocess.Popen, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"uvicorn exited with status {proc.returncode}")
        try:
            if httpx.get(f"{base}/api/v1/health/ready", timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise SystemExit("server did not become ready in time")


def load_real_detector_showcase(base: str, eval_dir: Path) -> None:
    """Real SSD-MobileNet output on real photos, plus a real-image evaluation run."""
    c = httpx.Client(base_url=f"{base}/api/v1", timeout=300)
    token = c.post("/auth/login", json={"username_or_email": "admin", "password": DEMO_PASSWORD}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {token}"
    ssd = [m for m in c.get("/cv/models").json()["items"] if m["adapter_key"] == "ssd_mobilenet_v1_coco"]
    if not ssd:
        log("real detector not registered; skipping the real-photo showcase")
        return
    model_id = ssd[0]["id"]
    manifest_file = eval_dir / "coco_val2017_subset" / "manifest.json"
    if not manifest_file.is_file():
        log("COCO sample not installed (scripts/fetch_eval_data.py); skipping the real-photo showcase")
        return
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    # Photos under CC BY (attribution only) that contain both people and vehicles.
    picks = [im for im in manifest["images"]
             if (im.get("licence") or {}).get("name") == "Attribution License"
             and {"person", "vehicle"} <= {b["label"] for b in im["boxes"] if not b["ignore"]}][:SHOWCASE_PHOTOS]
    for im in picks:
        path = manifest_file.parent / im["file"]
        name = f"coco-val2017-{im['image_id']}-cc-by.jpg"
        media = c.post("/media", files={"file": (name, path.read_bytes(), "image/jpeg")})
        if media.status_code != 201:
            log(f"upload of {name} failed ({media.status_code})")
            continue
        job = c.post("/inference/jobs", json={"media_asset_id": media.json()["id"], "model_record_id": model_id,
                                              "job_type": "image_detection"})
        log(f"real detector on {name}: job {job.json().get('status', job.status_code)}")
    run_ = c.post("/evaluation/runs", json={"model_record_id": model_id, "dataset": "coco_val2017_subset",
                                           "sample_count": 200})
    body = run_.json()
    log(f"real-image evaluation: status {run_.status_code}, mAP@0.5 {(body.get('metrics_detail') or {}).get('map50')}")


def main() -> int:
    settings = get_settings()
    if not settings.DEMO_MODE:
        raise SystemExit("Refusing: set DEMO_MODE=true. This script deletes and re-creates its database.")
    db_file = sqlite_path(settings.DATABASE_URL)
    media_root = in_backend(settings.CV_MEDIA_STORAGE_ROOT)
    eval_dir = in_backend(settings.CV_EVAL_DATA_DIR)
    port = int(os.environ.get("PORT", "7860"))
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    if env.get("SECRET_KEY", DEFAULT_SECRET) == DEFAULT_SECRET:
        env["SECRET_KEY"] = secrets.token_urlsafe(48)
        log("SECRET_KEY not provided; generated one for this container start")

    proc: subprocess.Popen | None = None

    def stop(*_):
        if proc and proc.poll() is None:
            proc.terminate()
            proc.wait(30)
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    try:
        while True:
            log(f"resetting demo state ({db_file.name})")
            reset_state(db_file, media_root)
            run([sys.executable, "-m", "alembic", "upgrade", "head"], env)
            run([sys.executable, "scripts/seed.py"], env)
            proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
                                     "--port", str(port), "--no-server-header"], cwd=BACKEND, env=env)
            wait_ready(base, proc)
            walk = subprocess.run([sys.executable, "scripts/demo_walkthrough.py", "--base-url", base],
                                  check=False, cwd=BACKEND, env={**env, "AEGIS_DEMO_PASSWORD": DEMO_PASSWORD})
            log(f"demo walkthrough finished with status {walk.returncode}")
            try:
                load_real_detector_showcase(base, eval_dir)
            except Exception as exc:  # noqa: BLE001 -- optional extra; the demo runs without it
                log(f"real-detector showcase skipped: {exc.__class__.__name__}")
            # The documented seed password has done its job; nobody can use it once the demo is public.
            run([sys.executable, "scripts/secure_demo_accounts.py"], env)
            log(f"ready on port {port}")
            if settings.DEMO_RESET_HOURS <= 0:
                return proc.wait()
            try:
                proc.wait(timeout=settings.DEMO_RESET_HOURS * 3600)
                return proc.returncode  # the server stopped on its own
            except subprocess.TimeoutExpired:
                log("scheduled reset")
                proc.terminate()
                proc.wait(30)
    finally:
        if proc and proc.poll() is None:  # never leave an orphaned server behind
            proc.terminate()
            proc.wait(30)


if __name__ == "__main__":
    sys.exit(main())
