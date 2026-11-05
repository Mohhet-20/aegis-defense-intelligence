# Canonical Event Schema

The normalized shape every ingested record is mapped
onto, regardless of source or connector. `SCHEMA_VERSION = "1.0"` (see
`app/services/normalization_service.py`) -- bumped whenever a change here
would affect how an already-stored row should be interpreted.

## Fields (`app/models/event.py`)

| Field | Type | Constraint / policy |
|---|---|---|
| `id` | UUID string | generated |
| `organization_id` | string | required, FK |
| `source_id` | string | required, FK |
| `external_id` | string, nullable | the source's own stable id, or (if absent) a content fingerprint -- see `DEDUPLICATION_POLICY.md`. Never a made-up value. |
| `event_type` | string | **always preserved verbatim.** Separately checked against a known taxonomy (`normalization_service.classify_event_type`) for analytics, but an unrecognized type is NOT rejected and does NOT lose the source's original value. |
| `title` | string | required |
| `description` | string, nullable | |
| `observed_at` | datetime, tz-aware UTC | see "Timestamp policy" below |
| `ingested_at` | datetime, tz-aware UTC | when this platform actually processed the batch |
| `latitude` / `longitude` | float, nullable | see "Coordinate policy" below |
| `asset_id` | string, nullable | optional link to a known `Asset` |
| `source_severity` | string, nullable | **the source's own value, verbatim** -- never overwritten |
| `priority` | string, nullable | **this platform's own triage value**, mapped from `source_severity` via a documented, configurable table -- see "Severity policy" |
| `confidence` | float, nullable | only set when there is a real basis; never fabricated |
| `attributes` | JSON dict | every field from the raw record that isn't one of the above dedicated columns -- nothing from the source is silently discarded |
| `classification` | string | `unclassified` / `internal` / `restricted` |
| `provenance` | JSON dict | `raw_record_id`, `connector_type`, `connector_version`, `normalization_version`, `schema_version`, `content_fingerprint`, `timestamp_policy`, `validation_warning_codes` -- see `DATA_PROVENANCE.md` |
| `processing_status` | string | `ingested` / `normalized` / `correlated` / `archived` |
| `data_origin` | string | `synthetic_demo` / `user_upload` / `external_source` -- Rule 9: never let a synthetic or uploaded record pass as a live connected feed |
| `ingestion_job_id` | string, nullable | which job produced this event |

`source_severity`, `priority`, `confidence` are three DIFFERENT numbers,
never collapsed into one field (carried over unchanged,
Section 7).

## Timestamp policy

Implemented in `normalization_service.normalize_timestamp()`:

- A value with explicit timezone/offset information is converted to UTC
  as given -- policy `"parsed_aware"`.
- A value with NO timezone information (a naive ISO string, or a bare
  date) is **assumed to already be UTC** -- policy `"assumed_utc"`. This is
  a documented assumption, not a silent one: the policy actually applied is
  recorded on `provenance.timestamp_policy` and surfaced as a
  `WARN_AMBIGUOUS_TIMESTAMP_ASSUMED_UTC` validation warning, so an analyst
  can tell which stored timestamps were a guess.
- Epoch seconds (`int`/`float`) are unambiguous and always parsed as UTC.
- A value that cannot be parsed at all is reported invalid (`None`) and the
  record is rejected -- **never defaulted to "now" or any other guessed
  value.**

## Coordinate policy

Implemented in `normalization_service.normalize_coordinates()`:

- A missing coordinate (either field absent/empty) stays missing --
  **never defaulted to `(0, 0)`.**
- A pair where only one of latitude/longitude is present is treated as
  entirely missing (and flagged with a `WARN_MISSING_COORDINATES` warning
  if the record clearly intended to supply one).
- A pair outside WGS84 decimal-degree range (`-90..90`, `-180..180`) is
  **rejected**, not clamped or silently corrected.
- No coordinate-system metadata beyond WGS84 is modeled yet -- a future
  work introducing a different coordinate system must add that metadata
  explicitly, never assume WGS84 silently.

## Severity -> priority mapping

Implemented in `normalization_service.map_severity_to_priority()`, default
table `DEFAULT_SEVERITY_TO_PRIORITY`:

| source value (case-insensitive) | priority |
|---|---|
| low, minor, info, informational | `low` |
| medium, moderate, warning | `medium` |
| high, major, severe | `high` |
| critical, emergency, catastrophic | `critical` |

An unrecognized, non-blank `source_severity` is **left unmapped**
(`priority = None`) and flagged with a `WARN_UNKNOWN_SEVERITY_LABEL`
warning -- it is never silently escalated to the highest priority, which
would manufacture urgency the source never actually reported. An absent
`source_severity` is recognized-as-absent and produces no warning.

## Known event-type taxonomy

`normalization_service.KNOWN_EVENT_TYPES`: `perimeter_motion`,
`unidentified_vehicle`, `access_attempt`, `sensor_offline`,
`anomalous_pattern`, `intrusion`, `equipment_malfunction`,
`personnel_movement`, `communications_intercept`, `other`. This list is
purely for analytics/filtering convenience; an event outside it is stored
exactly as reported with a `WARN_UNKNOWN_EVENT_TYPE` warning, not rejected.

## Backward compatibility / future extension

Every `Event` and `RawRecord` row records the `schema_version` and
`normalization_version` that produced it, so a future schema change can
distinguish rows normalized under the old rules from new ones without
guessing. The schema is deliberately left room to grow: observation/
tracking fields, geospatial precision/coordinate-system
metadata, and computer-vision detection fields all have
a natural home as additional nullable columns or `attributes`/`provenance`
keys -- none of them require restructuring what already exists.
