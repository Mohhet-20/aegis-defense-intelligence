from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def check_database(db: Session) -> bool:
    """Actually executes a trivial query against the real configured
    database -- 'ready' is never returned unconditionally."""
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def check_model_runtime() -> bool:
    """a per-dependency readiness check distinct from
    the bare process-is-alive liveness probe. Actually imports cv2/numpy
    and instantiates the real HOG adapter's detector -- the same
    operations app/cv/adapters/opencv_hog_adapter.py performs at
    inference time -- rather than assuming the runtime is fine because
    the process started. There is still no "worker" or "model-runtime"
    process distinct from the API process (Section 11's per-dependency
    liveness/readiness split is honored at the dependency-check level
    this function provides, not by running a separate process)."""
    try:
        import cv2

        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        return True
    except Exception:
        return False


def check_tracker_runtime() -> bool:
    """confirms the Hungarian-assignment dependency
    (scipy) this tracker needs is actually importable and callable in
    this process, the same "actually exercise it, don't just assume"
    discipline as check_model_runtime(). An available API process is
    never, by itself, proof that tracking actually works."""
    try:
        import numpy as np
        from scipy.optimize import linear_sum_assignment

        linear_sum_assignment(np.zeros((1, 1)))
        return True
    except Exception:
        return False


def check_sensor_analytics_runtime() -> bool:
    """actually exercises the statistics/anomaly
    engine's own dependency (Python's statistics module + a real
    computation) rather than assuming the import succeeded because the
    process started -- same discipline as check_tracker_runtime(). This
    is the "analytics-worker availability" signal Section 17 asks be
    reported separately from plain API availability; there is still no
    separate worker process, so this checks the code path in-process."""
    try:
        from datetime import datetime, timezone

        from app.sensors.statistics import TimedValue, compute_descriptive_statistics

        now = datetime.now(timezone.utc)
        series = [TimedValue(observed_at=now, value=1.0), TimedValue(observed_at=now, value=2.0)]
        compute_descriptive_statistics(series, measurement_type="__healthcheck__", unit=None)
        return True
    except Exception:
        return False


def check_media_storage() -> bool:
    """Confirms the configured media storage root is actually writable
    -- never assumed from the setting existing."""
    try:
        from app.cv import storage

        # A unique key per probe: with one shared name, two concurrent readiness
        # checks (load balancer + monitor + browser) race on write/read/delete and
        # one reports a false "storage error" (503). Reproduced before this fix.
        probe_key = f"__healthcheck__/probe-{uuid.uuid4().hex}.tmp"
        storage.write_bytes(probe_key, b"ok")
        storage.read_bytes(probe_key)
        storage.delete(probe_key)
        return True
    except Exception:
        return False
