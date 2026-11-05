# AEGIS API Reference --
Documents only the routes that actually exist in `backend/app/api/routes/*.py` as of
Every example below is a real request/response shape produced by the
Pydantic schemas in `backend/app/schemas/*.py` -- nothing here is aspirational.

Interactive OpenAPI docs are also served live by the running backend at
`GET /api/docs` (Swagger UI) and `GET /api/openapi.json` (raw schema).

## Conventions

- Base path: `/api/v1`
- Auth: `Authorization: Bearer <access_token>` on every route except `/auth/login`,
  `/auth/refresh`, and `/health/*`.
- Errors: `{"detail": "...", "request_id": "<uuid-or-null>"}`. A validation error's
  `detail` is a list of `{"type", "loc", "msg", "input"}` objects (FastAPI/Pydantic's
  native shape) -- never a bare string in that case.
- Pagination: list endpoints return `{"items": [...], "total": <int>, "page": <int>,
  "page_size": <int>}`. `page_size` is capped at 200 server-side; a request above
  that cap is a `422`, not a silent clamp.
- Every write is also recorded as an audit record (see `GET /audit`).

## Authentication

### `POST /auth/login`

Rate-limited (`10/minute` by default; see `RATE_LIMIT_AUTH`). Locks the account for
15 minutes after 5 consecutive failures (`MAX_FAILED_LOGIN_ATTEMPTS` /
`ACCOUNT_LOCKOUT_MINUTES`).

Request:
```json
{"username_or_email": "admin", "password": "DevPassword123!"}
```

Response `200`:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

Response `401` (wrong password, unknown user, disabled account, or locked account --
the message for a bad credential is deliberately generic to avoid username
enumeration):
```json
{"detail": "Invalid credentials", "request_id": "9b9d5a72-..."}
```

### `POST /auth/refresh`

```json
{"refresh_token": "eyJhbGciOiJIUzI1NiIs..."}
```
→ `200` with a new `{"access_token", "refresh_token", "token_type"}` pair. `401` if
the token is expired, malformed, or is actually an access token.

### `GET /auth/me`

No body. Returns the caller's own profile:
```json
{
  "id": "05c6d792-...", "username": "admin", "email": "admin@aegis-demo.example.com",
  "display_name": "Demo Administrator", "role": "administrator",
  "organization_id": "f963fccf-...", "is_active": true,
  "last_login_at": "2026-10-13T04:38:48Z"
}
```

## Users

Requires `user:read` (list/get) or `user:manage` (create/update) -- administrator
only by default (see Section 9 role table in `docs/architecture/MODULE_CATALOG.md`).

| Method | Path | Permission |
|---|---|---|
| GET | `/users` | `user:read` |
| POST | `/users` | `user:manage` |
| GET | `/users/{user_id}` | `user:read` |
| PATCH | `/users/{user_id}` | `user:manage` |

`POST /users` request:
```json
{"username": "newanalyst", "email": "newanalyst@example.com", "display_name": "New Analyst", "password": "SomePassword123!", "role": "analyst"}
```
`409` if the username or email is already taken. `422` if `role` is not one of
`administrator`, `analyst`, `investigator`, `viewer`.

`PATCH /users/{user_id}` accepts any subset of `{"display_name", "role",
"is_active"}`. Deactivating a user (`is_active: false`) takes effect immediately --
their next login attempt gets `401 Account is disabled`.

## Data Sources

| Method | Path | Permission |
|---|---|---|
| GET | `/sources` | `source:read` |
| POST | `/sources` | `source:manage` |
| GET | `/sources/{source_id}` | `source:read` |
| PATCH | `/sources/{source_id}` | `source:manage` |

`POST /sources`:
```json
{"name": "Perimeter Feed", "source_type": "manual", "description": "optional", "reliability_weight": 1.0, "config_metadata": {}}
```
Response includes `last_ingestion_attempt_at` / `last_ingestion_success_at`
(`null` until a real ingestion job runs against it) and `status` (`active` /
`inactive` / `error`).

## Assets

| Method | Path | Permission |
|---|---|---|
| GET | `/assets` | `asset:read` |
| POST | `/assets` | `asset:manage` |
| GET | `/assets/{asset_id}` | `asset:read` |
| PATCH | `/assets/{asset_id}` | `asset:manage` |

`POST /assets`:
```json
{"name": "North Gate Checkpoint", "entity_type": "facility", "latitude": 38.8977, "longitude": -77.0365}
```
`latitude`/`longitude` are both optional -- omit both rather than sending `0`.
Providing only one, or a value outside `[-90, 90]` / `[-180, 180]`, is a `422`.

## Sensors

| Method | Path | Permission |
|---|---|---|
| GET | `/sensors` | `sensor:read` |
| POST | `/sensors` | `sensor:manage` |
| GET | `/sensors/{sensor_id}` | `sensor:read` |
| PATCH | `/sensors/{sensor_id}` | `sensor:manage` |

A newly-created sensor always starts with `"status": "unknown"` regardless of what
the request body contains -- a sensor's operational status is only meaningful once
it has actually reported in. Valid statuses: `active`, `inactive`, `fault`,
`unknown`.

## Observations

| Method | Path | Permission |
|---|---|---|
| GET | `/observations?sensor_id=<optional>` | `observation:read` |

Read-only -- observations are written/future sensor
integrations, not through a public create endpoint yet.

## Events

| Method | Path | Permission |
|---|---|---|
| GET | `/events?event_type=&source_id=&priority=&data_origin=` | `event:read` |
| GET | `/events/{event_id}` | `event:read` |

Events are created only through the ingestion pipeline (below), never directly --
there is no `POST /events`. Response shape:
```json
{
  "id": "...", "source_id": "...", "external_id": "upload-1",
  "event_type": "perimeter_motion", "title": "Motion detected near North Gate",
  "observed_at": "2026-01-01T00:00:00Z", "ingested_at": "2026-01-01T00:00:31Z",
  "latitude": 38.8977, "longitude": -77.0365,
  "source_severity": "medium", "priority": "normal", "confidence": 0.62,
  "data_origin": "synthetic_demo", "classification": "unclassified",
  "processing_status": "ingested", "ingestion_job_id": "..."
}
```
Note the three distinct fields: `source_severity` (the source's own scale,
untouched), `priority` (this platform's triage), `confidence` (only ever set with a
real basis -- `null` otherwise, never a fabricated number).

## Ingestion

| Method | Path | Permission |
|---|---|---|
| GET | `/ingestion/jobs` | `ingestion:read` |
| POST | `/ingestion/jobs` | `ingestion:run` |

`POST /ingestion/jobs` is a `multipart/form-data` request with two fields:
`source_id` (form field, not query param) and `file` (`.json` or `.csv`, ≤5MB).

Response `201` (the job always returns `201`, even when every record in the file
was rejected -- the job itself was created and run; look at `status` and
`error_summary` for the real outcome):
```json
{
  "id": "7b2742e8-...", "source_id": "593aeb24-...", "job_type": "json_upload",
  "status": "completed_with_errors",
  "accepted_count": 1, "rejected_count": 2, "duplicate_count": 1, "skipped_count": 0,
  "error_summary": [
    {"index": 1, "error": "missing required field(s): ['observed_at']"},
    {"index": 2, "error": "coordinate out of range: lat=999.0, lon=20.0"}
  ]
}
```

`status` values: `completed` (no rejects), `completed_with_errors` (at least one
reject, but the job still ran), `failed` (the file itself couldn't be parsed at
all -- unsupported extension, invalid JSON, oversized). A record's `external_id`
(or, if absent, a SHA-256 hash of its own content) is used to detect duplicates
both within the same upload and against previously-ingested events for that
source -- never silently re-accepted, never a hard failure either.

Records uploaded through this endpoint are always stored with
`"data_origin": "user_upload"` -- never `"synthetic_demo"`, which is reserved for
`scripts/seed.py`'s own rows.

## Investigations

| Method | Path | Permission |
|---|---|---|
| GET | `/investigations?status=<optional>` | `investigation:read` |
| POST | `/investigations` | `investigation:manage` |
| GET | `/investigations/{id}` | `investigation:read` |
| PATCH | `/investigations/{id}` | `investigation:manage` |

`POST /investigations`:
```json
{"title": "Repeated loitering near North Gate", "priority": "high", "linked_event_ids": ["..."]}
```
New investigations start `"status": "open"` and `"review_status": "not_reviewed"`.
`PATCH` accepts any subset of `{"title", "description", "status", "priority",
"assigned_user_id", "linked_event_ids", "evidence_refs", "review_status",
"resolution_notes"}`.

## Risk Assessments

| Method | Path | Permission |
|---|---|---|
| GET | `/risk-assessments?human_review_status=<optional>` | `risk:read` |
| GET | `/risk-assessments/{id}` | `risk:read` |
| POST | `/risk-assessments/{id}/review` | `risk:review` |

Read-only creation (seeded examples only; there is no real scoring
model yet -- see `docs/architecture/AI_ANALYTICS_CONTRACTS.md`). Every row carries
`method` (attribution -- never a bare score), `score_scale` (always
`"0-100 (uncalibrated; see docs/architecture/AI_ANALYTICS_CONTRACTS.md)"`), and
starts `"human_review_status": "pending"`.

`POST /risk-assessments/{id}/review`:
```json
{"human_review_status": "confirmed", "reviewer_notes": "optional"}
```
`human_review_status` must be one of `confirmed`, `overridden`, `dismissed` --
`pending` is rejected (`422`) as a review target, since "review" must be a real
decision, never a no-op back to the starting state.

## Audit

| Method | Path | Permission |
|---|---|---|
| GET | `/audit` | `audit:read` (administrator only by default) |

Returns this organization's records plus system-level records (`organization_id`
is `null` for e.g. a failed login against an unknown username). This is an
append-oriented application log, not a cryptographically tamper-evident one -- see
`docs/security/SECURITY_BASELINE.md`.

## Dashboard

| Method | Path | Permission |
|---|---|---|
| GET | `/dashboard/summary` | any authenticated user |

```json
{
  "total_events": 6, "events_last_24h": 2, "open_investigations": 1,
  "active_sources": 1, "active_sensors": 2, "pending_risk_reviews": 2,
  "ingestion_jobs_last_24h": 3, "synthetic_data_present": true
}
```
Every field is a real `COUNT()`/aggregate query run at response time -- never a
cached or hardcoded figure.

## Health

| Method | Path | Auth |
|---|---|---|
| GET | `/health/live` | none |
| GET | `/health/ready` | none |

`/health/live` → `{"status": "alive"}` always (process is up). `/health/ready` →
`{"status": "ready", "checks": {"database": "ok"}}` with HTTP `200`, or
`{"status": "not_ready", "checks": {"database": "error"}}` with HTTP `503` if a
real `SELECT 1` against the database fails.


## Additions

Model outputs, explanations, model evaluations, assessment scoring and review routes are documented in
[`ANALYTICS_API.md`](ANALYTICS_API.md). New permissions: `analytics:read`, `analytics:evaluate`,
`assessment:review`.


## Additions

Investigation lifecycle, members, links, evidence registration/integrity/provenance, timeline, notes, search,
relationships, export and dashboard routes are documented in
[`INVESTIGATION_WORKSPACE_API.md`](INVESTIGATION_WORKSPACE_API.md). New permission: `investigation:export`.
`GET /investigations` gained filters/sorting; `PATCH /investigations/{id}` status changes now follow the transition rules.
