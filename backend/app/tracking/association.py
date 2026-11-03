"""Detection-to-track association. A pure,
deterministic function: given the last known box of every active track
and the boxes of every detection in the current frame, decide which
pairs represent the same object.

Deliberately uses `scipy.optimize.linear_sum_assignment` -- the Hungarian
algorithm, a tested library implementation -- rather than a hand-rolled
greedy sort, per Section 5's own instruction ("If an assignment algorithm
is used, choose a tested implementation compatible with the project").
Hungarian assignment is also a strictly better choice than greedy
matching here: greedy can lock in a locally-good-looking pair that
blocks a globally-better one, while the Hungarian algorithm finds the
assignment that minimizes TOTAL cost across all pairs simultaneously.

Boxes are fractional (0..1) image coordinates, the same convention
DetectionResult/TrackObservation already use -- IoU is scale-invariant,
so there is no need to denormalize to pixels for this comparison.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

BBox = tuple[float, float, float, float]  # (x_min, y_min, x_max, y_max)


@dataclass(frozen=True)
class AssociationCandidate:
    """One active track's current state, as the association function
    needs to see it -- never the full Track ORM row (this module has no
    database dependency)."""

    track_index: int  # position in the caller's own active-track list
    class_label: str
    last_bbox: BBox


@dataclass(frozen=True)
class AssociationDetection:
    detection_index: int  # position in the caller's own detection list
    class_label: str
    bbox: BBox


@dataclass(frozen=True)
class AssociationMatch:
    track_index: int
    detection_index: int
    cost: float  # 1 - IoU; lower is a better match


@dataclass(frozen=True)
class AssociationResult:
    matches: list[AssociationMatch]
    unmatched_track_indices: list[int]
    unmatched_detection_indices: list[int]


def compute_iou(a: BBox, b: BBox) -> float:
    """Standard intersection-over-union on two (x_min, y_min, x_max,
    y_max) boxes in the same coordinate space. Returns 0.0 for
    non-overlapping or degenerate boxes -- never raises, never divides
    by zero."""
    ax_min, ay_min, ax_max, ay_max = a
    bx_min, by_min, bx_max, by_max = b

    inter_x_min = max(ax_min, bx_min)
    inter_y_min = max(ay_min, by_min)
    inter_x_max = min(ax_max, bx_max)
    inter_y_max = min(ay_max, by_max)

    inter_w = max(0.0, inter_x_max - inter_x_min)
    inter_h = max(0.0, inter_y_max - inter_y_min)
    intersection = inter_w * inter_h

    area_a = max(0.0, ax_max - ax_min) * max(0.0, ay_max - ay_min)
    area_b = max(0.0, bx_max - bx_min) * max(0.0, by_max - by_min)
    union = area_a + area_b - intersection

    if union <= 0.0:
        return 0.0
    return intersection / union


def associate(
    tracks: list[AssociationCandidate],
    detections: list[AssociationDetection],
    *,
    min_iou_threshold: float,
    require_class_match: bool,
) -> AssociationResult:
    """Deterministic for identical inputs and configuration (Section 5:
    "Ensure association is deterministic ... when the selected
    algorithm permits it" -- the Hungarian algorithm's result is a
    pure function of the cost matrix, which is itself a pure function
    of the inputs, so this holds unconditionally here).

    Never forces a match below `min_iou_threshold` ("Never
    force a match when the association score does not satisfy the
    configured criteria") -- a pair the Hungarian solver assigns but
    whose IoU is too low, or whose class differs when
    require_class_match is True, is unassigned afterward and reported
    as two separate unmatched entries, not as a low-confidence match.
    """
    if not tracks or not detections:
        return AssociationResult(
            matches=[],
            unmatched_track_indices=[t.track_index for t in tracks],
            unmatched_detection_indices=[d.detection_index for d in detections],
        )

    n_tracks, n_detections = len(tracks), len(detections)
    # A cost high enough that the solver will always prefer any
    # genuinely-valid pairing over this one, but finite (required by
    # linear_sum_assignment) and never actually accepted as a real
    # match -- filtered out by the min_iou_threshold check below
    # regardless of what the solver picks.
    forbidden_cost = 10.0

    cost_matrix = np.full((n_tracks, n_detections), forbidden_cost, dtype=float)
    iou_matrix = np.zeros((n_tracks, n_detections), dtype=float)
    for i, track in enumerate(tracks):
        for j, det in enumerate(detections):
            if require_class_match and track.class_label != det.class_label:
                continue
            iou = compute_iou(track.last_bbox, det.bbox)
            iou_matrix[i, j] = iou
            cost_matrix[i, j] = 1.0 - iou

    row_indices, col_indices = linear_sum_assignment(cost_matrix)

    matches: list[AssociationMatch] = []
    matched_track_positions: set[int] = set()
    matched_detection_positions: set[int] = set()
    for row, col in zip(row_indices, col_indices):
        iou = iou_matrix[row, col]
        if iou < min_iou_threshold or not math.isfinite(iou):
            continue  # the solver's globally-optimal pick still fails this pair's own threshold -- never force it
        matches.append(AssociationMatch(track_index=tracks[row].track_index, detection_index=detections[col].detection_index, cost=round(float(1.0 - iou), 6)))
        matched_track_positions.add(row)
        matched_detection_positions.add(col)

    unmatched_track_indices = [t.track_index for i, t in enumerate(tracks) if i not in matched_track_positions]
    unmatched_detection_indices = [d.detection_index for j, d in enumerate(detections) if j not in matched_detection_positions]

    return AssociationResult(matches=matches, unmatched_track_indices=unmatched_track_indices, unmatched_detection_indices=unmatched_detection_indices)
