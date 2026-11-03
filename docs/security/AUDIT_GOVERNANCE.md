# Audit governance (Phase 14)

## What an audit record contains
`audit_records`: `id` (event id), `created_at` (timestamp, UTC), `actor_user_id`, `organization_id`, `action`, `target_type` + `target_id` (resource), `outcome` (`success` | `failure` | `denied`), `request_id` (correlation id, also returned in the `X-Request-ID` header and in error bodies), `context_metadata` (JSON; before/after values where relevant, e.g. `user.update` stores `before`/`after`/`sessions_revoked`).

## Audit ≠ application log
Audit rows are database records written in the request's transaction; ordinary logs (`aegis.*` loggers) are operational telemetry. Request bodies are never logged. Failed-login audit rows store only a short SHA-256 prefix and the length of the identifier — never the identifier or password.

## Coverage
Authentication (`auth.login`, `auth.password_change`, `auth.sessions_revoked`), account and permission changes (`user.create`, `user.update` with before/after, `user.password_reset`), denied authorization (`authz.denied`), data sources (`source.*`), ingestion (`ingestion.run/retry`, `sensor_ingestion.*`), evidence (`evidence.create/update/register/verify_integrity/supersede/review_status_change`), investigations (create/update/transition/members/links/notes/export), assessments (create/update/link/score/review/supersede), relationships/conflicts, detections/inference/tracking/evaluation, devices & fleet (`device.*`, `fleet.*`, `edge_*`), scenarios (`scenario.*`, `dataset.generate`), copilot/retrieval (`copilot.ask` — **query length and result counts, not the question text**; `retrieval.*`), exports (`event.export`, `geospatial.export`, `investigation.export`, `scenario.export`), media (`media.upload`, `media.upload_rejected`, `media.content_access`, `media.integrity_failure`), geospatial candidate generation, and lifecycle (`lifecycle.request/approve/reject/cancel/delete/archive/cleanup_failed/cleanup_completed`).
**Not audited:** ordinary reads of records (only media downloads, exports, retrieval document opens and copilot questions are), and non-mutating validation calls. `GET /audit` itself is not audited.

## Redaction
`audit_service.record` passes every `context_metadata` through `redact()`: keys named `password`, `new_password`, `current_password`, `password_hash`, `secret`, `api_key`, `authorization`, `access_token`, `refresh_token`, `cookie`, `client_secret`, `private_key` (or ending `_password`, `_secret`, `_api_key`, `_private_key`) are replaced by `[REDACTED]`; strings are truncated at 2 000 characters; nesting is capped. This is a safety net, not a reason to pass sensitive data.

## Append-only — what is and is not protected
| Layer | Protection | Defeated by |
|---|---|---|
| API | No route updates or deletes audit rows (`GET` only; test walks the route table). | — |
| ORM | `before_update` / `before_delete` listeners raise `AuditImmutableError`. | Raw SQL, Core bulk statements, `session.execute(delete(...))`. |
| Database (migration `a14c0de5ec01`) | SQLite / PostgreSQL triggers abort `UPDATE` and `DELETE` on `audit_records`. Verified on SQLite (`test_sqlite_trigger_blocks_raw_sql_modification_after_migration`). **The PostgreSQL trigger SQL was written but not executed in this environment.** | A DBA / table owner can `DROP TRIGGER`, `TRUNCATE`, or drop the table. Databases created with `Base.metadata.create_all()` (tests, `scripts/seed.py`) do not get the triggers. |

**Therefore: privileged database administrators can modify or remove audit history, and the application cannot detect it.** The log is *append-oriented*, not tamper-proof or tamper-evident, and carries no legal certification. Hash-chaining / external write-once shipping would be needed for that (see `KNOWN_RISKS.md`).

## Write-failure policy
* Mutations write the audit row **in the same transaction** as the change. If the audit insert fails the exception propagates and the change is rolled back ("fail closed"). Verified for user create/update and lifecycle execute.
* Exception: the `authz.denied` recorder is best-effort — failing to record a denial must not change a 403 into a 500; the failure is logged (`aegis.security`).
* Some older services commit their own change before the route writes its audit row. Phase 14 converted user create/update; others retain the old ordering, so in those paths an audit failure after the commit can leave an unaudited change (it would surface as a 500). Remaining ones are listed in `KNOWN_RISKS.md`.

## Access
`audit:read` is administrator-only; results are limited to the caller's organization. Filters: action (exact/prefix), outcome, actor, resource type/id, request id, time range; `page_size` ≤ 200. `GET /audit/actions` lists distinct actions for the UI. There is no audit export endpoint.

## Retention
The application never deletes audit rows. `AUDIT_RETENTION_DAYS` (0 = keep forever) only drives `GET /lifecycle/audit-retention`, a count of rows older than the window that an operator could archive externally under their own procedure.
