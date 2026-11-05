"""Controlled model-artifact references.

A model version never stores a binary in the database and never causes code to
be loaded from a registry value. ``artifact_reference`` is one of:

  * ``adapter:<key>``    -- a key in the closed adapter allow-list
                            (app/cv/adapters/registry.py). Available iff the key
                            is registered in this runtime.
  * ``artifact:<relpath>`` -- a RELATIVE path under MLOPS_ARTIFACT_ROOT. It is
                            only ever read for hashing / existence; it is never
                            imported, unpickled or executed.

Anything else (URLs, absolute paths, ``..``, backslashes, NUL, drive letters,
very long strings) is rejected at registration time, so a registry row cannot
point the server at an arbitrary file or make it fetch a remote resource.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Optional

from app.core.config import get_settings
from app.core.errors import MlopsValidationError

_ADAPTER_REF = re.compile(r"^adapter:([A-Za-z0-9_.\-]{1,100})$")
_FILE_REF = re.compile(r"^artifact:([A-Za-z0-9_.\-/]{1,400})$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CHUNK = 1024 * 1024


@dataclass
class ArtifactStatus:
    kind: str  # adapter | file | none
    available: bool
    reason: Optional[str] = None
    size_bytes: Optional[int] = None
    digest_checked: bool = False
    digest_match: Optional[bool] = None
    computed_digest: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "available": self.available, "reason": self.reason, "size_bytes": self.size_bytes,
            "digest_checked": self.digest_checked, "digest_match": self.digest_match,
        }


def validate_reference(ref: str) -> tuple[str, str]:
    """Returns (kind, value). Raises MlopsValidationError for anything unsafe."""
    m = _ADAPTER_REF.match(ref or "")
    if m:
        return "adapter", m.group(1)
    m = _FILE_REF.match(ref or "")
    if m:
        rel = m.group(1)
        parts = rel.split("/")
        if rel.startswith("/") or any(p in ("", ".", "..") for p in parts):
            raise MlopsValidationError("artifact_reference path must be relative and contain no '.', '..' or empty segments")
        return "file", rel
    raise MlopsValidationError("artifact_reference must be 'adapter:<key>' or 'artifact:<relative/path>'; URLs and absolute paths are not accepted")


def _resolve_file(rel: str) -> Optional[str]:
    root = get_settings().MLOPS_ARTIFACT_ROOT
    if not root:
        return None
    root_real = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(root_real, *rel.split("/")))
    # Containment is checked on the RESOLVED path, so symlinks cannot escape the root.
    if os.path.commonpath([root_real, candidate]) != root_real:
        return None
    return candidate


def sha256_file(path: str, max_bytes: int) -> str:
    h = hashlib.sha256()
    read = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            read += len(chunk)
            if read > max_bytes:
                raise MlopsValidationError("artifact exceeds the configured maximum size for digest verification")
            h.update(chunk)
    return h.hexdigest()


def check_artifact(artifact_reference: Optional[str], adapter_key: Optional[str], expected_digest: Optional[str], *, verify_digest: bool) -> ArtifactStatus:
    """Cheap availability check; hashes the file only when ``verify_digest``."""
    ref = artifact_reference or (f"adapter:{adapter_key}" if adapter_key else None)
    if not ref:
        return ArtifactStatus(kind="none", available=False, reason="no artifact or adapter is registered for this version")
    try:
        kind, value = validate_reference(ref)
    except MlopsValidationError:
        # Legacy rows may hold free-text references from earlier work; they are never dereferenced.
        return ArtifactStatus(kind="none", available=False, reason="legacy artifact reference is not a controlled reference and is not dereferenced")
    if kind == "adapter":
        from app.cv.adapters.registry import available_adapter_keys

        ok = value in available_adapter_keys()
        return ArtifactStatus(kind="adapter", available=ok, reason=None if ok else "adapter is not registered in this runtime")
    path = _resolve_file(value)
    if path is None:
        return ArtifactStatus(kind="file", available=False, reason="artifact storage root is not configured or the path is outside it")
    if not os.path.isfile(path):
        return ArtifactStatus(kind="file", available=False, reason="artifact file is missing")
    st = ArtifactStatus(kind="file", available=True, size_bytes=os.path.getsize(path))
    if verify_digest:
        st.digest_checked = True
        if not expected_digest:
            st.digest_match = None
            st.reason = "no digest was registered, so integrity cannot be verified"
        else:
            actual = sha256_file(path, get_settings().MLOPS_MAX_ARTIFACT_HASH_BYTES)
            st.computed_digest = actual
            st.digest_match = actual == expected_digest
            if not st.digest_match:
                st.available = False
                st.reason = "artifact content does not match the registered digest"
    return st
