from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.health_service import check_database, check_media_storage, check_model_runtime, check_sensor_analytics_runtime, check_tracker_runtime

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def liveness():
    """Liveness only ever answers "is this process running" -- it never
    touches the database, the filesystem, or any model runtime, so a
    slow dependency can never make this process look dead (Section 11:
    liveness and readiness must be distinguished, not conflated)."""
    return {"status": "alive"}


@router.get("/ready")
def readiness(response: Response, db: Session = Depends(get_db)):
    """Readiness checks every real external dependency this API
    currently has -- database, media storage, the CV model
    runtime, and the tracker runtime -- and reports each one
    individually, not just one pass/fail bit. There is still no
    separate 'worker' process or message queue in this codebase to
    report on; this list grows again only when one is actually built."""
    checks = {
        "database": check_database(db),
        "media_storage": check_media_storage(),
        "model_runtime": check_model_runtime(),
        "tracker_runtime": check_tracker_runtime(),
        "sensor_analytics_runtime": check_sensor_analytics_runtime(),
    }
    all_ok = all(checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if all_ok else "not_ready", "checks": {k: ("ok" if v else "error") for k, v in checks.items()}}
