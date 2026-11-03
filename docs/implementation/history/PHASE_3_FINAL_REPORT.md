# Phase 3 -- Definition of Done &amp; Final Engineering Report

This is the one-time completion record for Phase 3 (Phase 3: Advanced
Multi-Source Intelligence Fusion, Evidence Relationships, Temporal
Correlation, Conflict Detection and Explainable Assessments). For the
living, continuously-updated status, see
[`../PROJECT_STATUS.md`](../PROJECT_STATUS.md) instead -- this file is a
snapshot of what was true at the end of this phase.

## Definition of Done -- checklist (28 items)

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Existing repo inspected before writing code | Done | Phase 1/2's 14 modules read via `MODULE_CATALOG.md`; `Event`/`EventCorrelation`/`Investigation`/`correlation_service.py` identified as reuse targets before any new model was written |
| 2 | No duplication of existing entities | Done | `Event`/`EventCorrelation` untouched in shape; `correlation_service.py` extended (one new optional parameter), never replaced; `docs/architecture/INTELLIGENCE_FUSION_ARCHITECTURE.md`'s reuse table |
| 3 | Evidence as a reference layer, not media storage | Done | `app/models/evidence.py` -- 7 evidence types, DB CHECK constraint + service-level validation, never fetches a referenced URI |
| 4 | Evidence relationship model distinct from EventCorrelation | Done | `app/models/evidence_relationship.py`, directional, multi-entity-type, `candidate/confirmed/rejected/uncertain` + non-destructive `reverse`; `docs/data/EVIDENCE_RELATIONSHIP_MODEL.md` |
| 5 | Namespace-aware identifier/attribute comparison | Done | `app/services/identifier_service.py` -- never compares a local id across sources, allow-listed attribute keys only |
| 6 | Temporal correlation, including configurable per-type windows | Done | `correlation_service.recompute(time_window_seconds_by_type=...)`, wired and tested (`docs/analytics/TEMPORAL_CORRELATION.md`) |
| 7 | Spatial correlation with a separate, larger conflict threshold | Done | `FUSION_SPATIAL_THRESHOLD_METERS_DEFAULT` (500m) vs. `FUSION_SPATIAL_CONFLICT_THRESHOLD_METERS` (5000m); `docs/analytics/SPATIAL_CORRELATION.md` |
| 8 | Conflict detection scoped to existing correlations only, never an all-pairs scan | Done | `conflict_service.detect_conflicts()`, proven by `test_conflict_detection_requires_an_existing_correlation` |
| 9 | Missing information never treated as a conflict | Done | Every conflict rule requires both sides to actually report the field; `test_no_coordinates_on_either_side_is_never_a_spatial_conflict` |
| 10 | Conflict resolution workflow, auditable, never rewrites history | Done | `conflict_service.resolve_conflict()`, `docs/analytics/CONFLICT_DETECTION.md`, `docs/workflows/ANALYST_REVIEW_WORKFLOW.md` |
| 11 | Analyst review workflow for relationships: confirm/reject/uncertain/reverse | Done | `relationship_service.review_relationship()`/`reverse_relationship()`, fully audited via the existing `AuditRecord` table |
| 12 | Five/eight evidentiary concepts kept strictly separate (never collapsed into one score) | Done | `docs/analytics/CONFIDENCE_AND_SOURCE_RELIABILITY.md`'s 8-concept table |
| 13 | Qualitative-only analytical confidence, never a fabricated probability | Done | `Assessment.confidence_level` restricted to `low/moderate/high`; no code path computes it |
| 14 | Bounded, versioned, explainable Assessment entity | Done | `app/models/assessment.py` (3 tables); pre-update snapshot versioning, `docs/workflows/ASSESSMENT_LIFECYCLE.md` |
| 15 | Assessment evidence traceability (supporting/contradicting) | Done | `AssessmentEvidenceLink`, idempotent linking, nonexistent-reference rejection |
| 16 | Assessment status lifecycle with an enforced transition graph | Done | `ALLOWED_STATUS_TRANSITIONS`, tested for both allowed and refused moves |
| 17 | One explicit, authorized fusion-run entry point, never a background job | Done | `fusion_service.run_fusion_job()` -&gt; `POST /fusion/run`, `FusionJob` row per run, failure captured not swallowed |
| 18 | Bounded evidence graph, caps enforced server-side regardless of client request | Done | `graph_service.build_graph()`, `min()`-clamped caps, `test_graph_max_depth_is_clamped_server_side` |
| 19 | Evidence graph: node/edge types, explainability, filters | Done | 3 node types, 4 edge types, every edge self-explains; `relationship_type`/`review_status`/`source_id`/`since`/`until` filters |
| 20 | Expanded `/api/v1` surface for all of the above | Done | `docs/api/FUSION_API.md` cites every route by file and permission |
| 21 | Permission model extended, least-privilege per role | Done | 11 new `Permission` values; `FUSION_RUN` withheld from investigator/viewer, `*_MANAGE` withheld from viewer across the board |
| 22 | DB migration preserves existing data (no destructive change) | Done | upgrade/downgrade/re-upgrade cycle run against the real dev DB; 1 source, 5 events, 1 investigation, 4 users intact throughout (Section 6 below) |
| 23 | Frontend analyst workspace (observation explorer extension, relationship workspace, conflict review center, evidence graph, assessment workspace, fusion overview) | Done | 7 new pages + `EventDetailPage.tsx`/`DashboardPage.tsx` extended, wired into `App.tsx`/`AppShell.tsx` |
| 24 | Evidence graph rendered without a new frontend dependency, with an accessible non-SVG fallback | Done | `EvidenceGraphPage.tsx` -- hand-built SVG + an always-rendered HTML table of the same data |
| 25 | Automated backend tests, actually run | Done | 227 passed (55 new across 4 files), 90% line coverage -- re-run in this final pass |
| 26 | Frontend checks, actually run | Done | `tsc -b --force` clean, `eslint .` 0 new warnings/errors, `npm run build` succeeded -- re-run in this final pass |
| 27 | Documentation updated to match reality, "what this does NOT do" stated explicitly | Done | 11 new docs + `../MASTER_ROADMAP.md`/`EVENT_CORRELATION.md`/this file updated, each with an explicit scope-boundary section |
| 28 | Resume-safety: progress synced externally after this report | Done (final sync step follows this report) | zip -&gt; `SendUserFile` -&gt; device bridge to the owner's local folder, per standing instruction |

## Final Engineering Report (12 points)

**1. Repository state before this phase's changes.** The real Phase
1+2 deliverable, unmodified at the start of this session: a 20-model
backend (13 from Phase 1, 7 added in Phase 2 across `RawRecord`/
`EventCorrelation`/connector config), 172 passing backend tests at 93%
coverage, a 17-page frontend, and accurate `../PROJECT_STATUS.md`/
`MODULE_CATALOG.md` handoff records. Nothing was missing or had to be
reconstructed -- Phase 2's sync-to-local-folder pipeline had done its
job.

**2. Architecture and data models reused vs. newly introduced.** Reused
unchanged: `Event`, `Investigation` (extended with 3 new columns),
`AuditRecord`/`audit_service.py` (one new read helper added). Reused
with one small, additive extension: `EventCorrelation`/
`correlation_service.py` (one new optional parameter,
`time_window_seconds_by_type`; Phase 2's own `test_correlation.py`
suite, unmodified, still passes in full, confirming the extension is
behaviorally invisible when unconfigured). Newly introduced: `Evidence`,
`EvidenceRelationship`, `Conflict`, `Assessment`/
`AssessmentEvidenceLink`/`AssessmentRevision`, `FusionJob` -- see
`docs/architecture/INTELLIGENCE_FUSION_ARCHITECTURE.md` for why each one
earns its own table rather than overloading an existing one.

**3. Files created or changed.** Backend, new: 5 models
(`evidence.py`, `evidence_relationship.py`, `conflict.py`,
`assessment.py`, `fusion_job.py`), 7 services (`identifier_service.py`,
`evidence_service.py`, `relationship_service.py`, `conflict_service.py`,
`assessment_service.py`, `fusion_service.py`, `graph_service.py`), 5
schema modules, 5 route modules, 1 Alembic migration, 4 new test files
(55 new tests). Backend, modified: `config.py` (8 new `FUSION_*`
settings), `security.py` (11 new permissions), `main.py` (5 new
routers), `models/__init__.py`, `models/investigation.py`,
`schemas/investigation.py`, `services/audit_service.py`,
`services/correlation_service.py` (the per-type window wiring).
Frontend, new: `FusionPage.tsx`, `EvidencePage.tsx`,
`RelationshipsPage.tsx`, `ConflictsPage.tsx`, `EvidenceGraphPage.tsx`,
`AssessmentsPage.tsx`, `AssessmentDetailPage.tsx`. Frontend, modified:
`types/api.ts`, `api/client.ts`, `App.tsx`, `AppShell.tsx`,
`EventDetailPage.tsx`, `DashboardPage.tsx`. Docs, new: 11 files across
`architecture/`, `data/`, `analytics/` (4), `workflows/` (2), `api/`,
`testing/`. Docs, modified: `../MASTER_ROADMAP.md`,
`analytics/EVENT_CORRELATION.md`, this file.

**4. Migrations.** One new Alembic migration,
`c6c29182203f_phase3_fusion_evidence_relationships_....py`
(autogenerated, hand-edited for a `server_default='[]'` on
`investigations.collaborator_user_ids` so existing rows backfill
correctly). Verified against the real dev `aegis.db` (not a throwaway
copy) in this session: backed up (`aegis.db.bak_prompt3`), ran
`alembic upgrade head`, confirmed the pre-existing 1 organization, 4
users, 1 source, 3 assets, 3 sensors, 5 events, 3 observations, 1 model
record, 2 risk assessments, 1 investigation all survived with correctly
backfilled defaults, ran `alembic downgrade -1` and confirmed the data
was still intact and the new tables/columns were gone, ran `alembic
upgrade head` again and confirmed `head` was reached cleanly. Backup
deleted after verification. Re-confirmed in this final pass: `alembic
current`/`alembic heads` both report `c6c29182203f (head)`, and a direct
row-count query against every table (seed data plus the five new, still
empty, Phase 3 tables) matches exactly what's expected.

**5. APIs implemented.** 20 new routes across 5 routers (`/evidence`,
`/relationships`, `/conflicts`, `/assessments`, `/fusion`) -- full table
in `docs/api/FUSION_API.md`. Every route requires authentication;
`*_READ` is available to every role including viewer, `*_MANAGE` is
withheld from viewer, and `FUSION_RUN` specifically is withheld from
investigator too (mirroring Phase 2's own choice to withhold bulk
correlation-generation from that role).

**6. Frontend pages/workflows implemented.** A Fusion overview page
(live counts: candidate relationships, unresolved conflicts, in-review
assessments, evidence items; recent job history; a "run fusion" action
for analyst/admin). An Evidence library (list + create across all 7
evidence types). A Relationship workspace (filterable queue, draw-a-
relationship form, confirm/reject/uncertain/reverse actions, inline
review history). A Conflict review center (filterable queue,
field-by-field conflicting-value display, a standalone "detect
conflicts" action, resolution actions with a note field, inline
resolution history). An Evidence graph explorer (seed-driven bounded
SVG visualization with a type/status color key, plus an always-visible
accessible data table of the same nodes/edges -- no new npm dependency
added). An Assessment workspace (list/filter/create) and detail page
(inline editing of summary/assumptions/gaps/confidence, status
transition buttons, supporting/contradicting evidence lists with a
link-evidence form, full version history with pre-update snapshots).
`EventDetailPage.tsx` extended with the evidence and relationships
touching that event, plus a direct link into the graph explorer seeded
at that event. All of it calls the real backend -- `npx tsc -b --force`
and a production `npm run build` both succeeded against the actual
extended `api/client.ts`, confirming the types and the real endpoints
agree.

**7. Correlation and conflict rules implemented.** Temporal: unchanged
30-minute default window, now overridable per `event_type` (see point
2). Spatial: unchanged 500m match threshold; a new, separately
configured, intentionally-10x-larger 5000m conflict threshold so "too
far to confirm a match" and "far enough to actively disagree" are never
the same line. Identifier/attribute: namespace-aware (never compares a
local id across two different sources), allow-listed attribute keys
only (`FUSION_IDENTIFIER_ATTRIBUTE_KEYS`, default includes
serial_number/tail_number/call_sign/imei/vehicle_id/device_id). Four
conflict rules (`incompatible_event_type`, `conflicting_severity`,
`location`, `conflicting_attribute_value`), every one requiring BOTH
sides to actually report the field being compared.

**8. Security and governance behavior.** 11 new `Permission` values,
each route gated by `require_permission()` exactly as every prior
phase's routes are. Every mutating action (create/update/review/
reverse/resolve/run/link) writes to the SAME `AuditRecord` table in the
same transaction as the change it describes. Organization scoping is
enforced in every single new service query -- no cross-organization
read or write exists anywhere in this phase's code. No new
authentication mechanism, no change to how tokens are issued or
validated.

**9. Tests actually run, and their results.** `./.venv/bin/python3 -m
pytest -q --cov=app --cov-report=term-missing` from `backend/`: **227
passed, 0 failed, 90% line coverage** (172 carried over from Phase
1+2, unchanged and still passing, plus 55 new this phase across
`test_identifier_and_conflicts.py` (12), `test_evidence_and_relationships.py`
(16), `test_assessments.py` (12), `test_fusion_and_graph.py` (15)).
Frontend: `npx tsc -b --force` clean; `npx eslint .` -&gt; 0 errors, 1
pre-existing warning (`AuthContext.tsx`, unmodified since the Phase 1
baseline, not a regression); `npm run build` -&gt; succeeded (347.51 kB
JS / 100.25 kB gzip, 15.58 kB CSS / 3.68 kB gzip). See
`docs/testing/FUSION_TEST_STRATEGY.md` for the full scenario-by-scenario
mapping against Section 17's required checklist.

**10. Known failures / remaining limitations.** No load/performance
testing of the fusion pipeline at actual scale -- the caps
(`FUSION_MAX_EVENTS_PER_RUN=2000`, `FUSION_GRAPH_MAX_NODES=150`,
`FUSION_GRAPH_MAX_DEPTH=3`) are implemented and unit-tested for
correctness of the cap itself, not benchmarked against a large
synthetic dataset. No browser-driven end-to-end (Playwright/Selenium)
smoke test was run against a live server + browser for the 7 new
frontend pages in this pass -- they are verified by `tsc`/`eslint`/
`build` succeeding against the real API client types, which is real
evidence the code is correct and wired up, but is not the same as a
clicked-through UI smoke test. The environment quirk carried over from
Phase 2 (the `.venv`'s console-script shebangs pointing at a stale
path) is unchanged and was worked around the same way
(`./.venv/bin/python3 -m <tool>`).

**11. Features explicitly not implemented (deliberately, and
documented as such rather than silently dropped).** No ML-assisted or
probabilistic relationship/conflict detection (`model_assisted` is a
reserved, validated, unused enum value). No automated source-
reliability scoring from fusion outcomes. No `POST
/assessments/{id}/supersede` route (the service function exists and is
tested; the endpoint is not wired). No graph-rendering library or
force-directed layout (a deliberate choice, not an oversight -- see
`docs/analytics/EVIDENCE_GRAPH.md`). No bulk/batch submission endpoint
for relationships or evidence links. No deletion endpoint for any
Phase 3 entity.

**12. Exact next steps for Phase 4.** (a) Read this file, `docs/
architecture/INTELLIGENCE_FUSION_ARCHITECTURE.md`, and `docs/
implementation/MASTER_ROADMAP.md`'s Phase 4 row before writing any
code -- Phase 4 is Computer Vision Infrastructure, which has no
dependency on this phase's fusion tables beyond potentially producing
new `Evidence` rows of type `media_reference`/`document` once real
media processing exists. (b) Do not re-implement or duplicate `Event`,
`EventCorrelation`, `Evidence`, `EvidenceRelationship`, `Conflict`,
`Assessment`, or `FusionJob` -- extend them, following this phase's
own "do not duplicate existing entities" discipline. (c) If a future
phase needs ML-assisted relationship scoring, `RELATIONSHIP_ORIGINS`
already reserves `model_assisted` for exactly that -- wire it rather
than inventing a parallel field. (d) Wire `POST
/assessments/{id}/supersede` as an actual route when a phase's scope
calls for exposing it (the service function is ready). (e) Rebuild
`backend/.venv` properly before relying on bare `pytest`/`alembic`
commands, same carried-over note as Phase 2's report. (f) This file
must be updated again at the end of Phase 4, in place, following the
same "only claim what was actually run" discipline.
