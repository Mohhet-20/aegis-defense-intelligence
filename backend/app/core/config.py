"""Central settings, read from environment / .env (see .env.example).
DATABASE_URL defaults to a local SQLite file so the project runs with
zero external setup (Section 5 spec explicitly allows
this); set it to a postgresql+psycopg2://... URL for a real deployment
-- no code changes needed, see docs/architecture/ARCHITECTURE_DECISIONS.md."""
from __future__ import annotations

from functools import lru_cache

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "sqlite:///./aegis.db"

    SECRET_KEY: str = "dev-only-secret-change-me-in-production"
    # Key rotation grace period: comma-separated former SECRET_KEYs that are still
    # accepted to VERIFY tokens (never to sign). Remove them once the longest token
    # lifetime (REFRESH_TOKEN_EXPIRE_MINUTES) has passed since the rotation.
    SECRET_KEY_PREVIOUS: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Browser sessions keep the refresh token in an HttpOnly cookie (see app/api/routes/auth.py).
    # None = Secure flag on in production, off in development (plain-http localhost).
    AUTH_COOKIE_SECURE: Optional[bool] = None
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    RATE_LIMIT_AUTH: str = "10/minute"  # login and password change (credential guessing)
    # /auth/refresh needs a valid signed refresh cookie, so it is not a guessing target;
    # browsers call it on every full page load, so it gets a separate, higher limit.
    RATE_LIMIT_REFRESH: str = "120/minute"
    RATE_LIMIT_DEFAULT: str = "120/minute"

    # --- security / governance -------------------------------
    # Password policy applies to NEW passwords only (create / change);
    # existing hashes keep working. Length is counted in characters.
    PASSWORD_MIN_LENGTH: int = 10
    # Request-body ceilings enforced by SizeLimitMiddleware BEFORE the
    # handler runs. Upload routes (media + file ingestion) get the larger
    # ceiling; everything else is capped at the smaller one.
    MAX_REQUEST_BODY_BYTES: int = 10 * 1024 * 1024
    MAX_UPLOAD_REQUEST_BYTES: int = 80 * 1024 * 1024
    # None => API docs/openapi are served outside production only.
    ENABLE_API_DOCS: Optional[bool] = None
    SECURITY_HEADERS_ENABLED: bool = True
    # Record an audit row each time media bytes are downloaded (sensitive_source data).
    AUDIT_MEDIA_ACCESS: bool = True
    # Only honour X-Forwarded-For when the app sits behind a proxy you
    # control. Off by default (rate limiting then keys on the socket peer).
    TRUST_FORWARDED_HEADERS: bool = False
    # With TRUST_FORWARDED_HEADERS: how many proxies YOU control append to
    # X-Forwarded-For. The client address is that many entries from the right, so
    # values a client puts at the left of the header are never used.
    TRUSTED_PROXY_HOPS: int = 1

    # --- public demo / single-container hosting -----------------------
    # DEMO_MODE: a public showcase. The seeded demo accounts (documented password)
    # may be created in production, cannot be locked out, and cannot have their
    # password, role, status or sessions changed by visitors; /api/v1/demo tells the
    # sign-in page which accounts to offer. Never enable it on a deployment that
    # holds real data.
    DEMO_MODE: bool = False
    # Informational, shown on the sign-in page: how often the demo data is reset (0 = never).
    DEMO_RESET_HOURS: int = 0
    # Serve the built frontend (frontend/dist) from this process, for one-container
    # hosting. Empty = API only (nginx serves the frontend in docker-compose).
    FRONTEND_DIST_DIR: str = ""
    # File holding the Content-Security-Policy for the frontend's HTML, generated at
    # build time from frontend/nginx.conf (same policy nginx serves). Empty = built-in default.
    FRONTEND_CSP_FILE: str = ""
    # Origins allowed to embed the frontend in a frame (e.g. https://huggingface.co for a
    # Hugging Face Space page). Empty = framing forbidden.
    FRONTEND_FRAME_ANCESTORS: str = ""
    # Audit retention is REPORT-ONLY: the application never deletes audit
    # rows. 0 disables the eligibility report.
    AUDIT_RETENTION_DAYS: int = 0
    # Lifecycle (retention / deletion) -- see docs/security/DATA_LIFECYCLE.md
    LIFECYCLE_REQUIRE_SEPARATE_APPROVER: bool = True
    LIFECYCLE_SCENARIO_RUN_RETENTION_DAYS: int = 180
    LIFECYCLE_SYNTHETIC_DATASET_RETENTION_DAYS: int = 90
    LIFECYCLE_MEDIA_RETENTION_DAYS: int = 0  # 0 = media never auto-eligible
    LIFECYCLE_MAX_BATCH: int = 200

    # --- retrieval + copilot ---------------------------------
    # Generation/embedding providers are OFF by default. Nothing leaves the
    # server unless COPILOT_PROVIDER names a provider, COPILOT_API_KEY is
    # set AND COPILOT_ALLOW_EXTERNAL=true (an explicit data-egress opt-in).
    COPILOT_PROVIDER: str = "none"  # none | anthropic
    COPILOT_ALLOW_EXTERNAL: bool = False
    COPILOT_API_KEY: str = ""
    COPILOT_MODEL: str = ""
    COPILOT_BASE_URL: str = "https://api.anthropic.com"
    COPILOT_TIMEOUT_SECONDS: float = 20.0
    COPILOT_MAX_RETRIES: int = 1
    COPILOT_MAX_OUTPUT_TOKENS: int = 1200
    COPILOT_MAX_QUESTION_CHARS: int = 2000
    COPILOT_CONTEXT_CHUNKS: int = 8
    COPILOT_RATE_LIMIT_PER_MINUTE: int = 20
    COPILOT_CONVERSATION_RETENTION_DAYS: int = 90
    EMBEDDING_PROVIDER: str = "none"  # none: semantic search unavailable
    RETRIEVAL_CHUNK_CHARS: int = 1200
    RETRIEVAL_CHUNK_OVERLAP: int = 120
    RETRIEVAL_MAX_DOC_CHARS: int = 200_000
    RETRIEVAL_MAX_FILE_BYTES: int = 1_000_000
    RETRIEVAL_MAX_QUERY_CHARS: int = 500
    RETRIEVAL_MAX_CANDIDATES: int = 2000
    RETRIEVAL_MAX_RESULTS: int = 50
    RETRIEVAL_INDEX_TIMEOUT_SECONDS: float = 60.0
    RETRIEVAL_TOMBSTONE_DAYS: int = 30
    RETRIEVAL_MAX_INDEX_RECORDS: int = 5000

    # Scenario simulation limits (all enforced server-side)
    SCENARIO_MAX_RUN_SECONDS: float = 20.0       # wall-clock budget per simulation run
    SCENARIO_MAX_SWEEP_SECONDS: float = 45.0     # budget for a whole sensitivity sweep
    SCENARIO_STALE_RUN_SECONDS: int = 300        # 'running' rows older than this are failed
    SCENARIO_MAX_SCENARIOS_PER_ORG: int = 500
    SCENARIO_MAX_RUNS_PER_SCENARIO: int = 200
    SCENARIO_MAX_DATASETS_PER_ORG: int = 200
    SCENARIO_MAX_RESULT_BYTES: int = 400_000     # serialized result cap

    MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_MINUTES: int = 15

    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 200

    MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024  # 5 MB

    CORS_ALLOWED_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- multisource intelligence fusion ---------
    # "configurable defaults through validated application
    # settings rather than scattered hard-coded constants." These are
    # fusion_service.py's/graph_service.py's defaults; every one of them
    # can still be overridden per-call (e.g. a specific /fusion/run
    # request), same as the correlation_service already allowed.
    FUSION_TIME_WINDOW_SECONDS_DEFAULT: int = 30 * 60  # 30 minutes
    # Per-event-type overrides layered on top of the default above --
    # JSON object string, e.g. '{"sensor_offline": 3600}'. An event type
    # not listed here just uses the default; this is never a silent
    # fallback to "no window at all" (unbounded time windows are never
    # allowed -- see TEMPORAL_CORRELATION.md).
    FUSION_TIME_WINDOW_SECONDS_BY_TYPE: str = "{}"
    FUSION_SPATIAL_THRESHOLD_METERS_DEFAULT: float = 500.0
    # A LARGER distance than the correlation threshold above -- used by
    # conflict_service to flag "these were already correlated via a
    # non-spatial signal, but their reported locations disagree by more
    # than this" as a genuine conflict, not to find new candidates.
    FUSION_SPATIAL_CONFLICT_THRESHOLD_METERS: float = 5000.0
    # Comma-separated attribute keys treated as identifier-like for
    # identifier_service's namespaced comparison -- an
    # explicit, documented allow-list, never "compare every JSON key."
    FUSION_IDENTIFIER_ATTRIBUTE_KEYS: str = "serial_number,tail_number,call_sign,imei,vehicle_id,device_id"
    FUSION_MAX_EVENTS_PER_RUN: int = 2000
    # Evidence graph traversal bounds ("prevent unbounded
    # graph queries", "avoid loading the entire dataset into the
    # browser").
    FUSION_GRAPH_MAX_DEPTH: int = 3
    FUSION_GRAPH_MAX_NODES: int = 150

    # --- computer vision infrastructure ----------
    # media is NEVER served from a public static directory --
    # this is a private, server-controlled filesystem root the app reads
    # and writes through app/cv/storage.py only. Relative to the backend
    # process's working directory, same convention as DATABASE_URL's
    # sqlite:///./aegis.db.
    CV_MEDIA_STORAGE_ROOT: str = "./media_storage"
    # Separate caps per media type -- a video legitimately needs to be
    # much larger than an image, and conflating the two limits would
    # force one bad default for both.
    CV_MAX_IMAGE_UPLOAD_BYTES: int = 10 * 1024 * 1024  # 10 MB
    CV_MAX_VIDEO_UPLOAD_BYTES: int = 75 * 1024 * 1024  # 75 MB
    # Rejects a decoded image whose width or height exceeds this --
    # guards against decompression-bomb-style images that are tiny on
    # disk but enormous once decoded.
    CV_MAX_IMAGE_DIMENSION_PX: int = 6000
    CV_MAX_VIDEO_DIMENSION_PX: int = 4000
    # Bounded video frame sampling ("NOT continuous
    # real-time surveillance") -- a video job only ever samples frames
    # at this interval, up to this many frames total, never every frame
    # and never the whole decoded video held in memory at once.
    CV_VIDEO_FRAME_SAMPLE_INTERVAL_SECONDS: float = 2.0
    CV_VIDEO_MAX_FRAMES_PER_JOB: int = 30
    CV_MAX_VIDEO_DURATION_SECONDS: float = 600.0  # 10 minutes
    # Detection postprocessing/validation defaults -- always
    # overridable per inference-job request, same pattern the
    # FUSION_* defaults already established.
    CV_DEFAULT_CONFIDENCE_THRESHOLD: float = 0.35
    CV_DEFAULT_NMS_IOU_THRESHOLD: float = 0.45
    # A hard ceiling on detections persisted per frame/image regardless
    # of what a model/adapter returns -- prevents one pathological
    # frame from writing an unbounded number of DetectionResult rows.
    CV_MAX_DETECTIONS_PER_FRAME: int = 50
    # Pretrained model weights (scripts/fetch_models.py writes them here; never
    # committed). Each file is checked against a pinned SHA-256 before it is loaded.
    CV_MODEL_DIR: str = "./model_artifacts"
    # Real evaluation images + annotations (scripts/fetch_eval_data.py writes a
    # COCO val2017 subset here; never committed). Empty directory = dataset unavailable.
    CV_EVAL_DATA_DIR: str = "./eval_data"

    # --- object tracking -------------------------
    # The closed allow-list key from app/tracking/trackers/registry.py --
    # never a dynamic import. Always overridable per job request, same
    # pattern CV_DEFAULT_CONFIDENCE_THRESHOLD already established.
    TRACKING_DEFAULT_TRACKER_KEY: str = "iou_hungarian_v1"
    # minimum IoU for two boxes to be considered the same
    # object across frames. A candidate pair below this is NEVER forced
    # into a match, no matter how few alternatives exist.
    TRACKING_MIN_IOU_THRESHOLD: float = 0.3
    # how many consecutive frames a confirmed track may go
    # unmatched before it is permanently ended.
    TRACKING_MAX_MISSED_FRAMES: int = 5
    # how many matched observations a tentative track needs
    # before it becomes "confirmed" (and is persisted as more than a
    # one-off noise blip in practice, though a never-confirmed track is
    # still persisted as "rejected" for transparency -- see Track model).
    TRACKING_MIN_HITS_TO_CONFIRM: int = 2
    # whether a detection's class_label must match a track's
    # own class_label to be considered a candidate match at all. True by
    # default -- Section 5 explicitly forbids merging tracks "solely
    # because their detections share a class label," but the inverse
    # (refusing to even consider a cross-class match) is the safer
    # default; an operator who wants cross-class association can turn
    # this off per job.
    TRACKING_REQUIRE_CLASS_MATCH: bool = True
    # A hard ceiling on how many simultaneous active tracks one job will
    # maintain -- Section 11's "bounded concurrency"/"configurable
    # maximum" applied to tracking's own unbounded-growth risk (a
    # pathological frame full of false-positive detections should not be
    # able to spawn an unbounded number of tentative tracks).
    TRACKING_MAX_ACTIVE_TRACKS_PER_JOB: int = 100

    # --- multi-sensor data platform / analytics -
    # bounded ingestion batches -- a single submitted batch
    # larger than this is rejected outright, never silently truncated.
    SENSOR_MAX_OBSERVATIONS_PER_BATCH: int = 2000
    # a time-series query spanning more than this many
    # days is rejected -- "explicit limits for maximum query range."
    SENSOR_MAX_QUERY_RANGE_DAYS: int = 90
    # the maximum number of raw samples returned by the
    # time-series endpoint before server-side downsampling kicks in.
    # Above this, the endpoint deterministically downsamples and labels
    # the response as aggregated (never silently).
    SENSOR_MAX_RAW_SAMPLES: int = 1000
    # minimum number of prior valid observations required
    # before a rolling-window/MAD anomaly check will produce a result at
    # all -- below this, the engine reports "insufficient baseline data"
    # rather than manufacturing a baseline from too little history.
    SENSOR_ANOMALY_MIN_BASELINE_SAMPLES: int = 8
    # half-width (in samples) of the rolling window used by
    # the rolling-deviation/MAD checks.
    SENSOR_ANOMALY_ROLLING_WINDOW: int = 10
    # how many MADs (median absolute deviation) or standard
    # deviations away from the baseline counts as anomalous. Configured,
    # not hard-coded, so a result can always be explained as "N sigma
    # beyond a documented threshold."
    SENSOR_ANOMALY_MAD_THRESHOLD: float = 3.5
    SENSOR_ANOMALY_ZSCORE_THRESHOLD: float = 3.0
    # a sensor with no valid observation within this many
    # multiples of its own configured nominal_sampling_interval is
    # reported as a missing-heartbeat condition. Falls back to this
    # many seconds flat when the sensor has no configured interval.
    SENSOR_HEARTBEAT_MISSED_INTERVAL_MULTIPLE: float = 3.0
    SENSOR_HEARTBEAT_DEFAULT_SECONDS: float = 3600.0
    # a sensor is reported "offline" (ingestion health) once
    # its last valid observation is older than this many seconds AND it
    # has missed its configured heartbeat -- distinct from "degraded"
    # (data arriving but of poor quality).
    SENSOR_OFFLINE_AFTER_SECONDS: float = 86400.0
    # an observation whose observed_at is older than this
    # many seconds relative to its ingested_at is classified "stale" --
    # a data-quality flag, never treated as invalid.
    SENSOR_STALE_AFTER_SECONDS: float = 86400.0
    # how many consecutive identical readings in a row count
    # as "excessive repeated identical readings."
    SENSOR_MAX_IDENTICAL_RUN: int = 5

    # --- geospatial/temporal intelligence ---
    # Section 5A/19: a hard ceiling on how many located records a single
    # viewport/radius/combined query response can return -- never an
    # unrestricted full-dataset download. A query matching more than
    # this many usable locations is truncated (never silently, see
    # `truncated`/`total_matched` on GeospatialQueryResponse) rather
    # than returning everything.
    GEOSPATIAL_MAX_RESULTS: int = 500
    # Section 5B: radius queries are capped at this many km -- half of
    # Earth's circumference (~20015 km) would technically be the
    # farthest two points can ever be, but a request that large is
    # almost certainly a mistake, not a real query need.
    GEOSPATIAL_MAX_RADIUS_KM: float = 5000.0
    # Section 5C/19: how many days a single temporal query (timeline,
    # playback, time-bucketed analytics) may span -- mirrors
    # SENSOR_MAX_QUERY_RANGE_DAYS's existing bound-the-range discipline.
    GEOSPATIAL_MAX_TIME_RANGE_DAYS: int = 365
    # a location's own source timestamp older than this
    # many seconds is flagged "stale" in a location-quality finding.
    GEOSPATIAL_STALE_LOCATION_AFTER_SECONDS: float = 7 * 86400.0
    # the distance (meters) within which two location-bearing
    # records are considered "within a documented distance threshold" by
    # spatial_relationship_service -- same default as
    # correlation_service.DEFAULT_SPATIAL_THRESHOLD_METERS, kept as its
    # own setting since the candidates are not limited to events.
    GEOSPATIAL_RELATIONSHIP_DISTANCE_METERS: float = 500.0
    # the time window (seconds) within which two spatially
    # close records are also considered "temporally associated" -- same
    # default as correlation_service.DEFAULT_TIME_WINDOW_SECONDS.
    GEOSPATIAL_RELATIONSHIP_TIME_WINDOW_SECONDS: int = 30 * 60
    # a hard ceiling on GeoJSON/CSV export feature count --
    # mirrors export_service.MAX_EXPORT_ROWS's existing discipline.
    GEOSPATIAL_MAX_EXPORT_FEATURES: int = 5000
    # default spatial-aggregation grid resolution (decimal
    # degrees) for the "counts by geographic area" analytic -- documented
    # and overridable per request, never silently fixed.
    GEOSPATIAL_DEFAULT_GRID_RESOLUTION_DEGREES: float = 0.5
    # Section 15 ("avoid unbounded pairwise spatial comparisons"): the
    # most located Event+Observation records a single
    # spatial_relationship_service.generate_candidates() run will ever
    # pull in and compare. A sorted-by-time sliding window keeps actual
    # comparisons far below N^2, but this is the hard ceiling on N
    # itself -- once exceeded, the run processes only the first
    # GEOSPATIAL_RELATIONSHIP_MAX_CANDIDATES records (oldest-first
    # within the requested range) and reports that it was truncated
    # rather than silently running unbounded.
    GEOSPATIAL_RELATIONSHIP_MAX_CANDIDATES: int = 1000

    # --- edge AI / offline-first sync ------------
    # hard ceiling on records accepted in a single sync
    # batch request -- also enforced structurally on SyncBatchRequest
    # itself (app/schemas/edge_sync.py's MAX_BATCH_SIZE Field bound);
    # kept as a settings mirror so it can be tuned without a code change,
    # same "two places, one source of truth, deliberately duplicated for
    # Pydantic's Field(max_length=...) to stay a literal" tradeoff
    # documented on MAX_BATCH_SIZE itself.
    EDGE_SYNC_MAX_BATCH_SIZE: int = 100
    # Section 7 (retry/backoff): exponential-backoff base and ceiling for
    # a retryable_failure SyncRecord's next_retry_at -- delay doubles per
    # attempt (plus jitter, computed in edge_sync_service), never
    # exceeding the max.
    EDGE_SYNC_RETRY_BASE_DELAY_SECONDS: float = 5.0
    EDGE_SYNC_RETRY_MAX_DELAY_SECONDS: float = 3600.0  # 1 hour
    # jitter fraction applied on top of the computed
    # exponential delay (+/- this fraction) -- prevents many devices
    # that failed at the same moment from all retrying in lockstep.
    EDGE_SYNC_RETRY_JITTER_FRACTION: float = 0.2
    # a retryable_failure SyncRecord that has been retried
    # this many times transitions to permanent_failure instead of
    # retrying again -- bounded retries, never an infinite loop.
    EDGE_SYNC_MAX_RETRY_COUNT: int = 10
    # Section 6 (crash recovery): a SyncRecord left in `syncing` with no
    # update for longer than this is treated as an orphaned/crashed
    # attempt and reset to `retryable_failure` on the next recovery
    # sweep -- "nothing stuck permanently in an in-progress state."
    EDGE_SYNC_SYNCING_STALE_AFTER_SECONDS: float = 300.0
    # how many most-recent DeviceHealthReport rows per device
    # the Device Detail "Health history" tab will ever return in one
    # page -- bounded like every other list endpoint in this project.
    EDGE_DEVICE_HEALTH_REPORT_MAX_RESULTS: int = 200
    # Section 12 (large-payload handling): a single SyncRecordEnvelope's
    # `payload` is rejected if its serialized size exceeds this -- bounds
    # an individual record independent of the batch-size cap above.
    EDGE_SYNC_MAX_PAYLOAD_BYTES: int = 256 * 1024  # 256 KB

    # --- enterprise fleet management ------------
    # Section 3 (presence derivation): a device is "stale" once this
    # many seconds have passed since `last_seen_at` with no new
    # heartbeat/sync/health-report activity, and "offline" once the
    # longer threshold below has passed. Below `online` is any device
    # within the stale threshold; a device that has NEVER reported at
    # all is "unknown" -- never defaulted to "offline," since "never
    # seen" and "seen long ago" are genuinely different findings.
    FLEET_PRESENCE_STALE_AFTER_SECONDS: float = 120.0
    FLEET_PRESENCE_OFFLINE_AFTER_SECONDS: float = 600.0
    # the device-authenticated heartbeat endpoint is
    # rate-limited per device to prevent a misbehaving/compromised
    # device from flooding the ingestion path -- see
    # app/services/fleet_presence_service.py's in-process limiter (a
    # documented best-effort, single-process limit; see
    # docs/security/DEVICE_LIFECYCLE_SECURITY.md's "known limitations").
    FLEET_HEARTBEAT_MIN_INTERVAL_SECONDS: float = 5.0
    # Section 4 (health-finding rules): configurable thresholds a
    # device's most recent DeviceHealthReport.resource_metrics is
    # evaluated against. A device that never reports a given metric
    # produces no finding for it at all -- "missing data stays missing"
    # (Part 4, binding), never fabricated as 0% or 100%.
    FLEET_HEALTH_DISK_WARNING_PCT: float = 80.0
    FLEET_HEALTH_DISK_CRITICAL_PCT: float = 95.0
    FLEET_HEALTH_BATTERY_WARNING_PCT: float = 20.0
    FLEET_HEALTH_BATTERY_CRITICAL_PCT: float = 5.0
    FLEET_HEALTH_QUEUE_DEPTH_WARNING: int = 500
    FLEET_HEALTH_QUEUE_DEPTH_CRITICAL: int = 2000
    # Section 9 (alerting): how many most-recent InfrastructureAlert rows
    # a fleet-wide alert-center list page returns in one page -- bounded
    # like every other list endpoint in this project.
    FLEET_ALERT_MAX_PAGE_SIZE: int = 200
    # Section 7 ("recently-verified" as its own distinct capability
    # state): a capability's `last_verified_at` must fall within this
    # many seconds of "now" to count as recently-verified in the fleet
    # capability summary -- an older verification is real but stale,
    # never silently treated as current.
    FLEET_CAPABILITY_RECENTLY_VERIFIED_WINDOW_SECONDS: float = 3600.0

    # --- MLOps, model lifecycle, experiment tracking, observability -------
    # See docs/ml/MLOPS_ARCHITECTURE.md. Thresholds here are DEFAULTS that surface
    # review signals; none of them triggers an automatic operational action.
    APP_GIT_COMMIT: str = ""  # optional; recorded in experiment reproducibility metadata when set
    LOG_FORMAT: str = "text"  # "text" (default, unchanged) or "json"
    METRICS_ENABLED: bool = True
    METRICS_MAX_SERIES_PER_METRIC: int = 200  # hard cardinality cap per metric name
    MLOPS_ARTIFACT_ROOT: str = ""  # directory holding registered model artifacts; empty = file artifacts unavailable
    MLOPS_MAX_ARTIFACT_HASH_BYTES: int = 512 * 1024 * 1024
    MLOPS_MAX_METADATA_BYTES: int = 16384
    MLOPS_MAX_EVAL_SAMPLES: int = 5000
    MLOPS_MAX_DETECTION_FIXTURE_SAMPLES: int = 200
    MLOPS_STALE_RUN_SECONDS: int = 600  # a run stuck in "running" longer than this is marked failed (interrupted)
    MLOPS_EVALUATION_STALE_DAYS: int = 30
    MLOPS_APPROVAL_MAX_EVAL_AGE_DAYS: int = 90
    MLOPS_REQUIRE_SEPARATE_APPROVER: bool = True
    MLOPS_REGRESSION_ABS_THRESHOLD: float = 0.05  # absolute drop vs baseline that is flagged for review
    MLOPS_REGRESSION_THRESHOLDS_JSON: str = ""  # optional {"classification": {"macro_f1": 0.03}}
    MLOPS_METRIC_FLOORS_JSON: str = ""  # optional {"object_detection": {"recall": 0.5}}
    MLOPS_MONITOR_MAX_ROWS: int = 2000
    MLOPS_MONITOR_MAX_FEATURES: int = 30
    MLOPS_MONITOR_MIN_SAMPLES: int = 30
    MLOPS_MONITOR_MIN_LABELLED: int = 30
    MLOPS_PSI_WARN: float = 0.10
    MLOPS_PSI_ALERT: float = 0.25
    MLOPS_SCHEMA_VIOLATION_RATE_WARN: float = 0.05
    MLOPS_JOB_FAILURE_RATE_THRESHOLD: float = 0.20
    MLOPS_JOB_WINDOW_HOURS: int = 24
    MLOPS_JOB_MIN_SAMPLES: int = 10
    MLOPS_MONITOR_FRESHNESS_DAYS: int = 7

    # Analytics and reporting
    ANALYTICS_MAX_WINDOW_DAYS: int = 366
    ANALYTICS_DEFAULT_WINDOW_DAYS: int = 7
    ANALYTICS_MAX_ROWS: int = 20000  # bound for any analysis that must read rows (percentiles); sets `truncated`
    ANALYTICS_STALE_HOURS: int = 24  # data older than this is reported as stale
    ANALYTICS_LATE_ARRIVAL_HOURS: int = 24  # ingested_at - observed_at beyond this = late-arriving
    ANALYTICS_MIN_FINISHED_JOBS: int = 10  # failure rates below this denominator are not reported
    ANALYTICS_GEO_MIN_CELL_COUNT: int = 3  # grid cells with fewer records are suppressed (not shown individually)
    REPORT_STORAGE_ROOT: str = ""  # empty -> <CV_MEDIA_STORAGE_ROOT>/reports (private; never served statically)
    REPORT_RETENTION_DAYS: int = 30  # artifacts are deleted after this; the run record is kept as "expired"
    REPORT_MAX_ARTIFACT_BYTES: int = 10 * 1024 * 1024
    REPORT_MAX_NOTES_CHARS: int = 4000

    @property
    def mlops_regression_thresholds(self) -> dict:
        return _json_dict(self.MLOPS_REGRESSION_THRESHOLDS_JSON)

    @property
    def mlops_metric_floors(self) -> dict:
        return _json_dict(self.MLOPS_METRIC_FLOORS_JSON)

    @property
    def docs_enabled(self) -> bool:
        if self.ENABLE_API_DOCS is not None:
            return bool(self.ENABLE_API_DOCS)
        return self.ENVIRONMENT.lower() != "production"

    @property
    def previous_secret_keys(self) -> list[str]:
        return [k.strip() for k in self.SECRET_KEY_PREVIOUS.split(",") if k.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def fusion_identifier_attribute_keys_list(self) -> list[str]:
        return [k.strip() for k in self.FUSION_IDENTIFIER_ATTRIBUTE_KEYS.split(",") if k.strip()]

    @property
    def fusion_time_window_seconds_by_type(self) -> dict[str, int]:
        import json

        try:
            parsed = json.loads(self.FUSION_TIME_WINDOW_SECONDS_BY_TYPE)
            if isinstance(parsed, dict):
                return {str(k): int(v) for k, v in parsed.items()}
        except (ValueError, TypeError):
            pass
        return {}


def _json_dict(raw: str) -> dict:
    import json

    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


@lru_cache
def get_settings() -> Settings:
    return Settings()
