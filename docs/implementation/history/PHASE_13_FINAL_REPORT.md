# Phase 13 Final Report: Scenario Simulation, What-If, Synthetic Data, Sensitivity

All results below were observed in the build sandbox (Python 3.10; library versions differ from the pins in `requirements.txt`).
There is no Git working tree in this environment, so existing changes could not be diffed; existing tests were left unmodified and all still pass.

## 1. Existing components reused

* Auth/RBAC (`Permission`, `ROLE_PERMISSIONS`, `require_permission`), organization scoping, `audit_service`, `workspace_errors`, the global error handler, `paginate`/`Page`.
* `investigation_service.get_accessible` / `user_can_access` (optional investigation context; restricted-investigation visibility).
* The Phase 12 retrieval stack: `retrieval_sources` (doc builder, permission map, `can_view`), index service, BM25 search, citation service and `copilot_service` (extended, not duplicated).
* Frontend primitives (`Card`, `Tabs`, `DataTable`, `Pagination`, `LoadState`, `useLoad`, `Notice`, ...) and the shared `request` client.
* Not reused because it does not exist: any job runner or chart library. Runs are synchronous; charts are inline SVG with tables.

## 2. Files and migration

Migration `alembic/versions/980f1f55cbaa_phase13_scenarios_runs_synthetic_.py`: 3 new tables (`scenarios`, `scenario_runs`, `synthetic_datasets`); no existing table altered. Tested up -> down -> up on SQLite; `alembic check` reports no drift.

Backend, new: `app/simulation/{__init__,params,stats,errors,generator,simulators,analysis,templates}.py`, `app/models/scenario.py`, `app/services/scenario_service.py`, `app/schemas/scenario.py`, `app/api/routes/scenarios.py`, `tests/test_simulation_engine.py`, `tests/test_scenarios_api.py`.
Backend, modified: `app/core/security.py` (3 permissions), `app/core/config.py` (7 limits), `app/models/__init__.py`, `app/main.py` (router), `app/models/retrieval.py` (`scenario` type + `SIMULATED_RECORD_TYPES`), `app/services/retrieval_sources.py`, `retrieval_search_service.py` (default exclusion, investigation scope), `copilot_service.py` (hypothetical-content note), `app/schemas/copilot.py`, `app/api/routes/copilot.py` (type-count limit), `.env.example`.
Frontend, new: `types/scenario.ts`, `api/scenarios.ts`, `components/scenarios/{ScenarioBits.tsx,scenarioUtils.ts,RunPanel.tsx,CompareTab.tsx,SensitivityTab.tsx}`, `pages/ScenariosPage.tsx`, `pages/ScenarioDetailPage.tsx`. Modified: `api/client.ts` (`requestText` for authenticated exports), `App.tsx` (routes), `components/layout/AppShell.tsx` (nav), `types/copilot.ts`, `components/copilot/CopilotBits.tsx` (scenario filter label).
Docs: `docs/architecture/SCENARIO_SIMULATION.md`, `docs/api/SCENARIO_API.md`, `docs/security/SCENARIO_DATA_SEPARATION.md`, this report; updated `../PROJECT_STATUS.md`, `../MASTER_ROADMAP.md`, `README.md`, root `STATUS.md`.

## 3. Simulators actually implemented

1. `threshold_detection` - rolling median/MAD anomaly detector scored against injected spikes (confusion matrix, precision, recall, F1, flagged fraction).
2. `source_availability` - Markov source outages + exponential delay; update completeness, outage statistics, data age and freshness.
3. `duplicate_out_of_order` - naive arrival-order processing vs. duplicate removal + bounded reorder buffer; counts, ordering violations, spurious coincident pairs, events lost to late arrival.

Plus the shared synthetic generator (18 parameters). **Not implemented:** model-evaluation comparison and assessment-parameter simulators, and a stateful sensor-quality degradation/recovery model (the three above cover noise, missing/delayed data, thresholds, availability/freshness and duplicate/out-of-order inputs). Each simulator documents its units, assumptions and limitations; all are deterministic for a seed.

## 4. APIs and UI workflows completed

21 route handlers: discovery (simulators, templates), validate, create (template or simulator), list/get, patch (draft only), ready, duplicate (new version), archive, versions, run history, run, run detail, retry, sensitivity, comparison, export (JSON/Markdown), synthetic dataset generate/list/get. Audit actions for every state change, run, comparison, export and dataset generation.
UI (`/scenarios`, `/scenarios/:id`): builder from templates with typed parameter inputs showing range/default/description, validation, draft save; overview with purpose, parameters, assumptions, limitations, data origin and version history; draft editing; mark ready; run; runs list with filters-by-pagination; run details (timeline from stored fields, versions, seed, hash, config snapshot, errors, retry, metrics, dataset header, preview); comparison dashboard (changed/held-constant parameters, attribution statement, absolute/relative differences, incomparable metrics with reasons, bar chart + table); sensitivity explorer (sweep builder with live plan-size check against the caps, ranked parameters, line charts with accessible tables, past analyses); exports. Loading, empty, error and permission-denied (403/404) states use the shared `LoadState`. The retrieval screen labels the opt-in `scenario` type as simulated.

## 5. Reproducibility and resource controls

Seeded per-purpose `random.Random` streams (platform independent); config snapshot, simulator version, seed, dataset reference/hash and result SHA-256 stored per run; same inputs => identical hash (tested). Nested fault sets keep what-if comparisons about the changed parameter. Idempotency keys (unique constraint + replay), concurrent-run guard, stale-run expiry, retry as a new linked run, failed runs never store results or a summary. Caps: 20,000 generated records, 5,000 stored, 20 s per run / 45 s per sweep, 400 KB result, sweeps <= 4 parameters x 9 values x 20 repetitions and <= 200 runs, 3 alternatives per comparison, per-organization/per-scenario row limits. Runtime values are measured, never invented.

## 6. Tests actually executed

* Backend full suite: **1052 passed, 0 failed** (919 prior + 133 new: 60 in `test_simulation_engine.py`, 73 in `test_scenarios_api.py`), run with `pytest -n 2` and also serially for the new files.
* New tests cover: parameter validation and boundaries; deterministic generation, provenance header, fault injection, size/time guards; simulator correctness (confusion-matrix identities, undefined metrics are `null`, monotonic behaviours, reproducibility, registry rejects unknown/injected ids); statistics edge cases (n = 0/1/<5, quantiles only for n >= 5, no CI keys); comparison attribution (single / multiple / seed / identical / incomparable, zero baseline, missing metrics); sensitivity bounds and invalid sweeps; scenario creation/validation (15 invalid payloads), draft/ready immutability, version lineage, list filters; runs (snapshot, runtime, hash, history, idempotency replay, concurrent guard, stale expiry, failure/retry, unexpected-exception hygiene, oversize result, run cap); datasets (determinism, labelling, truncation, guards, limits); separation from operational tables; RBAC for all four roles; other-organization 404s across 14 endpoints; restricted-investigation visibility; export labelling/headers/format whitelist; path-traversal ids; audit records; retrieval/copilot integration (indexed with `[SIMULATED]`, excluded by default, opt-in, restricted scenarios hidden, assessments untouched).
* The tests found and fixed one real defect: sessions here use `autoflush=False`, so the stale-run expiry was not visible to the following in-progress check; an explicit flush was added.
* Frontend (in a copy at `$HOME/fe_build`): `tsc -b` clean; `eslint` 0 errors (2 pre-existing warnings); `vite build` succeeds.
* **Not run:** any browser/UI interaction test (the screens were never rendered), Postgres, load/performance tests, multi-process concurrency.

## 7. Known limitations

* Only three simulators; no model-evaluation or assessment-parameter what-ifs; no stateful sensor-degradation model.
* Synchronous execution only; no cancellation (so no `cancelled` state), queue or background worker. A request stays open for up to the time budget.
* Limits are logical (record counts, sweep sizes, time checks, result size). There is no OS-level memory/CPU isolation.
* Sensitivity is one-parameter-at-a-time: interactions are not explored. The "exceeds seed variability" flag is a rough heuristic. No confidence intervals are computed by design.
* The synthetic generator models independent faults on a sinusoid + drift + Gaussian noise; real faults are correlated. Metrics describe the model, not any real sensor.
* A simultaneous duplicate idempotency key can yield 409 rather than a replay for one caller.
* No retention/purge for stored runs and datasets; no rate limit on scenario endpoints beyond the caps.
* Scoped (investigation) search includes linked scenarios only when `scenario` is explicitly requested; linking a scenario does not add it to the investigation timeline or evidence (intentional).
* Frontend not browser-tested.

## 8. Recommended Phase 14 (Security and Governance)

Add retention/purge and an archive policy for simulated runs/datasets (and the retrieval index), rate limiting for compute-heavy endpoints on shared storage, a cross-phase authorization/audit review (every route vs. permission matrix, with a test that enumerates routes), a resource-isolation story for simulations (separate worker process with CPU/memory limits) before any heavier simulator is added, and browser-level tests for the copilot and scenario screens.
