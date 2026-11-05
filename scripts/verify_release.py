"""Repeatable local release verification for AEGIS.

Run from the repository root with the backend virtualenv's Python (it needs the
backend dependencies, e.g. alembic):

    backend\\.venv\\Scripts\\python.exe scripts\\verify_release.py            # Windows
    backend/.venv/bin/python scripts/verify_release.py                      # macOS/Linux

Options:
    --quick                skip the slow checks (full backend suite, frontend build)
    --pg-url URL           also run the full backend suite on a DISPOSABLE PostgreSQL
                           database (every table in it is dropped); or set AEGIS_VERIFY_PG_URL
    --docker-build         also build the container images (needs Docker)
    --release              exit non-zero on BLOCKED items too (e.g. no LICENSE)

Every check reports one of:
    PASS            ran and succeeded
    FAIL            ran and failed (mandatory checks make the exit status non-zero)
    NOT RUN         the tool or service is not available here, or was skipped
    BLOCKED         cannot pass until someone acts (e.g. owner chooses a license)
    NOT APPLICABLE  does not apply to this environment

Safety: backend commands get a throwaway SQLite file and media directory in a
temporary folder, never backend/.env's database. Nothing is pushed, tagged or
published, and no secret values are printed (output is truncated and secret
scanners report file paths only).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
PY = sys.executable
RESULTS: list[tuple[str, str, str, bool]] = []  # name, status, detail, mandatory


def record(name: str, status: str, detail: str = "", mandatory: bool = True) -> None:
    RESULTS.append((name, status, detail, mandatory))
    print(f"{status:<15} {name}" + (f"  -- {detail}" if detail else ""), flush=True)


def run(cmd: list[str], cwd: Path, env: dict | None = None, timeout: int = 3600) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout + p.stderr)
    except FileNotFoundError as exc:
        return 127, str(exc)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def tail(text: str, n: int = 3) -> str:
    text = ANSI.sub("", text)
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return " | ".join(lines[-n:])[:300]


def check(name: str, cmd: list[str], cwd: Path, env: dict | None = None, mandatory: bool = True,
          ok_detail=None, timeout: int = 3600) -> bool:
    started = time.monotonic()
    code, out = run(cmd, cwd, env, timeout)
    secs = f"{time.monotonic() - started:.0f}s"
    if code == 127:
        record(name, "NOT RUN", f"command not found: {cmd[0]}", mandatory)
        return False
    if code == 0:
        record(name, "PASS", (ok_detail(out) if ok_detail else tail(out, 1)) + f" ({secs})", mandatory)
        return True
    record(name, "FAIL", f"exit {code}: {tail(out)}", mandatory)
    return False


def has_module(mod: str) -> bool:
    return run([PY, "-c", f"import {mod}"], ROOT)[0] == 0


def main() -> int:
    # Windows consoles default to cp1252; tool output (eslint, vitest) contains Unicode.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--pg-url", default=os.environ.get("AEGIS_VERIFY_PG_URL"))
    ap.add_argument("--docker-build", action="store_true")
    ap.add_argument("--release", action="store_true")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="aegis-verify-"))
    db = tmp / "verify.db"
    safe_env = {**os.environ, "DATABASE_URL": f"sqlite:///{db.as_posix()}", "ENVIRONMENT": "development",
                "CV_MEDIA_STORAGE_ROOT": str(tmp / "media"), "PYTHONIOENCODING": "utf-8"}
    safe_env.pop("TEST_DATABASE_URL", None)
    (tmp / "media").mkdir()
    print(f"AEGIS release verification -- {ROOT}\nPython {sys.version.split()[0]}; scratch dir {tmp}\n")

    # --- repository hygiene -------------------------------------------------------
    git = shutil.which("git")
    if git:
        code, out = run([git, "diff", "--check", "HEAD"], ROOT)
        record("git diff --check (whitespace errors vs HEAD)", "PASS" if code == 0 else "FAIL", tail(out) if code else "")
        # Everything that is or would be committed: tracked files plus untracked files
        # that .gitignore does not exclude (what `git add -A` would pick up).
        code, out = run([git, "ls-files", "--cached", "--others", "--exclude-standard"], ROOT)
        candidates = sorted(set(out.splitlines()))
        bad = [f for f in candidates if (f.endswith((".db", ".sqlite", ".db-journal", ".pem", ".key", ".p12", ".coverage"))
               or Path(f).name == ".env" or "/media_storage/" in f"/{f}" or "node_modules/" in f
               or "/.venv/" in f"/{f}" or f.startswith(("frontend/dist/",)))]
        record("committable files contain no env/db/media/venv/build output", "PASS" if not bad else "FAIL",
               f"{len(candidates)} tracked + untracked-not-ignored files" if not bad else f"{len(bad)} offending, e.g. {bad[:3]}")
    else:
        candidates = []
        record("git checks", "NOT RUN", "git not found")

    hook = shutil.which("detect-secrets-hook") or shutil.which("detect-secrets-hook", path=str(Path(PY).parent))
    if hook and git:
        files = [f for f in candidates if (ROOT / f).is_file()]
        # In batches: one command line with every path exceeds Windows' 32 767-character limit.
        code = 0
        for i in range(0, len(files), 150):
            batch_code, out = run([hook, "--baseline", ".secrets.baseline", *files[i:i + 150]], ROOT)
            code = code or batch_code
        record("secret scan vs reviewed .secrets.baseline (detect-secrets)", "PASS" if code == 0 else "FAIL",
               "no new findings" if code == 0 else "new findings -- run detect-secrets-hook to see file:line (values not printed here)")
    else:
        record("secret scan (detect-secrets)", "NOT RUN", "pip install detect-secrets==1.5.0")

    # --- backend ------------------------------------------------------------------
    if has_module("ruff"):
        check("backend lint gate (ruff E9,F63,F7,F82)", [PY, "-m", "ruff", "check", "--select", "E9,F63,F7,F82", "app", "tests", "scripts"], BACKEND)
        check("backend: no unused imports/variables (ruff F401,F811,F841)",
              [PY, "-m", "ruff", "check", "--select", "F401,F811,F841", "--exclude", "__init__.py", "app", "scripts"], BACKEND)
    else:
        record("backend lint gate (ruff)", "NOT RUN", "pip install ruff")
    check("configuration reference is current", [PY, "scripts/gen_config_reference.py", "--check"], BACKEND, safe_env,
          ok_detail=lambda o: "matches app/core/config.py")
    if check("migrations: fresh database -> head", [PY, "-m", "alembic", "upgrade", "head"], BACKEND, safe_env,
             ok_detail=lambda o: "upgraded scratch SQLite"):
        check("migrations: alembic check (ORM == migrations)", [PY, "-m", "alembic", "check"], BACKEND, safe_env,
              ok_detail=lambda o: "no differences" if "No new upgrade operations" in o else tail(o, 1))
        check("migrations: downgrade -1 then upgrade head", [PY, "-c",
              "import subprocess,sys;r=lambda *a:subprocess.run([sys.executable,'-m','alembic',*a],check=True);r('downgrade','-1');r('upgrade','head')"],
              BACKEND, safe_env, ok_detail=lambda o: "round trip ok")
        check("seed on the migrated scratch database", [PY, "scripts/seed.py"], BACKEND, safe_env, ok_detail=lambda o: tail(o, 1))
    if args.quick:
        record("backend test suite (SQLite)", "NOT RUN", "--quick")
    else:
        check("backend test suite (SQLite, in-memory)", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"], BACKEND, safe_env,
              ok_detail=lambda o: tail(o, 1), timeout=7200)
    if args.pg_url:
        check("backend test suite on PostgreSQL (disposable DB)", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"], BACKEND,
              {**safe_env, "TEST_DATABASE_URL": args.pg_url}, ok_detail=lambda o: tail(o, 1), timeout=10800)
    else:
        record("backend test suite on PostgreSQL", "NOT RUN", "pass --pg-url to a disposable database", mandatory=False)
    if has_module("bandit"):
        check("static analysis (bandit -ll)", [PY, "-m", "bandit", "-q", "-r", "app", "-ll"], BACKEND, ok_detail=lambda o: "no medium+ findings")
    else:
        record("static analysis (bandit)", "NOT RUN", "pip install bandit", mandatory=False)
    if has_module("pip_audit"):
        check("Python dependency audit (pip-audit)", [PY, "-m", "pip_audit", "-r", "requirements.txt"], BACKEND,
              ok_detail=lambda o: tail(o, 1), mandatory=False)
    else:
        record("Python dependency audit (pip-audit)", "NOT RUN", "pip install pip-audit (needs network)", mandatory=False)

    # --- frontend -----------------------------------------------------------------
    npm = shutil.which("npm")
    if not npm:
        record("frontend checks", "NOT RUN", "npm not found")
    else:
        if not (FRONTEND / "node_modules").exists():
            check("frontend clean install (npm ci)", [npm, "ci"], FRONTEND, timeout=1800)
        else:
            record("frontend clean install (npm ci)", "NOT RUN", "node_modules exists; delete it to test a clean install", mandatory=False)
        check("frontend lint (eslint)", [npm, "run", "lint"], FRONTEND, ok_detail=lambda o: tail(o, 1) or "clean")
        check("frontend tests (vitest)", [npm, "test"], FRONTEND, ok_detail=lambda o: next((ln.strip() for ln in ANSI.sub("", o).splitlines() if "Tests" in ln), "ok"))
        if args.quick:
            record("frontend type-check + production build", "NOT RUN", "--quick")
        elif check("frontend type-check + production build", [npm, "run", "build"], FRONTEND, ok_detail=lambda o: "tsc -b + vite build ok"):
            assets = FRONTEND / "dist" / "assets"
            maps = list(assets.glob("*.map"))
            hard = [p.name for p in assets.glob("*.js") if re.search(r"https?://(localhost|127\.0\.0\.1):\d+", p.read_text(encoding="utf-8", errors="ignore"))]
            record("bundle: no source maps, no hard-coded backend URL", "PASS" if not maps and not hard else "FAIL",
                   "" if not maps and not hard else f"maps={len(maps)} urls_in={hard[:3]}")
        check("frontend runtime dependency audit (npm audit --omit=dev, high+)", [npm, "audit", "--omit=dev", "--audit-level=high"],
              FRONTEND, ok_detail=lambda o: tail(o, 1), mandatory=False)

    # --- deployment / release -----------------------------------------------------
    docker = shutil.which("docker")
    if not docker:
        record("docker compose config / image build", "NOT RUN", "Docker not installed", mandatory=False)
    else:
        env = {**os.environ, "AEGIS_DB_PASSWORD": "verify-only", "AEGIS_SECRET_KEY": "verify-only-" + "x" * 40}
        check("docker compose config", [docker, "compose", "config", "-q"], ROOT, env)
        if args.docker_build:
            check("docker compose build", [docker, "compose", "build"], ROOT, env, timeout=3600)
        else:
            record("docker compose build", "NOT RUN", "pass --docker-build", mandatory=False)
    record("GitHub Actions run", "NOT RUN", "workflow is authored; it runs only after the branch is pushed", mandatory=False)
    has_license = any((ROOT / n).exists() for n in ("LICENSE", "LICENSE.md", "LICENSE.txt"))
    record("license file present", "PASS" if has_license else "BLOCKED",
           "" if has_license else "add a LICENSE file")

    shutil.rmtree(tmp, ignore_errors=True)
    counts = {s: sum(1 for r in RESULTS if r[1] == s) for s in ("PASS", "FAIL", "NOT RUN", "BLOCKED", "NOT APPLICABLE")}
    print("\nSummary: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    failed = [r for r in RESULTS if r[1] == "FAIL" and r[3]]
    blocked = [r for r in RESULTS if r[1] == "BLOCKED"]
    if failed:
        print("Mandatory checks failed: " + "; ".join(r[0] for r in failed))
    if blocked:
        print("Blocked (owner action needed): " + "; ".join(r[0] for r in blocked))
    return 1 if failed or (args.release and blocked) else 0


if __name__ == "__main__":
    sys.exit(main())
