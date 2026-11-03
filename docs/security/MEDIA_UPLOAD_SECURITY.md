# Media Upload Security (Phase 4, Section 3)

Every control below runs, in order, for every upload, with no bypass
path -- `app/services/media_service.ingest_media()` is the **only**
function anywhere in this codebase that creates a `MediaAsset` row, and
it calls every one of these checks itself rather than trusting a caller
to have already done so.

## 1. Signature sniffing -- never trust the client

`app/cv/media_validation.sniff_signature()` reads the file's own first
bytes and decides what it actually is: PNG (`\x89PNG\r\n\x1a\n`), JPEG
(`\xff\xd8\xff`), or an ISO base media file (MP4/MOV family, detected via
the `ftyp` box at offset 4). **The client's `Content-Type` header and
the uploaded filename's extension are never consulted for this
decision** -- a file named `cat.png` whose bytes are actually an ELF
binary, a shell script, or anything else unrecognized is rejected with
`MediaValidationError` before any other processing, including before
the size check.

## 2. Size limits, checked before anything else touches the bytes

`validate_size()` rejects an empty upload (`byte_size <= 0`) and
anything over `settings.CV_MAX_IMAGE_UPLOAD_BYTES` (10MB) /
`CV_MAX_VIDEO_UPLOAD_BYTES` (75MB), by the type already determined in
step 1 -- so an attacker can't claim "image" to get the smaller limit's
scrutiny while uploading video-sized content, or vice versa.

## 3. Decompression-bomb / dimension guard

`Image.MAX_IMAGE_PIXELS = 500_000_000` is set at import time in
`media_validation.py` -- Pillow itself refuses to report `.size` for
anything past this, independent of and set deliberately above this
platform's own `CV_MAX_IMAGE_DIMENSION_PX` (6000px/side) check, so the
platform's own, more specific error message is the one an analyst
actually sees in the normal case; Pillow's guard is the backstop for a
truly extreme claim. `img.verify()` additionally raises on a
truncated/corrupt image stream without fully decoding the pixel buffer.
A video's dimensions are checked the same way, against
`CV_MAX_VIDEO_DIMENSION_PX` (4000px/side), after step 5's probe.

## 4. Content hashing and deduplication

`hashlib.sha256(content).hexdigest()` is computed over the raw bytes
once validation passes size/signature checks. A second upload of the
exact same bytes by the same organization returns the **existing** row
(`UniqueConstraint('organization_id', 'content_hash')` on `MediaAsset`)
rather than being re-validated, re-stored, and duplicated -- idempotent
by content, not by filename (two different filenames for the same bytes
dedupe; the same filename with different bytes does not).

## 5. Video duration cap, enforced at upload -- not at inference time

For video, `video_sampling.probe_video()` actually opens the file with
`cv2.VideoCapture` to measure real `fps`/`frame_count`/`width`/`height`/
`duration_seconds` -- a video whose real duration exceeds
`CV_MAX_VIDEO_DURATION_SECONDS` (600s / 10 minutes) is rejected **here**,
at upload, so a too-long video can never even become the subject of an
inference job later; `storage.delete()` removes the already-written
bytes on any post-write rejection (duration or dimension), so a rejected
upload never lingers on disk.

## 6. Content-addressed, private storage -- never a static file directory

`app/cv/storage.py`'s `storage_key` is always built from a
server-computed `organization_id` (a UUID) and `content_hash` (a sha256
digest) -- **never** from a client-supplied filename, so there is no
path-traversal input surface in the first place. `_resolve()` still
checks, unconditionally, via `os.path.commonpath` against the fully
`os.path.realpath`-resolved root, that the resolved path never escapes
the configured storage root (`PathTraversalError` if it would) --
defense in depth even though every caller in this codebase only ever
constructs a `storage_key` the safe way. `settings.CV_MEDIA_STORAGE_ROOT`
is **never** registered as a static file-serving directory in
`app/main.py` -- the only way to read media bytes back out is the
authenticated, organization-scoped `GET /api/v1/media/{id}/content`
route (`MEDIA_READ`), which calls `storage.read_bytes()`.

## 7. Display filename sanitization -- never the on-disk name

`sanitize_display_filename()` strips any path components (`/` or `\`)
and anything outside `[A-Za-z0-9._ -]`, truncated to 255 characters, and
is used **only** for what the UI shows the analyst (`declared_filename`)
-- the actual on-disk path is always the content-addressed
`storage_key` from step 6, never derived from this value at all.

## What this does NOT do

- Does not scan uploaded content for malware signatures -- out of scope
  for this phase; this platform's own controls are signature sniffing,
  size/dimension bounds, and never executing uploaded content (media
  bytes are only ever decoded by `PIL`/`cv2`, never `exec`'d, imported,
  or shelled out to).
- Does not fetch media from a URL the client supplies -- every upload
  arrives as a request body (`POST /api/v1/media`); there is no
  "ingest from this remote link" endpoint anywhere, by design (Section
  13's "no unrestricted remote media fetching").
- Does not virus-scan or sandbox video decoding -- `cv2.VideoCapture`
  runs against untrusted bytes with the standard risk profile of any
  OpenCV deployment; no additional isolation (a separate decode process,
  a seccomp sandbox) was added in this phase.
