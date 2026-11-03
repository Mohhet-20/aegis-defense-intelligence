# Changelog

Versioning follows [Semantic Versioning](https://semver.org/): MAJOR for incompatible API or
schema changes that need operator action beyond `alembic upgrade head`, MINOR for features,
PATCH for fixes. Pre-releases use `-rc.N`. The version lives in `frontend/package.json` and in
the release tag. Each entry says whether a database migration is required.

## [1.0.0-rc.3] -- 2026-10-19

Public-showcase release. Not yet tagged or pushed. No database migration (head `c16r3p0rt01`).

### Added
- **One-container public demo** (root `Dockerfile`): frontend served by the API process, real
  detector weights and the COCO sample baked in, `scripts/demo_server.py` resets and reloads synthetic
  demo data on every start and every `DEMO_RESET_HOURS`, then runs the real detector on three CC BY
  photos and the real-photo evaluation. Runs free on Hugging Face Spaces (`scripts/export_hf_space.py`,
  `deploy/huggingface/`) or Render (`render.yaml`); guide in `docs/operations/PUBLIC_DEMO.md`.
- `DEMO_MODE`: one-click demo sign-in (`GET /api/v1/demo`); shared demo accounts cannot be locked out
  or have their password, role, status or sessions changed.
- `FRONTEND_DIST_DIR`, `FRONTEND_CSP_FILE`, `FRONTEND_FRAME_ANCESTORS`: serve the built frontend with
  the same CSP and caching rules as the nginx image.
- Inference job page draws the detections on the analysed image and names the model.
- CI job `demo-image` builds and checks the demo container; Dependabot; issue and PR templates.
- README rewritten for showcasing, with new screenshots and an architecture diagram.

### Fixed
- `TRUST_FORWARDED_HEADERS` was documented but never used: behind a proxy every visitor shared one
  rate-limit bucket. The client address is now read from `X-Forwarded-For`, `TRUSTED_PROXY_HOPS`
  entries from the right (client-supplied entries are ignored).
- The sign-in page showed the development password in every build; it now appears only in demo mode
  (from the server) or in the development server.
- Model Evaluation listed synthetic runs' mAP as "undefined" (not computed): now "--".
- `scripts/verify_release.py` reported a false secret-scan failure on Windows once the repository passed
  ~840 files (command line too long); the scan now runs in batches.

### Changed
- Owner-only notes (local archive inventory, machine-specific handover) moved out of the repository.

## [1.0.0-rc.2] -- 2026-10-19

Not yet tagged or pushed (local branch `release/final-stabilization`). No database migration: the
schema head is still `c16r3p0rt01`; the timestamp column type change is Python-side only.
**Upgrade notes:** run `alembic upgrade head` as usual; browsers sign in again once (sessions move to
an HttpOnly cookie); optionally run `scripts/fetch_models.py` and `scripts/fetch_eval_data.py`.

### Added
- **Real pretrained object detector**: SSD-MobileNet v1 COCO via OpenCV DNN (person, vehicle), weights
  downloaded by `scripts/fetch_models.py` and verified against pinned SHA-256s before every load.
- **Real-image evaluation**: `scripts/fetch_eval_data.py` (deterministic COCO val2017 sample) and
  `app/cv/coco_eval.py` (per-class AP@0.5, P/R/F1, mean IoU through production post-processing),
  available in the evaluation API, MLOps experiments and the Model Evaluation page. Measured: SSD
  mAP@0.5 0.461 vs HOG 0.003 on 200 photos.
- Browser sessions with the refresh token in an HttpOnly, SameSite=Strict cookie; access token in
  memory only; `/auth/logout`; `SECRET_KEY_PREVIOUS` rotation grace period.
- `scripts/sweep_orphan_files.py`; persistent `aegis_models` Docker volume.
- MIT `LICENSE`.

### Fixed
- Timestamps on SQLite were returned without an offset (UI showed shifted times outside UTC) and
  aware non-UTC values were stored as wall time: new `UTCDateTime` column type everywhere.
- `GET /events` returned 500 when one stored row had an out-of-range coordinate.
- Spatial-relationship runs silently analysed only the earliest records (and a query LIMIT hid it).
- Sensor detail kept the previous sensor's measurement type across navigation.
- Session refresh shared the 10/min login limit (a few reloads signed users out); a failed refresh
  left its request open.

### Changed
- Map uses plain Leaflet (react-leaflet, Hippocratic License 2.1, removed).
- Tailwind CSS 3 -> 4: `npm audit` 0 vulnerabilities (was 5 high + 2 moderate, dev-only).
- 13 duplicated UTC helpers replaced by one; ~90 unused imports removed; frontend lint 0 warnings;
  build-history narration removed from source; per-phase reports moved to `docs/implementation/history/`.
- One shared rate limiter; `RATE_LIMIT_REFRESH` for session refresh.

### Also in this release (consolidation pass, 2026-10-18)
#### Fixed
- **Analytics on non-UTC PostgreSQL servers** labelled time buckets in the server's local zone and
  silently dropped late events from bucketed series (`to_char()` follows the session `TimeZone`).
  Buckets are now computed in UTC; regression tests run on both engines. Found by running the full
  suite on a real PostgreSQL 16 configured with the OS time zone.
- The full backend suite now passes on PostgreSQL: 26 fixtures that referenced non-existent users/assets
  now create real rows; 2 tests that assumed naive datetimes now convert correctly.
- Model/dataset versions were shown as "vv1"; a shared `formatVersion` helper is used instead.
- Vitest 3.2.7 (briefly added in this pass) carried 2 critical dev-only advisories; pinned Vitest 4.1.11 instead.

#### Added
- Content-Security-Policy for the frontend container (`script-src 'self'`, no inline script), defined
  once in `nginx.conf`, rendered at image build time with the map tile origin, served identically by
  `npm run preview`, and browser-verified (0 violations; injected inline script blocked).
- Route-level code splitting: main bundle 930 kB -> 337 kB.
- Frontend tests (Vitest + Testing Library, 49 tests) and `npm test`.
- `scripts/verify_release.py`: repeatable local release checks reporting PASS / FAIL / NOT RUN / BLOCKED.
- `detect-secrets` baseline and CI secret scan.
- CI: runs on `release/**` branches and on demand; Python 3.12/3.13/3.14 matrix; full PostgreSQL suite
  in a non-UTC session; frontend tests; container CSP-header and restart-persistence checks.
- `SECURITY.md`; `docs/operations/{LICENSE_DECISION,GITHUB_PUBLICATION}.md` (plus owner-only archive and handover notes, kept outside the repository since rc.2);
  real screenshots in `docs/images/`.

#### Changed
- `AdminOnly` moved to its own component (no behaviour change).
- README restructured (scope disclaimer; implemented vs simulated vs planned; evidence-based
  requirements; release status).

## [1.0.0-rc.1] -- 2026-10-18

First release candidate: the result of the 18-phase build (history in
`docs/implementation/`) plus a final stabilization pass verified on a clean Windows 11
machine. Migration head: `c16r3p0rt01` (no new migration in this release).

### Fixed
- `scripts/seed.py` created tables with `Base.metadata.create_all()`, so seeding a database that
  was behind the migration head made the next `alembic upgrade head` fail with "table already
  exists". It now refuses unless the database is at head.
- Python 3.14: `psycopg2-binary` 2.9.10 has no wheel and failed to build; pinned 2.9.11.
- ORM and migrations disagreed on `model_records` (unique `(name, version)` index, nullable
  `framework_metadata`); `alembic check` is now clean and `check_schema_drift.py` is strict.
- `gen_config_reference.py --check` (and its test) failed on Python 3.14 because `Optional[...]`
  is reported as `Union`.
- Rate-limited requests returned `{"error": ...}`, which the UI could not display; 429s now use
  the standard `{detail, request_id}` shape with `Retry-After`.
- Event detail requested a raw record for every event and showed a wrong explanation when none
  existed; the job detail page requested raw records for viewers (always 403).
- Model output detail listed a record twice (duplicate React key).
- CI: the PostgreSQL job passed `-n0` without `pytest-xdist` installed.
- Data-origin badge called uploaded and connector records "real upload"; labels now describe how
  a record entered ("file upload", "external source", "synthetic demo").

### Changed
- Navigation: grouped, collapsible sidebar from a single `navigation.ts`, with a slide-in menu on
  phones; the Overview page lists workspaces instead of a stale build note.
- Administrator-only pages show an explicit notice to other roles (the server already refused
  their requests).
- `react-router-dom` 6.28 → 7.18.4 (clears the two moderate runtime advisories).
- Documented support: Python 3.12+ (3.11 cannot install the pinned NumPy), Node.js 20+.
- `AEGIS_DEV_API_TARGET` points the Vite dev/preview proxy at another backend.
- README rewritten for new readers; the build-history README moved to
  `docs/implementation/history/README.md`.

### Added
- `scripts/demo_walkthrough.py`: an 11-step demo across all major modules through the public API.
- `scripts/e2e_route_walk.py`: browser walk over every route, per role and viewport.
- `docs/guides/LOCAL_DEVELOPMENT.md`, `CONTRIBUTING.md`, this changelog.
- Tests: seed/migration regression, rate-limit error shape, navigation-completeness contract.
