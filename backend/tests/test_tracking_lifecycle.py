"""/16: explicit track lifecycle states. Pure, DB-free
tests of `IoUHungarianTracker` -- the project's single tracker
implementation, serving as both its deterministic test fixture and its
baseline algorithm (app/tracking/trackers/iou_tracker.py).
"""
from __future__ import annotations

import pytest

from app.tracking.trackers.base import TrackerDetectionInput
from app.tracking.trackers.iou_tracker import IoUHungarianTracker, TrackerConfig


def _det(detection_result_id, bbox, class_label="mock_object", confidence=0.9):
    return TrackerDetectionInput(
        detection_result_id=detection_result_id, class_label=class_label, confidence=confidence,
        bbox_x_min=bbox[0], bbox_y_min=bbox[1], bbox_x_max=bbox[2], bbox_y_max=bbox[3],
    )


def _box_at(cx, cy, half=0.03):
    return (round(cx - half, 6), round(cy - half, 6), round(cx + half, 6), round(cy + half, 6))


def test_new_detection_initializes_a_tentative_track():
    tracker = IoUHungarianTracker(TrackerConfig(min_hits_to_confirm=3))
    tracker.update(0, 0.0, [_det("d0", _box_at(0.2, 0.2))])
    tracks = tracker.finalize()
    assert len(tracks) == 1
    # min_hits_to_confirm=3 was never reached (only 1 hit, then the
    # sequence ended) -- a tentative track that never confirms before
    # the sequence ends is explicitly "rejected", never silently
    # dropped and never "ended" (that would misleadingly imply it was
    # once confirmed).
    assert tracks[0].final_state == "rejected"


def test_track_confirms_after_min_hits_to_confirm():
    tracker = IoUHungarianTracker(TrackerConfig(min_hits_to_confirm=2, min_iou_threshold=0.3))
    tracker.update(0, 0.0, [_det("d0", _box_at(0.2, 0.2))])
    tracker.update(1, 0.1, [_det("d1", _box_at(0.22, 0.2))])  # small shift, same object
    tracks = tracker.finalize()
    assert len(tracks) == 1
    confirm_events = [e for e in tracks[0].lifecycle_events if e.to_state == "confirmed"]
    assert len(confirm_events) == 1
    assert confirm_events[0].frame_index == 1


def test_confirmed_track_becomes_missing_then_reacquired():
    # Per-frame center shifts are kept small enough that even the
    # 2-frame gap (frame1 -> frame3, after the frame2 miss) stays
    # within the tracker's own min_iou_threshold -- the same
    # displacement-vs-box-size arithmetic app/tracking/synthetic_fixture.py
    # documents (IoU=(w-d)/(w+d) for same-size boxes shifted by d).
    tracker = IoUHungarianTracker(TrackerConfig(min_hits_to_confirm=2, max_missed_frames=3, min_iou_threshold=0.3))
    tracker.update(0, 0.0, [_det("d0", _box_at(0.20, 0.2))])
    tracker.update(1, 0.1, [_det("d1", _box_at(0.21, 0.2))])  # confirmed here
    tracker.update(2, 0.2, [])  # missed -- object not detected this frame
    tracker.update(3, 0.3, [_det("d3", _box_at(0.23, 0.2))])  # reacquired
    tracks = tracker.finalize()
    assert len(tracks) == 1
    transitions = [(e.from_state, e.to_state, e.frame_index) for e in tracks[0].lifecycle_events]
    assert ("confirmed", "missing", 2) in transitions
    assert ("missing", "reacquired", 3) in transitions
    # A fourth frame with another match should roll it back to confirmed.
    tracker2 = IoUHungarianTracker(TrackerConfig(min_hits_to_confirm=2, max_missed_frames=3, min_iou_threshold=0.3))
    tracker2.update(0, 0.0, [_det("d0", _box_at(0.20, 0.2))])
    tracker2.update(1, 0.1, [_det("d1", _box_at(0.21, 0.2))])
    tracker2.update(2, 0.2, [])
    tracker2.update(3, 0.3, [_det("d3", _box_at(0.23, 0.2))])
    tracker2.update(4, 0.4, [_det("d4", _box_at(0.24, 0.2))])
    tracks2 = tracker2.finalize()
    transitions2 = [(e.from_state, e.to_state, e.frame_index) for e in tracks2[0].lifecycle_events]
    assert ("reacquired", "confirmed", 4) in transitions2


def test_track_ends_after_exceeding_max_missed_frames():
    tracker = IoUHungarianTracker(TrackerConfig(min_hits_to_confirm=2, max_missed_frames=2, min_iou_threshold=0.3))
    tracker.update(0, 0.0, [_det("d0", _box_at(0.2, 0.2))])
    tracker.update(1, 0.1, [_det("d1", _box_at(0.22, 0.2))])  # confirmed
    tracker.update(2, 0.2, [])
    tracker.update(3, 0.3, [])
    tracker.update(4, 0.4, [])  # 3rd consecutive miss > max_missed_frames=2
    tracks = tracker.finalize()
    assert len(tracks) == 1
    assert tracks[0].final_state == "ended"
    end_events = [e for e in tracks[0].lifecycle_events if e.to_state == "ended"]
    assert len(end_events) == 1
    assert end_events[0].frame_index == 4
    # Never labelled with anything implying a real-world outcome.
    for event in tracks[0].lifecycle_events:
        assert event.to_state not in ("destroyed", "captured", "hostile")


def test_tentative_track_that_times_out_is_rejected_not_ended():
    tracker = IoUHungarianTracker(TrackerConfig(min_hits_to_confirm=5, max_missed_frames=1, min_iou_threshold=0.3))
    tracker.update(0, 0.0, [_det("d0", _box_at(0.2, 0.2))])  # tentative, 1 hit
    tracker.update(1, 0.1, [])
    tracker.update(2, 0.2, [])  # 2 consecutive misses > max_missed_frames=1, still tentative
    tracks = tracker.finalize()
    assert tracks[0].final_state == "rejected"


def test_sequence_end_closes_out_every_remaining_active_track():
    tracker = IoUHungarianTracker(TrackerConfig(min_hits_to_confirm=1))
    tracker.update(0, 0.0, [_det("d0", _box_at(0.2, 0.2))])
    tracks = tracker.finalize()
    assert len(tracks) == 1
    # min_hits_to_confirm=1 means it confirmed on frame 0, so sequence
    # end must mark it "ended", not "rejected" (it was never merely
    # tentative at the time the sequence closed).
    assert tracks[0].final_state == "ended"


def test_finalize_is_idempotent():
    tracker = IoUHungarianTracker(TrackerConfig(min_hits_to_confirm=1))
    tracker.update(0, 0.0, [_det("d0", _box_at(0.2, 0.2))])
    first = tracker.finalize()
    second = tracker.finalize()
    assert [t.final_state for t in first] == [t.final_state for t in second]
    assert [len(t.lifecycle_events) for t in first] == [len(t.lifecycle_events) for t in second]


def test_track_ids_are_unique_within_one_run():
    tracker = IoUHungarianTracker(TrackerConfig(min_hits_to_confirm=1, min_iou_threshold=0.3))
    # Two spatially distant objects every frame -- each frame's
    # detections never match an existing track, so every one becomes
    # a new track (deliberately stressing ID allocation).
    for i in range(3):
        tracker.update(i, float(i), [_det(f"d{i}-a", _box_at(0.05 + 0.3 * i, 0.1)), _det(f"d{i}-b", _box_at(0.05 + 0.3 * i, 0.9))])
    tracks = tracker.finalize()
    ids = [t.internal_track_id for t in tracks]
    assert len(ids) == len(set(ids))


def test_update_rejects_duplicate_frame_index():
    tracker = IoUHungarianTracker(TrackerConfig())
    tracker.update(0, 0.0, [_det("d0", _box_at(0.2, 0.2))])
    with pytest.raises(ValueError, match="strictly increase"):
        tracker.update(0, 0.0, [_det("d0b", _box_at(0.2, 0.2))])


def test_update_rejects_out_of_order_frame_index():
    tracker = IoUHungarianTracker(TrackerConfig())
    tracker.update(5, 0.5, [_det("d5", _box_at(0.2, 0.2))])
    with pytest.raises(ValueError, match="strictly increase"):
        tracker.update(3, 0.3, [_det("d3", _box_at(0.2, 0.2))])


def test_update_after_finalize_raises():
    tracker = IoUHungarianTracker(TrackerConfig())
    tracker.update(0, 0.0, [_det("d0", _box_at(0.2, 0.2))])
    tracker.finalize()
    with pytest.raises(ValueError, match="already been finalized"):
        tracker.update(1, 0.1, [_det("d1", _box_at(0.2, 0.2))])


def test_empty_frame_is_handled_without_error():
    tracker = IoUHungarianTracker(TrackerConfig())
    result = tracker.update(0, 0.0, [])
    assert result.new_track_count == 0
    assert result.matched_count == 0
    tracks = tracker.finalize()
    assert tracks == []


def test_max_active_tracks_caps_new_track_creation():
    tracker = IoUHungarianTracker(TrackerConfig(max_active_tracks=1, min_iou_threshold=0.3))
    result = tracker.update(0, 0.0, [_det("d0-a", _box_at(0.1, 0.1)), _det("d0-b", _box_at(0.9, 0.9))])
    assert result.new_track_count == 1
    assert result.unmatched_detection_count == 1
    tracks = tracker.finalize()
    assert len(tracks) == 1
