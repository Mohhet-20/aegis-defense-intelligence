# File, Upload and Export Security (Phase 14)

Complements MEDIA_UPLOAD_SECURITY.md (earlier phases).

## Request size limits
`SizeLimitMiddleware` (pure ASGI) rejects with 413 using Content-Length and also counts streamed bytes:
- `/api/v1/media`: `MAX_UPLOAD_REQUEST_BYTES` (80 MB default)
- `/api/v1/ingestion/jobs`, `/api/v1/sensor-ingestion/batches`: `MAX_UPLOAD_BYTES` + 256 KiB
- everything else: `MAX_REQUEST_BODY_BYTES` (10 MB default)

## Uploads
- `read_bounded` (`app/core/uploads.py`) reads uploads in chunks and stops at the bound instead of loading unbounded bodies.
- Ingestion uploads are bounded at `MAX_REQUEST_BODY_BYTES`; an over-`MAX_UPLOAD_BYTES` file within that bound still produces a *failed job* (existing behaviour, preserved).
- Media type/content checks, safe filename handling and controlled storage ids come from the earlier media phase.

## Download
- Authorization by permission and organization (cross-org = 404).
- Stored SHA-256 is verified on download: mismatch -> 500 and a `media.integrity_failure` audit event; missing file -> 410.
- `media.content_access` audited (toggle `AUDIT_MEDIA_ACCESS`); `Cache-Control: no-store`.

## Exports
Export endpoints need dedicated export permissions (tested). Export row/size limits are those of the existing export features; no new global export size cap was added in Phase 14.

## Response headers
`SecurityHeadersMiddleware` (toggle `SECURITY_HEADERS_ENABLED`) sets nosniff, X-Frame-Options DENY, no-referrer, a restrictive Permissions-Policy, same-origin CORP and `Cache-Control: no-store` (unless a route sets its own). No CSP is set, and the SPA host is responsible for its own headers.

## Not done
Antivirus/content-disarm scanning, archive-bomb limits on archive uploads beyond size bounds, encryption at rest.
