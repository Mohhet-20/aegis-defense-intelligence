# MediaAsset Schema (Phase 4)

`app/models/media_asset.py` -- table `media_assets`. A securely-ingested
image or video file. Every row here passed real file-signature
sniffing, size/dimension/duration limits, and content hashing
(`app/services/media_service.py`) before it was ever written to disk or
inserted. See `docs/security/MEDIA_UPLOAD_SECURITY.md` for the full
validation pipeline this table's rows are the output of.

## Columns

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `organization_id` | FK -> organizations | Cascade delete. |
| `media_type` | `"image"` \| `"video"` | Decided by `app/cv/media_validation.sniff_signature()` from the real bytes, never the client's declared type. |
| `status` | `"stored"` \| `"rejected"` | In practice only `"stored"` rows ever exist -- a rejected upload raises `MediaValidationError` before any row is created (see "Rejected uploads" below). The column stays for forward compatibility with a future async validation path. |
| `rejection_reason` | string, nullable | Always NULL today, for the same reason. |
| `declared_filename` | string | **Display only.** Sanitized via `sanitize_display_filename()` (name-only, no path separators, no `..`) -- never used to build a filesystem path. |
| `detected_mime_type` | string | From the real byte signature: `image/png`, `image/jpeg`, or `video/mp4`. |
| `content_hash` | string(64) | sha256 hex digest of the raw bytes. |
| `storage_key` | string | `{organization_id}/{content_hash}.{ext}` -- the ONLY thing that ever becomes a real filesystem path (`app/cv/storage.py`), and it is built entirely from server-generated values. |
| `byte_size` | int | `CHECK (byte_size > 0)`. |
| `width_px` / `height_px` | int, nullable | Image: decoded dimensions. Video: first-frame dimensions. |
| `duration_seconds` / `frame_count` / `fps` | float/int, nullable | Video only -- real, measured values from `cv2.VideoCapture`, never estimated. |
| `uploaded_by_user_id` | FK -> users, SET NULL | |

## Constraints

- `UNIQUE (organization_id, content_hash)` -- a duplicate upload of the
  exact same bytes by the same organization returns the existing row
  (`media_service.ingest_media()`'s idempotent path) rather than
  creating a second one or erroring.
- `CHECK (byte_size > 0)`.

## Rejected uploads

A file that fails signature sniffing, size, dimension, or (for video)
duration/probe validation **never gets a row in this table and never
reaches disk** -- `media_service.ingest_media()` raises
`MediaValidationError` before `db.add()` is ever called. The rejection
itself is recorded as an `AuditRecord` (`action="media.upload_rejected"`)
by `app/api/routes/media.py`, not as a `MediaAsset` row. See
`tests/test_media_security.py::test_unrecognized_file_signature_is_rejected_and_never_stored`.

## What this does NOT do

- Never exposes `storage_key` or any real filesystem path to a client
  -- the only way to read content back is the authorized
  `GET /media/{id}/content` route (`app/api/routes/media.py`), which
  streams bytes through `media_service.read_media_content()`.
- Never serves media from a public/static directory -- `app/main.py`
  registers no `StaticFiles` mount for `settings.CV_MEDIA_STORAGE_ROOT`.
- Never trusts `file.filename` or `file.content_type` from the
  upload -- both are sniffed/sanitized server-side (see
  `docs/security/MEDIA_UPLOAD_SECURITY.md`).
- Never retains a second copy of the same bytes per organization
  (content-addressed dedup).
