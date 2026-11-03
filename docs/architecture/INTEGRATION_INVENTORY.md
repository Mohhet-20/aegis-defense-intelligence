# AEGIS integration inventory (Phase 17)

Status vocabulary: **verified** = exercised end to end by an executed test in this repository (see "Evidence"); **partially verified** = covered by module tests and the cross-cutting sweeps but not by a cross-module workflow; **unverified**; **blocked**; **not implemented**. A module is never "verified" because its files exist. "Verified" here means on SQLite, with synthetic fixtures and mock adapters; PostgreSQL, real model weights and real devices are not covered anywhere.

Cross-cutting evidence that applies to every module (all in `backend/tests/`):
- `test_integration_sweeps.py` — over every one of the 319 OpenAPI operations: unauthenticated → 401 (except the reviewed public allowlist); no 5xx for four roles on empty/dummy input; viewers cannot mutate (reviewed allowlist); a foreign-organization administrator cannot succeed against guessed ids; device routes reject missing/wrong/human credentials.
- `test_frontend_contract.py` — every frontend `request()/fetch()` call matches a backend path+method; every navigation target has a route.
- `test_integration_integrity.py` — no dangling foreign keys and no cross-tenant references (derived from ORM metadata) after populating eight modules through the API; audit rows reference real orgs/users; org B sees none of org A's rows in 11 list endpoints.
- `test_integration_errors.py`, `test_integration_jobs.py`, `test_integration_migrations.py` — error sanitization, job-status truthfulness, migration/ORM parity.

| Module | Main routes | Workflow evidence | Status | Notes / limits |
|---|---|---|---|---|
| Auth, RBAC, sessions | `/auth`, `/users` | A | verified | JWT; refresh revocation tested. No MFA / SSO (not implemented). |
| Tenancy | all org-scoped routes | sweeps + integrity | verified | Foreign/missing records return 404. SQLite has no row-level security. |
| Sources, events, observations | `/sources`, `/events`, `/observations` | B | verified | |
| Ingestion (file) | `/ingestion` | B | verified | Synchronous; malformed file → recorded failed job (201), never "completed". |
| Evidence, relationships | `/evidence`, `/relationships` | C | verified | Uncertain vs contradicting stay distinct; review audited. |
| Fusion, correlation, conflicts, graph | `/fusion`, `/correlation`, `/conflicts` | C (fusion run only) | partially verified | `correlation/recompute` and `conflicts/detect` are covered by module tests, not by a cross-module workflow. |
| Media, CV inference, detections | `/media`, `/inference`, `/detections`, `/cv-models` | D | verified (mock adapter) | Real detector weights are not part of the repo; HOG adapter has module tests only. |
| Tracking | `/tracking`, `/track-annotations` | sweeps only | partially verified | Module tests (tracking security/evaluation) pass; no Phase 17 workflow. |
| Investigations, workspace, export | `/investigations` | E | verified | |
| MLOps registry, experiments, monitoring | `/mlops` | F | verified (synthetic data) | Approval is not deployment gating (KNOWN_RISKS 19). |
| Analytics, dashboards, reports | `/reporting` | F, G | verified | Report numbers equal the analytics section for the same window; tamper → 409 + audit. Browser run from Phase 16 was re-checked (see final report). |
| Edge devices, sync, presence, conflicts | `/devices`, `/edge/*` | H | verified (simulated device) | No real hardware. |
| Fleet, sites, sensors, sensor ingestion, sensor/geo analytics | `/fleet*`, `/sensors*`, `/geo*` | sweeps only | partially verified | Module tests only. |
| Scenarios, evaluation, model outputs | `/scenarios`, `/evaluation` | sweeps only | partially verified | Scenario data separation has dedicated tests. |
| Copilot | `/copilot` | sweeps only | partially verified | Uses a deterministic offline retrieval path; no external LLM. |
| Assessments / risk | `/assessments`, `/risk-assessments` | sweeps only | partially verified | |
| Lifecycle / retention, security admin, observability, audit | `/lifecycle`, `/security`, `/observability`, `/audit` | A (audit read) + sweeps | partially verified | Audit is append-only by convention, **not tamper-proof**. |
| Frontend | `frontend/src` | contract test; `tsc -b`, `eslint`, `vite build` | partially verified | No frontend unit/component test runner exists (not implemented). Browser E2E exists only for the Phase 16 pages. |
| CI | `.github/workflows/ci.yml` | static validation only | unverified on GitHub | Never executed on GitHub Actions; each command was run locally. |

## Conventions confirmed by the sweeps
- Errors: `{"detail": <string | [{type, loc, msg}]>, "request_id": ...}`; 401 unauthenticated, 403 lacking permission, 404 foreign or missing record, 409 state conflict, 422 validation (values are **never** echoed).
- Services flush; routes commit; audit writes are flush-only inside the same transaction.
- Device routes use `X-Device-Id` / `X-Device-Api-Key`; missing credentials are 401 (they used to be 422).
