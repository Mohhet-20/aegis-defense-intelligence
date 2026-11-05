# Fusion Test Strategy

's required scenario list, mapped to the actual
tests that cover it. Four new test files, 55 new tests, all against a
real FastAPI app via `TestClient` and/or a real (in-memory SQLite)
session -- never a mock of the service layer itself. Combined with
the unchanged 172 tests, the full suite is **227 tests, 90%
line coverage**, all passing currently's final verification
pass.

## File-by-file

| File | Tests | Covers |
|---|---|---|
| `test_identifier_and_conflicts.py` | 12 | `identifier_service.py` (namespaced identifier comparison, allow-listed attributes) + `conflict_service.py` (detection scoped to existing correlations, the four conflict rules, idempotency, resolution workflow) |
| `test_evidence_and_relationships.py` | 16 | `evidence_service.py` (reference validation for all evidence types, free-text-only editability) + `relationship_service.py` (creation, validation, idempotency, the confirm/reject/uncertain/reverse workflow, API-level permissions) |
| `test_assessments.py` | 12 | `assessment_service.py` (creation defaults, confidence validation, the full status-transition graph, version/revision snapshotting, evidence traceability, API-level permissions) |
| `test_fusion_and_graph.py` | 15 | `fusion_service.py` (job orchestration, failure handling via parameters), the per-event-type temporal window override, `graph_service.py` (bounded BFS, all node/edge types, depth/node caps, filters), API-level permission and clamping checks |

## Section 17's scenario checklist

Reproduced here with the exact test that satisfies each one, so this
document can be checked against the design directly rather than taken on
faith:

**Identifier/attribute comparison**: matching source-local IDs
(`test_matching_source_local_identifiers_within_the_same_source`); the
same local ID in different namespaces never compared
(`test_same_local_id_in_different_namespaces_is_never_compared`);
missing identifiers (`test_missing_identifier_on_either_side_is_unknown_not_a_conflict`);
conflicting attributes (`test_conflicting_attribute_value_is_flagged`);
undocumented keys never diffed (`test_only_documented_identifier_keys_are_compared`).

**Conflict detection**: requires an existing correlation
(`test_conflict_detection_requires_an_existing_correlation`); an actual
contradictory value produces a real conflict
(`test_full_conflict_detection_and_resolution_workflow`); missing
values are never a conflict
(`test_no_coordinates_on_either_side_is_never_a_spatial_conflict`,
`test_missing_identifier_on_either_side_is_unknown_not_a_conflict`);
a legitimate difference can be accepted rather than left unresolved
forever (the same full-workflow test's `resolve(..., "accepted")`
step); resolution + audit history
(`test_full_conflict_detection_and_resolution_workflow`'s history
assertions, `test_invalid_resolution_status_is_rejected`).

**Evidence relationships**: valid creation
(`test_valid_relationship_creation_between_two_events`); invalid
references (`test_relationship_to_a_nonexistent_record_is_rejected`);
self-link behavior (`test_self_link_is_rejected`); duplicate submission
(`test_duplicate_relationship_submission_is_idempotent`); relationship
provenance (`test_rule_based_relationship_requires_no_human_author`,
`test_analyst_created_relationship_without_an_author_is_rejected`);
analyst review permissions
(`test_viewer_cannot_create_a_relationship_but_can_read_one`);
reversal/supersession (`test_review_confirm_reject_and_reverse_workflow`).

**Assessments**: evidence traceability
(`test_evidence_traceability_supporting_and_contradicting`);
supporting/contradicting evidence (same test); missing information
(`test_information_gaps_and_assumptions_are_stored_as_stated`);
unauthorized updates (`test_viewer_cannot_update_an_assessment`);
version history (`test_version_history_is_visible_through_the_api`,
`test_every_update_bumps_version_and_writes_a_revision_snapshot`).

**Evidence graph**: empty graph
(`test_graph_for_an_isolated_event_is_just_the_seed`); bounded
traversal (`test_graph_depth_limit_stops_traversal`,
`test_graph_node_cap_truncates_and_reports_it`); filters
(`test_graph_review_status_filter`); authorization (`GRAPH_READ`
required on every graph route, confirmed implicitly by every
API-level graph test using an authenticated role); maximum
depth/result limits (`test_graph_max_depth_is_clamped_server_side`).

## What makes these integration-level, not unit mocks

Every `client`-fixture test drives the REAL FastAPI app
(`app/main.py`) through `TestClient`, hitting real route handlers,
real permission checks (`require_permission()`), and a real (SQLite,
in-memory, isolated per test) database session via the `db` fixture's
`get_db` override -- including real multipart file uploads for the
ingestion-dependent graph test
(`test_graph_max_depth_is_clamped_server_side`). The `db`-fixture-only
tests construct model rows directly and call service functions
directly, which is appropriate for service-level logic (e.g.
`identifier_service`'s pure comparison functions) that doesn't need an
HTTP round-trip to be meaningfully tested.

## Honesty check: the one real gap found and fixed

`settings.FUSION_TIME_WINDOW_SECONDS_BY_TYPE` was added to
`config.py` with a parsing property but was NOT consumed by any service
until this was caught during its own verification pass --
exactly the "file exists but isn't wired in" trap Section 19 warns
against. It was fixed (see `docs/analytics/TEMPORAL_CORRELATION.md`)
and the fix is covered by a dedicated test,
`test_per_event_type_time_window_override_is_actually_consumed`, which
would fail if the wiring were removed (it asserts a concrete count
difference -- 0 correlations without the override, 1 with it -- not
just "no error was raised").

## What this does NOT do

No load/performance testing of the fusion pipeline at scale (Section
13's performance safeguards -- `FUSION_MAX_EVENTS_PER_RUN`,
`FUSION_GRAPH_MAX_NODES`/`MAX_DEPTH` -- are implemented and unit-tested
for correctness of the CAP itself, but no test here measures actual
wall-clock performance against a large synthetic dataset).
No browser-driven end-to-end test of the new frontend fusion workspace
pages -- `npx tsc -b --force`, `npx eslint .`, and `npm run build` all
pass clean, confirming
the pages compile and build correctly against the real API client
types, but no Playwright/Selenium smoke test was run against a live
server + browser for these specific pages in this pass.
