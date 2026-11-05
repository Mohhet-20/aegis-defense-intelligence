# Geospatial Contracts — Planned

**Status: PLANNED. No map rendering, spatial query, or clustering code
exists yet.** `Event`, `Asset`, and `Sensor` already carry optional
`latitude`/`longitude` columns in the schema specifically so
Doesn't need a migration just to have coordinates to query.

## What actually ships

- Nullable `latitude: float` / `longitude: float` columns on `Event`,
  `Asset`, and `Sensor`, each validated at the schema layer (Pydantic)
  to reject out-of-range values (`-90..90` / `-180..180`) when present
  — but a value is never invented when the source didn't provide one.
- No spatial index, no PostGIS extension, no map UI. The frontend Event
  Explorer shows latitude/longitude as plain numeric columns when
  present, not a map.

## What will add

- **Interactive maps** (frontend) rendering events/assets/sensors with
  coordinates, using a geospatial mapping library (Section 5 reserves
  this choice for when map rendering is actually built, so the frontend
  doesn't carry an unused heavy dependency today).
- **Geospatial queries** — "events within N km of point X," bounding-box
  filters — which will need either a real spatial index (PostGIS, if
  the deployment is on Postgres) or an accepted-as-documented
  non-indexed fallback for SQLite deployments. That trade-off gets
  decided and written down when actually needs the query, not
  guessed now.
- **Spatial clustering** of nearby events for dense-area visualization.
- **Track visualization** once produces real tracks to draw.

## Binding principles (apply onward)

- A **missing** coordinate is `None` — never `(0.0, 0.0)` (a real,
  valid coordinate off the coast of West Africa). This is already true
  of every location field in the schema and must stay true.
- Coordinate reference system must be stated, not assumed — every
  coordinate in this system today is WGS84 decimal degrees; if a future
  source reports in a different CRS, it must be converted explicitly
  and the conversion logged, never silently treated as WGS84.
- A geospatial query result must say what it searched (radius, bounding
  box, time window) in its response, not just return points with no
  context for how they were selected.

## What does NOT do

No map component exists in the frontend. No spatial query endpoint
exists in the backend. No coordinate conversion logic exists (nothing
yet reports in a non-WGS84 CRS to convert from).
