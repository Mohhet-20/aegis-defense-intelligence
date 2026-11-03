"""Browser walk over every frontend route (development use; needs Playwright).

    pip install playwright                      # dev tool only, not in requirements.txt
    python scripts/e2e_route_walk.py --ui http://localhost:5173 --api http://127.0.0.1:8000 \\
        [--channel chrome] [--screenshots DIR] [--width 1280]

Logs in as the seeded `admin` (DEVELOPMENT database only; password from
AEGIS_E2E_PASSWORD or the documented seed password), then opens each route
listed in frontend/src/App.tsx. Detail routes are filled with real ids fetched
from the API. For every page it records uncaught exceptions, console errors,
API responses >= 400 and whether the error boundary or a blank page rendered.
It only reads; it creates no data. Exit status 0 = no page had a failure.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

APP_TSX = Path(__file__).resolve().parents[2] / "frontend" / "src" / "App.tsx"
DEFAULT_PASSWORD = "DevPassword123!"  # scripts/seed.py development accounts

# param route -> API list path whose first item's id fills the route
DETAIL_SOURCES = {
    "/events/:eventId": "/events",
    "/sensors/:sensorId": "/sensors",
    "/investigations/:investigationId": "/investigations",
    "/ingestion/:jobId": "/ingestion/jobs",
    "/mlops/models/:modelId": "/mlops/models",
    "/fusion/assessments/:assessmentId": "/assessments",
    "/scenarios/:scenarioId": "/scenarios",
    "/cv/jobs/:jobId": "/inference/jobs",
    "/edge/devices/:deviceId": "/devices",
    "/edge/conflicts/:conflictId": "/edge/conflicts",
    "/tracking/jobs/:jobId": "/tracking/jobs",
    "/analytics/evaluations/:runId": "/model-evaluations?kind=classification",
}


def detail_url(client: httpx.Client, route: str) -> str | None:
    if route == "/tracking/tracks/:trackId":
        job = first_id(client, "/tracking/jobs")
        track = first_id(client, f"/tracking/jobs/{job}/tracks") if job else None
        return f"/tracking/tracks/{track}" if track else None
    if route == "/analytics/outputs/:outputType/:outputId":
        out = first_id(client, "/model-outputs?output_type=detection_result")
        return f"/analytics/outputs/detection_result/{out}" if out else None
    src = DETAIL_SOURCES.get(route)
    ident = first_id(client, src) if src else None
    return re.sub(r":[A-Za-z]+", ident, route) if ident else None


def routes() -> list[str]:
    found = re.findall(r'path="([^"]+)"', APP_TSX.read_text(encoding="utf-8"))
    return [r for r in dict.fromkeys(found) if r not in ("*", "/login")]


def first_id(client: httpx.Client, path: str) -> str | None:
    r = client.get(path)
    if r.status_code != 200:
        return None
    body = r.json()
    items = body.get("items", body.get("results", [])) if isinstance(body, dict) else body
    items = [i for i in items if i.get("kind", "classification") == "classification"] if "model-evaluations" in path else items
    return (items[0].get("id") or items[0].get("output_id")) if items else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ui", default="http://localhost:5173")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--channel", default=None, help="e.g. chrome or msedge to use an installed browser")
    ap.add_argument("--screenshots", default=None)
    ap.add_argument("--width", type=int, default=1280)
    args = ap.parse_args()
    password = os.environ.get("AEGIS_E2E_PASSWORD", DEFAULT_PASSWORD)

    api = httpx.Client(base_url=args.api.rstrip("/") + "/api/v1", timeout=30)
    tok = api.post("/auth/login", json={"username_or_email": args.username, "password": password})
    tok.raise_for_status()
    api.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"

    targets: list[tuple[str, str | None]] = []
    for r in routes():
        if ":" not in r:
            targets.append((r, r))
            continue
        targets.append((r, detail_url(api, r)))

    shots = Path(args.screenshots) if args.screenshots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel) if args.channel else p.chromium.launch()
        page = browser.new_context(viewport={"width": args.width, "height": 900}).new_page()
        problems: list[str] = []
        page.on("pageerror", lambda e: problems.append(f"exception: {e}"))
        page.on("console", lambda m: problems.append(f"console: {m.text[:200]}") if m.type == "error" else None)
        page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.request.method} {r.url.split('/api/v1')[-1][:120]}")
                if "/api/v1/" in r.url and r.status >= 400 else None)

        page.goto(f"{args.ui}/login")
        page.locator("input").first.fill(args.username)
        page.locator("input[type=password]").fill(password)
        page.locator("button[type=submit]").click()
        page.wait_for_url(lambda u: "/login" not in u, timeout=20000)

        for route, url in targets:
            if url is None:
                print(f"SKIP {route}  [no record to open]")
                continue
            problems.clear()
            page.goto(f"{args.ui}{url}")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:  # noqa: BLE001 - a long-polling page still gets checked below
                pass
            body = page.locator("body").inner_text()
            if "Something went wrong" in body:
                problems.append("error boundary rendered")
            if len(body.strip()) < 40:
                problems.append("page is (nearly) blank")
            if "/login" in page.url:
                problems.append("redirected to login")
            if shots:
                name = route.strip("/").replace("/", "_").replace(":", "") or "root"
                page.screenshot(path=str(shots / f"{name}.png"), full_page=True)
            # Expected, user-visible denials are not failures for an admin walk; everything else is.
            real = [x for x in problems if x]
            failures += bool(real)
            print(("FAIL " if real else "PASS ") + route + ("  " + " | ".join(dict.fromkeys(real)) if real else ""))
        browser.close()
    print(f"\n{len(targets) - failures}/{len(targets)} routes without failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
