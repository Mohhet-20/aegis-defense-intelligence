# Reporting and analytics API (`/api/v1/reporting`)
| Method & path | Permission | Notes |
|---|---|---|
| GET `/metrics?section=` | reporting:read | Metric catalog |
| GET `/analytics/{section}` | reporting:read + section permission | Query: `days` or `start`+`end`, `bucket` (auto/hour/day), `time_basis` (event/ingestion), `source_id`, `category`, `include_archived`. 422 on invalid; 404 unknown section |
| GET `/dashboards/executive` | reporting:read | 12 KPIs + nine sections, same filters |
| GET `/templates` | reporting:read | Templates, availability for caller, formats, retention |
| POST `/reports/validate` | report:generate | Resolves window/sections/required permissions; creates nothing |
| POST `/reports` | report:generate | 201 (new) / 200 (idempotent replay, `idempotency_key`); 403 missing section permission; 409 key reused with different parameters. A failed generation returns 201 with `status: failed` |
| GET `/reports?status=&template_key=&page=&page_size=` | reporting:read | Only reports the caller may read; page_size ≤ MAX_PAGE_SIZE |
| GET `/reports/{id}` | reporting:read | 404 if not visible |
| GET `/reports/{id}/download` | reporting:read | 409 if failed/expired/missing/hash mismatch |
| POST `/reports/purge-expired` | lifecycle:approve (admin) | Deletes expired files, marks `expired` |
Errors use `{detail, error_category, request_id}` and never include paths or stack traces.
