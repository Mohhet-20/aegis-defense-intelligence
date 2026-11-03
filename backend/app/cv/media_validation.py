"""Media signature validation. The single place
that decides what an uploaded file actually is -- by sniffing its real
bytes, never by trusting the client's Content-Type header or the
filename's extension. A file that claims to be `photo.png` but is
actually a shell script, an executable, or arbitrary unrecognized bytes
is rejected here before a single byte reaches disk.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Optional

from PIL import Image

from app.core.config import get_settings

settings = get_settings()

# Decompression-bomb guard independent of our own explicit dimension
# check below -- Pillow refuses to even report .size past this many
# total pixels. Set generously above our own cap so our cap is always
# the one that actually fires with a clear message.
Image.MAX_IMAGE_PIXELS = 500_000_000


class MediaValidationError(ValueError):
    """Carries a short, specific, user-facing reason -- never a raw
    exception message from a decoding library."""


@dataclass(frozen=True)
class SniffedMedia:
    media_type: str  # "image" | "video"
    mime_type: str
    extension: str


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"


def sniff_signature(content: bytes) -> SniffedMedia:
    """Identifies the file purely from its own bytes. Returns the
    narrowest type this platform is willing to accept at all; anything
    else raises MediaValidationError with no further processing."""
    if content[:8] == _PNG_SIGNATURE:
        return SniffedMedia(media_type="image", mime_type="image/png", extension="png")
    if content[:3] == _JPEG_SIGNATURE:
        return SniffedMedia(media_type="image", mime_type="image/jpeg", extension="jpg")
    # ISO base media file format (MP4/MOV family): a 4-byte big-endian
    # box size followed by the 4-byte ASCII box type. The first box in a
    # valid MP4 is almost always "ftyp".
    if len(content) >= 12 and content[4:8] == b"ftyp":
        return SniffedMedia(media_type="video", mime_type="video/mp4", extension="mp4")
    raise MediaValidationError(
        "unrecognized or unsupported file signature -- only PNG/JPEG images and MP4 video containers are accepted, "
        "determined from the file's actual bytes, not its name or declared content type"
    )


def validate_size(media_type: str, byte_size: int) -> None:
    limit = settings.CV_MAX_IMAGE_UPLOAD_BYTES if media_type == "image" else settings.CV_MAX_VIDEO_UPLOAD_BYTES
    if byte_size <= 0:
        raise MediaValidationError("uploaded file is empty")
    if byte_size > limit:
        raise MediaValidationError(f"{media_type} exceeds the {limit}-byte upload limit (got {byte_size} bytes)")


def validate_image_dimensions(content: bytes) -> tuple[int, int]:
    """Reads only the header, not the full decoded pixel buffer -- safe
    against a tiny file that claims an enormous resolution, because
    Pillow's own MAX_IMAGE_PIXELS guard (set above) fires first on a
    truly extreme claim, and our own explicit cap below fires on
    anything merely over this platform's configured limit."""
    try:
        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
            img.verify()  # raises on a truncated/corrupt image without fully decoding it
    except MediaValidationError:
        raise
    except Exception as exc:
        raise MediaValidationError(f"file could not be decoded as a valid image: {exc}") from exc

    if width <= 0 or height <= 0:
        raise MediaValidationError("image reports zero or negative dimensions")
    if width > settings.CV_MAX_IMAGE_DIMENSION_PX or height > settings.CV_MAX_IMAGE_DIMENSION_PX:
        raise MediaValidationError(
            f"image dimensions {width}x{height} exceed the {settings.CV_MAX_IMAGE_DIMENSION_PX}px-per-side limit"
        )
    return width, height


_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._ -]")


def sanitize_display_filename(filename: Optional[str]) -> str:
    """Produces a NAME-ONLY string safe to store and render -- never a
    path. Used purely for display (the UI shows what the analyst called
    the file); the actual on-disk name is always the content-addressed
    `storage_key`, never this value."""
    if not filename:
        return "upload"
    # Strip any directory components a client might send (both
    # separators, regardless of the server OS) before anything else.
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    base = _SANITIZE_RE.sub("_", base).strip(" ._") or "upload"
    return base[:255]
