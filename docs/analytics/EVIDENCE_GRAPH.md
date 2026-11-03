# Evidence Graph

Phase 3, Section 10. Implemented in `app/services/graph_service.py`
(backend), `GET /api/v1/fusion/graph` (`app/api/routes/fusion.py`), and
`frontend/src/pages/EvidenceGraphPage.tsx` (an SVG rendering + an
always-present accessible table, never SVG-only).

## The one hard requirement: always bounded

Section 10 explicitly warns against "unbounded graph queries" and
"loading the entire dataset into the browser." Two independent caps
enforce this, applied server-side regardless of what the client
requests:

- `settings.FUSION_GRAPH_MAX_DEPTH` (default 3)
- `settings.FUSION_GRAPH_MAX_NODES` (default 150)

`graph_service.build_graph()`:

```python
depth_cap = min(max_depth, settings.FUSION_GRAPH_MAX_DEPTH) if max_depth is not None else settings.FUSION_GRAPH_MAX_DEPTH
node_cap = min(max_nodes, settings.FUSION_GRAPH_MAX_NODES) if max_nodes is not None else settings.FUSION_GRAPH_MAX_NODES
```

A client can only ever ask for a SMALLER graph than the server default,
never a larger one -- `min()`, never a raw pass-through. The route's
own query-parameter bounds (`ge=1`, no upper `le`) exist only to reject
nonsensical negative/zero values early; they are deliberately NOT the
real cap (an earlier version of this route used `le=10`/`le=1000`,
which caused the API to REJECT an over-large request with a 422 instead
of CLAMPING it -- the wrong behavior for a "bounded no matter what the
client asks" guarantee. Fixed before this phase's final report; see
`backend/tests/test_fusion_and_graph.py::
test_graph_max_depth_is_clamped_server_side`, which asserts a request
for `max_depth=999&max_nodes=999999` comes back `200` with the response
body's own `max_depth`/`max_nodes` equal to the configured caps, not
the requested numbers).

When the node cap is hit mid-traversal, the response says so explicitly
(`"truncated": true`) rather than silently returning a partial,
unlabeled slice -- `test_graph_node_cap_truncates_and_reports_it`.

## Traversal: a plain bounded BFS

`build_graph()` uses `collections.deque` for a standard breadth-first
traversal starting from one seed `(seed_type, seed_id)`. At each
visited node, `_neighbors()` returns every edge incident on it (already
filtered -- see below), adding new nodes/edges to the result and new
frontier entries to the queue, UNLESS the depth cap or node cap is
already reached. This is not a spring-layout or force-directed graph
library -- the frontend lays positions out itself (seed at center,
neighbors spaced evenly around it; see `EvidenceGraphPage.tsx`), by
design: no new npm dependency was added for this (Section 10 doesn't
require a specific rendering library, and a from-scratch SVG keeps the
bundle small and the behavior fully inspectable).

## Node and edge types

| Node type | Backed by |
|---|---|
| `event` | `Event` |
| `evidence` | `Evidence` |
| `assessment` | `Assessment` |

| Edge type | Backed by | Appears between |
|---|---|---|
| `correlation` | `EventCorrelation` (Phase 2, read-only here) | event <-> event |
| `relationship` | `EvidenceRelationship` | event/evidence <-> event/evidence |
| `conflict` | `Conflict` | event <-> event |
| `assessment_link` | `AssessmentEvidenceLink` | assessment <-> event/evidence |

Every edge in the response carries why it exists: `reasons` (for a
correlation), `relationship_type`/`explanation` (for a relationship),
`conflicting_fields` (for a conflict), `role` (for an assessment link),
plus `review_status`/`origin` where applicable -- so a viewer (human or
this platform's own frontend) can visually distinguish an
analyst-confirmed link from an unreviewed candidate, never presenting
both the same way.

## Filters

All applied server-side, inside `_neighbors()`, BEFORE an edge or its
endpoint is ever added to the traversal frontier -- a filtered-out edge
never contributes to reaching a node that would otherwise be out of
reach:

- `relationship_type` (one or more) -- only for `relationship` edges.
- `review_status` -- applies to both `correlation` and `relationship`
  edges (an unconfirmed relationship can be hidden by filtering to
  `confirmed` -- `test_graph_review_status_filter`).
- `source_id` / `since` / `until` -- applied to the EVENT on the far
  side of an edge (`_event_passes_filters()`), so the graph can be
  scoped to "only continue through events from source X" or "only
  within this time window."

## Authorization and not-found handling

`GET /fusion/graph` requires `Permission.GRAPH_READ` (granted to every
authenticated role, including viewer -- this is a read surface over
data each role can already see individually). An unknown seed raises
`ValueError` in `graph_service.build_graph()`, translated to a 404 by
the route (`test_graph_for_nonexistent_seed_is_404`) -- never a 500 or
an empty-but-200 response for a seed that doesn't exist.

## Frontend: SVG + accessible table, never SVG-only

`EvidenceGraphPage.tsx` renders two things from the exact same
`GraphResponse`, always both:

1. An inline SVG with the seed at the center and neighbors arranged
   around it, nodes colored by type, edges colored/dashed by type and
   review status, with an on-page color-key legend.
2. A plain HTML `<table>` listing every node and every edge -- for
   screen readers, keyboard navigation, or anyone who prefers data to a
   picture. This table is not hidden behind a toggle; it's always
   rendered below the SVG.

A `truncated: true` response shows an explicit warning banner above
both views -- the viewer is never left to infer a possibly-incomplete
graph is actually complete.

## What this does NOT do

No graph database, no persisted adjacency table, no caching layer --
every call is a fresh, bounded BFS over the live relational tables.
No cross-organization traversal -- every lookup filters by
`organization_id`. No force-directed/physics layout (a deliberate
choice to avoid a new frontend dependency; node positions are a simple
deterministic circle layout, not a "nice-looking" graph-drawing
algorithm). No write operations through this endpoint at all -- it is
GET-only; reviewing a relationship or resolving a conflict happens
through their own dedicated endpoints, not through the graph view.

## Tests

`backend/tests/test_fusion_and_graph.py`'s graph_service section (9
tests): isolated-seed graph, nonexistent-seed error, correlation-edge
traversal, analyst-relationship-to-evidence traversal, depth-limit
enforcement (A-B-C chain, `max_depth=1` sees only A/B), node-cap
truncation and its `truncated` flag, the review-status filter, and an
assessment-seed reaching its linked evidence via an `assessment_link`
edge. Plus two API-level tests: `test_viewer_cannot_run_fusion_but_can_read_jobs`
is in the fusion section, but
`test_graph_max_depth_is_clamped_server_side` and
`test_graph_for_nonexistent_seed_is_404` exercise this endpoint
specifically end-to-end through a real `TestClient` call, not just the
service function directly.
