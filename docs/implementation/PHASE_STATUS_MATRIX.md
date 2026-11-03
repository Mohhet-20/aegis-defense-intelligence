# Phase status matrix (Phase 18)

"Verified" below means exercised by automated tests that were run (SQLite for the whole suite; the integration subset and migrations also on PostgreSQL 16; see `history/PHASE_18_FINAL_REPORT.md` for counts). All phases were delivered as **bounded slices**; none is a production-hardened product on its own, and none was verified against real hardware, real model weights, or a multi-node deployment.

| # | Phase | Implemented | Verified by | Known limits / remaining | Depends on |
|---|---|---|---|---|---|
| 1 | Enterprise foundation | FastAPI app, SQLAlchemy/Alembic, JWT auth, RBAC, React shell | auth/RBAC/users tests; workflow A; 401/403 sweeps over all 319 operations | no MFA/SSO; tokens kept in browser `localStorage` | – |
| 2 | Intelligence data platform | sources, file ingestion (JSON/CSV), validation, dedup, provenance | ingestion tests; workflow B; smoke test | ingestion is synchronous; file connectors only | 1 |
| 3 | Multisource fusion | evidence, relationships, correlation, conflicts, graph | module tests; workflow C (evidence+relationship review, fusion run) | conflict detection/correlation recompute not in a cross-module workflow | 2 |
| 4 | Computer vision infrastructure | private media, adapters (mock, OpenCV HOG), inference jobs, detections | CV tests; workflow D; media-security tests; byte-identical round trip in smoke test | no real model weights shipped; no GPU path | 1,2 |
| 5 | Tracking | tracker, tracks, annotations, evaluation | tracking tests + sweeps | no Phase-17/18 workflow | 4 |
| 6 | Sensor analytics | sensors, observation ingestion, health/anomaly | sensor tests + sweeps; PostgreSQL JSON-filter defect found and fixed in Phase 18 | – | 2 |
| 7 | Geospatial | geo queries, timeline, relationships, export | geo tests + sweeps | k-suppression only (risk 27) | 2,6 |
| 8 | Edge / offline | device auth, sync protocol, conflicts | edge tests; workflow H (simulated device) | no real devices | 1 |
| 9 | Fleet | device inventory, health, alerts | fleet tests + sweeps | – | 8 |
| 10 | Explainable AI / risk | assessments, evaluation, decision support | module tests + sweeps | advisory only by design | 3 |
| 11 | Investigations | cases, notes, evidence, timeline, export | module tests; workflow E | – | 3 |
| 12 | Copilot / retrieval | offline retrieval, citations, optional provider | copilot tests + sweeps | external provider path untested against a live provider | 11 |
| 13 | Scenarios | synthetic scenarios, runs, sensitivity | scenario tests + sweeps | – | 1 |
| 14 | Security & governance | headers, size limits, lifecycle, audit controls | security tests; sweeps; production startup refusal tests | audit not tamper-proof | all |
| 15 | MLOps & observability | registry, experiments, monitoring, logs, metrics | MLOps tests; workflow F | metrics per-process; approval not deployment gating | 4 |
| 16 | Analytics & reporting | metric catalog, dashboards, reports | analytics/report tests; workflows F,G; browser E2E 21/21 | no PDF/scheduling | 2,15 |
| 17 | Full system integration | sweeps, contract test, workflows A–H, integrity, CI | 35 added tests | see `history/PHASE_17_FINAL_REPORT.md` | all |
| 18 | Production readiness | production compose/Docker files, bootstrap admin, backup/restore tool, smoke test, runbooks, CI PostgreSQL+container jobs, error boundary, session-expiry handling | see below | containers **not built**; CI **not run on GitHub**; no HA | all |

Phase 18 evidence: restore round-trip tests (SQLite, automated; PostgreSQL, manual); production-mode smoke test 23/23 on PostgreSQL 16 including graceful SIGTERM and restart; migrations from empty on PostgreSQL 16 with downgrade/upgrade and schema-drift comparison; full suite on PostgreSQL (see final report); browser checks for the error boundary and session expiry (8/8).
Blockers to claiming more: no container runtime registry access (Docker Hub blocked) and no GitHub Actions execution in the authoring environment.

## Final stabilization pass (2026-10-18, Windows 11)
Every phase above was re-exercised on the final code: the full backend suite (1384 passed, 0 failed, 0 skipped; 94% line coverage (406 s)), a browser
walk of all 76 routes for each of the four roles and at 390 px, the reporting (21/21) and session
(8/8) browser journeys, an 11-step public-API demo touching phases 2-4, 5, 8, 11, 13, 15 and 16,
and production-mode smoke 23/23. Status per subsystem, using verified / partially verified /
mock-simulated / unverified / not implemented, is in `PROJECT_STATUS.md` ("Current state"). Changes
to the table above: phase 18's container and CI rows remain **unverified**; phase 1's React
Router advisories are fixed; phase 15's `model_records` drift is resolved.

## Consolidation pass (2026-10-18)
All phases re-verified on SQLite **and PostgreSQL 16** with the full suite (1386 passed, 0 failed, 0 skipped (38 min 43 s; server TimeZone Asia/Calcutta) on PostgreSQL).
Changes to the table: phase 16's analytics had a PostgreSQL time-zone defect (fixed, KNOWN_RISKS 54);
phase 3/11 fixtures are now valid under foreign-key enforcement; phase 14 gains a browser-verified CSP;
phase 18's PostgreSQL deployment, backup/restore and production smoke are verified locally, while
containers and CI remain unverified.

## Release candidate 2 (2026-10-19)
Phase 4 (computer vision) now includes a real pretrained detector evaluated on real photographs
(previously mock + classical HOG only). Phase 1/14 sessions moved to an HttpOnly cookie; phase 16
analytics and every timestamp are UTC-correct on SQLite and PostgreSQL; phase 7 discloses truncation.
Evidence: full suite on SQLite and PostgreSQL 16, browser walks for all roles under the CSP
(`RELEASE_VERIFICATION.md`). Phase 18's containers and CI remain unverified.
