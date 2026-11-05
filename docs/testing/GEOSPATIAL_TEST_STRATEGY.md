# Geospatial Test Strategy

**Status: IMPLEMENTED.** 113 new backend tests across 9 files, plus a
live Playwright browser-verification pass against the real running
backend/frontend with real seeded data. Full backend suite: **620
passed, 0 failed**, 93% line coverage across `app/` (re-run fresh
during this layer's completion pass, not assumed from an earlier
run).

## 1. Backend test files, by layer

**Pure logic (`app/geo/`), zero database:**

- `tests/test_geo_distance.py` (12 tests) -- haversine correctness
  against a known real-world distance (New York-London), symmetry,
  non-negativity, the "~111.32km per degree of latitude everywhere"
  invariant, antimeridian crossing computed as *short* not *long*,
  pole-to-pole distance against half the Earth's circumference,
  `bounding_box_for_radius()` actually containing a point at the
  requested radius, and the near-pole/full-longitude-span edge case
  not crashing.
- `tests/test_geo_validation.py` (21 tests) -- every finding code
  (`missing`, `invalid_range` at all four boundary directions,
  `non_finite` for both NaN and infinity, `unsupported_crs`,
  `stale_location_timestamp` both flagged and not-flagged,
  `uncertainty_unavailable`), boundary values (exactly ±90/±180) are
  correctly `valid` not `invalid_range`, and both
  `classify_validation_status()` and `is_usable_for_mapping()`'s
  narrower pure-function contracts.

**Services (`app/services/`), real SQLite-backed Session fixtures:**

- `tests/test_geo_query_service.py` (20 tests) -- viewport bounds
  correctness, missing/invalid-location exclusion (the specific
  distinction documented in
  `docs/data/LOCATION_PROVENANCE_AND_UNCERTAINTY.md` Section 3),
  invalid-bounds rejection, multi-record-type combination, tenant
  isolation, antimeridian-crossing bounding boxes, truncation
  reporting, per-record-type timestamp selection (`observed_at` vs.
  `registered_at`), half-open time-interval boundaries, radius-query
  distance filtering/sorting/excessive-radius rejection/near-pole
  stability, and `spatial_grid_counts()`'s bucketing, exclusion, and
  resolution validation.
- `tests/test_geo_timeline_service.py` (9 tests) -- range filtering,
  ascending-vs-descending ordering (the exact mechanism historical
  playback depends on), `since >= until` and excessive-range
  rejection, time-bucket counting, non-positive-bucket rejection, and
  gap detection both above and below threshold plus an
  unknown-record-type rejection.
- `tests/test_location_quality_service.py` (8 tests) -- missing
  location is an exact count (not a sample), invalid-range counting,
  unsupported-CRS counting, uncertainty-unavailable counted only for
  otherwise-valid rows, stale-location counting, `list_quality_issues()`
  excluding clean records by default vs. including them with
  `only_issues=False`, and tenant isolation on `quality_summary()`.
- `tests/test_geo_overview_service.py` (4 tests) -- basic aggregate
  counts, unreviewed-spatial-relationship-candidate counting,
  unreviewed-location-conflict counting, tenant isolation. (One test's
  own initial assumption about `missing_or_invalid_location_total` was
  wrong during authoring and was corrected to match established
  behavior -- see
  `docs/data/LOCATION_PROVENANCE_AND_UNCERTAINTY.md` Section 3 -- not
  a defect in the service.)
- `tests/test_geo_export_service.py` (10 tests) -- GeoJSON structural
  correctness (coordinate order `[longitude, latitude]` per RFC 7946),
  exclusion of missing/invalid locations from export, CSV structural
  correctness, the CSV-formula-injection guard, `max_features`
  honoring + `truncated` flag, the hard export ceiling never being
  exceeded regardless of requested size, bbox/time-range filtering,
  partial-bbox rejection, and tenant isolation.
- `tests/test_spatial_relationship_service.py` (11 tests) -- candidate
  creation for a genuinely close pair, exclusion by distance, exclusion
  by time window, idempotency on re-run, Observation-as-Evidence
  wrapping, skipping records with missing/invalid locations,
  since/until filtering, rejection of non-positive thresholds,
  review-status filtering on `list_candidates()`, reviewability via
  the **existing** `relationship_service.review_relationship()` (not a
  new endpoint -- this is the specific test confirming Section 2's
  reuse decision), and tenant isolation.

**API/route layer (`tests/test_geospatial_api.py`, 18 tests):**
authentication-required on every route, `GEOSPATIAL_READ` granted to
every role, invalid-bounds rejection surfaced as `400`, every one of
the 13 endpoints exercised at least once with a real response-shape
assertion, `GEOSPATIAL_MANAGE`-gating on relationship generation
(explicit 403 for a role without it),
`test_generated_relationship_is_reviewable_via_existing_relationships_endpoint`
(posts to `/relationships/{id}/review`, confirming the reuse claim end
to end through the HTTP layer, not just at the service layer),
`GEOSPATIAL_EXPORT`-gating (explicit 403 for Investigator/Viewer), and
a dedicated cross-endpoint tenant-isolation test covering all 4 new
route files in one pass.

## 2. Why this split

Pure `app/geo/` functions are tested with zero database fixture
overhead (fast, exhaustive boundary-condition coverage); every
service-layer test uses the project's existing SQLite
Session-per-test fixture (same pattern as each layer's test
suite); route tests verify permission-gating and response shape, not
business logic already covered at the service layer -- no test
duplicates assertions across layers unnecessarily.

## 3. Frontend verification

`npx tsc -b --force` -- clean, no errors. `npx eslint .` -- 0 errors,
2 warnings (1 pre-existing in `AuthContext.tsx`, 1 pre-existing
intentional `react-hooks/exhaustive-deps` in `SensorDetailPage.tsx`;
neither is new this layer). `npm run build` -- succeeds, `dist/`
628.47 kB JS (174.54 kB gzip) / 33.02 kB CSS, only the standard
Vite large-chunk informational warning.

**Live browser verification** (its own addition, beyond the
`tsc`/`eslint`/`build` bar): a Playwright script, run against the real
backend (`uvicorn`) and frontend (`vite`) dev servers with the real
seeded database, logged in as the seeded `analyst` account and visited
all 7 Geospatial Intelligence Workspace pages, confirming for each: the
expected page heading renders, no error banner appears in the page
body, and zero browser console errors occur (the Map Explorer's
`ERR_TUNNEL_CONNECTION_FAILED` tile-image errors are the one documented
exception -- confirmed via screenshot review to be a sandbox
network-proxy limitation, not an application bug; see
`docs/operations/MAP_PROVIDER_CONFIGURATION.md` Section 5). Two live
interaction tests were additionally run: confirming a real
spatial-relationship candidate (button click -> API call -> UI moves
the item from the "candidate" filter to the "confirmed" filter,
verified by element count before/after, not merely "no exception
thrown") and downloading a real GeoJSON export (button click ->
`page.expect_download()` -> saved file parsed and confirmed to contain
a well-formed `FeatureCollection`). All 7 pages' full-page screenshots
were visually reviewed, which is specifically how the
`unsupported_crs`/`invalid_range` seed-data ordering bug described in
`docs/data/LOCATION_SCHEMA_AND_COORDINATE_SYSTEMS.md` Section 2 was
caught -- a bug `tsc`/`eslint`/unit tests alone would not have
surfaced, since the seed data itself (not the validation logic) was
wrong.

## 4. What this does NOT do

- No load/performance testing of the bounding-box-scan query pattern
  at a larger data volume than this project's seeded/test data (see
  `docs/architecture/GEOSPATIAL_INTELLIGENCE_ARCHITECTURE.md` Section 4's
  honest statement that this has not been benchmarked at scale).
- No visual-regression/screenshot-diffing automation -- screenshots
  were captured and reviewed manually this session, not compared
  against a stored baseline by an automated tool.
- No end-to-end test of a real external tile provider actually
  serving tiles (blocked by this sandbox's network egress policy, not
  by application design -- see
  `docs/operations/MAP_PROVIDER_CONFIGURATION.md`).
- No mutation/fuzz testing of the coordinate-validation boundary
  conditions beyond the explicit boundary-value tests listed above.
