"""RBAC primitives (Role/Permission/ROLE_PERMISSIONS), password hashing,
and JWT issuance/verification. Every protected route depends on
`require_permission(...)` -- never a frontend-only check.
"""
from __future__ import annotations

import enum
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import InvalidSignatureError, PyJWTError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db

settings = get_settings()

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class Role(str, enum.Enum):
    ADMINISTRATOR = "administrator"
    ANALYST = "analyst"
    INVESTIGATOR = "investigator"
    VIEWER = "viewer"


class Permission(str, enum.Enum):
    # Users / org
    USER_MANAGE = "user:manage"
    USER_READ = "user:read"
    # Sources
    SOURCE_MANAGE = "source:manage"
    SOURCE_READ = "source:read"
    # Events
    EVENT_READ = "event:read"
    # Ingestion
    INGESTION_RUN = "ingestion:run"
    INGESTION_READ = "ingestion:read"
    # Assets
    ASSET_MANAGE = "asset:manage"
    ASSET_READ = "asset:read"
    # Sensors / observations
    SENSOR_MANAGE = "sensor:manage"
    SENSOR_READ = "sensor:read"
    OBSERVATION_READ = "observation:read"
    # Investigations
    INVESTIGATION_MANAGE = "investigation:manage"
    INVESTIGATION_READ = "investigation:read"
    # Risk assessments
    RISK_READ = "risk:read"
    RISK_REVIEW = "risk:review"
    # Audit
    AUDIT_READ = "audit:read"
    # Dashboard / health are open to any authenticated user -- no
    # dedicated permission needed.

    # --- data platform ---------------------------
    DATA_QUALITY_READ = "data_quality:read"
    CORRELATION_READ = "correlation:read"
    # Reviewing (confirm/reject) AND recomputing correlation candidates
    # -- both are "do something," not "look at something."
    CORRELATION_MANAGE = "correlation:manage"
    # A raw record's payload may carry source-side detail a normalized
    # Event intentionally drops -- gated separately from EVENT_READ
    # ("access controls on provenance/raw data").
    RAW_RECORD_READ = "raw_record:read"
    # Bulk CSV/JSON export -- Section 17: "not every role gets
    # unrestricted bulk export."
    DATA_EXPORT = "data:export"

    # --- multisource intelligence fusion ---------
    EVIDENCE_READ = "evidence:read"
    EVIDENCE_MANAGE = "evidence:manage"
    # Reading relationships/conflicts/the evidence graph vs. actually
    # creating a relationship, reviewing/reversing one, or resolving a
    # conflict -- "do something" always needs the *_MANAGE/_REVIEW
    # variant, same split Phase 2 used for correlation.
    RELATIONSHIP_READ = "relationship:read"
    RELATIONSHIP_MANAGE = "relationship:manage"
    CONFLICT_READ = "conflict:read"
    CONFLICT_MANAGE = "conflict:manage"
    ASSESSMENT_READ = "assessment:read"
    ASSESSMENT_MANAGE = "assessment:manage"
    # Running the fusion pipeline (correlation recompute + conflict
    # detection as one job) and reading its job history.
    FUSION_RUN = "fusion:run"
    FUSION_READ = "fusion:read"
    # The bounded evidence graph -- a read-only view over
    # events/evidence/relationships/conflicts/assessments, gated
    # separately so a role that can't manage any of those can still be
    # granted (or denied) the graph specifically.
    GRAPH_READ = "graph:read"

    # --- computer vision infrastructure ----------
    MEDIA_READ = "media:read"
    MEDIA_MANAGE = "media:manage"  # uploading media
    MODEL_READ = "model:read"
    # Registering a new CV model record / adapter pairing -- kept
    # admin-only (unlike SOURCE_MANAGE/ASSET_MANAGE, which analysts also
    # hold) because an adapter_key determines what code this platform
    # will execute; see app/cv/adapters/registry.py.
    MODEL_MANAGE = "model:manage"
    INFERENCE_RUN = "inference:run"
    INFERENCE_READ = "inference:read"
    # Confirming/rejecting a detection and promoting a confirmed one to
    # Evidence -- "do something," same split as every other *_MANAGE/
    # *_REVIEW permission in this file.
    DETECTION_REVIEW = "detection:review"
    EVALUATION_RUN = "evaluation:run"
    EVALUATION_READ = "evaluation:read"

    # --- object tracking -------------------------
    TRACKING_RUN = "tracking:run"
    TRACKING_READ = "tracking:read"
    # Creating/correcting a track annotation -- "do something," same
    # split as DETECTION_REVIEW: a role that can review a detection can
    # also annotate a track, even if it can't run new tracking jobs.
    TRACK_ANNOTATE = "track:annotate"
    TRACKING_EVALUATION_RUN = "tracking_evaluation:run"
    TRACKING_EVALUATION_READ = "tracking_evaluation:read"

    # --- multi-sensor data platform / analytics --
    # Submitting/retrying a sensor observation batch -- split from
    # OBSERVATION_READ the same way INFERENCE_RUN/TRACKING_RUN are split
    # from their *_READ counterparts.
    OBSERVATION_INGEST = "observation:ingest"
    ANOMALY_READ = "anomaly:read"
    # Confirming/dispositioning an anomaly candidate or a data-quality
    # finding -- "do something," same split as DETECTION_REVIEW/
    # TRACK_ANNOTATE. Never classifies anything as a threat; see
    # app/services/anomaly_service.py.
    ANOMALY_REVIEW = "anomaly:review"
    SENSOR_QUALITY_REVIEW = "sensor_quality:review"

    # --- geospatial intelligence -----------------
    # Viewing the map/timeline/analytics/location-quality tabs -- as
    # broadly granted as EVENT_READ/SENSOR_READ/OBSERVATION_READ/
    # ASSET_READ, since a geospatial query is a read over records a
    # role can already read individually.
    GEOSPATIAL_READ = "geospatial:read"
    # Bulk GeoJSON/CSV export of located records -- mirrors
    # DATA_EXPORT's Administrator+Analyst-only grant exactly (Section
    # 14: "not every role gets unrestricted bulk export," same as
    # Phase 2 already decided for event export).
    GEOSPATIAL_EXPORT = "geospatial:export"
    # Triggering spatial-relationship candidate generation -- mirrors
    # CORRELATION_MANAGE's Analyst-only (not Investigator) grant:
    # generating NEW candidates at scale stays analyst/admin, while
    # REVIEWING a generated candidate reuses the existing
    # RELATIONSHIP_READ/RELATIONSHIP_MANAGE permissions (a candidate is
    # just an ordinary EvidenceRelationship row -- no new permission
    # needed for that half).
    GEOSPATIAL_MANAGE = "geospatial:manage"

    # --- edge AI / offline-first sync ------------
    # Viewing the device registry (Edge Operations Center overview +
    # device detail) -- a device record itself, never the sync payload
    # content it carries (that's EDGE_SYNC_READ below).
    DEVICE_READ = "device:read"
    # Registering a new device, rotating its API key, and lifecycle
    # transitions (activate/suspend/revoke) -- mirrors SENSOR_MANAGE's
    # Analyst-only grant: onboarding/decommissioning physical capability
    # stays analyst/admin, same split as every other *_MANAGE pair here.
    DEVICE_MANAGE = "device:manage"
    # Viewing the sync queue (per-device and fleet-wide), individual
    # SyncRecord rows, and device health-report history -- a read over
    # records a role can already read individually once synced, same
    # "a query is a read" rationale as GEOSPATIAL_READ.
    EDGE_SYNC_READ = "edge_sync:read"
    # Forcing a retry of a retryable_failure/permanent_failure
    # SyncRecord, or cancelling a queued one -- "do something to a
    # queue entry," same split as ANOMALY_REVIEW/DETECTION_REVIEW: never
    # fabricates sync success, only re-attempts or cancels.
    EDGE_SYNC_MANAGE = "edge_sync:manage"
    # Viewing the conflict review queue -- a SyncConflict is read-only
    # inspection until resolved, same split as every other *_READ here.
    EDGE_CONFLICT_READ = "edge_conflict:read"
    # Resolving a SyncConflict (keep_central/keep_local/merged) -- this
    # is deliberately granted to Investigator as well (see below): a
    # human reviewing conflicting field data is case-work, the same
    # category as EVIDENCE_MANAGE/ASSESSMENT_MANAGE, not fleet
    # administration like DEVICE_MANAGE/EDGE_SYNC_MANAGE.
    EDGE_CONFLICT_MANAGE = "edge_conflict:manage"

    # --- enterprise fleet management ------------
    # Viewing fleet sites/groups and their summaries -- a read over
    # records a role can already read individually (devices), same
    # "a query is a read" rationale as GEOSPATIAL_READ/EDGE_SYNC_READ.
    FLEET_SITE_READ = "fleet_site:read"
    # Creating a site and assigning a device to one -- fleet
    # administration, same Analyst-only split as DEVICE_MANAGE.
    FLEET_SITE_MANAGE = "fleet_site:manage"
    # Viewing the infrastructure alert center -- distinct from
    # ANOMALY_READ/RISK_READ (those are about SENSED conditions; this
    # is about fleet health, see app/models/infrastructure_alert.py's
    # module docstring for the deliberate separation).
    INFRA_ALERT_READ = "infra_alert:read"
    # Acknowledging/resolving/reopening an infrastructure alert -- kept
    # analyst/admin-only (unlike EDGE_CONFLICT_MANAGE) because this is
    # fleet operations, not case-work over intelligence data.
    INFRA_ALERT_MANAGE = "infra_alert:manage"
    # Viewing the fleet overview/analytics dashboard -- as broadly
    # granted as every other *_READ here, since it is itself just an
    # aggregate read over devices/alerts/sync-conflicts a role can
    # already read individually.
    FLEET_ANALYTICS_READ = "fleet_analytics:read"

    # --- explainable AI / model evaluation / review --
    # Viewing model evaluations, normalized model outputs and their
    # explanations -- a read over records a role can already read
    # individually (detections, risk assessments), granted to every role.
    ANALYTICS_READ = "analytics:read"
    # Submitting a labelled-dataset evaluation of a registered model --
    # "do something," Analyst/Administrator only (same split as
    # EVALUATION_RUN / TRACKING_EVALUATION_RUN).
    ANALYTICS_EVALUATE = "analytics:evaluate"
    # Computing an advisory review-priority score for an assessment and
    # recording an accept/reject/further-review decision on it -- the
    # consequential half of the assessment workflow, so it is NOT held by
    # the read-only Viewer. Scores themselves never trigger actions.
    ASSESSMENT_REVIEW = "assessment:review"

    # Phase 11: producing an investigation report/export bundle is its own
    # permission (it can copy media bytes out of the platform); viewers
    # can read investigations but cannot export them.
    INVESTIGATION_EXPORT = "investigation:export"

    # Phase 12: retrieval + copilot. RETRIEVAL_READ lets a user search and
    # ask questions, but results are STILL filtered by the per-record-type
    # read permission and live record access (it grants no new data).
    # RETRIEVAL_INDEX triggers/inspects indexing; RETRIEVAL_EVALUATE runs
    # the synthetic-fixture evaluation.
    RETRIEVAL_READ = "retrieval:read"
    RETRIEVAL_INDEX = "retrieval:index"
    RETRIEVAL_EVALUATE = "retrieval:evaluate"

    # Phase 13: scenario simulation. READ covers viewing scenarios, runs,
    # comparisons and exports; WRITE creates/edits/versions scenarios and
    # generates synthetic datasets; RUN executes simulations/sensitivity
    # sweeps (bounded CPU). Simulated output is never operational evidence.
    SCENARIO_READ = "scenario:read"
    SCENARIO_WRITE = "scenario:write"
    SCENARIO_RUN = "scenario:run"

    # Phase 14: governance. SECURITY_READ shows the (secret-free)
    # security-configuration report. LIFECYCLE_* split reading policies/
    # previews, REQUESTING an archive/delete, and APPROVING/EXECUTING it.
    # None of these are granted to non-administrators by default.
    SECURITY_READ = "security:read"
    LIFECYCLE_READ = "lifecycle:read"
    LIFECYCLE_REQUEST = "lifecycle:request"
    LIFECYCLE_APPROVE = "lifecycle:approve"

    # Phase 15: MLOps. READ covers the registry, experiments (including their
    # full configuration), comparisons, monitoring and review signals. REGISTER
    # adds a model version. RUN executes an evaluation experiment. REVIEW
    # requests a model review, selects a baseline, and acknowledges/resolves
    # review signals. MONITOR submits monitoring snapshots and runs scans.
    # APPROVE is the approval authority (approve / deprecate / reactivate /
    # archive); OBSERVABILITY_READ exposes process metrics and detailed health.
    # Only the last two are administrator-only.
    MLOPS_READ = "mlops:read"
    MLOPS_REGISTER = "mlops:register"
    MLOPS_RUN = "mlops:run"
    MLOPS_REVIEW = "mlops:review"
    MLOPS_MONITOR = "mlops:monitor"
    MLOPS_APPROVE = "mlops:approve"
    OBSERVABILITY_READ = "observability:read"

    # Phase 16 (analytics and reporting). REPORTING_READ opens the dashboards
    # and report history; each analytics SECTION additionally requires the read
    # permission of the data it aggregates (events, investigations, ...), so a
    # dashboard never reveals counts the caller could not list directly.
    # REPORT_GENERATE creates a report artifact.
    REPORTING_READ = "reporting:read"
    REPORT_GENERATE = "report:generate"


# Administrator implicitly has every permission -- enforced in
# has_permission() below, not by listing every value here (so adding a
# new Permission automatically covers ADMINISTRATOR without editing this
# table).
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMINISTRATOR: set(Permission),
    Role.ANALYST: {
        Permission.ANALYTICS_READ,
        Permission.RETRIEVAL_READ,
        Permission.ANALYTICS_EVALUATE,
        Permission.RETRIEVAL_INDEX,
        Permission.RETRIEVAL_EVALUATE,
        Permission.SCENARIO_READ,
        Permission.SCENARIO_WRITE,
        Permission.SCENARIO_RUN,
        Permission.ASSESSMENT_REVIEW,
        Permission.USER_READ,
        Permission.SOURCE_READ,
        Permission.SOURCE_MANAGE,
        Permission.EVENT_READ,
        Permission.INGESTION_RUN,
        Permission.INGESTION_READ,
        Permission.ASSET_READ,
        Permission.ASSET_MANAGE,
        Permission.SENSOR_READ,
        Permission.SENSOR_MANAGE,
        Permission.OBSERVATION_READ,
        Permission.INVESTIGATION_READ,
        Permission.INVESTIGATION_MANAGE,
        Permission.INVESTIGATION_EXPORT,
        Permission.RISK_READ,
        Permission.RISK_REVIEW,
        Permission.DATA_QUALITY_READ,
        Permission.CORRELATION_READ,
        Permission.CORRELATION_MANAGE,
        Permission.RAW_RECORD_READ,
        Permission.DATA_EXPORT,
        Permission.EVIDENCE_READ,
        Permission.EVIDENCE_MANAGE,
        Permission.RELATIONSHIP_READ,
        Permission.RELATIONSHIP_MANAGE,
        Permission.CONFLICT_READ,
        Permission.CONFLICT_MANAGE,
        Permission.ASSESSMENT_READ,
        Permission.ASSESSMENT_MANAGE,
        Permission.FUSION_RUN,
        Permission.FUSION_READ,
        Permission.GRAPH_READ,
        Permission.MEDIA_READ,
        Permission.MEDIA_MANAGE,
        Permission.MODEL_READ,
        Permission.INFERENCE_RUN,
        Permission.INFERENCE_READ,
        Permission.DETECTION_REVIEW,
        Permission.EVALUATION_RUN,
        Permission.EVALUATION_READ,
        Permission.TRACKING_RUN,
        Permission.TRACKING_READ,
        Permission.TRACK_ANNOTATE,
        Permission.TRACKING_EVALUATION_RUN,
        Permission.TRACKING_EVALUATION_READ,
        Permission.OBSERVATION_INGEST,
        Permission.ANOMALY_READ,
        Permission.ANOMALY_REVIEW,
        Permission.SENSOR_QUALITY_REVIEW,
        Permission.GEOSPATIAL_READ,
        Permission.GEOSPATIAL_EXPORT,
        Permission.GEOSPATIAL_MANAGE,
        Permission.DEVICE_READ,
        Permission.DEVICE_MANAGE,
        Permission.EDGE_SYNC_READ,
        Permission.EDGE_SYNC_MANAGE,
        Permission.EDGE_CONFLICT_READ,
        Permission.EDGE_CONFLICT_MANAGE,
        Permission.FLEET_SITE_READ,
        Permission.FLEET_SITE_MANAGE,
        Permission.INFRA_ALERT_READ,
        Permission.INFRA_ALERT_MANAGE,
        Permission.FLEET_ANALYTICS_READ,
        Permission.MLOPS_READ,
        Permission.MLOPS_REGISTER,
        Permission.MLOPS_RUN,
        Permission.MLOPS_REVIEW,
        Permission.MLOPS_MONITOR,
        Permission.REPORTING_READ,
        Permission.REPORT_GENERATE,
    },
    Role.INVESTIGATOR: {
        Permission.REPORTING_READ,
        Permission.REPORT_GENERATE,
        Permission.ANALYTICS_READ,
        Permission.RETRIEVAL_READ,
        Permission.SCENARIO_READ,
        Permission.ASSESSMENT_REVIEW,
        Permission.USER_READ,
        Permission.SOURCE_READ,
        Permission.EVENT_READ,
        Permission.INGESTION_READ,
        Permission.ASSET_READ,
        Permission.SENSOR_READ,
        Permission.OBSERVATION_READ,
        Permission.INVESTIGATION_READ,
        Permission.INVESTIGATION_MANAGE,
        Permission.INVESTIGATION_EXPORT,
        Permission.RISK_READ,
        Permission.RISK_REVIEW,
        Permission.DATA_QUALITY_READ,
        Permission.CORRELATION_READ,
        Permission.RAW_RECORD_READ,
        Permission.EVIDENCE_READ,
        Permission.EVIDENCE_MANAGE,
        Permission.RELATIONSHIP_READ,
        Permission.RELATIONSHIP_MANAGE,
        Permission.CONFLICT_READ,
        Permission.CONFLICT_MANAGE,
        Permission.ASSESSMENT_READ,
        Permission.ASSESSMENT_MANAGE,
        # Investigator can review/resolve/author case-work, same as it
        # already can for investigations and risk assessments -- but
        # NOT run the fusion pipeline itself (FUSION_RUN), mirroring
        # Phase 2's own choice to withhold CORRELATION_MANAGE from this
        # role: generating NEW candidates at scale stays analyst/admin.
        Permission.FUSION_READ,
        Permission.GRAPH_READ,
        Permission.MEDIA_READ,
        Permission.MODEL_READ,
        Permission.INFERENCE_READ,
        Permission.DETECTION_REVIEW,
        Permission.EVALUATION_READ,
        # Investigator can review/annotate tracking results, same as it
        # can for detections, but NOT run new tracking jobs (TRACKING_RUN)
        # or new tracking evaluations -- mirroring the exact split Phase
        # 4 already drew for INFERENCE_RUN/EVALUATION_RUN.
        Permission.TRACKING_READ,
        Permission.TRACK_ANNOTATE,
        Permission.TRACKING_EVALUATION_READ,
        # Investigator can review anomalies/quality findings, same as it
        # can review detections/tracks, but NOT submit new observation
        # batches (OBSERVATION_INGEST) -- mirroring the TRACKING_RUN
        # split above.
        Permission.ANOMALY_READ,
        Permission.ANOMALY_REVIEW,
        Permission.SENSOR_QUALITY_REVIEW,
        # Investigator can view everything geospatial and review a
        # generated spatial-relationship candidate (via the existing
        # RELATIONSHIP_MANAGE it already holds above), but cannot
        # trigger new candidate generation (GEOSPATIAL_MANAGE) or bulk
        # export (GEOSPATIAL_EXPORT) -- same split as every other
        # *_RUN/*_MANAGE permission withheld from this role.
        Permission.GEOSPATIAL_READ,
        # Investigator can view devices/sync queue and resolve a
        # conflict (case-work -- see EDGE_CONFLICT_MANAGE's docstring
        # above), but cannot register/revoke a device (DEVICE_MANAGE)
        # or force-retry/cancel a sync record (EDGE_SYNC_MANAGE) --
        # same fleet-administration-stays-analyst/admin split as every
        # other *_MANAGE withheld from this role.
        Permission.DEVICE_READ,
        Permission.EDGE_SYNC_READ,
        Permission.EDGE_CONFLICT_READ,
        Permission.EDGE_CONFLICT_MANAGE,
        # Investigator can view fleet sites/alerts/analytics (read-only
        # fleet awareness, same as DEVICE_READ/EDGE_SYNC_READ above),
        # but cannot create a site or ack/resolve an infrastructure
        # alert -- fleet operations, not case-work.
        Permission.FLEET_SITE_READ,
        Permission.INFRA_ALERT_READ,
        Permission.FLEET_ANALYTICS_READ,
        Permission.MLOPS_READ,
    },
    Role.VIEWER: {
        Permission.REPORTING_READ,
        Permission.ANALYTICS_READ,
        Permission.RETRIEVAL_READ,
        Permission.SCENARIO_READ,
        Permission.USER_READ,
        Permission.SOURCE_READ,
        Permission.EVENT_READ,
        Permission.INGESTION_READ,
        Permission.ASSET_READ,
        Permission.SENSOR_READ,
        Permission.OBSERVATION_READ,
        Permission.INVESTIGATION_READ,
        Permission.RISK_READ,
        Permission.DATA_QUALITY_READ,
        Permission.CORRELATION_READ,
        Permission.EVIDENCE_READ,
        Permission.RELATIONSHIP_READ,
        Permission.CONFLICT_READ,
        Permission.ASSESSMENT_READ,
        Permission.FUSION_READ,
        Permission.GRAPH_READ,
        Permission.MEDIA_READ,
        Permission.MODEL_READ,
        Permission.INFERENCE_READ,
        Permission.EVALUATION_READ,
        Permission.TRACKING_READ,
        Permission.TRACKING_EVALUATION_READ,
        Permission.ANOMALY_READ,
        Permission.GEOSPATIAL_READ,
        Permission.DEVICE_READ,
        Permission.EDGE_SYNC_READ,
        Permission.EDGE_CONFLICT_READ,
        Permission.FLEET_SITE_READ,
        Permission.INFRA_ALERT_READ,
        Permission.FLEET_ANALYTICS_READ,
        Permission.MLOPS_READ,
    },
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def hash_password(password: str) -> str:
    # bcrypt directly (not passlib -- passlib 1.7.x's bcrypt backend
    # self-test is broken against bcrypt>=4.1's stricter 72-byte check,
    # a known compatibility bug unrelated to any real password).
    # bcrypt itself has the same 72-byte input limit; truncate the UTF-8
    # bytes deterministically rather than let hashing raise.
    password_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    password_bytes = password.encode("utf-8")[:72]
    try:
        return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))
    except ValueError:
        return False


def _create_token(subject: str, role: str, expires_delta: timedelta, token_type: str, token_version: int = 0) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": token_type,
        "tv": int(token_version),
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(user_id: str, role: str, token_version: int = 0) -> str:
    return _create_token(user_id, role, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), "access", token_version)


def create_refresh_token(user_id: str, role: str, token_version: int = 0) -> str:
    return _create_token(user_id, role, timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES), "refresh", token_version)


def token_matches_user(payload: dict[str, Any], user: Any) -> bool:
    """True only if the token was issued at the user's CURRENT token
    version. Tokens minted before Phase 14 carry no `tv` claim and are
    treated as version 0, so they keep working until the first
    revocation event for that user bumps the version."""
    return int(payload.get("tv", 0)) == int(getattr(user, "token_version", 0) or 0)


def decode_token(token: str) -> dict[str, Any]:
    # algorithms is pinned to ONE symmetric algorithm: never derived from the token header.
    # During a key rotation, tokens signed with a key listed in SECRET_KEY_PREVIOUS are
    # still accepted -- but only when the signature (not the expiry) failed for the current key.
    for i, key in enumerate([settings.SECRET_KEY, *settings.previous_secret_keys]):
        try:
            return jwt.decode(token, key, algorithms=[settings.ALGORITHM], options={"require": ["exp", "sub"]})
        except InvalidSignatureError:
            continue
        except PyJWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


class AuthenticatedUser:
    """Lightweight principal attached to each request -- avoids every
    route re-querying the full User row just to check a role."""

    def __init__(self, id: str, role: Role, is_active: bool, organization_id: str):
        self.id = id
        self.role = role
        self.is_active = is_active
        self.organization_id = organization_id


def get_current_user(token: str = Depends(_oauth2_scheme), db: Session = Depends(get_db)) -> AuthenticatedUser:
    from app.models.user import User  # local import avoids a circular import at module load time

    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expected an access token")
    user_id = payload.get("sub")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    if not token_matches_user(payload, user):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked")
    return AuthenticatedUser(id=user.id, role=Role(user.role), is_active=user.is_active, organization_id=user.organization_id)


def _audit_denied(db: Session, request: Request, current_user: "AuthenticatedUser", permission: Permission) -> None:
    """Best-effort audit of a denied operation (Phase 14, Phase B.8).
    Records WHO, which permission, and the method + route template -- never
    the request body, query string values, or headers. A failure to write
    this row must never turn a 403 into a 500, so it is swallowed (and
    logged); denial itself is still enforced."""
    import logging

    try:
        from app.services import audit_service

        import re

        # Concrete path with id-looking segments masked -> a stable route-ish
        # template that never records a specific record id.
        masked = re.sub(r"/[0-9a-fA-F-]{16,}(?=/|$)", "/{id}", request.url.path)
        audit_service.record(
            db, action="authz.denied", actor_user_id=current_user.id, organization_id=current_user.organization_id,
            outcome="denied", request_id=getattr(request.state, "request_id", None),
            context_metadata={
                "permission": permission.value, "role": current_user.role.value,
                "method": request.method, "route": masked,
            },
        )
        db.commit()
    except Exception:  # pragma: no cover - defensive
        logging.getLogger("aegis.security").exception("failed to audit denied operation")
        try:
            db.rollback()
        except Exception:
            pass


audit_denied = _audit_denied  # public alias for action-level checks made inside a route


def require_permission(permission: Permission):
    """Returns a FastAPI dependency enforcing `permission` server-side.
    This is the ONLY place authorization is decided -- routes never
    inline a role check, and the frontend's own role-aware UI hiding is
    a convenience layered on top of this, never a substitute for it."""

    def _check(
        request: Request,
        current_user: AuthenticatedUser = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> AuthenticatedUser:
        if not has_permission(current_user.role, permission):
            _audit_denied(db, request, current_user, permission)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {permission.value}")
        return current_user

    return _check


def require_device_auth(
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id"),
    x_device_api_key: Optional[str] = Header(None, alias="X-Device-Api-Key"),
    db: Session = Depends(get_db),
):
    """Device-facing authentication -- completely
    separate from `get_current_user`/`require_permission` above, which
    are JWT-and-human-only. Every sync/health endpoint a device calls
    depends on THIS, never on a JWT: a device has no user account, no
    Role, and no Permission. Returns the real `app.models.device.Device`
    ORM row (not a lightweight principal like AuthenticatedUser) since
    every sync-service call needs the full device record anyway.

    Rejects with 401 for an unknown device_identifier, a wrong key, or
    any administrative_status other than `active` -- a `pending`
    (not yet activated) or `suspended`/`revoked` device cannot
    authenticate a single request (Part 3: "enrollment must never
    silently grant unrestricted access")."""
    from app.services import device_service  # local import avoids a circular import at module load time

    # Phase 17: missing credentials are an authentication failure (401), not a request-validation failure (422),
    # so unauthenticated callers get the same answer on every protected route.
    device = device_service.authenticate_device(db, x_device_id, x_device_api_key) if x_device_id and x_device_api_key else None
    if device is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device credentials, or the device is not active")
    return device
