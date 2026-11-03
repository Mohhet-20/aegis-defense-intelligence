"""Phase 5, Section 5/16: detection-to-track association. Pure, DB-free
tests of app/tracking/association.py's `associate()` -- a cost matrix
(1 - IoU) solved by scipy's Hungarian algorithm, never a hand-rolled
greedy sort, with a `min_iou_threshold` post-filter that can reject even
the solver's own globally-optimal pick.
"""
from __future__ import annotations

import pytest

from app.tracking.association import AssociationCandidate, AssociationDetection, associate, compute_iou


def _cand(idx, label, bbox):
    return AssociationCandidate(track_index=idx, class_label=label, last_bbox=bbox)


def _det(idx, label, bbox):
    return AssociationDetection(detection_index=idx, class_label=label, bbox=bbox)


def test_compute_iou_identical_boxes_is_one():
    box = (0.1, 0.1, 0.3, 0.3)
    assert compute_iou(box, box) == pytest.approx(1.0)


def test_compute_iou_disjoint_boxes_is_zero():
    assert compute_iou((0.0, 0.0, 0.1, 0.1), (0.5, 0.5, 0.6, 0.6)) == 0.0


def test_compute_iou_never_raises_on_degenerate_box():
    # Zero-area box -- union would be computed against a zero-area
    # rectangle; must return 0.0, never divide by zero or raise.
    assert compute_iou((0.5, 0.5, 0.5, 0.5), (0.0, 0.0, 1.0, 1.0)) == 0.0


def test_single_detection_single_track_matches_above_threshold():
    tracks = [_cand(0, "mock_object", (0.1, 0.1, 0.3, 0.3))]
    detections = [_det(0, "mock_object", (0.11, 0.11, 0.31, 0.31))]
    result = associate(tracks, detections, min_iou_threshold=0.3, require_class_match=True)
    assert len(result.matches) == 1
    assert result.matches[0].track_index == 0
    assert result.matches[0].detection_index == 0
    assert result.unmatched_track_indices == []
    assert result.unmatched_detection_indices == []


def test_multiple_pairs_resolved_optimally_not_greedily():
    """Track 0 is a near-perfect match for detection 1, and a mediocre
    match for detection 0. Track 1 is a near-perfect match for detection
    0, and a mediocre match for detection 1. A greedy row-by-row scan
    could lock in a locally-good pairing that blocks the globally best
    one; the Hungarian solver must find the total-cost-minimizing
    assignment: 0<->1 and 1<->0."""
    tracks = [
        _cand(0, "mock_object", (0.60, 0.60, 0.70, 0.70)),  # close to det 1
        _cand(1, "mock_object", (0.10, 0.10, 0.20, 0.20)),  # close to det 0
    ]
    detections = [
        _det(0, "mock_object", (0.10, 0.10, 0.20, 0.20)),  # matches track 1
        _det(1, "mock_object", (0.60, 0.60, 0.70, 0.70)),  # matches track 0
    ]
    result = associate(tracks, detections, min_iou_threshold=0.3, require_class_match=True)
    matches_by_track = {m.track_index: m.detection_index for m in result.matches}
    assert matches_by_track == {0: 1, 1: 0}


def test_no_detections_leaves_every_track_unmatched():
    tracks = [_cand(0, "mock_object", (0.1, 0.1, 0.3, 0.3)), _cand(1, "mock_object", (0.5, 0.5, 0.7, 0.7))]
    result = associate(tracks, [], min_iou_threshold=0.3, require_class_match=True)
    assert result.matches == []
    assert sorted(result.unmatched_track_indices) == [0, 1]
    assert result.unmatched_detection_indices == []


def test_no_active_tracks_leaves_every_detection_unmatched():
    detections = [_det(0, "mock_object", (0.1, 0.1, 0.3, 0.3))]
    result = associate([], detections, min_iou_threshold=0.3, require_class_match=True)
    assert result.matches == []
    assert result.unmatched_track_indices == []
    assert result.unmatched_detection_indices == [0]


def test_ambiguous_association_resolves_to_exactly_one_match_per_side():
    """Two tracks sit equidistant-ish from one detection; only one may
    be matched to it (never both), and the loser is reported as
    unmatched, never forced."""
    tracks = [
        _cand(0, "mock_object", (0.10, 0.10, 0.30, 0.30)),
        _cand(1, "mock_object", (0.12, 0.12, 0.32, 0.32)),
    ]
    detections = [_det(0, "mock_object", (0.11, 0.11, 0.31, 0.31))]
    result = associate(tracks, detections, min_iou_threshold=0.3, require_class_match=True)
    assert len(result.matches) == 1
    matched_track_indices = {m.track_index for m in result.matches}
    assert len(matched_track_indices) == 1
    assert len(result.unmatched_track_indices) == 1


def test_below_threshold_pair_is_never_forced_into_a_match():
    # The only candidate pair has a real IoU, but below the configured
    # threshold -- it must be rejected, not forced through because it
    # was the solver's only option.
    tracks = [_cand(0, "mock_object", (0.0, 0.0, 0.10, 0.10))]
    detections = [_det(0, "mock_object", (0.08, 0.08, 0.18, 0.18))]
    iou = compute_iou((0.0, 0.0, 0.10, 0.10), (0.08, 0.08, 0.18, 0.18))
    assert iou < 0.3  # sanity on the fixture itself
    result = associate(tracks, detections, min_iou_threshold=0.3, require_class_match=True)
    assert result.matches == []
    assert result.unmatched_track_indices == [0]
    assert result.unmatched_detection_indices == [0]


def test_class_mismatch_excluded_when_require_class_match_true_even_with_perfect_iou():
    tracks = [_cand(0, "person", (0.1, 0.1, 0.3, 0.3))]
    detections = [_det(0, "vehicle", (0.1, 0.1, 0.3, 0.3))]  # identical box, different class
    result = associate(tracks, detections, min_iou_threshold=0.3, require_class_match=True)
    assert result.matches == []
    assert result.unmatched_track_indices == [0]
    assert result.unmatched_detection_indices == [0]


def test_class_mismatch_still_matches_on_iou_when_require_class_match_false():
    tracks = [_cand(0, "person", (0.1, 0.1, 0.3, 0.3))]
    detections = [_det(0, "vehicle", (0.1, 0.1, 0.3, 0.3))]
    result = associate(tracks, detections, min_iou_threshold=0.3, require_class_match=False)
    assert len(result.matches) == 1


def test_association_is_deterministic_across_repeated_calls():
    tracks = [_cand(0, "mock_object", (0.1, 0.1, 0.3, 0.3)), _cand(1, "mock_object", (0.5, 0.5, 0.7, 0.7))]
    detections = [_det(0, "mock_object", (0.11, 0.11, 0.31, 0.31)), _det(1, "mock_object", (0.51, 0.51, 0.71, 0.71))]
    first = associate(tracks, detections, min_iou_threshold=0.3, require_class_match=True)
    second = associate(tracks, detections, min_iou_threshold=0.3, require_class_match=True)
    assert first == second
