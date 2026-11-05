# Environment Configuration

Settings live in `app/core/config.py` and are read from environment / `backend/.env`.

## Settings
| Setting | Default | Meaning |
|---|---|---|
| `PASSWORD_MIN_LENGTH` | 10 | Password policy minimum |
| `MAX_REQUEST_BODY_BYTES` | 10 MB | Default request cap |
| `MAX_UPLOAD_REQUEST_BYTES` | 80 MB | Media upload cap |
| `ENABLE_API_DOCS` | unset | Unset: docs on in development, off in production |
| `SECURITY_HEADERS_ENABLED` | true | Response security headers |
| `AUDIT_MEDIA_ACCESS` | true | Audit media downloads |
| `TRUST_FORWARDED_HEADERS` | false | Trust X-Forwarded-* (only behind a trusted proxy) |
| `AUDIT_RETENTION_DAYS` | 0 | 0 = no audit retention report threshold |
| `LIFECYCLE_REQUIRE_SEPARATE_APPROVER` | true | Four-eyes approval |
| `LIFECYCLE_SCENARIO_RUN_RETENTION_DAYS` | 180 | |
| `LIFECYCLE_SYNTHETIC_DATASET_RETENTION_DAYS` | 90 | |
| `LIFECYCLE_MEDIA_RETENTION_DAYS` | 0 | |
| `LIFECYCLE_MAX_BATCH` | 200 | |
| `COPILOT_CONVERSATION_RETENTION_DAYS` | existing | |

## Production checklist
- `ENVIRONMENT=production`. The app **refuses to start** with a default or <32-char `SECRET_KEY`, or wildcard CORS.
- Set explicit `CORS_ALLOWED_ORIGINS`; terminate TLS at a proxy; set `TRUST_FORWARDED_HEADERS` only if the proxy is trusted.
- Use a managed database (Postgres) with least-privilege app role; the audit triggers can be dropped by anyone with DDL rights.
- `seed.py` refuses to run in production; connector `allow_local_dev` is rejected in production.
- Docs/openapi are off in production unless `ENABLE_API_DOCS=true`.

## SECRET_KEY rotation
Changing `SECRET_KEY` invalidates **all** issued tokens (no key-id/multi-key support). Rotate during a maintenance window and expect all users to log in again. Per-user revocation is available via `token_version` without rotating the key.

## Caveats
- `Dockerfile`/`docker-compose.yml` contain development credentials; they must not be used as-is in production.
- Postgres was not executed in this environment; the Postgres trigger SQL is untested.
