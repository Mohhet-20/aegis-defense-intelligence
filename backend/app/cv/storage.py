"""Private, content-addressed media storage.

Every path this module touches is derived from a server-computed
content hash, never from a client-supplied filename -- so there is no
path-traversal surface even though this module is the one place that
turns a `storage_key` string into a real filesystem path. The storage
root is NEVER registered as a static file-serving directory in
app/main.py; the only way to read a byte of media content back out is
through app/api/routes/media.py's authorized, organization-scoped
`GET /media/{id}/content` route, which calls `read_bytes()` below.
"""
from __future__ import annotations

import os

from app.core.config import get_settings

settings = get_settings()


class PathTraversalError(ValueError):
    """Raised if a resolved path would ever escape the configured
    storage root -- defense in depth; every caller in this codebase
    only ever builds `storage_key` from a content hash, so this should
    be unreachable in practice, but it is checked unconditionally
    anyway rather than trusted to stay that way."""


def _root() -> str:
    root = os.path.abspath(settings.CV_MEDIA_STORAGE_ROOT)
    os.makedirs(root, exist_ok=True)
    return root


def build_storage_key(organization_id: str, content_hash: str, extension: str) -> str:
    """organization_id and content_hash are both always server-generated
    (a UUID and a sha256 hex digest respectively) -- never derived from
    a client-supplied filename."""
    ext = extension.lstrip(".").lower()
    if not ext.isalnum():
        ext = "bin"
    return f"{organization_id}/{content_hash}.{ext}"


def _resolve(storage_key: str) -> str:
    root = _root()
    candidate = os.path.abspath(os.path.join(root, storage_key))
    # realpath resolves any symlink components too -- the check below
    # is against the fully resolved path, not the merely-joined one.
    if os.path.commonpath([os.path.realpath(root), os.path.realpath(os.path.dirname(candidate) if not os.path.exists(candidate) else candidate)]) != os.path.realpath(root):
        raise PathTraversalError(f"resolved media path escapes the storage root: {storage_key!r}")
    return candidate


def write_bytes(storage_key: str, content: bytes) -> None:
    path = _resolve(storage_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)


def read_bytes(storage_key: str) -> bytes:
    path = _resolve(storage_key)
    with open(path, "rb") as fh:
        return fh.read()


def path_for(storage_key: str) -> str:
    """Returns a real filesystem path for APIs (cv2.VideoCapture) that
    need a path rather than a bytes buffer. Still goes through the same
    traversal-safe resolution as every other accessor."""
    return _resolve(storage_key)


def delete(storage_key: str) -> None:
    path = _resolve(storage_key)
    if os.path.exists(path):
        os.remove(path)
