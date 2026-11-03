"""Browser checks for Phase 18 frontend behaviour (needs backend on :8000 with a seeded DEVELOPMENT database,
vite on :5173, playwright + chromium): session expiry returns to /login, a render crash is contained by the
error boundary, and unknown routes do not white-screen. Demo password is from scripts/seed.py."""
import os
import json
import sys
from playwright.sync_api import sync_playwright

UI = os.environ.get("AEGIS_E2E_UI", "http://localhost:5173")
PW = "DevPassword123!"
OUT = []


def check(name, cond, detail=""):
    OUT.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


with sync_playwright() as p:
    b = p.chromium.launch(channel=os.environ.get("AEGIS_E2E_CHANNEL") or None)
    page = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{UI}/login")
    page.locator("input").first.fill("admin")
    page.locator("input[type=password]").fill(PW)
    page.get_by_role("button", name="Sign in").click() if page.get_by_role("button", name="Sign in").count() else page.locator("button[type=submit]").click()
    page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
    check("login reaches the app", "/login" not in page.url)

    # 1. Render crash is contained: make /events answer with a body the page cannot render.
    page.route("**/api/v1/events?*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"items": [{"id": 1, "title": {"x": 1}, "event_type": {"y": 2}}], "total": "boom", "page": 1, "page_size": 20})))
    page.goto(f"{UI}/events")
    page.wait_for_timeout(1500)
    alert = page.get_by_role("alert")
    contained = alert.count() > 0 and "Something went wrong" in alert.first.inner_text()
    check("render crash is contained by the error boundary (alert shown)", contained, page.locator("body").inner_text()[:80])
    check("app shell stays visible around the contained crash", page.locator("nav, aside").count() > 0)
    page.unroute("**/api/v1/events?*")
    # navigating away clears the error
    page.goto(f"{UI}/sources")
    page.wait_for_timeout(1000)
    check("other pages still work after a contained crash", page.get_by_role("alert").filter(has_text="Something went wrong").count() == 0)

    # 2. Session storage: the refresh token is an HttpOnly cookie, invisible to page scripts;
    #    nothing token-like is in localStorage; a full reload restores the session from it.
    cookies = {c["name"]: c for c in page.context.cookies()}
    rc = cookies.get("aegis_refresh")
    check("refresh token is an HttpOnly, SameSite=Strict cookie", bool(rc) and rc["httpOnly"] and rc["sameSite"] == "Strict", str(rc))
    check("page scripts cannot read the refresh token", "aegis_refresh" not in page.evaluate("() => document.cookie"))
    stored = page.evaluate("() => Object.keys(localStorage).filter(k => /token/i.test(k))")
    check("no tokens in localStorage", stored == [], str(stored))
    page.reload()
    page.wait_for_load_state("networkidle")
    check("a full reload keeps the session (restored from the cookie)", "/login" not in page.url, page.url)

    # 3. Expired session: revoke tokens server-side, then trigger an API call from the SPA.
    import requests
    API = os.environ.get("AEGIS_E2E_API", "http://127.0.0.1:8000") + "/api/v1"
    t = requests.post(f"{API}/auth/login", json={"username_or_email": "admin", "password": PW}).json()["access_token"]
    # Revoke ALL admin sessions (bumps the token version) -> the browser's tokens are now dead.
    requests.post(f"{API}/auth/revoke-sessions", headers={"Authorization": f"Bearer {t}"})
    page.goto(f"{UI}/sources")  # full reload: /auth/me fails, tokens cleared
    page.wait_for_url("**/login", timeout=15000)
    check("revoked session returns to the login page", "/login" in page.url)

    # 4. Mid-session expiry (no reload): log in again, kill sessions, click a nav link that fetches.
    page.locator("input").first.fill("admin")
    page.locator("input[type=password]").fill(PW)
    page.locator("button[type=submit]").click()
    page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
    t = requests.post(f"{API}/auth/login", json={"username_or_email": "admin", "password": PW}).json()["access_token"]
    requests.post(f"{API}/auth/revoke-sessions", headers={"Authorization": f"Bearer {t}"})
    page.get_by_role("link", name="Events").first.click()
    try:
        page.wait_for_url("**/login", timeout=15000)
        check("mid-session expiry redirects to login without a reload", True)
    except Exception:
        check("mid-session expiry redirects to login without a reload", False, page.url)

    page.goto(f"{UI}/definitely/not/a/page")
    page.wait_for_timeout(1000)
    check("unknown route lands on a rendered page", page.locator("body").inner_text().strip() != "")
    b.close()

print(f"\n{sum(OUT)}/{len(OUT)} checks passed")
sys.exit(0 if all(OUT) else 1)
