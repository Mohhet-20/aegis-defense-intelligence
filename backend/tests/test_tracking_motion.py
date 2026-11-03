"""Phase 5, Section 7/16: image-space-only motion analytics. Pure,
DB-free tests of app/tracking/motion.py -- every value here must be
pixels on the source video's own stored resolution, never a
physical-world unit, never a fabricated/interpolated position.
"""
from __future__ import annotations

import math

from app.tracking.motion import ObservationPoint, compute_motion_summary


def test_empty_observations_returns_a_zeroed_summary():
    summary = compute_motion_summary([], width_px=100, height_px=100)
    assert summary.observation_count == 0
    assert summary.steps == []
    assert summary.total_path_length_px == 0.0
    assert summary.bbox_area_change_ratio is None


def test_stationary_object_has_zero_displacement_and_undefined_direction():
    points = [
        ObservationPoint(frame_index=0, timestamp_seconds=0.0, bbox=(0.4, 0.4, 0.6, 0.6)),
        ObservationPoint(frame_index=1, timestamp_seconds=0.1, bbox=(0.4, 0.4, 0.6, 0.6)),
    ]
    summary = compute_motion_summary(points, width_px=100, height_px=100)
    assert summary.steps[0].displacement_px == 0.0
    # Direction is undefined for zero displacement -- must be None,
    # never fabricated as 0.0 (which would falsely imply "moving right").
    assert summary.steps[0].direction_degrees is None


def test_horizontal_displacement_is_measured_in_pixels_on_stored_resolution():
    # width_px=200 -- a bbox center moving from x=0.4 to x=0.5 (both
    # fractional) is a real 20px move on THIS video's stored
    # resolution, not a fraction and not a physical distance.
    points = [
        ObservationPoint(frame_index=0, timestamp_seconds=0.0, bbox=(0.35, 0.45, 0.45, 0.55)),
        ObservationPoint(frame_index=1, timestamp_seconds=0.1, bbox=(0.45, 0.45, 0.55, 0.55)),
    ]
    summary = compute_motion_summary(points, width_px=200, height_px=100)
    assert summary.steps[0].displacement_px == 20.0
    assert summary.steps[0].direction_degrees == 0.0  # +x, moving right, image convention


def test_vertical_displacement_direction_is_90_degrees_moving_down():
    # Image-coordinate convention: +y is DOWN (screen space), so moving
    # straight down is 90 degrees -- never a compass bearing.
    points = [
        ObservationPoint(frame_index=0, timestamp_seconds=0.0, bbox=(0.45, 0.35, 0.55, 0.45)),
        ObservationPoint(frame_index=1, timestamp_seconds=0.1, bbox=(0.45, 0.45, 0.55, 0.55)),
    ]
    summary = compute_motion_summary(points, width_px=100, height_px=200)
    assert summary.steps[0].direction_degrees == 90.0


def test_diagonal_displacement_combines_both_axes():
    points = [
        ObservationPoint(frame_index=0, timestamp_seconds=0.0, bbox=(0.0, 0.0, 0.1, 0.1)),
        ObservationPoint(frame_index=1, timestamp_seconds=0.1, bbox=(0.1, 0.1, 0.2, 0.2)),
    ]
    summary = compute_motion_summary(points, width_px=100, height_px=100)
    # Center moves from (5,5) to (15,15) -- displacement = sqrt(10^2+10^2).
    assert summary.steps[0].displacement_px == round(math.hypot(10, 10), 2)
    assert summary.steps[0].direction_degrees == 45.0


def test_variable_frame_intervals_compute_correct_elapsed_seconds():
    points = [
        ObservationPoint(frame_index=0, timestamp_seconds=0.0, bbox=(0.1, 0.1, 0.2, 0.2)),
        ObservationPoint(frame_index=5, timestamp_seconds=2.5, bbox=(0.2, 0.2, 0.3, 0.3)),
        ObservationPoint(frame_index=6, timestamp_seconds=2.6, bbox=(0.3, 0.3, 0.4, 0.4)),
    ]
    summary = compute_motion_summary(points, width_px=100, height_px=100)
    assert summary.steps[0].elapsed_seconds == 2.5
    assert summary.steps[1].elapsed_seconds == 0.1  # rounded to 6 decimals in motion.py -- no float drift survives


def test_missing_observations_are_reported_never_interpolated():
    # The track has observations at frames 0 and 3 only; frames 1 and 2
    # of the job's own sampled timeline have no observation for this
    # track -- they must be reported as missing, never filled in with a
    # guessed position.
    points = [
        ObservationPoint(frame_index=0, timestamp_seconds=0.0, bbox=(0.1, 0.1, 0.2, 0.2)),
        ObservationPoint(frame_index=3, timestamp_seconds=0.3, bbox=(0.4, 0.4, 0.5, 0.5)),
    ]
    summary = compute_motion_summary(points, width_px=100, height_px=100, job_sampled_frame_indices=[0, 1, 2, 3, 4])
    assert summary.missing_frame_indices == [1, 2]
    assert summary.missed_sampled_frame_count == 2
    # Exactly 2 observations were recorded -- motion.py never inserts a
    # synthetic third point for the gap.
    assert summary.observation_count == 2
    assert len(summary.steps) == 1  # one real step: frame 0 -> frame 3, never a fabricated 0->1->2->3 chain


def test_fragmentation_count_reflects_distinct_observed_runs():
    # Two separate runs within the job's sampled span: frames {0,1} and
    # {4,5}, with a gap at {2,3}.
    points = [
        ObservationPoint(frame_index=0, timestamp_seconds=0.0, bbox=(0.1, 0.1, 0.2, 0.2)),
        ObservationPoint(frame_index=1, timestamp_seconds=0.1, bbox=(0.11, 0.1, 0.21, 0.2)),
        ObservationPoint(frame_index=4, timestamp_seconds=0.4, bbox=(0.2, 0.1, 0.3, 0.2)),
        ObservationPoint(frame_index=5, timestamp_seconds=0.5, bbox=(0.21, 0.1, 0.31, 0.2)),
    ]
    summary = compute_motion_summary(points, width_px=100, height_px=100, job_sampled_frame_indices=[0, 1, 2, 3, 4, 5])
    assert summary.fragmentation_count == 2
    assert summary.missing_frame_indices == [2, 3]


def test_no_job_sampled_frame_indices_skips_gap_computation_rather_than_guessing():
    points = [
        ObservationPoint(frame_index=0, timestamp_seconds=0.0, bbox=(0.1, 0.1, 0.2, 0.2)),
        ObservationPoint(frame_index=5, timestamp_seconds=0.5, bbox=(0.2, 0.2, 0.3, 0.3)),
    ]
    summary = compute_motion_summary(points, width_px=100, height_px=100, job_sampled_frame_indices=None)
    assert summary.missing_frame_indices == []
    assert summary.missed_sampled_frame_count == 0


def test_unit_note_explicitly_disclaims_physical_or_geographic_meaning():
    summary = compute_motion_summary(
        [ObservationPoint(frame_index=0, timestamp_seconds=0.0, bbox=(0.1, 0.1, 0.2, 0.2))], width_px=100, height_px=100
    )
    assert "pixel" in summary.unit_note.lower()
    assert "never a physical-world unit" in summary.unit_note
    assert "never a geographic coordinate" in summary.unit_note


def test_no_speed_or_predicted_position_field_exists_on_motion_step():
    """Section 8 explicitly deferred any motion-prediction (Kalman)
    filter -- confirms there is no 'predicted' or 'speed' field for
    this module to ever have populated, so a predicted-vs-observed test
    category genuinely does not apply here."""
    points = [
        ObservationPoint(frame_index=0, timestamp_seconds=0.0, bbox=(0.1, 0.1, 0.2, 0.2)),
        ObservationPoint(frame_index=1, timestamp_seconds=0.1, bbox=(0.2, 0.2, 0.3, 0.3)),
    ]
    summary = compute_motion_summary(points, width_px=100, height_px=100)
    step_fields = summary.steps[0].__dataclass_fields__.keys()
    assert "predicted" not in step_fields
    assert "speed" not in step_fields
    assert "predicted_position" not in step_fields
