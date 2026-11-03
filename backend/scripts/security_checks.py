"""Operational security checks (Phase 14, Phase K).

Runs whichever scanners are installed and reports -- honestly -- which were
unavailable. A clean result is NOT proof of security: these tools find known
vulnerable versions, a few risky code patterns, and committed-looking secrets.

    python scripts/security_checks.py [--frontend ../frontend]

Exit code is non-zero if any available scanner reports a finding at/above its
threshold or the migration check fails. Unavailable scanners do not fail the
run but are listed under "skipped".
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def check_pip_audit(results):
    exe = shutil.which("pip-audit")
    if not exe:
        results["skipped"].append("pip-audit (pip install pip-audit)")
        return
    # --no-deps / --disable-pip audits the pinned names+versions in requirements.txt
    # directly (transitive dependencies are NOT resolved or audited in this mode).
    p = _run([exe, "-r", str(BACKEND / "requirements.txt"), "--no-deps", "--disable-pip", "-f", "json"])
    try:
        data = json.loads(p.stdout)
        vulns = [(d["name"], d["version"], [v["id"] for v in d["vulns"]]) for d in data["dependencies"] if d.get("vulns")]
    except Exception:
        results["failed"].append(f"pip-audit produced unreadable output: {p.stderr[-200:]}")
        return
    results["ran"].append(f"pip-audit (direct pins only): {len(vulns)} vulnerable package(s)")
    if vulns:
        results["failed"].append(f"pip-audit: {vulns}")


def check_bandit(results):
    exe = shutil.which("bandit")
    if not exe:
        results["skipped"].append("bandit (pip install bandit)")
        return
    p = _run([exe, "-r", str(BACKEND / "app"), "-q", "-f", "json", "-ll"])  # medium+ only
    try:
        issues = json.loads(p.stdout)["results"]
    except Exception:
        results["failed"].append("bandit produced unreadable output")
        return
    results["ran"].append(f"bandit (medium+): {len(issues)} issue(s); reviewed list in docs/security/OPERATIONAL_SECURITY_CHECKS.md")
    known = {("B608", "app/edge/local_store.py")}  # reviewed: identifiers are code constants, values are bound parameters
    new = [i for i in issues if (i["test_id"], os.path.relpath(i["filename"], BACKEND).replace("\\", "/")) not in known]
    if new:
        results["failed"].append("bandit: " + "; ".join(f"{i['test_id']} {i['filename']}:{i['line_number']}" for i in new))


def check_secrets(results):
    exe = shutil.which("detect-secrets")
    if not exe:
        results["skipped"].append("detect-secrets (pip install detect-secrets)")
        return
    p = _run([exe, "scan", "--all-files", "--exclude-files", r"(node_modules|package-lock\.json|dist/|media_storage|__pycache__|\.db$|\.pyc$|alembic/versions|/tests/)"], cwd=REPO)
    try:
        found = json.loads(p.stdout)["results"]
    except Exception:
        results["failed"].append("detect-secrets produced unreadable output")
        return
    n = sum(len(v) for v in found.values())
    results["ran"].append(f"detect-secrets (excluding tests + migration revision ids): {n} candidate(s) -- each needs human review")
    for f, items in found.items():
        for it in items:
            results["notes"].append(f"secret-candidate {f}:{it['line_number']} ({it['type']})")


def check_npm_audit(results, frontend: Path):
    npm = shutil.which("npm")
    if not npm or not (frontend / "package.json").exists():
        results["skipped"].append("npm audit (npm / frontend not available)")
        return
    p = _run([npm, "audit", "--omit=dev", "--json"], cwd=frontend)
    try:
        meta = json.loads(p.stdout)["metadata"]["vulnerabilities"]
    except Exception:
        results["skipped"].append("npm audit (registry unreachable or unreadable output)")
        return
    results["ran"].append(f"npm audit --omit=dev (runtime deps): {meta}")
    if meta.get("high", 0) or meta.get("critical", 0):
        results["failed"].append(f"npm audit runtime deps: {meta}")


def check_migrations(results):
    """Single head + clean upgrade + downgrade/upgrade round-trip of the newest revision on a scratch SQLite DB."""
    try:
        from alembic import command
        from alembic.config import Config
        from alembic.script import ScriptDirectory
    except ImportError:
        results["skipped"].append("migration validation (alembic not installed)")
        return
    sys.path.insert(0, str(BACKEND))
    from app.core.config import get_settings

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    if len(heads) != 1:
        results["failed"].append(f"migrations: expected exactly one head, found {heads}")
        return
    settings = get_settings()
    old = settings.DATABASE_URL
    with tempfile.TemporaryDirectory() as d:
        settings.DATABASE_URL = f"sqlite:///{Path(d) / 'check.db'}"
        try:
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "-1")
            command.upgrade(cfg, "head")
            results["ran"].append(f"migration validation: single head {heads[0]}, upgrade -> downgrade -1 -> upgrade OK (SQLite only)")
        except Exception as exc:  # noqa: BLE001
            results["failed"].append(f"migrations: {type(exc).__name__}: {exc}")
        finally:
            settings.DATABASE_URL = old


def check_container(results):
    results["skipped"].append("container image scan (trivy/grype not run by this script); Dockerfile/compose reviewed manually -- see docs")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frontend", default=str(REPO / "frontend"))
    args = ap.parse_args()
    results = {"ran": [], "skipped": [], "failed": [], "notes": []}
    check_pip_audit(results)
    check_bandit(results)
    check_secrets(results)
    check_npm_audit(results, Path(args.frontend))
    check_migrations(results)
    check_container(results)
    for k in ("ran", "skipped", "notes", "failed"):
        for line in results[k]:
            print(f"[{k.upper()}] {line}")
    print("\nA clean run is not proof of security. See docs/security/KNOWN_RISKS.md.")
    return 1 if results["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
