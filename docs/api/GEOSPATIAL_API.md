# Geospatial API

**Status: IMPLEMENTED.** 13 endpoints, 4 route files, all under
`/api/v1/geospatial/...`, all authenticated (bearer JWT, unchanged
auth) and permission-gated. Confirmed registered via
`TestClient(app).get('/api/openapi.json')` and 18 passing route-level
tests in `tests/test_geospatial_api.py`.

## Permissions

| Permission | Granted to | Mirrors |
|---|---|---|
| `GEOSPATIAL_READ` | Administrator, Analyst, Investigator, Viewer | `EVENT_READ` -- broad read access |
| `GEOSPATIAL_EXPORT` | Administrator, Analyst | `DATA_EXPORT` -- bulk-export is a narrower privilege than viewing |
| `GEOSPATIAL_MANAGE` | Administrator, Analyst (**not** Investigator) | `CORRELATION_MANAGE` -- generating candidates is an analytical action, not a review action |

Every route resolves `organization_id` from `current_user.organization_id`
(the authenticated session), never from a request parameter -- a
cross-tenant request is structurally impossible to express, not merely
filtered after the fact.

## `app/api/routes/geospatial.py`

| Method | Path | Permission | Service call | Notes |
|---|---|---|---|---|
| GET | `/geospatial/overview` | `GEOSPATIAL_READ` | `geo_overview_service.build_overview` | Landing-page aggregation |
| GET | `/geospatial/viewport` | `GEOSPATIAL_READ` | `geo_query_service.query_viewport` | `min_lat`/`max_lat`/`min_lon`/`max_lon` required; `ValueError` -> 400 |
| GET | `/geospatial/radius` | `GEOSPATIAL_READ` | `geo_query_service.query_radius` | `center_latitude`/`center_longitude`/`radius_km` required; `ValueError` -> 400 |
| GET | `/geospatial/quality/summary` | `GEOSPATIAL_READ` | `location_quality_service.quality_summary` | |
| GET | `/geospatial/quality/issues` | `GEOSPATIAL_READ` | `location_quality_service.list_quality_issues` | `limit` capped `1..1000` |
| POST | `/geospatial/relationships/generate` | `GEOSPATIAL_MANAGE` | `spatial_relationship_service.generate_candidates` | Body: `SpatialRelationshipGenerateRequest`; `ValueError` -> 400 |
| GET | `/geospatial/relationships` | `GEOSPATIAL_READ` | `spatial_relationship_service.list_candidates` | Reviewing a result uses the **existing** `POST /relationships/{id}/review` endpoint -- not duplicated here |

Every list/viewport/radius/relationships `record_types`/`review_status`
filter is an optional query parameter; omitting it returns every
supported value.

## `app/api/routes/geo_timeline.py` (prefix `/geospatial/timeline`)

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/geospatial/timeline` | `GEOSPATIAL_READ` | `since`/`until` required. `ascending=false` (default) for list view, `ascending=true` for historical playback (Section 8). `TimeRangeTooLargeError`/`ValueError` -> 400 |
| GET | `/geospatial/timeline/buckets` | `GEOSPATIAL_READ` | `bucket_seconds` required (`gt=0`). Returns `TimeBucketCountsResponse` (`buckets` + `is_approximate`) |

## `app/api/routes/geo_analytics.py` (prefix `/geospatial/analytics`)

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/geospatial/analytics/temporal-gaps` | `GEOSPATIAL_READ` | `record_type`/`since`/`until`/`min_gap_seconds` required. Returns `TemporalGapsResponse` |
| GET | `/geospatial/analytics/spatial-grid` | `GEOSPATIAL_READ` | `grid_resolution_degrees` optional (`gt=0` if given; else `GEOSPATIAL_DEFAULT_GRID_RESOLUTION_DEGREES`). Returns `SpatialGridResponse` |

## `app/api/routes/geo_export.py` (prefix `/geospatial/export`)

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/geospatial/export/geojson` | `GEOSPATIAL_EXPORT` | `record_types` required (repeated query param). Returns a raw `Response` (see below), never a JSON envelope |
| GET | `/geospatial/export/csv` | `GEOSPATIAL_EXPORT` | Same filters as GeoJSON export |

**Export responses are not JSON.** Both endpoints return
`fastapi.responses.Response(content=result.content, media_type=result.content_type,
headers={"Content-Disposition": 'attachment; filename="..."'})`
-- a real downloadable file, matching how a browser or the frontend's
own `fetchGeoExport()` client helper expects an attachment to behave.
Every successful export is also recorded via `audit_service.record(action="geospatial.export", ...)`
and committed, mirroring the `export_service` audit discipline.

## Response envelope conventions

- Every bounded spatial query (`viewport`, `radius`, `timeline`)
  returns the shared `GeospatialQueryResponse`: `items`,
  `total_matched`, `returned_count`, `truncated`, `max_results`, plus
  context on exactly what was searched (`bounds_searched` /
  `radius_km`+`center_latitude`+`center_longitude` /
  `time_range_searched`, `record_types_searched`,
  `missing_or_invalid_location_count`).
- Every bounded-sample analytic (`timeline/buckets`, `analytics/temporal-gaps`,
  `analytics/spatial-grid`) wraps its list in an envelope carrying
  `is_approximate: bool` (`TimeBucketCountsResponse`,
  `TemporalGapsResponse`, `SpatialGridResponse`) -- added specifically
  because a bare `list[...]` response model would silently drop this
  flag at the API boundary (Section 15's "never present a bounded
  sample as a complete/exact result").
- A service-level `ValueError` (bad input: invalid range, non-positive
  threshold, time range too large, etc.) is always translated to HTTP
  `400` with the exception's own message as `detail` -- never a `500`.

## Full endpoint list (confirmed via live OpenAPI introspection)

```
GET  /api/v1/geospatial/overview
GET  /api/v1/geospatial/viewport
GET  /api/v1/geospatial/radius
GET  /api/v1/geospatial/quality/summary
GET  /api/v1/geospatial/quality/issues
POST /api/v1/geospatial/relationships/generate
GET  /api/v1/geospatial/relationships
GET  /api/v1/geospatial/timeline
GET  /api/v1/geospatial/timeline/buckets
GET  /api/v1/geospatial/analytics/temporal-gaps
GET  /api/v1/geospatial/analytics/spatial-grid
GET  /api/v1/geospatial/export/geojson
GET  /api/v1/geospatial/export/csv
```

## What this does NOT do

- No endpoint accepts or trusts a client-supplied `organization_id`.
- No endpoint returns more than `GEOSPATIAL_MAX_RESULTS`/the relevant
  bounded-sample cap, regardless of what a caller requests.
- No websocket, SSE, or polling-push endpoint -- every route is a
  plain request/response GET or POST.
- No endpoint in this file set assigns a threat, priority, or
  hostile-intent value to any response.
