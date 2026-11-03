# Phase 16 plan (written after repository discovery)

**Baseline:** backend 1283 tests passing; frontend `tsc -b`, eslint (0 errors) and `vite build` clean; migration head `b15e0ps0001`.

**Reused:** `Event`/`Observation`/`IngestionJob`/`RawRecord`/`FusionJob`/correlation, relationship, conflict, evidence, investigation, anomaly, assessment, inference, MLOps (`evaluation_status`, signals) models; `investigation_service.user_can_access` rules (restricted investigations) and `evidence_registry_service.evidence_visible`; the CSV formula-injection guard used by `export_service`/`geo_export_service`; `audit_service`; the `Permission`/RBAC table; Phase 15 observability registry; `CV_MEDIA_STORAGE_ROOT` as the private storage base; the frontend `Primitives`, `DataTable` and SVG chart pattern.

**Extended:** permissions (`reporting:read`, `report:generate`), config, main.py, AppShell/App routes.

**Genuinely missing (built):** shared metric catalog and window/filter semantics; per-domain analytics sections; executive/analyst/operations dashboards; report templates, generator, artifact storage with retention; deterministic summaries; report history/retrieval API; one new table (`report_runs`).

**Not built (and why):** PDF (no PDF dependency in `requirements.txt`; HTML is print-ready); LLM summaries (deterministic only; no mandatory provider); saved filter presets and report definitions table (not required for the smallest coherent workflow); queue depth (no queue exists); uptime percentages (no uptime telemetry exists); asynchronous generation (synchronous and bounded; no queue).

**Order:** foundation (window/definitions) → sections → API → report builder/export → tests → frontend → docs/verification.
