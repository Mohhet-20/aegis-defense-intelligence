# Release verification and assessment

Records, newest first: **1.0.0-rc.3**, 1.0.0-rc.2, the consolidation pass, the final stabilization pass and
the original record. Where they differ, the newest reflects the current code.

## 1.0.0-rc.3 -- public-showcase release, 2026-10-19

Adds the one-container public demo, `DEMO_MODE`, proxy-aware rate limiting and showcase polish on top
of rc.2 (below, still valid for everything else). Same environment as rc.2.

| # | Check | Result |
|---|---|---|
| 1 | Backend suite, SQLite | 1426 passed, 1 skipped, 0 failed (12 new demo-mode tests) |
| 2 | PostgreSQL 16.10, `PGTZ=Asia/Kolkata` | the 87 tests touching rc.3 changes (demo mode, auth, users, cookie sessions, key rotation, whole-API sweeps, release config): 87 passed. Full suite last run on rc.2: 1415 passed |
| 3 | Frontend | lint 0 / 0; 59 Vitest tests (2 new for demo sign-in); type-check + build |
| 4 | Demo server with the image's exact settings (outside Docker) | fresh reset, migrations, seed, walkthrough 11/11, real detector on 3 CC BY photos, real-photo evaluation mAP@0.5 0.461, `[demo] ready` |
| 5 | Browser on the single-process server | 76/76 routes for administrator and viewer; one-click sign-in |
| 6 | Headers | HTML: nginx CSP incl. tile host, `frame-ancestors https://huggingface.co`, no X-Frame-Options; assets immutable; `/api/*` never falls back to HTML |
| 7 | CI `demo-image` check script | run against the local demo: passed; every run block `bash -n` clean |
| 8 | `scripts/verify_release.py --release` | 18 PASS; 1 FAIL on the first run fixed: the secret scanner flagged the public demo password and made-up test passwords, now marked inline as reviewed; a second, false failure came from Windows' command-line length limit and is fixed by scanning in batches -- rerun: secret scan PASS, quick run 16 PASS / 0 FAIL; 4 NOT RUN by design (PostgreSQL run separately, `npm ci` with existing node_modules, no Docker, CI not pushed) |
| 9 | Privacy sweep of every publishable file | no personal email, no local paths, no archive names; owner-only notes moved outside the repository |

**Not verified:** building the root `Dockerfile` (no Docker here; the CI `demo-image` job does it),
Hugging Face and Render deployments themselves.

---

## 1.0.0-rc.2 -- Windows 11 + PostgreSQL 16.10, 2026-10-19

**Status: release candidate, MIT licensed. Verified locally end to end; the GitHub Actions workflow and
Docker images are AUTHORED, NOT EXECUTED (no remote, no Docker here).** Environment: Windows 11, Python
3.14.4, Node 24.18, Chrome via Playwright 1.64, PostgreSQL 16.10 portable (throwaway cluster, server zone
`Asia/Calcutta`, test sessions with `PGTZ=Asia/Kolkata`). All results on the final committed code.

| # | Check | Result |
|---|---|---|
| 1 | Backend suite, SQLite | 1414 passed, 1 skipped (SQLite-only skip), 0 failed |
| 2 | Backend suite, PostgreSQL 16 | 1415 passed, 0 failed (PGTZ=Asia/Kolkata, 1 h 16 min) |
| 3 | Migrations, both engines | fresh → head, `alembic check` 0 differences, strict drift 0, downgrade to base and back |
| 4 | Frontend | lint 0 errors / 0 warnings; 57 Vitest tests; `tsc -b`; production build (main chunk 337 kB); full `npm audit` **0 vulnerabilities** |
| 5 | Browser route walk | 76/76 routes for admin, analyst, investigator, viewer and 390 px, production build under the CSP, cookie sessions (each page load restores the session) |
| 6 | Session journey (`e2e_release_browser.py`) | 11/11: HttpOnly + SameSite=Strict refresh cookie, not script-readable, no tokens in storage, reload keeps session, revocation and mid-session expiry return to login, error boundary |
| 7 | Real detector | SSD-MobileNet v1 COCO on 200 COCO photos: mAP@0.5 0.461 (person 0.457, vehicle 0.466); HOG 0.003; mock 0.000; also run from the UI and as an MLOps experiment |
| 8 | Model supply chain | archive + file SHA-256 verified on install; tampered file refused on load |
| 9 | Tailwind 4 visual check | pixel diff of 17 screenshots (12 pages, desktop + phone): 9 identical, others differ only in live timestamps / one re-wrapped hint |
| 10 | Security scans | pip-audit none; bandit medium+ none; detect-secrets no new findings; `npm audit` 0 |
| 11 | `scripts/verify_release.py` | `--release`: 18 PASS; 1 FAIL fixed (secret scanner flagged the public SHA-256 pins -- marked inline, rescan clean); 4 NOT RUN by design (PostgreSQL run separately above, `npm ci` with existing node_modules, Docker absent, GitHub Actions not pushed) |
| 12 | CI workflow | YAML parses; every run block passes `bash -n`; **not executed** |

### Defects found and fixed in rc.2
Timestamps without offsets on SQLite (shifted UI times; wall-time storage of aware values) · `GET /events`
500 on one bad stored coordinate · silent truncation in spatial-relationship runs (hidden by a LIMIT) ·
sensor page stale measurement type · session refresh sharing the login rate limit (found by the route
walk) · unread body on failed refresh · no orphan-file sweeper · no key-rotation grace period ·
Tailwind 3 toolchain advisories · react-leaflet licence. Each has a regression test or browser check.

### Not verified
Docker images and Compose · GitHub Actions · Python 3.12/3.13 locally · macOS · real hardware ·
operational imagery for the detector · multi-process deployment.

### Assessment
**Release candidate for single-host use, ready for demonstration.** No open defect in authentication,
authorization, tenant isolation, private artifacts, secrets or data integrity in the verified scope.
The remaining gate before tagging is a green CI run on GitHub, including the first container build.

---


## Consolidation pass -- Windows 11 + PostgreSQL 16.10, 2026-10-18 (proposed 1.0.0-rc.2)

**Status: release candidate, publication BLOCKED (license selection pending); CI AUTHORED, NOT
EXECUTED; containers NOT BUILT.** All results below were produced on the final working tree
(committed afterwards, unchanged, as `a111654`). Environment: Windows 11 (10.0.26200), Python 3.14.4,
Node 24.18, Chrome via Playwright 1.64, PostgreSQL 16.10 from the official portable binaries
(throwaway cluster on 127.0.0.1:55432; server `TimeZone` = `Asia/Calcutta`, as initdb set it). No Docker.

### Executed checks

| # | Check | Command / method | Result |
|---|---|---|---|
| 1 | Git state | `git branch -vv`, `git log`, `git diff --check` | branch `release/final-stabilization`, 8 commits above `main` (`8c1aaa3`, unchanged), no remote, whitespace clean |
| 2 | Archive consolidation | read-only blob-hash comparison of 23 archive files (21 readable, 1 empty, 1 truncated) + backup folder | 0 files missing from HEAD; nothing to merge (owner-only inventory, outside the repository) |
| 3 | Recovery record | `git bundle create --all` + `git bundle verify` | OK: verified bundle stored outside the repository |
| 4 | Backend suite, SQLite | `python -m pytest -q` (via `verify_release.py`) | 1385 passed, 0 failed, 1 skipped (a PostgreSQL-only test), 5 min 11 s |
| 5 | Backend suite, PostgreSQL 16 -- before fixes | `TEST_DATABASE_URL=... python -m pytest -q` | 1355 passed, **29 failed** (48 min) |
| 6 | Backend suite, PostgreSQL 16 -- after fixes | same | 1386 passed, 0 failed, 0 skipped (38 min 43 s; server TimeZone Asia/Calcutta) |
| 7 | Migrations on PostgreSQL | fresh `upgrade head`; `alembic check`; `downgrade -1`/`upgrade`; `downgrade base`/`upgrade head`; `check_schema_drift.py` | all pass; **0** ORM/migration differences |
| 8 | Migrations on SQLite | same via `verify_release.py` | pass |
| 9 | Production mode on PostgreSQL | migrate + `bootstrap_admin.py` + uvicorn (`ENVIRONMENT=production`) + `smoke_test.py --expect-docs-disabled` | **23/23**; secret, admin password and DB password absent from logs |
| 10 | Persistence across restart (PostgreSQL) | count events/media/reports, kill + restart, recount | identical (2/1/1) |
| 11 | Backup/restore (PostgreSQL) | `backup_restore.py backup` → `verify` → `restore` into an empty DB → app read-back → smoke | 30 rows + 2 files verified; non-empty target refused; restored app 23/23 |
| 12 | Frontend clean install | `npm ci` in a fresh copy of the committable file set | 320 packages; lint 0 errors (2 pre-existing warnings); 49/49 tests; build OK |
| 13 | Frontend tests | `npm test` (Vitest 4.1.11) | 49 passed (5 files); two mutation checks confirmed the tests fail when CSP or labels regress |
| 14 | Production bundle | `npm run build` | main chunk 337 kB (was 930 kB); 87 chunks; no source maps; no port-qualified localhost URL |
| 15 | CSP in a browser | `vite preview` serving the `nginx.conf` policy; `e2e_route_walk.py` for admin/analyst/investigator/viewer + 390 px; `securitypolicyviolation` listener on media/map/report pages | 76/76 routes, 0 violations; blob media and 15 map tiles load; injected inline script **blocked** |
| 16 | Secret scan | `detect-secrets` 1.5.0 on all committable files + full git history grep + deleted-path check | 63 findings, all reviewed false positives (baseline committed); history: 0 high-signal patterns, 0 deleted paths, 0 env/db/key files ever added |
| 17 | Dependency scans | pip-audit; `npm audit --omit=dev`; full `npm audit`; bandit `-ll` | none; **0**; 5 high + 2 moderate dev-only (Tailwind 3 chain); no findings |
| 18 | License inventory | package metadata, frontend runtime tree | permissive except LGPL (`psycopg2-binary`) and **Hippocratic 2.1** (`react-leaflet`) |
| 19 | CI workflow | YAML parse; `bash -n` on all 23 run blocks; persistence snippet run against a live backend | valid; **not executed on GitHub** |
| 20 | Release script | `scripts/verify_release.py` | PASS 17, FAIL 0, NOT RUN 4 (PostgreSQL flag not passed -- run separately; clean npm ci -- run separately; Docker; GitHub Actions), BLOCKED 1 (license); exit 0 |

### Defects found and fixed in this pass
1. **Application:** analytics bucket labels used the PostgreSQL session time zone; late events vanished
   from bucketed series on non-UTC servers (KNOWN_RISKS 54). Fixed + 2 regression tests.
2. **Tests:** 26 fixtures with fabricated foreign keys; 2 tests assuming naive datetimes (KNOWN_RISKS 44).
3. **CI:** never triggered on the release branch; PostgreSQL job ran only a subset in a UTC session.
4. **UI:** "vv1" version labels; 930 kB single bundle; no CSP.
5. **Hygiene:** root `.gitignore` did not ignore `__pycache__` outside `backend/`.
6. **Tooling:** Vitest 3.2.7 (added mid-pass) had 2 critical dev advisories → Vitest 4.1.11.

### Not verified
Docker images and Compose (no Docker here) · GitHub Actions (no remote) · Python 3.12/3.13 locally ·
macOS · graceful shutdown on Windows (servers were stopped with `taskkill /F`) · real hardware,
real model weights, multi-process deployment.

### Assessment
**Ready for local demonstration. Release candidate for single-host use, not yet releasable:**
publication is blocked on the license decision, and the CI workflow and container images must run
green on GitHub before a release tag. No authentication, authorization, tenant-isolation,
private-artifact, secret-handling or data-loss defect is open in the verified scope; the one
data-correctness defect found (item 1) is fixed.

---


## Final stabilization pass -- Windows 11, 2026-10-18 (release candidate 1.0.0-rc.1)

Environment: Windows 11 Home (10.0.26200), Python 3.14.4 (venv), Node 24.18 / npm 11.16,
Google Chrome via Playwright 1.64 (`channel=chrome`), SQLite only. **No Docker, no PostgreSQL,
no GitHub Actions** on this machine. All data synthetic; all databases disposable (scratch
directories), except one read-only copy test of the developer's local database.

### Executed checks (after the final code changes unless noted)

| # | Check | Command | Result |
|---|---|---|---|
| 1 | Backend suite + coverage | `python -m pytest -q --cov=app` | **1384 passed, 0 failed, 0 skipped; 94% line coverage (406 s)** |
| 2 | Frontend lint | `npm run lint` | 0 errors, 2 pre-existing warnings |
| 3 | Frontend type-check + build | `npm run build` | passed (`tsc -b` clean; one >500 kB chunk warning; no source maps; no port-qualified localhost URLs -- React Router 7 contains a port-less internal `http://localhost` URL base, so the CI check was narrowed accordingly) |
| 4 | Clean install, Python 3.11 | `pip install -r requirements.txt` | **failed as expected** -- `numpy==2.5.4` needs Python 3.12 (docs corrected) |
| 5 | Clean install, Python 3.14 | same, fresh venv | failed on `psycopg2-binary==2.9.10` (no wheel); **passed** after pinning 2.9.11 |
| 6 | Clean-room README run (PowerShell, `git archive` of HEAD, new venv, `npm ci`) | README "Windows" steps verbatim (Python 3.14) | migrate, seed, backend on :8000, Vite on :5173, proxy all worked |
| 7 | Migrations, fresh SQLite | `alembic upgrade head`; `alembic check`; `downgrade -2` / `upgrade head` | passed; `alembic check`: no differences (was 2 before the ORM fix) |
| 8 | Migration upgrade of a populated database | copy of the local dev DB at `a14c0de5ec01` → `upgrade head` | passed; row counts identical in all 57 pre-existing tables; 6 new tables; `alembic check` clean |
| 9 | Seed on unmigrated DB | `tests/test_release_seed.py` | refuses and creates nothing (the old script fails this test) |
| 10 | Smoke test, development | `scripts/smoke_test.py` | 22/22 (scratch DB and clean room) |
| 11 | Production mode | weak / short `SECRET_KEY`; seed in production; migrate + `bootstrap_admin.py` + start + smoke with `--expect-docs-disabled` | both start-ups refused; seed refused; second bootstrap refused; **23/23**; secret and password absent from logs |
| 12 | Demo walkthrough | `scripts/demo_walkthrough.py` | 11/11 (scratch DB and clean room) |
| 13 | Browser: every route | `scripts/e2e_route_walk.py` as admin, analyst, investigator, viewer, and admin at 390 px | 76/76 routes without console errors, failed API calls, error screens or blank pages (clean room, final code); 1 detail route has no record to open (`/edge/conflicts/:id`, needs a sync conflict) |
| 14 | Browser: horizontal overflow at 390 px | Playwright, all 62 static routes | 0 pages scroll sideways |
| 15 | Browser: session expiry / error boundary | `scripts/e2e_release_browser.py` | 8/8 (clean room) |
| 16 | Browser: analytics and reporting journey | `scripts/e2e_reporting_browser.py` | 21/21 (on React Router 7) |
| 17 | Backup / restore (SQLite) | `backup_restore.py backup` → `verify` → `restore` to empty target; restore again | 541 rows + 6 files verified; overwrite refused; app read back events, investigations, media bytes and a report download |
| 18 | Static and dependency checks | ruff gate; bandit `-ll`; pip-audit; `npm audit --omit=dev`; full `npm audit` | clean; no findings; no known vulnerabilities; **0**; 5 high + 2 moderate in dev-only Tailwind 3 tooling (KNOWN_RISKS 51) |
| 19 | CI workflow | YAML parse + each command run locally | parses; `-n0` defect fixed; **not run on GitHub** |

### Defects found and fixed in this pass
1. `seed.py` bypassed Alembic (`create_all`) -- broke the next upgrade on any DB behind head.
2. False "Python 3.11+" requirement; `psycopg2-binary` pin uninstallable on Python 3.14.
3. ORM/migration drift on `model_records` (now declared; drift checker strict). Exposed one
   test fixture that inserted duplicate `(name, version)` rows; the fixture was fixed.
4. `gen_config_reference.py --check` failed on Python 3.14 (the baseline's only failing test).
5. 429 responses unreadable by the UI (non-standard body).
6. Event detail and job detail pages made requests guaranteed to 404/403; wrong explanation text.
7. Duplicate React key on model output detail.
8. CI PostgreSQL job would fail immediately (`-n0` without pytest-xdist).
9. React Router 6 runtime advisories (upgraded to 7.18.4).
10. UX: 70 ungrouped sidebar links, no phone layout, stale "stage"/"not-yet-built ... not
    implemented yet" texts, admin forms shown to non-admins, "real upload" origin label.

### Not verified in this pass
Containers (no Docker here), PostgreSQL (verified sandbox only), GitHub
Actions, Python 3.12/3.13 locally, macOS/Linux instructions (CI covers Linux), real hardware,
real model weights, multi-process deployment, form-by-form UI interaction beyond the scripted
journeys.

### Release checklist (for each release)
1. `CHANGELOG.md` entry and version in `frontend/package.json`; note migrations.
2. Backend suite green; frontend lint + build green; `alembic check` clean on a fresh DB.
3. Upgrade test: copy of the previous release's database → `alembic upgrade head` → row counts.
4. `smoke_test.py` against a production-mode instance; `e2e_route_walk.py` for all roles.
5. Backup → restore into a scratch target → app read-back.
6. Dependency audits (pip-audit, `npm audit --omit=dev`), bandit; review `KNOWN_RISKS.md`.
7. CI green on the release commit (including `postgres` and `containers` jobs); tag `vX.Y.Z`.

### Assessment
**Ready for local demo; release candidate for single-host use with conditions.** No
authentication, authorization, tenant-isolation, private-artifact, secret-handling or data-loss
defect is open in the verified scope. Conditions before calling it a release: the CI `postgres`
and `containers` jobs must pass on GitHub (containers have never been built), and a license must
be chosen before publication.

---

## Record (Linux sandbox)

Environment: Linux x86_64 sandbox, 2 CPUs, Python 3.13, Node 22, PostgreSQL 16 server installed locally, Docker CLI + daemon present but **Docker Hub and other registries unreachable** (HTTP 403 from the egress policy), no GitHub Actions. All data synthetic; all databases disposable.

### Checklist
| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Fresh environment configuration | Verified | generated `CONFIGURATION_REFERENCE.md` covers all 160 settings (test enforces); production start refused for placeholder/short secret and wildcard CORS (4 tests) |
| 2 | Dependency installation | Partially | `pip install -r requirements.txt` `npm ci` used throughout this layer's environment; a clean-room install was not repeated |
| 3 | Database initialization / migration | Verified | `alembic upgrade head` from empty on **SQLite and PostgreSQL 16**; downgrade -1 / upgrade on both; single head `c16r3p0rt01`; ORM-vs-migration comparison on PostgreSQL: 2 known accepted differences, 0 unexpected |
| 4 | Backend startup | Verified | production mode on PostgreSQL: ready in 2.6 s, ~190 MB RSS idle / ~205 MB after the smoke test; graceful shutdown on SIGTERM; restart keeps data |
| 5 | Frontend production build | Verified | `npm run build` OK; no source maps; no localhost URLs in `dist/assets`; `tsc -b` clean; eslint 0 errors / 2 pre-existing warnings |
| 6 | Health and readiness | Verified | `/health/live`, `/health/ready`; concurrency defect found and fixed (28/300 false 503 → 0/300) |
| 7 | Authentication | Verified | smoke test (login, wrong password, /auth/me); workflow A; bootstrap-admin tests |
| 8 | Authorization and tenant isolation | Verified | sweeps over all 319 operations on **SQLite and PostgreSQL**; cross-tenant integrity checks; foreign-admin guessed-id sweep |
| 9 | Core ingestion workflow | Verified | workflow B; smoke test |
| 10 | Evidence and investigation workflow | Verified | workflows C, E |
| 11 | Model evaluation workflow | Verified | workflow F (synthetic classifier fixture) |
| 12 | Analytics and reporting | Verified | workflows F, G; smoke test; browser E2E 21/21 |
| 13 | Private artifact access | Verified | media/report download require auth (smoke), byte/SHA identity, foreign org 404, tamper → 409 |
| 14 | Error handling | Verified | sanitized 404/422/500, no value echo, request ids |
| 15 | Backup and restore | Verified (scope below) | automated SQLite round trip incl. application read-back; manual PostgreSQL round trip |
| 16 | Container startup and smoke test | **Blocked / not verified** | images could not be built (registry 403); `docker compose config` validates; the CI `containers` job is the first real test |
| 17 | CI configuration | **Unverified remotely** | YAML parses; each step's commands were executed locally (SQLite tests, ruff, PostgreSQL migrations + drift + integration subset + production smoke, frontend lint/build, bandit, pip-audit, npm audit) |
| 18 | Existing regression tests | See counts | SQLite full suite: **1381 passed, 0 failed**, 94% line coverage. PostgreSQL full suite (serial, 17 min): **1352 passed, 27 failed** — 26 tests insert fabricated foreign-key values that SQLite ignores, 1 asserts SQLite's naive datetimes (KNOWN_RISKS 44); the one real PostgreSQL defect found (sensor filter) was fixed and re-verified (13/13 on PostgreSQL). Integration/sweep/workflow subset on PostgreSQL: 36 passed. |

Also executed: production-mode smoke test **23/23** against PostgreSQL (docs disabled, 401s, ingestion + duplicate, media round trip, report integrity, error sanitization); browser checks for the error boundary and session expiry **8/8**; the reporting layer browser E2E **21/21** re-run on the final code.

### Defects found and fixed
1. `GET /sensors?measurement_type=` → HTTP 500 on PostgreSQL (`json LIKE`). Fixed (cast); PostgreSQL-dialect regression test.
2. Intermittent false 503 from `/health/ready` under concurrent probes (shared probe file). Fixed; regression test fails on the old code.
3. No way to create the first administrator in production. Added `scripts/bootstrap_admin.py` (found a crash in its first CLI version through the real production run; fixed + regression test).
4. Frontend: no error boundary; expired refresh token left the user on a failing page. Fixed; browser-verified.
5. nginx default `client_max_body_size 1m` would have rejected every upload through the compose frontend; compose also used a hard-coded dev secret, published the database port, ran migrations on every start and ran as root. All changed (unverified at runtime).
6. Two reviewed dynamic-SQL sites in `app/edge/local_store.py` hardened/annotated for bandit.

### Release blockers and findings
| Severity | Finding | Release implication |
|---|---|---|
| – | No unresolved auth, tenant-isolation, private-artifact, secret-handling or data-loss defects identified in the verified scope | none |
| Medium (hardening) | Tokens in `localStorage`, no CSP (risk 43) | accepted limitation for an internal deployment; address before exposing to untrusted networks |
| Medium (process) | Container images and CI never executed (risks 36, 45) | do not rely on compose until the CI `containers` job or a local build + smoke test passes |
| Low | PostgreSQL full suite not green (risk 44); stored invalid coordinates → `/events` 500 (risk 33); react-router moderate advisories (risk 34); schema drift (39) | tracked; none blocks the verified scope |
| Info | Single-process design: per-process rate limits/metrics, synchronous jobs, local-disk storage, no HA (risks 37, 47) | state clearly to operators; do not run multiple backend processes against one storage root without understanding this |

### Not tested
Large datasets and PostgreSQL performance beyond the SQLite benchmark; TLS/reverse-proxy deployment; backup of a live (writing) system; restore across PostgreSQL versions; real model weights, GPUs, edge hardware; external copilot providers; image scanning; the `nginx.conf` itself (no nginx binary available); upgrade from a pre-original database containing real data.

### Release assessment: **Conditionally ready**
Basis: for the verified scope — a single host running the backend natively against PostgreSQL 16 with the built frontend behind a TLS reverse proxy — migrations, startup validation, authentication/authorization/tenant isolation, core workflows, private artifacts, error handling, graceful shutdown and backup/restore were exercised and passed, and no unresolved release blocker was found. It is *conditional* because (a) the container deployment and the CI pipeline have not been executed anywhere, (b) the PostgreSQL full-suite run has 27 fixture-related failures, (c) the hardening items above (token storage/CSP) are open, and (d) the system is single-process by design. It is not "release-ready" without those caveats, and nothing here supports claims of high availability, horizontal scalability or tested large-scale throughput.
