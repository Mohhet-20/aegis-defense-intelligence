"""Image-space motion analytics. Purely
descriptive statistics derived from a track's own OBSERVED bounding
boxes -- never a physical-world speed, never a geographic coordinate,
and never an interpolated position presented as fact (Section 7's three
central prohibitions, all enforced by this module simply never
computing those things in the first place, not by a flag that could be
turned off).

Pixel figures use the source video's own stored `width_px`/`height_px`
(Phase 4's MediaAsset -- a real, measured property of the file, not a
guess) to convert the fractional (0..1) bbox coordinates this platform
already stores everywhere else into real pixel units ON THE STORED
FRAME RESOLUTION. This is still an image-space measurement, not a
physical-world one: it answers "how many pixels did this box's center
move between two sampled frames of this specific video," never "how
many metres did the object move."
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class ObservationPoint:
    frame_index: int
    timestamp_seconds: float
    bbox: BBox


@dataclass(frozen=True)
class MotionStep:
    """Describes the transition from one observation to the NEXT
    observation actually recorded for this track -- which may not be
    the immediately-next sampled frame of the source video if the
    track went missing in between (see `gap_sampled_frames` on
    MotionSummary, computed separately, with full knowledge of the
    source job's own sampled-frame list)."""

    from_frame_index: int
    to_frame_index: int
    elapsed_seconds: float
    center_from_px: tuple[float, float]
    center_to_px: tuple[float, float]
    displacement_px: float
    direction_degrees: Optional[float]  # None for zero displacement -- a direction is undefined, never fabricated as 0.0


@dataclass(frozen=True)
class MotionSummary:
    unit_note: str
    observation_count: int
    duration_seconds: float
    steps: list[MotionStep]
    total_path_length_px: float
    net_displacement_px: float
    bbox_area_px_first: float
    bbox_area_px_last: float
    bbox_area_change_ratio: Optional[float]
    missed_sampled_frame_count: int
    missing_frame_indices: list[int]
    fragmentation_count: int  # number of separate observed runs within the job's own sampled-frame timeline


def _center_px(bbox: BBox, width_px: int, height_px: int) -> tuple[float, float]:
    x_min, y_min, x_max, y_max = bbox
    return ((x_min + x_max) / 2.0 * width_px, (y_min + y_max) / 2.0 * height_px)


def _area_px(bbox: BBox, width_px: int, height_px: int) -> float:
    x_min, y_min, x_max, y_max = bbox
    return max(0.0, (x_max - x_min) * width_px) * max(0.0, (y_max - y_min) * height_px)


def compute_motion_summary(
    observations: list[ObservationPoint],
    *,
    width_px: int,
    height_px: int,
    job_sampled_frame_indices: Optional[list[int]] = None,
) -> MotionSummary:
    """`job_sampled_frame_indices` is the FULL list of frame indices the
    source InferenceJob sampled for the whole video (not just this
    track's own observations) -- it is what lets this function tell the
    difference between "this track has a real gap" (some sampled frames
    in its span have no observation) and "this track is simply short"
    (it only existed for the frames it has). Passing None skips the gap/
    fragmentation computation rather than guessing.
    """
    unit_note = "pixels, on the source video's stored frame resolution -- never a physical-world unit, never a geographic coordinate"

    if not observations:
        return MotionSummary(
            unit_note=unit_note, observation_count=0, duration_seconds=0.0, steps=[], total_path_length_px=0.0, net_displacement_px=0.0,
            bbox_area_px_first=0.0, bbox_area_px_last=0.0, bbox_area_change_ratio=None, missed_sampled_frame_count=0,
            missing_frame_indices=[], fragmentation_count=0,
        )

    ordered = sorted(observations, key=lambda o: o.frame_index)
    steps: list[MotionStep] = []
    total_path_length = 0.0

    for prev, curr in zip(ordered[:-1], ordered[1:]):
        prev_center = _center_px(prev.bbox, width_px, height_px)
        curr_center = _center_px(curr.bbox, width_px, height_px)
        dx = curr_center[0] - prev_center[0]
        dy = curr_center[1] - prev_center[1]
        displacement = math.hypot(dx, dy)
        total_path_length += displacement
        direction: Optional[float] = None
        if displacement > 1e-9:
            # Image-coordinate convention: +x is right, +y is DOWN
            # (screen space, not mathematical/geographic space) -- 0 deg
            # = moving right, 90 deg = moving down. Documented explicitly
            # in docs/ml/IMAGE_SPACE_MOTION_ANALYTICS.md so nobody mistakes
            # this for a compass bearing.
            direction = round(math.degrees(math.atan2(dy, dx)), 2)
        steps.append(
            MotionStep(
                from_frame_index=prev.frame_index, to_frame_index=curr.frame_index,
                elapsed_seconds=round(curr.timestamp_seconds - prev.timestamp_seconds, 6),
                center_from_px=(round(prev_center[0], 2), round(prev_center[1], 2)),
                center_to_px=(round(curr_center[0], 2), round(curr_center[1], 2)),
                displacement_px=round(displacement, 2), direction_degrees=direction,
            )
        )

    first_center = _center_px(ordered[0].bbox, width_px, height_px)
    last_center = _center_px(ordered[-1].bbox, width_px, height_px)
    net_displacement = math.hypot(last_center[0] - first_center[0], last_center[1] - first_center[1])

    area_first = _area_px(ordered[0].bbox, width_px, height_px)
    area_last = _area_px(ordered[-1].bbox, width_px, height_px)
    area_ratio = round(area_last / area_first, 4) if area_first > 0 else None

    missed_count = 0
    missing_frame_indices: list[int] = []
    fragmentation_count = 1 if ordered else 0
    if job_sampled_frame_indices:
        observed_set = {o.frame_index for o in ordered}
        span = [f for f in sorted(job_sampled_frame_indices) if ordered[0].frame_index <= f <= ordered[-1].frame_index]
        missing_frame_indices = [f for f in span if f not in observed_set]
        missed_count = len(missing_frame_indices)
        # Fragmentation: count transitions from "observed" to "missed"
        # across the track's own span of the job's sampled timeline --
        # a track with zero gaps has fragmentation_count == 1 (one
        # single run); every gap adds one more run.
        fragmentation_count = 0
        previously_observed: Optional[bool] = None
        for f in span:
            is_observed = f in observed_set
            if is_observed and not previously_observed:
                fragmentation_count += 1
            previously_observed = is_observed

    return MotionSummary(
        unit_note=unit_note, observation_count=len(ordered), duration_seconds=round(ordered[-1].timestamp_seconds - ordered[0].timestamp_seconds, 6),
        steps=steps, total_path_length_px=round(total_path_length, 2), net_displacement_px=round(net_displacement, 2),
        bbox_area_px_first=round(area_first, 2), bbox_area_px_last=round(area_last, 2), bbox_area_change_ratio=area_ratio,
        missed_sampled_frame_count=missed_count, missing_frame_indices=missing_frame_indices, fragmentation_count=fragmentation_count,
    )
