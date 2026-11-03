"""Black-box smoke test for a RUNNING AEGIS deployment (uses only httpx).

    AEGIS_SMOKE_PASSWORD='...' python scripts/smoke_test.py \\
        --base-url http://127.0.0.1:8000 --username admin [--expect-docs-disabled]

It logs in as an existing administrator and exercises the core path: health,
authentication, ingestion, private media round trip, investigation, report
generation + download integrity, and error-format sanitization. It CREATES a
small amount of clearly named synthetic data ("smoke-<timestamp>"); run it
against a throwaway or staging deployment, not a production database you
cannot add test rows to. The password is read from the environment only.
Exit status 0 = every check passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import time
import zlib
from datetime import datetime, timedelta, timezone

import httpx

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    return bool(ok)


def tiny_png(w: int = 32, h: int = 24) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes((40, 90, 160)) * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--username", required=True)
    ap.add_argument("--expect-docs-disabled", action="store_true")
    a = ap.parse_args(argv)
    password = os.environ.get("AEGIS_SMOKE_PASSWORD")
    if not password:
        print("Set AEGIS_SMOKE_PASSWORD.", file=sys.stderr)
        return 2
    base = a.base_url.rstrip("/")
    api = base + "/api/v1"
    tag = f"smoke-{int(time.time())}"
    c = httpx.Client(timeout=30)

    r = c.get(f"{api}/health/live")
    check("liveness 200", r.status_code == 200 and r.json().get("status") == "alive")
    r = c.get(f"{api}/health/ready")
    check("readiness 200 with per-dependency checks", r.status_code == 200 and r.json().get("status") == "ready" and r.json().get("checks"), r.text[:200])
    check("readiness exposes no paths or URLs", "/" not in json.dumps(r.json().get("checks", {})))
    check("unauthenticated API call is 401", c.get(f"{api}/events").status_code == 401)
    if a.expect_docs_disabled:
        check("interactive docs disabled", c.get(f"{base}/api/docs").status_code == 404 and c.get(f"{base}/api/openapi.json").status_code == 404)

    bad = c.post(f"{api}/auth/login", json={"username_or_email": a.username, "password": password + "-wrong"})
    check("wrong password is 401", bad.status_code == 401)
    r = c.post(f"{api}/auth/login", json={"username_or_email": a.username, "password": password})
    if not check("login succeeds", r.status_code == 200, r.text[:150]):
        return 1
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    check("/auth/me returns the account", c.get(f"{api}/auth/me", headers=h).status_code == 200)
    check("API responses carry nosniff", c.get(f"{api}/auth/me", headers=h).headers.get("x-content-type-options") == "nosniff")

    src = c.post(f"{api}/sources", headers=h, json={"name": tag, "source_type": "manual"})
    if check("create source", src.status_code == 201, src.text[:150]):
        recs = [{"event_type": "smoke_test", "title": f"{tag}-{i}", "observed_at": "2026-01-01T00:00:00Z", "external_id": f"{tag}-{i}"} for i in range(2)]
        up = c.post(f"{api}/ingestion/jobs", headers=h, data={"source_id": src.json()["id"]},
                    files={"file": ("smoke.json", json.dumps(recs).encode(), "application/json")})
        check("ingestion accepts 2 records", up.status_code == 201 and up.json().get("accepted_count") == 2, up.text[:200])
        again = c.post(f"{api}/ingestion/jobs", headers=h, data={"source_id": src.json()["id"]},
                       files={"file": ("smoke.json", json.dumps(recs).encode(), "application/json")})
        check("re-ingesting the same file creates no duplicates", again.status_code == 201 and again.json().get("accepted_count") == 0)

    png = tiny_png()
    m = c.post(f"{api}/media", headers=h, files={"file": (f"{tag}.png", png, "image/png")})
    if check("media upload", m.status_code == 201, m.text[:150]):
        body = m.json()
        check("media response hides the storage path", "storage_path" not in body and "/data" not in json.dumps(body))
        got = c.get(f"{api}/media/{body['id']}/content", headers=h)
        check("media downloads byte-identical", got.status_code == 200 and got.content == png)
        check("media content requires authentication", c.get(f"{api}/media/{body['id']}/content").status_code == 401)
    check("non-image upload rejected", c.post(f"{api}/media", headers=h, files={"file": ("x.png", b"not an image", "image/png")}).status_code in (400, 415, 422))

    inv = c.post(f"{api}/investigations", headers=h, json={"title": tag, "priority": "normal", "purpose": "smoke test", "scope": "synthetic"})
    check("create investigation", inv.status_code == 201, inv.text[:150])

    end = datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    rep = c.post(f"{api}/reporting/reports", headers=h, json={"template_key": "platform_activity", "format": "json",
                 "start": (end - timedelta(days=30)).strftime(fmt), "end": end.strftime(fmt)})
    if check("report generated", rep.status_code == 201 and rep.json().get("status") == "completed", rep.text[:200]):
        d = c.get(f"{api}/reporting/reports/{rep.json()['id']}/download", headers=h)
        check("report download matches recorded sha256", d.status_code == 200 and hashlib.sha256(d.content).hexdigest() == rep.json()["content_sha256"])
        check("report download requires authentication", c.get(f"{api}/reporting/reports/{rep.json()['id']}/download").status_code == 401)

    nf = c.get(f"{api}/events/00000000-0000-0000-0000-000000000000", headers=h)
    check("404 is JSON with a request_id", nf.status_code == 404 and nf.json().get("request_id"))
    secret = "Sm0ke-Secret-Marker"
    v = c.post(f"{api}/auth/login", json={"username_or_email": "x", "pasword": secret})
    check("validation error does not echo submitted values", v.status_code == 422 and secret not in v.text)

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
