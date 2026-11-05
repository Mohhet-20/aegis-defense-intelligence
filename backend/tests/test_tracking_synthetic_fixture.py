"""/16: the synthetic multi-object fixture itself.
Confirms it is genuinely deterministic (pure arithmetic, no `random`,
no wall-clock) and that its "crossing" sequence really does cross where
its own docstring claims.
"""
from __future__ import annotations

from app.tracking.synthetic_fixture import FRAME_COUNT, generate


def test_generate_returns_both_named_sequences_in_a_fixed_order():
    sequences = generate()
    assert [s.name for s in sequences] == ["parallel", "crossing"]


def test_generate_is_deterministic_across_calls():
    first = generate()
    second = generate()
    for s1, s2 in zip(first, second):
        assert s1.name == s2.name
        assert len(s1.frames) == len(s2.frames)
        for f1, f2 in zip(s1.frames, s2.frames):
            assert f1.frame_index == f2.frame_index
            assert [d.bbox for d in f1.detections] == [d.bbox for d in f2.detections]


def test_parallel_sequence_objects_never_overlap():
    from app.tracking.association import compute_iou

    sequences = generate()
    parallel = next(s for s in sequences if s.name == "parallel")
    for frame in parallel.frames:
        a, b = frame.detections
        assert compute_iou(a.bbox, b.bbox) == 0.0


def test_crossing_sequence_actually_crosses_at_the_midpoint_frame():
    from app.tracking.association import compute_iou

    sequences = generate()
    crossing = next(s for s in sequences if s.name == "crossing")
    midpoint = FRAME_COUNT // 2
    midpoint_frame = crossing.frames[midpoint]
    a, b = midpoint_frame.detections
    # Heavy overlap at the midpoint -- this is the honest, deliberately
    # constructed stress test, not an accident of arithmetic.
    assert compute_iou(a.bbox, b.bbox) > 0.9

    # Before the midpoint the two objects are still well separated.
    early_a, early_b = crossing.frames[0].detections
    assert compute_iou(early_a.bbox, early_b.bbox) == 0.0


def test_every_sequence_has_both_ground_truth_tracks_present_in_every_frame():
    for sequence in generate():
        for frame in sequence.frames:
            gt_ids = {d.ground_truth_track_id for d in frame.detections}
            assert gt_ids == set(sequence.ground_truth_track_ids)
