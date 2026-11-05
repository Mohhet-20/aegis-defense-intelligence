# Ingestion & Data Platform API

the expanded `/api/v1` surface: source management, ingestion jobs
(file-upload and connector-driven), raw-record provenance, data quality,
correlation, and controlled export. All routes below sit under `/api/v1`
and require a valid bearer token (see the `AUTHENTICATION.md`) --
this document only covers what's new/changed. Every route
appears in the live OpenAPI docs at `/docs` (FastAPI's auto-generated
schema; nothing here is hand-maintained separately from the actual route
code, so if this doc and `/docs` ever disagree, `/docs` -- i.e. the code --
is correct).

## Sources: `app/api/routes/sources.py`

| Method & path | Permission | What it does |
|---|---|---|
| `GET /sources` | `SOURCE_READ` | Paginated list, this organization only |
| `POST /sources` | `SOURCE_MANAGE` | Create, with `owner_team`/`connection_mode`/`enabled` |
| `GET /sources/{id}` | `SOURCE_READ` | Detail |
| `PATCH /sources/{id}` | `SOURCE_MANAGE` | Partial update; bumps `config_metadata`'s `config_revision` when config changes |
| `POST /sources/{id}/enable` | `SOURCE_MANAGE` | Re-enable a disabled source |
| `POST /sources/{id}/disable` | `SOURCE_MANAGE` | Disable -- file uploads (409) and `/run` (409) are then refused for this source until re-enabled |
| `PUT /sources/{id}/reliability` | `SOURCE_MANAGE` | Set `reliability_weight` (0.0-1.0). **`reason` is required** -- a 400 with `ValueError`'s message is returned otherwise. Audit-logged as `source.reliability_change` with the new weight and reason. See `docs/analytics/SOURCE_RELIABILITY.md`. |
| `POST /sources/{id}/validate-config` | `SOURCE_MANAGE` | Calls the matching connector's `validate_config()` without fetching anything; returns `{valid, errors}` |
| `POST /sources/{id}/check-connectivity` | `SOURCE_MANAGE` | Calls the matching connector's `check_connectivity()` (a lightweight reachability probe, not a full fetch); records the outcome on the source (`last_error_category` etc.) and returns `{ok, detail, applicable}` -- `applicable=false` for a source type with no connector (file-upload-only) |
| `POST /sources/{id}/run` | `INGESTION_RUN` | Explicitly fetches one batch from a connector-driven source (`http_api`, `synthetic_demo`, legacy `synthetic_generator`). Returns 400 (`NoConnectorForSourceError`) for a file-upload-only source type, or 409 (`SourceDisabledError`) if the source is disabled. Produces a real `IngestionJob` through the same `_process_batch()` engine a file upload uses. |

## Ingestion jobs: `app/api/routes/ingestion.py`

| Method & path | Permission | What it does |
|---|---|---|
| `POST /ingestion/jobs` | `INGESTION_RUN` | Multipart upload: `source_id` (form field) + `file`. 404 if the source doesn't exist in this org; **409 if the source is disabled**. `data_origin` is always set to `"user_upload"` server-side -- never client-supplied (Rule 9: a human-uploaded file can never masquerade as a live connected feed). |
| `GET /ingestion/jobs` | `INGESTION_READ` | Paginated list; optional `source_id` filter |
| `GET /ingestion/jobs/{id}` | `INGESTION_READ` | Detail -- includes `accepted_count`/`rejected_count`/`duplicate_count`, `trigger_type`, `retry_count`, `correlation_id` |
| `GET /ingestion/jobs/{id}/raw-records` | `RAW_RECORD_READ` | **Gated separately from `INGESTION_READ`** -- see `docs/data/DATA_PROVENANCE.md` for why. Paginated; every record this job touched, including rejected/duplicate ones, each with its own `validation_status`/`validation_errors`/`validation_warnings`. |
| `POST /ingestion/jobs/{id}/retry` | `INGESTION_RUN` | Re-runs a connector-driven job (`RETRYABLE_JOB_TYPES = {http_api, synthetic_demo, synthetic_generator}`) as a brand-new `IngestionJob` with `trigger_type="retry"` and `retry_count` incremented. **400 for a file-upload job** (`ValueError` -- there is no original file bytes to replay; the caller must re-upload). |

## Data quality: `app/api/routes/data_quality.py`

| Method & path | Permission | What it does |
|---|---|---|
| `GET /data-quality/summary` | `DATA_QUALITY_READ` | On-the-fly SQL aggregate over `RawRecord` (never a stored/cached summary table -- always current). Optional `source_id`, `since`, `until` filters. Always returns its own denominator (`total`) alongside counts, and a bounded category-code breakdown (capped at `MAX_RECORDS_FOR_CATEGORY_BREAKDOWN = 5000` records server-side to keep the endpoint fast on a large table). |
| `GET /data-quality/jobs-summary` | `DATA_QUALITY_READ` | Same shape, aggregated over `IngestionJob` instead -- job counts by status/trigger_type, accepted/rejected/duplicate totals. |

Granted to every authenticated role (including viewer) -- these describe
pipeline health, not evidentiary weight. See
`docs/analytics/SOURCE_RELIABILITY.md`'s "What's exposed to whom".

## Correlation: `app/api/routes/correlation.py`

| Method & path | Permission | What it does |
|---|---|---|
| `GET /correlation` | `CORRELATION_READ` | Paginated list of all correlation candidates/confirmed/rejected pairs in this org |
| `GET /correlation/{id}` | `CORRELATION_READ` | Detail -- `reasons`, `match_strength`, `temporal_delta_seconds`, `spatial_delta_meters`, `review_status`, `rule_version` |
| `POST /correlation/recompute` | `CORRELATION_MANAGE` | **The one explicit entry point that produces correlations** (see `docs/analytics/EVENT_CORRELATION.md`) -- there is no background job. Optional `time_window_seconds` (default 1800) / `spatial_threshold_meters` (default 500) override the defaults for this run only. Idempotent: re-running with the same `rule_version` never duplicates existing rows. Audit-logged as `correlation.recompute` with the exact parameters and result counts. |
| `POST /correlation/{id}/review` | `CORRELATION_MANAGE` | The only way `review_status` ever changes (`confirmed` or `rejected` -- never back to `candidate`, enforced by the schema). Audit-logged as `correlation.review`. |

## Events (additions): `app/api/routes/events.py`

| Method & path | Permission | What it does |
|---|---|---|
| `GET /events` | `EVENT_READ` | Existing listing, extended with `source_id` and `data_origin` filters alongside the `event_type`/`priority` |
| `GET /events/export` | `DATA_EXPORT` | **Its own permission, separate from `EVENT_READ`** -- not every role that can read events may bulk-export them. `format=csv\|json` (default csv). Applies the same filters as the list endpoint. **Hard-refuses (400) if the filtered result exceeds `MAX_EXPORT_ROWS = 5000` rather than silently truncating** -- the caller must narrow filters. CSV values are guarded against formula injection (a leading `=`, `+`, `-`, `@`, tab, or carriage return is neutralized with a leading single quote) before being written. Only normalized `Event` fields are exported, never a raw payload. Every export is audit-logged (`event.export`) with format, row count, and the filters used. Registered **before** `/{event_id}` in route order so `"export"` is never swallowed as an `event_id` path parameter. |
| `GET /events/{id}/raw-record` | `RAW_RECORD_READ` | Resolves an event to the `RawRecord` that produced it via `Event.provenance.raw_record_id`. 404 if the event predates (no linked raw record) or the id doesn't resolve. |
| `GET /events/{id}/correlations` | `CORRELATION_READ` | All correlation rows (any `review_status`) involving this event, either side of the pair. |

## Cross-cutting concerns

- **Pagination**: every list endpoint uses the same `Page[...]`/`PageParams` pattern (`page`, `page_size` query params) -- nothing new introduced for the endpoints.
- **Organization scoping**: every query in every service function above filters by `organization_id` from the authenticated token -- there is no endpoint that can read or act across organizations.
- **Audit logging**: every mutating endpoint above (`enable`/`disable`/`reliability`/`run`/`recompute`/`review`/upload/`retry`/`export`) calls `audit_service.record()` in the same database transaction as the mutation, before `db.commit()` -- an audit entry can never exist without the action it describes actually having committed, and vice versa.
- **Request size bounds**: the file-upload endpoint is subject to the same body-size limits as the upload handling; the HTTP connector enforces its own response-size cap (see `docs/architecture/CONNECTOR_ARCHITECTURE.md`) independent of this.
- **SSRF defense**: `POST /sources/{id}/run` and `POST /sources/{id}/check-connectivity` are the only two routes that can cause this server to make an outbound HTTP request on an analyst's behalf (for an `http_api` source) -- both go through `url_safety.py`'s validation before any request is attempted. See `docs/architecture/CONNECTOR_ARCHITECTURE.md`.
- **OpenAPI docs**: `GET /docs` (Swagger UI) and `GET /openapi.json` reflect every route and schema above automatically -- generated from the same Pydantic schemas and FastAPI route declarations referenced in this document, not maintained separately.

## What this layer does NOT add

No webhook/callback endpoints for push-based ingestion (every connector in
this layer is pull-based -- the server reaches out, nothing reaches in).
No bulk/batch job-submission endpoint (one `POST /ingestion/jobs` call is
one file; one `POST /sources/{id}/run` call is one connector fetch). No
endpoint to delete a `RawRecord`, an `Event`, or a correlation -- retention
and deletion are explicitly out of scope (see
`docs/data/DEDUPLICATION_POLICY.md`'s retention note). No endpoint exposes
cross-organization data under any role.

## Tests exercising this surface

`backend/tests/test_connectors.py`, `test_provenance_and_dedup.py`,
`test_correlation.py`, `test_quality_and_sources.py`,
`test_security_baseline.py`, and `test_retry_and_correlation_api.py`
collectively exercise every route in this document, including permission
gates (a role lacking the required permission gets 403), the export size
limit, the disabled-source 409s, and the retry 400 for a non-retryable job
type. See each file's test names for the exact scenario covered -- this
document cites them rather than re-describing what they already state
precisely.
