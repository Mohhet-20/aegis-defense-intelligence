# Phase 15 final report -- Enterprise MLOps, lifecycle, experiment tracking, observability

## 1. Summary of implemented capabilities
* **Registry:** organization-owned, immutable model versions (families are a derived view); validated artifact references; audited lifecycle with evidence-gated approval and separate approver; legacy `status` kept in sync so deprecation blocks new CV inference.
* **Experiments:** synchronous, reproducible runs (dataset/config/run fingerprints, reproducibility metadata), idempotency (200 replay / 409 mismatch), failure recording without disturbing earlier results, stale-run reaper. Detection runs reuse the synthetic-fixture evaluator; classification runs score submitted predictions.
* **Metrics/comparison:** undefined metrics are `null` with reasons; Wilson intervals only for proportions; baseline comparison rejects incompatible runs with 422 reasons; per-metric result, no overall winner; configurable thresholds raise review signals only.
* **Monitoring:** bounded snapshots; separate data drift (PSI), prediction drift, labelled performance, operational (job rows); `not_assessable` instead of fabricated results.
* **Review signals:** deduplicated, escalate-only severity, acknowledge/resolve with audit and same-org assignee check.
* **Observability:** metrics registry with bounded labels, JSON logging + redaction, request/job id context, error classification, public live/ready plus authenticated detailed health.
* **Fix found by testing:** NaN in a request body caused a 500 in the default validation handler; it now returns 422. `GET /mlops/signals` now returns its `counts`.

## 2. Important files
`backend/app/{core/obs_metrics.py,core/logging_config.py,core/errors.py,models/mlops.py,mlops/*,services/mlops_*_service.py,services/observability_service.py,schemas/mlops.py,api/routes/mlops.py,api/routes/observability.py}`, `frontend/src/{api/mlops.ts,types/mlops.ts,components/mlops/*,pages/mlops/*}`, docs listed in the roadmap entry.

## 3. Migrations
`backend/alembic/versions/b15e0ps0001_phase15_mlops.py` (single head, revises `a14c0de5ec01`). Adds model_records columns/indexes (backfills lifecycle_state), unique `(name, version)` index unless legacy duplicates exist (then skipped with a warning), 5 tables. Downgrade drops them.

## 4. API routes
`/api/v1/mlops`: families; models (GET/POST), models/{id}, history, verify-artifact, transition; experiments (GET/POST), history, {id}, {id}/comparison; baselines (GET/PUT); monitoring/snapshots (GET/POST), coverage, snapshots/{id}, {id}/drift; signals (GET), scan, {id}, acknowledge, resolve. `/api/v1/observability`: metrics, metrics/prometheus, summary, health.

## 5. Frontend views
Model registry (`/mlops/models`), Model-version detail, Experiment workspace, Monitoring dashboard, Review queue. Loading, empty and error states; undefined shown as undefined; chart captions state metric, window and units; metadata rendered as plain text (verified with a `<script>` string in a browser).

## 6. Tests executed
* `pytest -q` (full backend suite): **1283 passed**, 0 failed, 136 s (baseline 1152; +131 in `test_mlops_{e2e,registry,experiments,monitoring,signals,observability,security}.py`). No existing assertion was weakened.
* Migration: upgrade → downgrade → upgrade on SQLite with legacy rows (backfill, row preservation, duplicate-skip) -- passing tests.
* End-to-end flow (register → evaluate → baseline → regression → signal → acknowledge → resolve → approve) and failure scenario (artifact lost after registration) -- passing tests.
* Browser smoke: live backend + Vite dev server, headless Chromium, analyst and viewer: all five pages rendered, 0 console/page errors; screenshots reviewed.

## 7. Build and type-check
`tsc -b` clean; `eslint .` 0 errors (2 pre-existing warnings); `vite build` succeeded (one >500 kB chunk warning, pre-existing pattern).

## 8. Known limitations
No serving/activation environment (approval is metadata only); synchronous execution only; classification runs score submitted predictions; detection evaluation synthetic only; legacy platform-level model rows visible to all orgs and not immutable; signal dedup is service-level (concurrent race possible); metrics are per-process; no frontend automated test runner exists (none added); Postgres not tested; snapshot submission has no UI form (API only); Ruff was not run as a gate (no project config; default rule set reports thousands of pre-existing findings).

## 9. Remaining work
Serving/activation if a runtime is introduced; queue + cancellation; Postgres run of the migration; frontend tests; UI for snapshot submission; cross-process metrics aggregation.

## 10. Commands
```
cd backend && pip install -r requirements.txt && alembic upgrade head && python scripts/seed.py
pytest -q
uvicorn app.main:app --port 8000
cd ../frontend && npm ci && npx tsc -b && npx eslint . && npm run build && npm run dev
```

## 11. Roadmap status
Phases 1–15 delivered as bounded slices; Phase 16 (Advanced Analytics and Reporting) next.
