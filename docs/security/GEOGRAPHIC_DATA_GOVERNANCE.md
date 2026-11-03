# Geographic Data Governance (Phase 7)

**Status: IMPLEMENTED.**

## 1. Permission model

Three new permissions in `app/core/security.py`'s `Permission` enum,
following the same least-privilege-per-role discipline every prior
phase used:

| Permission | Administrator | Analyst | Investigator | Viewer |
|---|---|---|---|---|
| `GEOSPATIAL_READ` | yes (implicit, full `Permission` set) | yes | yes | yes |
| `GEOSPATIAL_EXPORT` | yes | yes | **no** | **no** |
| `GEOSPATIAL_MANAGE` | yes | yes | **no** | **no** |

`GEOSPATIAL_READ` is deliberately broad (same tier as `EVENT_READ`) --
viewing the map, timeline, quality findings, and spatial-relationship
list is read access, available to every authenticated role including
Viewer. `GEOSPATIAL_EXPORT` (bulk GeoJSON/CSV download) and
`GEOSPATIAL_MANAGE` (triggering spatial-relationship candidate
generation) are both restricted to Administrator/Analyst, mirroring
`DATA_EXPORT` and `CORRELATION_MANAGE` respectively -- an Investigator
can review and confirm/reject a spatial-relationship candidate (via
the existing `RELATIONSHIP_MANAGE`-equivalent review permission, see
`docs/analytics/SPATIAL_RELATIONSHIPS.md` Section 6), but cannot
trigger a new generation run or bulk-export located records.

## 2. Tenant isolation

Every geospatial service function requires `organization_id` as a
non-optional parameter, and every SQL statement in this subsystem
filters on it explicitly -- the same per-call discipline every prior
phase's service functions use (Phase 1's documented, not-yet-
framework-enforced tenant model; Phase 14's eventual job to enforce
this at a framework/middleware level). Every route resolves
`organization_id` exclusively from `current_user.organization_id`
(the authenticated session's own claim), never from a client-supplied
query parameter or request body field -- a cross-tenant request is
structurally unable to even express another tenant's id. Verified for
every one of the 4 new route files by `tests/test_geospatial_api.py`'s
tenant-isolation tests (a second organization's seeded data never
appears in the first organization's query results).

## 3. Audit logging

Every successful GeoJSON/CSV export calls
`audit_service.record(action="geospatial.export", actor_user_id=...,
organization_id=..., target_type="geospatial_export",
target_id=result.format, context_metadata={format, feature_count,
truncated, filters})` before committing -- the same audit discipline
Phase 2's `export_service.py` established for its own tabular export.
Read-only queries (viewport, radius, timeline, quality, relationship
listing) are not individually audit-logged, consistent with how every
other read-only query endpoint in this codebase behaves (Phase 1-6).
Spatial-relationship candidate generation is not separately
audit-logged beyond the standard request logging middleware every
route already goes through -- its effect (new `EvidenceRelationship`
rows) is itself a durable, queryable record.

## 4. CSV-injection safety

`geo_export_service.py` reuses the **identical** formula-prefix guard
Phase 2's `export_service.py` already established
(`_FORMULA_PREFIXES`, `_csv_safe()`): any CSV cell value beginning with
`=`, `+`, `-`, `@`, tab, or carriage return is prefixed with a leading
single-quote before being written, neutralizing a formula-injection
attack if the exported CSV is later opened in a spreadsheet
application. Verified by
`tests/test_geo_export_service.py::test_csv_formula_injection_guard`.

## 5. No live/real-time position exposure

This phase introduces no streaming, push, or "live tracking" surface
-- every query is a bounded, point-in-time read of already-stored
data. There is no capability anywhere in this subsystem that could
expose a real-time device or asset position to an unauthorized party,
because no real-time position feed exists in this codebase at all.

## 6. Synthetic data labeling

Every located record's `is_synthetic` field is derived live from the
underlying row's `data_origin == "synthetic_demo"` (never a separate,
independently-maintained flag that could drift out of sync). The
frontend's `DataOriginBadge` renders this visibly on every page that
shows record detail (Overview's recent-records list, Map Explorer's
popups) -- synthetic demo data is never presented as though it were a
real observation. This governance rule is binding project-wide (not
new to Phase 7) but is repeated here because geospatial data is
exactly the category most easily mistaken for operationally real
information if mislabeled.

## 7. What this does NOT do

- No field-level redaction or classification-marking system (e.g.
  "SECRET"/"UNCLASSIFIED" banners) -- out of this project's scope
  entirely, not just this phase's.
- No geofencing or access restriction based on a user's own location
  -- access control here is purely role/permission-based, identical
  in kind to every other subsystem in this codebase.
- No data-retention or automatic-purge policy specific to location
  data -- retention policy in general remains Phase 14/15's job,
  unchanged from every prior phase's own statement of scope.
- No rate limiting specific to the export endpoints beyond the
  per-call result-size bound (`GEOSPATIAL_MAX_EXPORT_FEATURES`) --
  no new throttling middleware was introduced this phase.
