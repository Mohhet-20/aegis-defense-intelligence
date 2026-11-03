"""Deterministic fingerprints.

A fingerprint is the SHA-256 of a canonical JSON encoding: keys sorted, no
whitespace, UTF-8, and NaN/Infinity REJECTED (they have no stable JSON form).
Two configurations that are semantically equal always hash equal; any change to
a value, key or list order changes the hash. A fingerprint identifies *inputs*;
it does not prove two runs will produce bit-identical numbers (see
``reproducibility_info`` limitations).
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from typing import Any

from app.core.config import get_settings

FINGERPRINT_VERSION = "1"


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def fingerprint(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def reproducibility_info(*, seed_description: str, fixture_version: str, metrics_version: str, artifact_digest: str | None,
                         execution_backend: str = "in-process-cpu", preprocessing_version: str = "none") -> dict:
    """Software/runtime facts that can be captured honestly in this process.
    Anything that cannot be determined is omitted or reported as null -- never
    guessed."""
    info: dict[str, Any] = {
        "fingerprint_version": FINGERPRINT_VERSION,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "application_version": "1.0.0-phase1",
        "git_commit": get_settings().APP_GIT_COMMIT or None,
        "execution_backend": execution_backend,
        "random_seed": seed_description,
        "evaluation_fixture_version": fixture_version,
        "preprocessing_version": preprocessing_version,
        "metric_implementation_version": metrics_version,
        "model_artifact_digest": artifact_digest,
    }
    libs = {}
    for mod in ("numpy", "scipy", "cv2"):
        try:
            m = __import__(mod)
            libs[mod] = getattr(m, "__version__", None)
        except Exception:  # noqa: BLE001 -- an optional library that is missing is simply not reported
            libs[mod] = None
    info["library_versions"] = libs
    info["determinism_notes"] = [
        "Fingerprints identify the inputs (model version, configuration, dataset). They do not guarantee bit-identical metrics on different hardware or library versions.",
        "Library and Python versions are recorded so a difference can be investigated; they are not pinned by this system.",
    ]
    return info
