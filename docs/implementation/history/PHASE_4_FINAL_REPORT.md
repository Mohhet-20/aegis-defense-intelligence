# Phase 4 -- Definition of Done &amp; Final Engineering Report

This is the one-time completion record for Phase 4 (Phase 4: Enterprise
Computer Vision Infrastructure, Image and Video Analytics, Model
Registry, Inference Pipelines, and Analyst Review Workspace). For the
living, continuously-updated status, see
[`../PROJECT_STATUS.md`](../PROJECT_STATUS.md) instead -- this file is a
snapshot of what was true at the end of this phase.

## Definition of Done -- checklist (26 items)

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Existing repo inspected before writing code | Done | `docs/architecture/COMPUTER_VISION_CONTRACTS.md`'s PLANNED `ModelRecord` row and `Evidence`'s reserved `"media_reference"` type both identified as reuse targets before any new model was written |
| 2 | No duplication of existing entities | Done | `ModelRecord` extended (3 new nullable columns) rather than a new `CVModel` table; `Evidence` extended (1 new FK) rather than a parallel evidence concept; `docs/architecture/COMPUTER_VISION_ARCHITECTURE.md`'s reuse table |
| 3 | `MediaAsset` domain model with real security controls | Done | `app/models/media_asset.py`; signature sniffing, size/dimension/duration limits, content-addressed storage, dedup by hash -- `docs/security/MEDIA_UPLOAD_SECURITY.md` |
| 4 | CV model registry extending `ModelRecord` | Done | `task_type`/`adapter_key`/`supported_media_types` columns; `docs/ml/MODEL_REGISTRY.md` |
| 5 | Closed adapter allow-list -- no arbitrary code execution from a DB row | Done | `app/cv/adapters/registry.py`'s hand-written `_FACTORIES` dict, never a dynamic `importlib` call |
| 6 | At least one mock adapter | Done | `MockDetectionAdapter` -- deterministic, sha256-hash-derived boxes, never claims real inference |
| 7 | At least one real adapter if the environment supports it, OR a documented, honest failure | Done | `OpenCVHOGPersonAdapter` -- genuinely real CPU-only inference; YOLO/torch explicitly evaluated and documented as not viable here (`docs/ml/MODEL_ADAPTERS.md`) |
| 8 | End-to-end image detection pipeline | Done | `inference_service.submit_inference_job()` (`job_type="image_detection"`), tested end-to-end in `tests/test_image_inference.py` |
| 9 | Bounded video frame analysis -- explicitly not surveillance, not re-identification | Done | `app/cv/video_sampling.py` -- sequential, capped sampling; `docs/ml/VIDEO_FRAME_ANALYSIS.md`'s explicit non-goals section |
| 10 | Detection postprocessing with real NMS | Done | `app/cv/postprocessing.py`, `cv2.dnn.NMSBoxes()`, not hand-rolled math |
| 11 | Class-label allow-list -- no identity/hostile-intent labels, structurally | Done | `ALLOWED_CLASS_LABELS` in `app/models/detection_result.py`, enforced in `postprocessing.py` before persistence |
| 12 | Model evaluation against a real or clearly-labelled-synthetic dataset | Done | `app/cv/synthetic_eval_fixture.py` + `evaluation_service.py`; every run stamps `is_synthetic=True`; `docs/ml/MODEL_EVALUATION.md` |
| 13 | Deep lineage: Media asset → Inference job → Model/version → Detection result → Evidence reference → Analyst review | Done | Every FK present and tested end-to-end in `tests/test_detection_review_and_evidence.py` |
| 14 | Never auto-promote a detection to Evidence | Done | `detection_review_service.promote_to_evidence()` raises unless `review_status == "confirmed"`, tested for both `unreviewed` and `rejected` |
| 15 | Expanded backend API | Done | 5 new routers (`media`, `cv_models`, `inference`, `detections`, `evaluation`); `docs/api/COMPUTER_VISION_API.md` |
| 16 | Background job execution reusing existing job patterns | Done (stated honestly) | `InferenceJob` runs synchronously, identical lifecycle shape to `IngestionJob`/`FusionJob` -- no new async infra invented, none claimed |
| 17 | Full CV Analyst Workspace (8 sections) | Done | 9 frontend pages: overview, media library, image detection, video analysis, model registry, inference job monitor/detail, evaluation workspace, CV evidence links |
| 18 | No facial recognition, biometric matching, automated person ID, hostile-intent classification, autonomous targeting | Done | Structurally enforced by `ALLOWED_CLASS_LABELS` + the adapter contract; `docs/ml/MODEL_ADAPTERS.md`/`docs/data/DETECTION_RESULT_SCHEMA.md` state it explicitly |
| 19 | No arbitrary model downloads, no arbitrary code execution, no unrestricted remote media fetching | Done | Closed adapter allow-list (item 5); no "ingest from URL" endpoint exists anywhere; synthetic eval fixture generated in-process, never fetched |
| 20 | Observability: liveness vs. readiness distinguished | Done | `check_model_runtime()`/`check_media_storage()` added to `/health/ready`; `/health/live` untouched, verified by a test that would fail if it touched a dependency |
| 21 | Exhaustive testing, including honest reporting if a real model can't be installed | Done | 64 new tests (291 total), 91% coverage; `docs/ml/MODEL_ADAPTERS.md` documents the YOLO/torch installation failure with its exact evidence (403, CUDA chain size) |
| 22 | 12 new required doc files | Done | All 12 written -- see Section 3 below for the full list |
| 23 | DB migration preserves existing data | Done | upgrade/downgrade/re-upgrade cycle run against the real dev DB; pre-existing `demo-risk-scorer` row backfilled correctly (Section 4 below) |
| 24 | Automated backend tests, actually run | Done | 291 passed, 91% line coverage -- re-run in this final pass after fixing a drifted dependency pin (Section 11) |
| 25 | Frontend checks, actually run | Done | `tsc -b --force` clean, `eslint .` 0 new warnings/errors, `npm run build` succeeded -- re-run in this final pass |
| 26 | Documentation updated to match reality, including updating `COMPUTER_VISION_CONTRACTS.md`/`../PROJECT_STATUS.md`/`../MASTER_ROADMAP.md` | Done | `COMPUTER_VISION_CONTRACTS.md` marked superseded (historical content kept); `../PROJECT_STATUS.md` fully rewritten; `../MASTER_ROADMAP.md` Phase 4 sections added |

## Final Engineering Report (15 points)

**1. Repository state before this phase's changes.** The real Phase
1+2+3 deliverable, unmodified at the start of this session: a 25-model
backend (13 from Phase 1, 7 from Phase 2, 5 from Phase 3), 227
passing backend tests at 90% coverage, a 24-page frontend, and accurate
`../PROJECT_STATUS.md`/`../MASTER_ROADMAP.md` handoff records, including
`docs/architecture/COMPUTER_VISION_CONTRACTS.md`'s own PLANNED sketch
for exactly this phase. Nothing was missing or had to be reconstructed.

**2. Components reused vs. newly introduced.** Reused, extended in
place: `ModelRecord` (Phase 1 -- gained `task_type`/`adapter_key`/
`supported_media_types`, its pre-existing seeded row untouched in every
other respect), `Evidence` (Phase 3 -- gained `detection_result_id`,
its `"media_reference"` type was already reserved for this exact
purpose), the synchronous job-execution shape itself (`InferenceJob`
follows the identical lifecycle vocabulary as Phase 2's
`IngestionJob`/Phase 3's `FusionJob`, no new state machine invented),
`audit_service.record()` (every new mutating route uses it unchanged),
and the health-check readiness pattern (`check_database`, now joined by
two new per-dependency checks following the same shape). Newly
introduced: `MediaAsset`, `InferenceJob`, `DetectionResult`,
`ModelEvaluationRun`, the entire `app/cv/` package (storage, media
validation, video sampling, postprocessing, synthetic fixture, two
adapters plus the allow-list registry), and 5 new service modules --
see `docs/architecture/COMPUTER_VISION_ARCHITECTURE.md` for why each one
earns its own table/module rather than overloading an existing one.

**3. Files created or changed.** Backend, new: 4 models
(`media_asset.py`, `inference_job.py`, `detection_result.py`,
`model_evaluation_run.py`), the `app/cv/` package (10 files across
`storage.py`, `media_validation.py`, `video_sampling.py`,
`postprocessing.py`, `synthetic_eval_fixture.py`, and
`adapters/{base,mock_adapter,opencv_hog_adapter,registry}.py`), 5
services (`media_service.py`, `model_registry_service.py`,
`inference_service.py`, `detection_review_service.py`,
`evaluation_service.py`), 5 schema modules, 5 route modules, 1 Alembic
migration, 8 new test files (64 new tests). Backend, modified:
`config.py` (11 new `CV_*` settings), `.env.example` (mirrored),
`requirements.txt` (added `pillow`, `numpy`, pinned
`opencv-python-headless==4.14.0.94`), `security.py` (9 new
permissions), `main.py` (5 new routers), `models/__init__.py`,
`models/model_record.py`, `models/evidence.py`, `schemas/evidence.py`,
`services/health_service.py`, `api/routes/health.py`, `scripts/seed.py`
(2 new `ModelRecord` rows), `tests/conftest.py` (CV fixtures + storage
isolation). Frontend, new: `components/cv/BoundingBoxOverlay.tsx`, 9
pages under `pages/cv/`. Frontend, modified: `types/api.ts`,
`api/client.ts`, `App.tsx`, `AppShell.tsx`, `DashboardPage.tsx`,
`HealthPage.tsx`. Docs, new: 12 files (listed in point 3 of the DoD
table's evidence columns, full list in `../PROJECT_STATUS.md` Section 5).
Docs, modified: `COMPUTER_VISION_CONTRACTS.md`, `../MASTER_ROADMAP.md`,
`README.md`, `../PROJECT_STATUS.md`.

**4. Migrations.** One new Alembic migration,
`c6553f99283a_phase4_computer_vision_media_models_....py` --
autogenerated then hand-fixed: the new `evidence_items.
detection_result_id` foreign key is added via
`op.batch_alter_table('evidence_items', ...)` with an explicit
constraint name (`fk_evidence_items_detection_result_id` -- SQLite
cannot `ALTER TABLE ... ADD CONSTRAINT` directly, and Alembic's
autogenerated unnamed-constraint drop would otherwise fail on
downgrade); the new NOT NULL `model_records.supported_media_types`
column gets `server_default='[]'` (conditionally dropped for
non-sqlite dialects) so the pre-existing `demo-risk-scorer` row
backfills correctly. Verified against the real dev `aegis.db` (not a
throwaway copy) in this session: backed up, ran `alembic upgrade head`,
confirmed all pre-existing data survived with correctly backfilled
defaults, ran `alembic downgrade -1` and confirmed the data was still
intact and the new tables/columns were gone, ran `alembic upgrade head`
again and confirmed `head` was reached cleanly. Backup deleted after
verification.

**5. API routes implemented.** 14 new routes across 5 routers:
`POST/GET /media`, `GET /media/{id}`, `GET /media/{id}/content`;
`POST/GET /cv/models`, `GET /cv/models/{id}`; `POST/GET /inference/jobs`,
`GET /inference/jobs/{id}`, `GET /inference/jobs/{id}/detections`,
`POST /inference/jobs/{id}/retry`; `POST /detections/{id}/review`,
`POST /detections/{id}/promote-to-evidence`; `POST/GET
/evaluation/runs`, `GET /evaluation/runs/{id}` -- full table with
exact permissions and request/response shapes in
`docs/api/COMPUTER_VISION_API.md`. `GET /health/ready` modified to
report `media_storage`/`model_runtime` individually alongside
`database`.

**6. Model adapters implemented.** Two, behind a common
`CVModelAdapter` Protocol: `MockDetectionAdapter`
(`mock_detector_v1`) -- fully synthetic, deterministic (sha256-hash-
derived boxes), class `"mock_object"`, exists so the whole pipeline is
testable with zero real CV capability. `OpenCVHOGPersonAdapter`
(`opencv_hog_person_v1`) -- **genuinely real**, pretrained, CPU-only
inference using OpenCV's bundled HOG+SVM person detector, class
`"person"`, zero network fetch ever. Both resolved only through the
closed `_FACTORIES` allow-list in `app/cv/adapters/registry.py` -- a
`ModelRecord.adapter_key` can never execute arbitrary code.

**7. Supported media formats and limits.** Images: PNG, JPEG (sniffed
by real file signature, never by extension/Content-Type), up to 10MB
and 6000px/side. Video: MP4 (ISO base media file format, `ftyp` box
sniffed), up to 75MB, 4000px/side, and 600 seconds (10 minutes)
duration -- the real duration/dimensions are measured by actually
opening the file with `cv2.VideoCapture`, never trusted from a header
claim. A video inference job samples at most `CV_VIDEO_MAX_FRAMES_PER_JOB`
(30, server-clamped unconditionally) frames at a configurable interval
(default 2.0s). Every one of these is a validated `Settings` field in
`app/core/config.py`, not a hardcoded constant.

**8. Frontend workflows implemented.** CV Overview (live counts: media
assets, active models, recent jobs, pending reviews). Media Library
(upload, list, metadata, content download). Image Detection Workspace
(select media + model, submit a job, view results with a responsive
SVG bounding-box overlay color-coded by review status, review
individual detections). Video Analysis Workspace (same submission flow
for video, results shown as a frame-indexed data table rather than an
extracted-frame overlay -- see point 13). Model Registry (list/register,
admin-gated). Inference Job Monitor (list/filter all jobs) and Job
Detail (full detection list, retry action). Evaluation Workspace
(run an evaluation, view precision/recall/F1/mean-IoU history per
model, always labelled synthetic). CV Evidence Links (detections
promoted to Evidence, with a link back to the originating job/model).
All 9 pages call the real backend through the extended `api/client.ts`
-- `tsc -b --force` and a production `npm run build` both succeeded
against those actual types.

**9. Security controls implemented.** Signature sniffing (never trusts
filename/Content-Type), size/dimension/duration limits enforced before
storage, content-hash dedup, content-addressed storage with
traversal-safe path resolution (`os.path.commonpath` check, never
reachable in practice since every caller builds `storage_key` from a
server-generated hash, but checked unconditionally anyway), media
bytes never served from a static directory (the only read path is an
authenticated `GET /media/{id}/content`). A closed adapter allow-list
(point 6) making arbitrary-code-execution-via-registration
structurally impossible. A fixed class-label allow-list
(`ALLOWED_CLASS_LABELS`) making identity/hostile-intent/biometric
labels structurally impossible to persist. Never-auto-promote
enforcement in code (point 14 of the DoD table). 9 new `Permission`
values, least-privilege per role (`MODEL_MANAGE` admin-only
specifically because `adapter_key` determines executable code).
Every mutating route audited via the same `AuditRecord` mechanism as
every prior phase. No new authentication mechanism, no change to how
tokens are issued or validated.

**10. Tests actually executed, and their results.** From `backend/`,
with the venv active: `pip install -r requirements.txt` (necessary in
this final pass -- see point 11) then `python -m pytest -q --cov=app
--cov-report=term-missing`: **291 passed, 0 failed, 91% line coverage**
(227 carried over from Phase 1+2+3, unchanged and still passing, plus
64 new this phase across 8 new test files -- full per-file breakdown
in `docs/testing/COMPUTER_VISION_TEST_STRATEGY.md`). Frontend, from
`frontend/`: `npx tsc -b --force` clean; `npx eslint .` → 0 errors, 1
pre-existing warning (`AuthContext.tsx`, unmodified since the Phase 1
baseline, not a regression); `npm run build` → succeeded (375.56 kB
JS / 107.19 kB gzip, 15.98 kB CSS / 3.76 kB gzip).

**11. Whether real inference actually ran, stated plainly.** Yes, both
ways. The mock adapter ran deterministically end-to-end
(`tests/test_image_inference.py::test_image_detection_job_with_mock_adapter_end_to_end`).
**The real, non-mock `OpenCVHOGPersonAdapter` also actually ran** --
`test_real_opencv_hog_adapter_runs_to_completion_without_crashing`
instantiates it and runs genuine `cv2.HOGDescriptor` inference against
a real decoded frame. This is not a claim taken on faith: this exact
test caught a real regression during this final verification pass --
the sandbox's `.venv` had drifted to the unpinned
`opencv-python-headless` 5.0.0 (which removed `HOGDescriptor` from its
Python bindings entirely) between sessions, causing 3 test failures
including this one. The fix, confirmed by re-running the full suite
afterward, was `pip install -r requirements.txt` (which re-applies the
`4.14.0.94` pin already correctly recorded in `requirements.txt` --
nothing about the pin itself was wrong, only what was actually
installed in that moment). This is now documented in `README.md`'s
troubleshooting section and `../PROJECT_STATUS.md` Section 9 specifically
so a future session hitting the same symptom fixes it the same way
rather than re-investigating from scratch.

**12. Hardware/runtime actually detected in this sandbox.** CPU-only,
no GPU/CUDA available or assumed. Both shipped adapters run on CPU by
construction. `pip install torch --index-url
https://download.pytorch.org/whl/cpu` returns **403 Forbidden** through
this environment's proxy (confirmed by actually running the command);
the default PyPI `torch` package pulls a multi-gigabyte CUDA
dependency chain (`nvidia-cublas`, `nvidia-cudnn`, `nvidia-cusolver`,
etc.) unnecessary for CPU inference and large enough to risk exhausting
this session's disk allowance. This is why Ultralytics YOLO was
evaluated and explicitly not used -- see `docs/ml/MODEL_ADAPTERS.md`
for the full writeup, written at the time the attempt was made, not
reconstructed after the fact.

**13. Known failures / remaining limitations.** Classical HOG+SVM
detection is meaningfully weaker than a modern deep detector --
`test_real_opencv_hog_adapter_runs_to_completion_without_crashing`
deliberately asserts only "completes, schema-valid output," never a
specific detection count, for exactly this reason. No background
worker/task queue for inference jobs -- every job still runs
synchronously inside its own API request. No frame-thumbnail/
extracted-image endpoint for video (detections shown as a data table,
not an overlay on an extracted frame). No object-storage backend,
retention policy, or storage quota for uploaded media. No evaluation
against a real, labelled, operational dataset -- only the deterministic
synthetic fixture exists. No browser-driven end-to-end smoke test for
the 9 new frontend pages. The `opencv-python-headless` venv-drift issue
from point 11 is an environment-reproducibility risk worth flagging to
whoever operates this sandbox across sessions, not just a one-time fix.

**14. Features explicitly deferred (deliberately, and documented as
such rather than silently dropped).** Tracking or re-identification
across frames or media assets -- no `track_id`-like concept anywhere
in this schema; this is explicitly Phase 5's job, and
`docs/architecture/COMPUTER_VISION_CONTRACTS.md`'s
`TrackIdentifier`/`TrackObservation` sketch is kept, unmodified, for
exactly that future work. A second real deep-learning adapter (point
12 explains why). A per-job worker-pool concurrency limit (vs. this
phase's actual "bounded work per job" caps). Any facial
recognition, biometric matching, automated person identification, or
hostile-intent classification -- not deferred as "not yet built" but
structurally excluded by design (the class-label allow-list and the
adapter contract have no path to produce these even if a future
adapter tried).

**15. Exact recommended scope for Phase 5.** Phase 5 is **Tracking and
Re-Identification**. (a) Read this file, `../PROJECT_STATUS.md`, and
`docs/architecture/COMPUTER_VISION_CONTRACTS.md`'s still-live
`TrackIdentifier`/`TrackObservation` sketch before writing any code.
(b) Extend `DetectionResult` with a track-assignment relationship
rather than duplicating it -- a `TrackObservation` row linking one
`TrackIdentifier` to one `DetectionResult`, with its own confidence
distinct from the detection's own confidence, exactly as the Phase 1
contract doc already specifies. (c) Re-identification is privacy-
sensitive by nature -- any face/gait/biometric matching capability
needs an explicit, deliberate, documented decision at the start of that
phase's work, not an incidental consequence of adding a `track_id`
column; the existing `ALLOWED_CLASS_LABELS`-style allow-list pattern
used in this phase is a reasonable template for whatever privacy
control Phase 5 needs. (d) Before trusting bare `pytest`/`cv2` behavior
in that session, run `pip install -r requirements.txt` first -- don't
assume the pin from `requirements.txt` is what's actually installed
(point 11). (e) If a future phase needs a second real deep-learning
adapter, re-check whether the PyTorch CPU wheel index is reachable in
that environment before assuming it can simply be `pip install`ed --
it was not reachable in this one. (f) This file's successor
(`PHASE_5_FINAL_REPORT.md`) and `../PROJECT_STATUS.md` must both be
updated again at the end of Phase 5, in place, following the same
"only claim what was actually run" discipline.
