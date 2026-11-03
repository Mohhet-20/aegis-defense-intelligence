# Temporal Exploration and Historical Playback (Phase 7)

**Status: IMPLEMENTED.** `app/services/geo_timeline_service.py`,
frontend `pages/geo/TimelineExplorerPage.tsx`.

## 1. A timeline query is a spatial query with no bounding box

`query_timeline()` reuses `geo_query_service`'s own
`fetch_record_type()`/`resolve_record_types()` -- it is deliberately
**not** a parallel implementation. The only real addition is sort
direction: `ascending=False` (default) serves the Timeline Explorer's
"most recent first" list; `ascending=True` serves historical playback,
consumed in order by the frontend's step control.

## 2. Historical playback is real, bounded, and never interpolated

This is a binding, repeatedly-verified requirement (Section 8, and the
specification's prohibited-scope list): playback steps through the
**real, stored, ascending-ordered array** `query_timeline(...,
ascending=True)` returns. `TimelineExplorerPage.tsx`'s Step
back/Play/Step forward controls and range slider all move an index
into that array -- nothing client-side computes, guesses, or draws a
position or timestamp between two adjacent real records. A gap between
two consecutive records (see Section 4) is reported as a gap, never
silently bridged with an invented in-between point. No server-side
playback state exists either -- the backend has no concept of a
"playback session"; the frontend owns the current index entirely.

## 3. Time-range bounding

`_validate_range()` rejects `since >= until` and any span exceeding
`settings.GEOSPATIAL_MAX_TIME_RANGE_DAYS` (365 days) by raising
`TimeRangeTooLargeError` (a `ValueError` subclass), surfaced by
`app/api/routes/geo_timeline.py` as an HTTP `400` rather than silently
truncating the window or running an unbounded query. Combined with
`GEOSPATIAL_MAX_RESULTS` (returned-item cap, same as every other
geospatial query), this bounds both the query's time window and its
result size independently.

## 4. Time-bucket counts and temporal gaps

- **`time_bucket_counts()`**: fixed-width buckets (`bucket_seconds`,
  caller-chosen -- the frontend uses 6-hour buckets for its inline-CSS
  bar chart) across the requested range, per record type, summed.
- **`temporal_gaps()`**: for one record type, every consecutive-pair
  gap `>= min_gap_seconds` between that type's own timestamps in
  range -- explicitly documented as **an absence of records in this
  project's own data**, never a claim that nothing happened in the
  real world during that interval (Section 20's binding "never draw a
  causal conclusion" discipline extends to silence, not just
  co-occurrence).

Both pull raw timestamps via the shared, capped
`_timestamps_for_bucketing()` helper (`MAX_TEMPORAL_SAMPLE_ROWS = 5000`
per record type) and both return `(result, is_approximate)` --
`is_approximate` is `True` only when the row cap was actually hit for
some included record type, and is carried all the way to the API
response via the `TimeBucketCountsResponse`/`TemporalGapsResponse`
envelope schemas specifically so a bounded sample is never presented
as a silently-complete result (Section 15).

## 5. The naive/aware SQLite datetime bug, re-fixed here

`_timestamps_for_bucketing()` selects a bare `DateTime` column (not a
full ORM row) for efficiency; SQLite hands these back as naive
`datetime` objects even though the column is declared
`DateTime(timezone=True)` -- the same bug class first fixed in
Phase 1's `user_service.py` and re-fixed in three Phase 6 services.
`geo_timeline_service.py`'s own `_as_aware_utc()` helper normalizes
every value read this way before any arithmetic touches it.
`app/geo/validation.py` later centralized an equivalent helper so
every Phase 7 caller is protected automatically (see
`docs/data/LOCATION_PROVENANCE_AND_UNCERTAINTY.md`).

## 6. What this does NOT do

- No live/streaming timeline -- every call is a point-in-time read; a
  user must re-query (or the frontend must re-poll on an explicit
  action) to see new records.
- No interpolated or predicted position between two real records, at
  any point in the playback or timeline UI.
- No "what happened at exactly this instant" synthesis across record
  types beyond simply listing whichever real records fall in the
  requested window -- no cross-type correlation or narrative is
  generated.
- No claim that a temporal gap means nothing happened -- it means
  nothing was *recorded* in this system during that interval, stated
  exactly that way in the gap's own documentation and in
  `docs/analytics/SPATIAL_TEMPORAL_ANALYTICS.md`'s binding-principles
  section.
