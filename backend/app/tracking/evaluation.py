"""Tracking evaluation metrics. Runs a tracker
against the deterministic synthetic fixture (synthetic_fixture.py) and
computes real track-level precision/recall, identity switches, track
fragmentation, mostly-tracked/mostly-lost ratios, and mean association
IoU -- by comparing the tracker's own output back against the fixture's
known ground truth.

HOTA/IDF1/MOTA are deliberately not computed -- see
app/models/tracking_evaluation_run.py's module docstring and
docs/ml/TRACKING_EVALUATION.md for why. The metrics here are simpler,
custom-defined, and documented in full below so nobody mistakes them
for those standard metrics.

Metric definitions used here (all are this module's own definitions,
not a standard MOT benchmark's):

- A ground-truth track's "coverage" by a given predicted track is the
  fraction of the ground-truth track's own frames for which that
  specific predicted track holds the matching observation.
- A ground-truth track is "mostly tracked" if its single
  best-covering predicted track covers >= 0.8 of its frames, "mostly
  lost" if the best coverage is < 0.2, otherwise "partially tracked."
- A ground-truth track is "recalled" if its best-covering predicted
  track covers >= 0.5 of its frames (track_recall's numerator).
- A predicted track is a "true positive" if its own observations are
  >= 0.5 dominated by a single ground-truth identity (track_precision's
  numerator); otherwise it is a "false positive" (no real
  correspondence to any one object).
- An "identity switch" is counted every time a ground-truth track's
  sequence of covering predicted-track-ids changes from one real
  (non-gap) predicted id to a DIFFERENT real predicted id.
- "Fragmentation" for a ground-truth track is (the number of distinct
  predicted tracks that ever covered it) - 1, floored at 0; the
  reported `fragmentation_count` is the sum of this across all
  ground-truth tracks.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.tracking.synthetic_fixture import SyntheticSequence, generate
from app.tracking.trackers.base import ObjectTracker, TrackerDetectionInput

MOSTLY_TRACKED_THRESHOLD = 0.8
MOSTLY_LOST_THRESHOLD = 0.2
RECALL_THRESHOLD = 0.5
PRECISION_DOMINANCE_THRESHOLD = 0.5


@dataclass
class SequenceEvaluationResult:
    sequence_name: str
    ground_truth_track_count: int
    predicted_track_count: int
    true_positive_predicted_tracks: int
    false_positive_predicted_tracks: int
    recalled_ground_truth_tracks: int
    mostly_tracked_count: int
    mostly_lost_count: int
    identity_switches: int
    fragmentation_count: int
    association_ious: list[float]


def _evaluate_sequence(tracker: ObjectTracker, sequence: SyntheticSequence) -> SequenceEvaluationResult:
    detection_to_gt: dict[str, str] = {}
    for frame in sequence.frames:
        inputs: list[TrackerDetectionInput] = []
        for i, det in enumerate(frame.detections):
            detection_result_id = f"{sequence.name}-f{frame.frame_index}-{det.ground_truth_track_id}"
            detection_to_gt[detection_result_id] = det.ground_truth_track_id
            inputs.append(
                TrackerDetectionInput(
                    detection_result_id=detection_result_id, class_label=det.class_label, confidence=det.confidence,
                    bbox_x_min=det.bbox[0], bbox_y_min=det.bbox[1], bbox_x_max=det.bbox[2], bbox_y_max=det.bbox[3],
                )
            )
        tracker.update(frame.frame_index, frame.timestamp_seconds, inputs)

    finalized = tracker.finalize()

    # gt_id -> ordered list of (frame_index, predicted_track_id or None)
    gt_coverage: dict[str, dict[int, int]] = {gt_id: {} for gt_id in sequence.ground_truth_track_ids}
    association_ious: list[float] = []
    for track in finalized:
        for obs in track.observations:
            gt_id = detection_to_gt.get(obs.detection_result_id)
            if gt_id is not None:
                gt_coverage[gt_id][obs.frame_index] = track.internal_track_id
            if obs.association_cost is not None:
                association_ious.append(round(1.0 - obs.association_cost, 6))

    # Per ground-truth track: coverage fraction by each predicted track id.
    recalled = 0
    mostly_tracked = 0
    mostly_lost = 0
    identity_switches = 0
    fragmentation_count = 0
    for gt_id in sequence.ground_truth_track_ids:
        frame_to_pred = gt_coverage[gt_id]
        total_frames = len(frame_to_pred)
        if total_frames == 0:
            mostly_lost += 1
            continue
        counts: dict[int, int] = {}
        for pred_id in frame_to_pred.values():
            counts[pred_id] = counts.get(pred_id, 0) + 1
        best_pred_id, best_count = max(counts.items(), key=lambda kv: kv[1])
        best_coverage = best_count / total_frames

        if best_coverage >= MOSTLY_TRACKED_THRESHOLD:
            mostly_tracked += 1
        elif best_coverage < MOSTLY_LOST_THRESHOLD:
            mostly_lost += 1
        if best_coverage >= RECALL_THRESHOLD:
            recalled += 1

        fragmentation_count += max(0, len(counts) - 1)

        ordered_pred_ids = [frame_to_pred[f] for f in sorted(frame_to_pred.keys())]
        last_real: int | None = None
        for pred_id in ordered_pred_ids:
            if last_real is not None and pred_id != last_real:
                identity_switches += 1
            last_real = pred_id

    # Predicted-track-side precision: does each predicted track
    # correspond, in the main, to one real object?
    true_positive_tracks = 0
    false_positive_tracks = 0
    for track in finalized:
        gt_ids_for_track = [detection_to_gt[o.detection_result_id] for o in track.observations if o.detection_result_id in detection_to_gt]
        if not gt_ids_for_track:
            continue
        counts: dict[str, int] = {}
        for gid in gt_ids_for_track:
            counts[gid] = counts.get(gid, 0) + 1
        dominant_fraction = max(counts.values()) / len(gt_ids_for_track)
        if dominant_fraction >= PRECISION_DOMINANCE_THRESHOLD:
            true_positive_tracks += 1
        else:
            false_positive_tracks += 1

    return SequenceEvaluationResult(
        sequence_name=sequence.name, ground_truth_track_count=len(sequence.ground_truth_track_ids), predicted_track_count=len(finalized),
        true_positive_predicted_tracks=true_positive_tracks, false_positive_predicted_tracks=false_positive_tracks,
        recalled_ground_truth_tracks=recalled, mostly_tracked_count=mostly_tracked, mostly_lost_count=mostly_lost,
        identity_switches=identity_switches, fragmentation_count=fragmentation_count, association_ious=association_ious,
    )


@dataclass
class AggregateEvaluationResult:
    sequence_results: list[SequenceEvaluationResult]
    track_precision: float
    track_recall: float
    identity_switches: int
    fragmentation_count: int
    mostly_tracked_ratio: float
    mostly_lost_ratio: float
    mean_association_iou: float


def run_synthetic_evaluation(tracker_factory) -> AggregateEvaluationResult:
    """`tracker_factory` is a zero-arg callable returning a FRESH tracker
    instance -- each sequence gets its own tracker so one sequence's
    state never leaks into the next ("per-sequence
    results")."""
    sequences = generate()
    sequence_results = [_evaluate_sequence(tracker_factory(), seq) for seq in sequences]

    total_gt = sum(r.ground_truth_track_count for r in sequence_results)
    total_recalled = sum(r.recalled_ground_truth_tracks for r in sequence_results)
    total_tp = sum(r.true_positive_predicted_tracks for r in sequence_results)
    total_fp = sum(r.false_positive_predicted_tracks for r in sequence_results)
    total_mostly_tracked = sum(r.mostly_tracked_count for r in sequence_results)
    total_mostly_lost = sum(r.mostly_lost_count for r in sequence_results)
    total_switches = sum(r.identity_switches for r in sequence_results)
    total_fragmentation = sum(r.fragmentation_count for r in sequence_results)
    all_ious = [iou for r in sequence_results for iou in r.association_ious]

    return AggregateEvaluationResult(
        sequence_results=sequence_results,
        track_precision=round(total_tp / (total_tp + total_fp), 4) if (total_tp + total_fp) > 0 else 0.0,
        track_recall=round(total_recalled / total_gt, 4) if total_gt > 0 else 0.0,
        identity_switches=total_switches, fragmentation_count=total_fragmentation,
        mostly_tracked_ratio=round(total_mostly_tracked / total_gt, 4) if total_gt > 0 else 0.0,
        mostly_lost_ratio=round(total_mostly_lost / total_gt, 4) if total_gt > 0 else 0.0,
        mean_association_iou=round(sum(all_ious) / len(all_ious), 4) if all_ious else 0.0,
    )
