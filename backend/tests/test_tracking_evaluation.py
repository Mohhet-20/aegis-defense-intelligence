"""/16: tracking evaluation against the
deterministic synthetic fixture. HOTA/IDF1/MOTA are deliberately never
computed here -- only this module's own custom, documented metrics
(app/tracking/evaluation.py).
"""
from __future__ import annotations

from app.services import tracking_evaluation_service
from app.tracking.trackers.iou_tracker import IoUHungarianTracker, TrackerConfig
from app.tracking.trackers.registry import UnsupportedTrackerError


def test_synthetic_evaluation_produces_the_expected_deterministic_metrics(db, org, seeded_users):
    """These exact numbers were confirmed by hand during development
    against the
    default-configured baseline tracker: the "parallel" sequence is
    tracked perfectly (0 identity switches), and the "crossing"
    sequence legitimately produces exactly 2 identity switches -- the
    tracker's own documented, accepted, appearance-free limitation at a
    real crossing -- never zero (that would mean the fixture broke) and
    never many more (that would mean the tracker regressed)."""
    run = tracking_evaluation_service.run_evaluation(
        db, organization_id=org.id, tracker_key="iou_hungarian_v1",
        min_iou_threshold=0.3, max_missed_frames=5, min_hits_to_confirm=2, require_class_match=True,
        evaluated_by_user_id=seeded_users["analyst"].id,
    )
    assert run.is_synthetic is True
    assert run.dataset_name == "synthetic_parallel_and_crossing_fixture"
    assert run.track_precision == 1.0
    assert run.track_recall == 1.0
    assert run.identity_switches == 2
    assert run.fragmentation_count == 2
    assert run.mostly_tracked_ratio == 0.5
    assert run.mostly_lost_ratio == 0.0
    assert run.mean_association_iou == 0.5
    assert "HOTA" in run.notes or "not computed" in run.notes
    sequence_names = {s["sequence_name"] for s in run.metrics_detail["sequences"]}
    assert sequence_names == {"parallel", "crossing"}


def test_evaluation_rejects_an_unsupported_tracker_key_before_running_anything(db, org, seeded_users):
    try:
        tracking_evaluation_service.run_evaluation(
            db, organization_id=org.id, tracker_key="definitely_not_registered",
            min_iou_threshold=0.3, max_missed_frames=5, min_hits_to_confirm=2, require_class_match=True,
            evaluated_by_user_id=None,
        )
        assert False, "expected UnsupportedTrackerError"
    except UnsupportedTrackerError:
        pass

    from sqlalchemy import select

    from app.models.tracking_evaluation_run import TrackingEvaluationRun

    runs = db.execute(select(TrackingEvaluationRun).where(TrackingEvaluationRun.organization_id == org.id)).scalars().all()
    assert runs == []  # nothing was persisted for the rejected tracker_key


def test_evaluation_runs_can_be_listed_and_filtered_by_tracker_key(db, org, seeded_users):
    tracking_evaluation_service.run_evaluation(
        db, organization_id=org.id, tracker_key="iou_hungarian_v1", min_iou_threshold=0.3, max_missed_frames=5,
        min_hits_to_confirm=2, require_class_match=True, evaluated_by_user_id=None,
    )
    from sqlalchemy import select

    from app.models.tracking_evaluation_run import TrackingEvaluationRun

    matching = db.execute(tracking_evaluation_service.list_runs_query(org.id, tracker_key="iou_hungarian_v1")).scalars().all()
    assert len(matching) == 1
    nonmatching = db.execute(tracking_evaluation_service.list_runs_query(org.id, tracker_key="something_else")).scalars().all()
    assert nonmatching == []


def test_evaluation_is_deterministic_across_repeated_runs(db, org, seeded_users):
    run1 = tracking_evaluation_service.run_evaluation(
        db, organization_id=org.id, tracker_key="iou_hungarian_v1", min_iou_threshold=0.3, max_missed_frames=5,
        min_hits_to_confirm=2, require_class_match=True, evaluated_by_user_id=None,
    )
    run2 = tracking_evaluation_service.run_evaluation(
        db, organization_id=org.id, tracker_key="iou_hungarian_v1", min_iou_threshold=0.3, max_missed_frames=5,
        min_hits_to_confirm=2, require_class_match=True, evaluated_by_user_id=None,
    )
    assert run1.id != run2.id  # two distinct, real rows
    assert (run1.track_precision, run1.track_recall, run1.identity_switches, run1.fragmentation_count) == (
        run2.track_precision, run2.track_recall, run2.identity_switches, run2.fragmentation_count,
    )


def test_run_synthetic_evaluation_is_a_pure_function_of_tracker_config():
    from app.tracking.evaluation import run_synthetic_evaluation

    result_a = run_synthetic_evaluation(lambda: IoUHungarianTracker(TrackerConfig()))
    result_b = run_synthetic_evaluation(lambda: IoUHungarianTracker(TrackerConfig()))
    assert result_a.track_precision == result_b.track_precision
    assert result_a.identity_switches == result_b.identity_switches == 2
