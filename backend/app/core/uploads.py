"""Bounded upload reads. `UploadFile.read()` with no
argument buffers the whole body; this reads in chunks and aborts with 413 as
soon as the limit is crossed."""
from __future__ import annotations

from fastapi import HTTPException, UploadFile, status

_CHUNK = 1024 * 1024


async def read_bounded(file: UploadFile, max_bytes: int) -> bytes:
    buf = bytearray()
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"File exceeds the {max_bytes}-byte limit")
    return bytes(buf)
