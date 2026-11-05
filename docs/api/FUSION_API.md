# Intelligence Fusion API

the expanded `/api/v1` surface: evidence, evidence relationships,
conflicts, assessments, and fusion-job orchestration (including the
bounded evidence graph). All routes below sit under `/api/v1` and
require a valid bearer token, same as each layer's routes.
Every route appears in the live OpenAPI docs at `/api/docs` -- nothing
here is hand-maintained separately from the actual route code.

## Evidence: `app/api/routes/evidence.py`

| Method & path | Permission | What it does |
|---|---|---|
| `GET /evidence` | `EVIDENCE_READ` | Paginated list; optional `evidence_type`/`event_id` filters |
| `POST /evidence` | `EVIDENCE_MANAGE` | Create. Server-side reference validation (see `docs/data/EVIDENCE_RELATIONSHIP_MODEL.md`) -- a 400 with a specific `ValueError` message for a missing required reference |
| `GET /evidence/{id}` | `EVIDENCE_READ` | Detail |
| `PATCH /evidence/{id}` | `EVIDENCE_MANAGE` | Only `title`/`summary`/`content` -- `content` is refused (400) on anything but a `report`/`analyst_note` item |

## Relationships: `app/api/routes/relationships.py`

| Method & path | Permission | What it does |
|---|---|---|
| `GET /relationships` | `RELATIONSHIP_READ` | Paginated list; filters: `relationship_type`, `origin`, `review_status`, `ref_type`+`ref_id` (every relationship touching one event/evidence record) |
| `POST /relationships` | `RELATIONSHIP_MANAGE` | Create. Always `origin="analyst_created"` -- never client-supplied. 404 (`InvalidReferenceError`) for a nonexistent source/target; 400 for a self-link or an invalid `relationship_type` |
| `GET /relationships/{id}` | `RELATIONSHIP_READ` | Detail |
| `GET /relationships/{id}/history` | `RELATIONSHIP_READ` | Full review/reverse audit history, oldest first |
| `POST /relationships/{id}/review` | `RELATIONSHIP_MANAGE` | `confirmed`/`rejected`/`uncertain` only -- `"candidate"` is rejected by the schema itself (422) before the service is even called |
| `POST /relationships/{id}/reverse` | `RELATIONSHIP_MANAGE` | Puts a reviewed relationship back to `candidate`; 400 if it was never reviewed |

## Conflicts: `app/api/routes/conflicts.py`

| Method & path | Permission | What it does |
|---|---|---|
| `GET /conflicts` | `CONFLICT_READ` | Paginated list; filters: `review_status`, `event_id` |
| `POST /conflicts/detect` | `CONFLICT_MANAGE` | Standalone conflict-detection entry point, independent of `/fusion/run` -- useful to re-scan existing correlations (e.g. after changing the conflict threshold) without also recomputing correlations. Optional `correlation_batch_id` narrows the scan to one correlation batch; optional `spatial_conflict_threshold_meters` overrides the default for this run only |
| `GET /conflicts/{id}` | `CONFLICT_READ` | Detail, including `conflicting_fields` |
| `POST /conflicts/{id}/resolve` | `CONFLICT_MANAGE` | Sets `review_status` to any of `explained`/`accepted`/`corrected`/`superseded`/`unresolved` -- 400 for any other string |
| `GET /conflicts/{id}/history` | `CONFLICT_READ` | Full resolution audit history, reusing the same `ReviewHistoryEntry` shape as relationships |

## Assessments: `app/api/routes/assessments.py`

| Method & path | Permission | What it does |
|---|---|---|
| `GET /assessments` | `ASSESSMENT_READ` | Paginated list; optional `status` filter (query param is literally named `status`, aliased in the route to avoid shadowing Python's builtin) |
| `POST /assessments` | `ASSESSMENT_MANAGE` | Create -- always starts `version=1`, `status="draft"` |
| `GET /assessments/{id}` | `ASSESSMENT_READ` | Detail |
| `PATCH /assessments/{id}` | `ASSESSMENT_MANAGE` | Partial update. Snapshots the PRE-update state into a new `AssessmentRevision` first, then applies changes and bumps `version`. `status` moves are validated against the allowed-transition graph (400 for an invalid move); unknown field names are rejected (400); `change_note` is accepted but not itself a tracked field -- it's attached to the revision instead |
| `GET /assessments/{id}/revisions` | `ASSESSMENT_READ` | Full version history, ascending |
| `POST /assessments/{id}/evidence` | `ASSESSMENT_MANAGE` | Link an Event or Evidence item as `supporting`/`contradicting`. Idempotent -- a duplicate submission returns the existing link, not a new one |
| `GET /assessments/{id}/evidence` | `ASSESSMENT_READ` | All evidence links for this assessment |

## Fusion: `app/api/routes/fusion.py`

| Method & path | Permission | What it does |
|---|---|---|
| `POST /fusion/run` | `FUSION_RUN` (administrator/analyst only -- NOT investigator, mirroring the own choice to withhold bulk correlation-generation from that role) | The one explicit entry point that composes `correlation_service.recompute()` + `conflict_service.detect_conflicts()` into one `FusionJob`. Optional `time_window_seconds`/`spatial_threshold_meters`/`spatial_conflict_threshold_meters` override the configured defaults for this run only. On an internal exception, the job is marked `failed` with `error_message` set -- the failure itself is still recorded and returned, never swallowed |
| `GET /fusion/jobs` | `FUSION_READ` (every authenticated role) | Paginated job history |
| `GET /fusion/jobs/{id}` | `FUSION_READ` | Detail -- status, parameters, counts, timing, error message if failed |
| `GET /fusion/graph` | `GRAPH_READ` (every authenticated role) | The bounded evidence graph -- see `docs/analytics/EVIDENCE_GRAPH.md` for the full parameter/filter/cap documentation. `seed_type`+`seed_id` required; `max_depth`/`max_nodes` are accepted but ALWAYS clamped server-side to the configured caps, never a raw pass-through; `relationship_type` (repeatable), `review_status`, `source_id`, `since`, `until` all filter which edges/nodes are included. 404 for a nonexistent seed |

## Cross-cutting concerns

- **Pagination**: every list endpoint uses the same `Page[...]`/
  `PageParams` pattern as every earlier work.
- **Organization scoping**: every query in every service
  function filters by `organization_id` from the authenticated token --
  no endpoint above can read or act across organizations.
- **Audit logging**: every mutating endpoint
  (`create`/`update`/`review`/`reverse`/`resolve`/`run`/`link evidence`)
  calls `audit_service.record()` in the SAME transaction as the
  mutation, before `db.commit()`.
- **Permission split**: `*_READ` is granted to every authenticated role
  including viewer; `*_MANAGE`/`FUSION_RUN` is withheld from viewer
  across the board, and `FUSION_RUN` specifically is withheld from
  investigator too (see `app/core/security.py`'s `ROLE_PERMISSIONS`).
- **OpenAPI docs**: `GET /docs`/`GET /openapi.json` reflect every route
  and schema above automatically.

## What this layer does NOT add

No endpoint to delete an Evidence item, EvidenceRelationship, Conflict,
Assessment, or FusionJob -- same retention/deletion-out-of-scope stance
as the data platform. No bulk/batch submission endpoint for relationships or
evidence links -- one call creates one row (idempotently). No
`POST /assessments/{id}/supersede` route -- the underlying
`assessment_service.supersede_assessment()` function exists and is
unit-tested, but is not yet wired to a route (see
`docs/workflows/ASSESSMENT_LIFECYCLE.md`'s "what this does NOT do").
No webhook/callback surface -- `/fusion/run` is pull-only, triggered by
an explicit authorized call, never a background schedule.

## Tests exercising this surface

`backend/tests/test_identifier_and_conflicts.py`,
`test_evidence_and_relationships.py`, `test_assessments.py`, and
`test_fusion_and_graph.py` collectively exercise every route in this
document, including permission gates (403 for a role lacking the
required permission), 404s for nonexistent records/seeds, and the
graph endpoint's server-side clamping. See each file's test names for
the exact scenario covered.
