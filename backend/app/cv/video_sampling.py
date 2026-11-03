"""Bounded video frame sampling. Reads a video
file frame-by-frame via `cv2.VideoCapture.read()` and yields only the
frames that land on the configured sampling interval, up to a hard
`max_frames` cap -- the decoded video is NEVER held in memory as a
list; at most one decoded frame exists at a time, and iteration stops
the instant `max_frames` is reached regardless of how much video is
left.

This is explicitly bounded, point-in-time sampling, not continuous
monitoring: a caller gets back a small, fixed-size set of
(frame_index, timestamp_seconds, frame) tuples and nothing more. See
docs/ml/VIDEO_FRAME_ANALYSIS.md's "What this does NOT do" section --
this module has no notion of a live/ongoing stream, no loop that keeps
pulling new frames over time, and is not wired to anything resembling
continuous surveillance.
"""
from __future__ import annotations

from typing import Iterator

import cv2
import numpy as np


class VideoOpenError(ValueError):
    pass


def probe_video(path: str) -> dict:
    """Returns real, measured metadata (never guessed) -- used both by
    media_service.py at ingestion time and by inference_service.py
    before sampling."""
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise VideoOpenError("file could not be opened as a valid video container")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if width <= 0 or height <= 0:
            raise VideoOpenError("video reports zero or negative frame dimensions")
        duration_seconds = (frame_count / fps) if fps > 0 else 0.0
        return {"fps": fps, "frame_count": frame_count, "width": width, "height": height, "duration_seconds": duration_seconds}
    finally:
        cap.release()


def sample_frames(path: str, *, interval_seconds: float, max_frames: int) -> Iterator[tuple[int, float, np.ndarray]]:
    """Yields (frame_index, timestamp_seconds, frame_bgr) tuples,
    sequentially decoding and immediately discarding every frame that
    is NOT selected (no seeking by position, which is unreliable across
    codecs for many containers -- sequential `.read()` is the
    conservative, broadly-correct choice).
    """
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise VideoOpenError("file could not be opened as a valid video container")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 1.0
        frame_stride = max(1, round(fps * interval_seconds))

        yielded = 0
        frame_index = 0
        while yielded < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_index % frame_stride == 0:
                timestamp_seconds = frame_index / fps
                yield frame_index, timestamp_seconds, frame
                yielded += 1
            frame_index += 1
    finally:
        cap.release()
