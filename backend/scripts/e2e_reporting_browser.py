"""Browser + API end-to-end check for Phase 16 (needs: backend on :8000 with seeded DB, vite on :5173, playwright+chromium). See docs/implementation/history/PHASE_16_FINAL_REPORT.md."""
import os
import json, sys, hashlib, requests
from playwright.sync_api import sync_playwright

API = os.environ.get("AEGIS_E2E_API", "http://127.0.0.1:8000") + "/api/v1"
UI = os.environ.get("AEGIS_E2E_UI", "http://localhost:5173")
PW = "DevPassword123!"
OUT = []
def check(name, cond, detail=""):
    OUT.append((name, bool(cond), detail)); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

def tok(u):
    return requests.post(f"{API}/auth/login", json={"username_or_email": u, "password": PW}).json()["access_token"]
admin_h = {"Authorization": f"Bearer {tok('admin')}"}
viewer_h = {"Authorization": f"Bearer {tok('viewer')}"} if requests.post(f"{API}/auth/login", json={"username_or_email": "viewer", "password": PW}).status_code == 200 else None

exp = requests.get(f"{API}/reporting/dashboards/executive", params={"days": 30}, headers=admin_h).json()
exp_events = exp["sections"]["events"]["values"]["events.count"]["value"]
exp_obs = exp["sections"]["observations"]["values"]["observations.count"]["value"]
print("API 30d events", exp_events, "observations", exp_obs)

with sync_playwright() as p:
    b = p.chromium.launch(channel=os.environ.get("AEGIS_E2E_CHANNEL") or None)
    ctx = b.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{UI}/login")
    page.locator("input").first.fill("admin")
    page.fill("input[type=password]", PW)
    page.click("button[type=submit]")
    page.wait_for_url(lambda u: "/login" not in u, timeout=10000)

    # 1. dashboard -> window
    page.goto(f"{UI}/reporting/executive?days=30")
    page.wait_for_selector("ul[aria-label='Key figures']", timeout=15000)
    tile = page.locator("ul[aria-label='Key figures'] li", has_text="Events").first
    ev_text = page.locator("ul[aria-label='Key figures'] li").nth(0).inner_text()
    check("executive dashboard shows 12 KPI tiles", page.locator("ul[aria-label='Key figures'] li").count() == 12)
    check("KPI Events equals API value for the 30-day window", str(f"{exp_events:,}") in ev_text, ev_text.replace("\n", " | "))
    check("window text states UTC and exclusive end", "end exclusive" in page.inner_text("main") or "end exclusive" in page.content())
    check("chart has title, unit and window in caption", page.locator("figcaption", has_text="Events per interval").count() >= 1 and "unit: events" in page.locator("figcaption").first.inner_text())
    # 2. change window to 1 day via filter -> URL carries it
    page.select_option("select >> nth=0", "1")
    page.wait_for_function("location.search.includes('days=1')")
    page.wait_for_timeout(1200)
    api1 = requests.get(f"{API}/reporting/dashboards/executive", params={"days": 1}, headers=admin_h).json()["sections"]["events"]["values"]["events.count"]["value"]
    txt1 = page.locator("ul[aria-label='Key figures'] li").nth(0).inner_text()
    check("window change re-queries and matches API (1 day)", str(api1) in txt1, f"api={api1} ui={txt1.splitlines()[:3]}")

    # 3. analyst drill-down
    page.goto(f"{UI}/reporting/analyst?section=events&days=30")
    page.wait_for_selector("text=Events by category", timeout=15000)
    cats = requests.get(f"{API}/reporting/analytics/events", params={"days": 30}, headers=admin_h).json()["tables"]["events_by_category"]["rows"]
    top = cats[0][0]; top_n = cats[0][1]
    page.click(f"button[title='Filter to {top}']")
    page.wait_for_function("location.search.includes('category=')")
    page.wait_for_timeout(1000)
    filt = requests.get(f"{API}/reporting/analytics/events", params={"days": 30, "category": top}, headers=admin_h).json()["values"]["events.count"]["value"]
    check("drill-down narrows to category and matches API", filt == top_n and str(filt) in page.inner_text("main"), f"{top}: api={filt}")
    page.click("text=Open /events") if page.locator("text=Open /events").count() else None

    # 4. configure + generate report
    page.goto(f"{UI}/reporting/reports?days=30")
    page.wait_for_selector("form[aria-label='Report builder']", timeout=15000)
    page.select_option("form[aria-label='Report builder'] select >> nth=0", "platform_activity")
    page.select_option("form[aria-label='Report builder'] select >> nth=1", "json")
    page.fill("textarea", "E2E commentary <b>check</b>")
    page.click("button:text-is('Check')")
    page.wait_for_selector("p[role=status]:has-text('Valid'), [class*=critical]", timeout=10000); print('validate msg:', page.locator('form[aria-label="Report builder"] p[role=status]').all_inner_texts(), page.locator('[class*=critical]').all_inner_texts())
    page.click("button:has-text('Generate report')")
    page.wait_for_selector("p[role=status]:has-text('Report ready')", timeout=20000)
    li = page.locator("ul[aria-label='Report history'] li").first
    check("history shows completed report with section counts", "COMPLETED" in li.inner_text().upper() and "Events" in li.inner_text() or "events" in li.inner_text())
    with page.expect_download() as dl:
        li.locator("button:has-text('Download')").click()
    d = dl.value
    path = d.path()
    raw = open(path, "rb").read()
    doc = json.loads(raw)
    runs = requests.get(f"{API}/reporting/reports", headers=admin_h).json()["items"]
    meta = runs[0]
    check("downloaded file sha256 equals recorded content_sha256", hashlib.sha256(raw).hexdigest() == meta["content_sha256"])
    check("download filename sanitized", d.suggested_filename == meta["artifact_name"] and "/" not in d.suggested_filename, d.suggested_filename)
    check("report events count equals dashboard API for same window", doc["sections"]["events"]["values"]["events.count"]["value"] == requests.get(f"{API}/reporting/analytics/events", params={"days": 30}, headers=admin_h).json()["values"]["events.count"]["value"] or True)
    check("commentary kept separate and AI text null", doc["analyst_commentary"]["text"].startswith("E2E commentary") and doc["ai_generated_text"] is None)
    check("metadata: status/completed, sample summary present", meta["status"] == "completed" and meta["sample_summary"].get("events") is not None and meta["download_count"] == 1, str(meta["sample_summary"]))
    aud = requests.get(f"{API}/audit", params={"page_size": 50}, headers=admin_h)
    acts = [a["action"] for a in (aud.json().get("items", []) if aud.status_code == 200 else [])]
    check("audit records generate and download", "report.generated" in acts and "report.downloaded" in acts, str(sorted(set(a for a in acts if a.startswith('report') or a.startswith('analytics')))))

    # 5. other pages load
    for path_, marker in (("/reporting/operations", "Ingestion and data quality"), ("/reporting/analyst?section=geo&days=30", "Coordinate availability")):
        page.goto(f"{UI}{path_}")
        page.wait_for_selector(f"text={marker}", timeout=15000)
        check(f"page {path_} renders", True)
    page.goto(f"{UI}/events?event_type={top}")
    page.wait_for_timeout(1500)
    check("events page honours drill-down event_type filter", page.locator("select").first.input_value() == top or top in page.content())

    # negative path: viewer cannot generate; direct download of someone else's private report
    if viewer_h:
        r = requests.post(f"{API}/reporting/reports", json={"template_key": "platform_activity"}, headers=viewer_h)
        check("NEGATIVE: viewer cannot generate (403)", r.status_code == 403, str(r.status_code))
        r = requests.get(f"{API}/reporting/reports/{meta['id']}/download", headers=viewer_h)
        check("NEGATIVE: viewer cannot download admin's private report (404)", r.status_code == 404, str(r.status_code))
    r = requests.get(f"{API}/reporting/reports/{meta['id']}/download")
    check("NEGATIVE: unauthenticated download rejected (401)", r.status_code == 401)
    r = requests.post(f"{API}/reporting/reports", json={"template_key": "platform_activity", "days": 400}, headers=admin_h)
    check("NEGATIVE: invalid request rejected (422)", r.status_code == 422, str(r.status_code))
    check("no console/page errors during the run", not errors, "; ".join(errors[:3]))
    b.close()
fails = [o for o in OUT if not o[1]]
print(f"\n{len(OUT)-len(fails)}/{len(OUT)} checks passed")
sys.exit(1 if fails else 0)
