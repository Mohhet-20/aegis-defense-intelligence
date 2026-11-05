# Sensor Analytics Test Strategy

Status: implemented, live-verified. Full backend suite (`pytest -q --cov=app
--cov-report=term-missing`), including every test alongside the new tests
below: **507 passed**, **0 failed**, **92% overall statement coverage**.

## Why pure, DB-free modules first

`app/sensors/units.py`, `app/sensors/quality.py`, `app/sensors/statistics.py`, and
`app/sensors/anomaly.py` import no SQLAlchemy and take whatever history/context a check needs
as plain arguments -- the same "pure function, caller supplies the context" discipline
`app/tracking/motion.py` and `app/tracking/association.py` already proved out. This
lets the heaviest-logic modules be exhaustively unit-tested without a database fixture at all,
which is why they reach the highest coverage numbers in the table below.

## Test files and what each covers

| File | Category | Covers |
|---|---|---|
| `tests/test_sensor_units.py` | Unit | 13 tests, pure `app/sensors/units.py` conversion tests. |
| `tests/test_sensor_quality.py` | Unit | 16 tests, pure `app/sensors/quality.py` validation tests. |
| `tests/test_sensor_statistics_and_anomaly.py` | Unit | 22 tests, pure `app/sensors/statistics.py` + `app/sensors/anomaly.py` tests. |
| `tests/test_sensor_ingestion.py` | Service | 14 tests, `sensor_ingestion_service` via a real DB, including a dedicated naive/aware datetime regression test. |
| `tests/test_anomaly_service.py` | Service | 8 tests, `anomaly_service` orchestration tests. |
| `tests/test_sensor_health_service.py` | Service | 10 tests, `sensor_health_service` tests (connectivity/measurement-quality/anomaly-status/device-reported signals, lifecycle recompute). |
| `tests/test_timeseries_service.py` | Service | 9 tests, `timeseries_service` tests (range validation, downsampling, descriptive statistics). |
| `tests/test_cross_source_comparison_service.py` | Service | 8 tests, `cross_source_comparison_service` tests. |
| `tests/test_sensor_registry_api.py` | API | 13 tests, `/sensors` + `/observations` API-level tests, including cross-tenant access. |
| `tests/test_sensor_ingestion_api.py` | API | 12 tests, `/sensor-ingestion` API-level tests (submission, listing, raw-record inspection, retry). |
| `tests/test_sensor_analytics_api.py` | API | 10 tests, `/sensor-analytics` API-level tests (time series, statistics, health, anomaly run/list/review). |
| `tests/test_cross_source_comparison_api.py` | API | 4 tests, `/cross-source-comparison` API-level tests. |

## What's deliberately not separately tested

- **A machine-learning anomaly model.** `app/sensors/anomaly.py` is entirely documented
  statistical heuristics (range/z-score/MAD/rate-of-change/heartbeat/repeated-value/sampling-gap)
  -- there is no model to validate against a held-out dataset, only the heuristics' own
  deterministic math, which the unit tests cover directly.
- **A background worker or scheduler.** There is none in this codebase (see
  `docs/operations/SENSOR_INGESTION_OPERATIONS.md`'s "Execution model"), so there is nothing to
  test for queueing, retry backoff, or cancellation beyond the synchronous request path already
  covered.
- **An HTTP/network sensor connector.** None is registered (`app/sensors/adapters/registry.py`
  has no network-fetching entry), so there is no SSRF/network-hardening surface to
  test -- that work is deferred along with the connector itself.

## What we learned (test-authoring mistakes, corrected -- not production bugs)

Three tests were initially written against a wrong assumption about the system's own behavior,
not against a bug in it; each was rewritten once the real behavior was understood, in the same
spirit of honest self-correction `docs/testing/TRACKING_TEST_STRATEGY.md` already models:

1. A test wrongly assumed `recompute_lifecycle_status()` controls the `registered` ->
   `active` transition, when that transition is actually automatic inside ingestion
   (`sensor_ingestion_service._process_batch()` flips it the moment a record is accepted) --
   rewritten using an `active` -> `degraded` scenario instead.
2. A test wrongly assumed a config-validation-failure ingestion job (`status="failed"`) is
   retryable, when by design it is **not** -- no `synthetic_config` was ever written to
   `job.provenance` for that failure path, so `retry_job()` has nothing to resubmit. Rewritten
   using a unit-incompatible scenario (`status="completed_with_errors"`, which *does* preserve
   its config) instead.
3. A test wrongly assumed a 5-minute-old observation series would report
   `connectivity="connected"`, when it actually correctly reported `"missed_heartbeat"` because
   the series' last point was really about 55 minutes in the past relative to the fixture's own
   clock -- fixed the test's time-window setup, not the connectivity logic.

## Results, as actually run

Per-module coverage, freshly confirmed in this session's run:

| Module | Coverage |
|---|---|
| `app/sensors/units.py` | 100% |
| `app/sensors/adapters/registry.py` | 100% |
| `app/sensors/statistics.py` | 99% |
| `app/sensors/quality.py` | 98% |
| `app/services/sensor_health_service.py` | 97% |
| `app/services/timeseries_service.py` | 98% |
| `app/services/anomaly_service.py` | 96% |
| `app/services/sensor_service.py` | 92% |
| `app/services/cross_source_comparison_service.py` | 93% |
| `app/sensors/anomaly.py` | 89% |
| `app/services/sensor_ingestion_service.py` | 89% |
| `app/sensors/adapters/synthetic.py` | 89% |
| `app/sensors/adapters/csv_batch.py` | 72% |
| `app/sensors/adapters/json_batch.py` | 70% |

The two adapter files sit lowest because their error-path branches (malformed CSV, oversized
JSON list, non-UTF-8 content) are each exercised by only a handful of tests relative to their
branch count -- a known, acceptable shape for thin parsing adapters, not a gap hidden from this
table.

## Frontend

`npx tsc -b --force` (clean), `npx eslint .` (0 errors; 1 pre-existing unrelated warning plus 1
intentional `react-hooks/exhaustive-deps` warning in the new `SensorDetailPage.tsx`), and
`npm run build` (succeeded, `dist/assets/index-*.js` 439.20 kB / gzip 120.17 kB) were all run
clean against the new sensor pages and API-client additions. There is no frontend unit-test
harness in this codebase (consistent with every earlier work); frontend correctness otherwise
rests on type-checking, linting, and a clean production build against the real backend API
shapes.

This layer additionally ran a **live, Playwright-driven browser verification pass** -- logged in
as the real seeded `admin`/`DevPassword123!` account against the real running dev stack --
confirming all 5 new frontend pages (Sensor Registry, Sensor Detail including the SVG
time-series chart, the four-signal health card, lifecycle actions, and the recompute/
run-anomaly-checks buttons; Sensor Ingestion Monitor; Anomaly Review Center; Cross-Source
Comparison) render correctly against real seeded data with zero browser console errors. This is
strictly more verification than had, which relied only on `tsc`/`eslint`/`build` with
no live browser pass -- a strengthened discipline worth carrying forward into later work,
not a one-off.
