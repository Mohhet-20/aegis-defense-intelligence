from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.routes import (
    assessments,
    assets,
    audit,
    auth,
    conflicts,
    correlation,
    cross_source_comparison,
    cv_models,
    dashboard,
    data_quality,
    demo,
    detections,
    edge_conflicts,
    edge_devices,
    edge_presence,
    edge_sync,
    edge_sync_admin,
    evaluation,
    evidence,
    events,
    fleet_analytics,
    model_outputs,
    model_evaluations,
    assessment_analytics,
    investigation_workspace,
    copilot,
    scenarios,
    lifecycle,
    mlops,
    reporting,
    observability,
    security_admin,
    fleet_capabilities,
    fleet_config,
    fleet_sites,
    fusion,
    geo_analytics,
    geo_export,
    geo_timeline,
    geospatial,
    health,
    inference,
    infra_alerts,
    ingestion,
    investigations,
    media,
    observations,
    relationships,
    risk_assessments,
    sensor_analytics,
    sensor_ingestion,
    sensors,
    sources,
    track_annotations,
    tracking,
    tracking_evaluation,
    users,
)
from app.core.config import get_settings
from app.core.errors import IncompatibleComparison, MlopsError, scrub
from app.core.rate_limit import limiter
from app.core.security_config import startup_blockers
from app.middleware.hardening import SecurityHeadersMiddleware, SizeLimitMiddleware
from app.core.logging_config import configure_logging
from app.middleware.request_context import RequestContextMiddleware
from app.web_frontend import mount_frontend

settings = get_settings()
configure_logging()
logger = logging.getLogger("aegis.startup")


def _check_production_safety() -> None:
    """Section 16: do not disable authentication globally to simplify
    development, and do not let a dev-only secret reach production
    unnoticed. Refuses to START (not just warns) when ENVIRONMENT=
    production still carries the placeholder SECRET_KEY."""
    if settings.ENVIRONMENT == "production" and settings.SECRET_KEY == "dev-only-secret-change-me-in-production":
        raise RuntimeError(
            "Refusing to start: ENVIRONMENT=production but SECRET_KEY is still the development "
            "placeholder. Set a real SECRET_KEY via environment variable before running in production."
        )
    blockers = startup_blockers(settings)
    if blockers:
        raise RuntimeError("Refusing to start in production: " + "; ".join(blockers) + ". See docs/security/ENVIRONMENT_CONFIGURATION.md.")


def create_app() -> FastAPI:
    _check_production_safety()

    app = FastAPI(
        title="AEGIS",
        description="AI Defense Intelligence, Threat Assessment and Situational Awareness Platform -- "
        "a decision-support platform. See docs/SECURITY.md and the non-lethality statement in the README: "
        "no autonomous targeting, weapon control, or engagement logic exists anywhere in this codebase.",
        version="1.0.0-rc.3",
        docs_url="/api/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.docs_enabled else None,
    )

    app.state.limiter = limiter  # the same instance the routes decorate with

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Device-Id", "X-Device-Api-Key"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    if settings.SECURITY_HEADERS_ENABLED:
        app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(SizeLimitMiddleware)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Never leaks a stack trace to the client --
        the real traceback goes to the server log only, tagged with the
        same request_id the client gets back."""
        request_id = getattr(request.state, "request_id", None)
        logger.exception("unhandled_exception", extra={"request_id": request_id, "path": request.url.path})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal error occurred.", "request_id": request_id},
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        """Same {"detail", "request_id"} shape as every other error (slowapi's default
        returns {"error": ...}, which the frontend could not display), plus Retry-After."""
        request_id = getattr(request.state, "request_id", None)
        item = getattr(getattr(exc, "limit", None), "limit", None)  # limits.RateLimitItem
        window = int(item.get_expiry()) if item is not None else 60
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": f"Too many requests ({exc.detail}). Try again in up to {window} seconds.",
                     "error_category": "rate_limited", "request_id": request_id},
            headers={"Retry-After": str(window)},
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "request_id": request_id}, headers=getattr(exc, "headers", None))

    @app.exception_handler(MlopsError)
    async def mlops_error_handler(request: Request, exc: MlopsError) -> JSONResponse:
        """Curated domain errors (validation, conflict, missing artifact, ...) map to
        their own status with a stable `error_category`; the message is the curated
        one, never a raw exception string."""
        request_id = getattr(request.state, "request_id", None)
        body = {"detail": scrub(str(exc)), "error_category": exc.category, "request_id": request_id}
        if isinstance(exc, IncompatibleComparison):
            body["reasons"] = exc.reasons
        return JSONResponse(status_code=exc.http_status, content=body)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Report where and why validation failed, never what was sent: the
        # default handler echoes the rejected value as `input`, which can be a
        # password, API key or the whole body (and, for NaN/Infinity, cannot
        # even be serialised). `ctx` is dropped for the same reason. The shape
        # stays {"detail": [{type, loc, msg}]} so existing clients keep working.
        errors = [{"type": e.get("type"), "loc": list(e.get("loc", ())), "msg": str(e.get("msg", ""))} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors, "request_id": getattr(request.state, "request_id", None)})

    api_prefix = "/api/v1"
    app.include_router(health.router, prefix=api_prefix)
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(users.router, prefix=api_prefix)
    app.include_router(sources.router, prefix=api_prefix)
    app.include_router(events.router, prefix=api_prefix)
    app.include_router(assets.router, prefix=api_prefix)
    app.include_router(sensors.router, prefix=api_prefix)
    app.include_router(observations.router, prefix=api_prefix)
    app.include_router(investigations.router, prefix=api_prefix)
    app.include_router(risk_assessments.router, prefix=api_prefix)
    app.include_router(ingestion.router, prefix=api_prefix)
    app.include_router(audit.router, prefix=api_prefix)
    app.include_router(dashboard.router, prefix=api_prefix)
    app.include_router(data_quality.router, prefix=api_prefix)
    app.include_router(correlation.router, prefix=api_prefix)
    app.include_router(evidence.router, prefix=api_prefix)
    app.include_router(relationships.router, prefix=api_prefix)
    app.include_router(conflicts.router, prefix=api_prefix)
    app.include_router(assessments.router, prefix=api_prefix)
    app.include_router(fusion.router, prefix=api_prefix)
    app.include_router(media.router, prefix=api_prefix)
    app.include_router(cv_models.router, prefix=api_prefix)
    app.include_router(inference.router, prefix=api_prefix)
    app.include_router(detections.router, prefix=api_prefix)
    app.include_router(evaluation.router, prefix=api_prefix)
    app.include_router(tracking.router, prefix=api_prefix)
    app.include_router(track_annotations.router, prefix=api_prefix)
    app.include_router(tracking_evaluation.router, prefix=api_prefix)
    app.include_router(sensor_ingestion.router, prefix=api_prefix)
    app.include_router(sensor_analytics.router, prefix=api_prefix)
    app.include_router(cross_source_comparison.router, prefix=api_prefix)
    app.include_router(geospatial.router, prefix=api_prefix)
    app.include_router(geo_timeline.router, prefix=api_prefix)
    app.include_router(geo_analytics.router, prefix=api_prefix)
    app.include_router(geo_export.router, prefix=api_prefix)
    app.include_router(edge_devices.router, prefix=api_prefix)
    app.include_router(edge_sync.router, prefix=api_prefix)
    app.include_router(edge_sync_admin.router, prefix=api_prefix)
    app.include_router(edge_conflicts.router, prefix=api_prefix)
    app.include_router(edge_presence.router, prefix=api_prefix)
    app.include_router(fleet_sites.router, prefix=api_prefix)
    app.include_router(fleet_config.router, prefix=api_prefix)
    app.include_router(fleet_capabilities.router, prefix=api_prefix)
    app.include_router(infra_alerts.router, prefix=api_prefix)
    app.include_router(fleet_analytics.router, prefix=api_prefix)
    app.include_router(model_outputs.router, prefix=api_prefix)
    app.include_router(model_evaluations.router, prefix=api_prefix)
    app.include_router(assessment_analytics.router, prefix=api_prefix)
    app.include_router(investigation_workspace.router, prefix=api_prefix)
    app.include_router(investigation_workspace.evidence_router, prefix=api_prefix)
    app.include_router(investigation_workspace.dashboard_router, prefix=api_prefix)
    app.include_router(copilot.router, prefix=api_prefix)
    app.include_router(copilot.copilot_router, prefix=api_prefix)
    app.include_router(scenarios.router, prefix=api_prefix)
    app.include_router(mlops.router, prefix=api_prefix)
    app.include_router(reporting.router, prefix=api_prefix)
    app.include_router(observability.router, prefix=api_prefix)
    app.include_router(lifecycle.router, prefix=api_prefix)
    app.include_router(security_admin.router, prefix=api_prefix)
    app.include_router(demo.router, prefix=api_prefix)

    # One-container hosting: the frontend is served last, so every API route above wins.
    if settings.FRONTEND_DIST_DIR:
        mount_frontend(app, settings.FRONTEND_DIST_DIR, settings.FRONTEND_CSP_FILE, settings.FRONTEND_FRAME_ANCESTORS)

    return app


app = create_app()
