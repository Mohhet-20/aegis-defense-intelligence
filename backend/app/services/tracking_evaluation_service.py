"""Tracking evaluation runs. Thin persistence
wrapper around app/tracking/evaluation.py's pure metric computation --
runs the configured tracker against the deterministic synthetic
fixture and stamps the result with full traceability (tracker/version/
config, dataset name/version, always `is_synthetic=True`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.tracking.evaluation import run_synthetic_evaluation
from app.tracking.synthetic_fixture import generate as generate_fixture_sequences
from app.tracking.trackers.iou_tracker import TrackerConfig
from app.tracking.trackers.registry import get_tracker, get_tracker_version
from app.models.tracking_evaluation_run import TrackingEvaluationRun

DATASET_NAME = "synthetic_parallel_and_crossing_fixture"
DATASET_VERSION = "1.0"


def run_evaluation(
    db: Session,
    *,
    organization_id: str,
    tracker_key: str,
    min_iou_threshold: float,
    max_missed_frames: int,
    min_hits_to_confirm: int,
    require_class_match: bool,
    evaluated_by_user_id: Optional[str],
) -> TrackingEvaluationRun:
    tracker_version = get_tracker_version(tracker_key)  # raises UnsupportedTrackerError for an unknown key, before anything else runs
    config = {
        "min_iou_threshold": min_iou_threshold, "max_missed_frames": max_missed_frames,
        "min_hits_to_confirm": min_hits_to_confirm, "require_class_match": require_class_match,
        "max_active_tracks": 100,
    }

    def factory():
        return get_tracker(tracker_key, TrackerConfig(**config))

    result = run_synthetic_evaluation(factory)

    run = TrackingEvaluationRun(
        organization_id=organization_id,
        tracker_key=tracker_key, tracker_version=tracker_version, config=config,
        dataset_name=DATASET_NAME, dataset_version=DATASET_VERSION, is_synthetic=True,
        sequence_count=len(generate_fixture_sequences()),
        track_precision=result.track_precision, track_recall=result.track_recall,
        identity_switches=result.identity_switches, fragmentation_count=result.fragmentation_count,
        mostly_tracked_ratio=result.mostly_tracked_ratio, mostly_lost_ratio=result.mostly_lost_ratio,
        mean_association_iou=result.mean_association_iou,
        metrics_detail={
            "sequences": [
                {
                    "sequence_name": sr.sequence_name, "ground_truth_track_count": sr.ground_truth_track_count,
                    "predicted_track_count": sr.predicted_track_count, "true_positive_predicted_tracks": sr.true_positive_predicted_tracks,
                    "false_positive_predicted_tracks": sr.false_positive_predicted_tracks, "recalled_ground_truth_tracks": sr.recalled_ground_truth_tracks,
                    "mostly_tracked_count": sr.mostly_tracked_count, "mostly_lost_count": sr.mostly_lost_count,
                    "identity_switches": sr.identity_switches, "fragmentation_count": sr.fragmentation_count,
                }
                for sr in result.sequence_results
            ]
        },
        notes=(
            f"Evaluated tracker '{tracker_key}' v{tracker_version} against a SYNTHETIC fixture "
            "('parallel' + 'crossing' sequences) -- not a real-world tracking accuracy measurement. "
            "HOTA/IDF1/MOTA are not computed (see docs/ml/TRACKING_EVALUATION.md). See docs/ml/TRACKING_EVALUATION.md."
        ),
        evaluated_by_user_id=evaluated_by_user_id,
        evaluated_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, organization_id: str, run_id: str) -> Optional[TrackingEvaluationRun]:
    stmt = select(TrackingEvaluationRun).where(TrackingEvaluationRun.id == run_id, TrackingEvaluationRun.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_runs_query(organization_id: str, *, tracker_key: Optional[str] = None):
    stmt = select(TrackingEvaluationRun).where(TrackingEvaluationRun.organization_id == organization_id)
    if tracker_key:
        stmt = stmt.where(TrackingEvaluationRun.tracker_key == tracker_key)
    return stmt.order_by(TrackingEvaluationRun.evaluated_at.desc())
