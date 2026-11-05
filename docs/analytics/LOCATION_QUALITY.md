# Location Quality

**Status: IMPLEMENTED.** `app/services/location_quality_service.py`,
frontend `pages/geo/LocationQualityCenterPage.tsx`.

## 1. Read-only, always

Nothing in this service mutates a record or "fixes" a bad coordinate.
It exists to **explain** what `app/geo/validation.py` finds for each
row and let an authorized analyst decide what to do -- edit the source
record through its own existing update path (unchanged, outside this
layer's scope), or, if a conflicting second source exists for the same
real-world thing, let `spatial_relationship_service.py` surface it as
a reviewable candidate (see `docs/analytics/SPATIAL_RELATIONSHIPS.md`).
There is no "repair" or "auto-correct" endpoint anywhere in this
subsystem.

## 2. Two endpoints, two different sampling guarantees

- **`GET /geospatial/quality/summary`** (`quality_summary()`):
  aggregate counts per finding type, overall and `by_record_type`.
  `missing_count` is always an **exact** SQL `COUNT(*) WHERE latitude
  IS NULL OR longitude IS NULL` -- cheap, indexable, never sampled.
  Every other count (`invalid_range`, `non_finite`, `unsupported_crs`,
  `valid`, `uncertainty_unavailable`, `stale`) requires per-row Python
  classification via `validate_coordinates()`, so it runs over a
  **bounded sample** (`MAX_QUALITY_SAMPLE_ROWS = 5000` present-coordinate
  rows per record type) -- each record type's own `by_record_type[rt]`
  entry carries `sampled` (how many rows were actually classified) and
  `is_approximate` (whether the 5000-row cap was hit), so the summary
  never claims a precise total it didn't actually count. There is no
  single top-level `is_approximate` flag on the response -- it is
  reported per record type, since one type's sample could be complete
  while another's is capped.
- **`GET /geospatial/quality/issues`** (`list_quality_issues()`): a
  per-record review queue, bounded to `limit` (default 200, split
  evenly across requested record types via `per_type_limit`).
  `only_issues=True` (default) excludes fully-clean records (valid,
  uncertainty known, not stale) -- this is a worklist, not a dump of
  every located record; `only_issues=False` returns the full sampled
  set including clean rows.

## 3. Finding set (see `app/geo/validation.py` for full explanations)

| Finding | `is_error` | Meaning |
|---|---|---|
| `missing_coordinates` | No | `latitude`/`longitude` both `None` |
| `invalid_range` | Yes | Outside WGS84 `-90..90`/`-180..180` |
| `non_finite` | Yes | `NaN` or infinite |
| `unsupported_crs` | Yes | `coordinate_reference_system` not `"WGS84"` |
| `uncertainty_unavailable` | No | `location_uncertainty_m is None` |
| `stale_location_timestamp` | No | Record's own occurrence timestamp older than `GEOSPATIAL_STALE_LOCATION_AFTER_SECONDS` (7 days) |
| `valid` | No | Present, finite, in range, supported CRS |

A location is classified `invalid_range`/`non_finite`/`unsupported_crs`
**exclusively** -- these three never co-occur with `valid` or with
each other, and the check order (`non_finite` -> `invalid_range` ->
`unsupported_crs`) is load-bearing for seed/demo data (see
`docs/data/LOCATION_SCHEMA_AND_COORDINATE_SYSTEMS.md` Section 2). A
`valid` location can additionally carry `uncertainty_unavailable`
and/or `stale_location_timestamp` as informational findings.

## 4. Authorization

`GET /geospatial/quality/summary` and `/quality/issues` both require
`Permission.GEOSPATIAL_READ` -- the same broad read permission as
every other geospatial read endpoint (Administrator, Analyst,
Investigator, Viewer). Quality findings are not considered sensitive
in the same way an export is; no separate, narrower permission exists
for viewing them.

## 5. What this does NOT do

- No write path -- a quality finding can never result in this service
  changing a stored coordinate.
- No scheduled/background quality sweep -- every call computes fresh,
  on demand, from the current data.
- No alerting or notification when a new issue appears -- the
  Location Quality Center is a pull-based review surface, not a push
  one.
- No cross-source conflicting-coordinate detection -- that is a
  cross-record concern handled entirely by
  `spatial_relationship_service.py`, never by this single-record
  finding system.
