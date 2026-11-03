"""A small, clearly-labelled SYNTHETIC multi-object tracking fixture.
No real, labelled, multi-object tracking
dataset exists in this repository, so this module generates one
deterministically at evaluation time -- never from a downloaded or
externally-fetched dataset (same "no unrestricted remote fetching"
discipline Phase 4's own synthetic_eval_fixture.py already follows).

Two fixed, named sequences, each with known ground truth:

- "parallel": two objects moving in straight, non-intersecting lines.
  A tracker with any reasonable IoU threshold should track both
  perfectly -- this is the fixture's "easy" sanity check.
- "crossing": two objects moving toward each other so their boxes
  overlap heavily at the midpoint frame. This is a deliberately
  constructed, honestly-labelled example of this tracker's own
  documented limitation (no appearance model -- see
  docs/ml/TRACKER_ADAPTERS.md): an appearance-free IoU tracker can
  legitimately swap identities when two objects' boxes overlap more
  with each other than with their own track's recent history.

Every sequence is pure arithmetic (no `random` module, no wall-clock
input) -- the same `sequence_count`/sequence names always produce the
same frames, detections, and ground truth, on every run, on every
machine.
"""
from __future__ import annotations

from dataclasses import dataclass

FRAME_COUNT = 20
FPS = 10.0
BBOX_HALF_SIZE = 0.03
GROUND_TRUTH_CLASS_LABEL = "mock_object"  # reuses Phase 4's reserved synthetic label -- never a real detector's class


@dataclass(frozen=True)
class SyntheticDetection:
    ground_truth_track_id: str
    class_label: str
    confidence: float
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class SyntheticFrame:
    frame_index: int
    timestamp_seconds: float
    detections: list[SyntheticDetection]


@dataclass(frozen=True)
class SyntheticSequence:
    name: str
    frames: list[SyntheticFrame]
    ground_truth_track_ids: list[str]


def _bbox_at(cx: float, cy: float) -> tuple[float, float, float, float]:
    x_min = max(0.0, cx - BBOX_HALF_SIZE)
    y_min = max(0.0, cy - BBOX_HALF_SIZE)
    x_max = min(1.0, cx + BBOX_HALF_SIZE)
    y_max = min(1.0, cy + BBOX_HALF_SIZE)
    return (round(x_min, 6), round(y_min, 6), round(x_max, 6), round(y_max, 6))


# Per-frame center displacement, deliberately kept well under what the
# default TRACKING_MIN_IOU_THRESHOLD (0.3) can still tolerate for a box
# of width 2*BBOX_HALF_SIZE: for two boxes of width w overlapping only
# along one axis by a shift of d, IoU = (w-d)/(w+d), so IoU>=0.3 requires
# d <= ~0.538*w. With w=0.06 that is d <= ~0.032; 0.02 leaves a
# comfortable margin so the "parallel" sequence is a genuine, reliable
# sanity check rather than an accidental stress test of the threshold
# itself.
STEP = 0.02


def _parallel_sequence() -> SyntheticSequence:
    frames: list[SyntheticFrame] = []
    for i in range(FRAME_COUNT):
        t = i / FPS
        # Object A: left-to-right along y=0.2. Object B: left-to-right
        # along y=0.8. They never come close to each other.
        a_cx = 0.1 + STEP * i
        b_cx = 0.1 + STEP * i
        detections = [
            SyntheticDetection("gt-a", GROUND_TRUTH_CLASS_LABEL, 0.9, _bbox_at(a_cx, 0.2)),
            SyntheticDetection("gt-b", GROUND_TRUTH_CLASS_LABEL, 0.9, _bbox_at(b_cx, 0.8)),
        ]
        frames.append(SyntheticFrame(frame_index=i, timestamp_seconds=round(t, 6), detections=detections))
    return SyntheticSequence(name="parallel", frames=frames, ground_truth_track_ids=["gt-a", "gt-b"])


def _crossing_sequence() -> SyntheticSequence:
    frames: list[SyntheticFrame] = []
    midpoint = FRAME_COUNT // 2  # = 10
    for i in range(FRAME_COUNT):
        t = i / FPS
        # Object A moves left-to-right through y=0.5 starting at 0.3;
        # object B moves right-to-left through the SAME y=0.5 starting
        # at 0.7 -- with STEP=0.02 each, they meet exactly at frame 10
        # (0.3 + 0.02*10 == 0.7 - 0.02*10 == 0.5), where their boxes
        # overlap heavily, by construction, not by accident.
        a_cx = 0.3 + STEP * i
        b_cx = 0.7 - STEP * i
        detections = [
            SyntheticDetection("gt-a", GROUND_TRUTH_CLASS_LABEL, 0.9, _bbox_at(a_cx, 0.5)),
            SyntheticDetection("gt-b", GROUND_TRUTH_CLASS_LABEL, 0.9, _bbox_at(b_cx, 0.5)),
        ]
        frames.append(SyntheticFrame(frame_index=i, timestamp_seconds=round(t, 6), detections=detections))
    assert abs((0.3 + STEP * midpoint) - (0.7 - STEP * midpoint)) < 1e-9  # the crossing point is exact, not approximate
    return SyntheticSequence(name="crossing", frames=frames, ground_truth_track_ids=["gt-a", "gt-b"])


_SEQUENCES: dict[str, SyntheticSequence] = {
    "parallel": _parallel_sequence(),
    "crossing": _crossing_sequence(),
}


def generate() -> list[SyntheticSequence]:
    """Always returns both named sequences, in a fixed order -- there is
    no `sequence_count` parameter because, unlike Phase 4's single-image
    fixture, these two sequences are each individually meaningful
    (one sanity check, one stress test), not interchangeable repeats of
    the same scenario."""
    return [_SEQUENCES["parallel"], _SEQUENCES["crossing"]]
