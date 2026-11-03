"""Phase 4, Section 6/17: detection postprocessing/validation --
finite-number checks, bbox/confidence bounds, class_label allow-list,
and real NMS via cv2.dnn.NMSBoxes (never hand-rolled IoU math).
"""
from __future__ import annotations

import math

from app.cv.adapters.base import RawDetection
from app.cv.postprocessing import postprocess


def _det(label="mock_object", conf=0.8, x0=10, y0=10, x1=50, y1=50):
    return RawDetection(class_label=label, confidence=conf, x_min=x0, y_min=y0, x_max=x1, y_max=y1)


def test_valid_detection_is_normalized_to_0_1_fractions():
    validated, rejected = postprocess([_det(x0=0, y0=0, x1=50, y1=25)], frame_width=100, frame_height=50)
    assert rejected == 0
    assert len(validated) == 1
    d = validated[0]
    assert d.bbox_x_min == 0.0 and d.bbox_x_max == 0.5
    assert d.bbox_y_min == 0.0 and d.bbox_y_max == 0.5


def test_non_finite_confidence_is_rejected():
    validated, rejected = postprocess([_det(conf=math.nan)], frame_width=100, frame_height=100)
    assert validated == []
    assert rejected == 1


def test_non_finite_bbox_coordinate_is_rejected():
    validated, rejected = postprocess([_det(x0=math.inf)], frame_width=100, frame_height=100)
    assert validated == []
    assert rejected == 1


def test_confidence_out_of_range_is_rejected():
    validated, rejected = postprocess([_det(conf=1.5)], frame_width=100, frame_height=100)
    assert validated == []
    assert rejected == 1


def test_degenerate_box_x_min_not_less_than_x_max_is_rejected():
    validated, rejected = postprocess([_det(x0=50, x1=50)], frame_width=100, frame_height=100)
    assert validated == []
    assert rejected == 1


def test_box_exceeding_frame_bounds_is_rejected():
    validated, rejected = postprocess([_det(x1=500)], frame_width=100, frame_height=100)
    assert validated == []
    assert rejected == 1


def test_unknown_class_label_is_rejected():
    validated, rejected = postprocess([_det(label="hostile_combatant")], frame_width=100, frame_height=100)
    assert validated == []
    assert rejected == 1


def test_below_confidence_threshold_is_rejected():
    validated, rejected = postprocess([_det(conf=0.1)], frame_width=100, frame_height=100, confidence_threshold=0.5)
    assert validated == []
    assert rejected == 1


def test_nms_reduces_heavily_overlapping_boxes_to_one():
    # Two near-identical boxes over the same region -- NMS should keep
    # only the higher-confidence one.
    dets = [_det(conf=0.9, x0=10, y0=10, x1=60, y1=60), _det(conf=0.6, x0=12, y0=12, x1=62, y1=62)]
    validated, rejected = postprocess(dets, frame_width=200, frame_height=200, nms_iou_threshold=0.3)
    assert len(validated) == 1
    assert validated[0].confidence == 0.9
    assert rejected == 1


def test_non_overlapping_boxes_are_both_kept():
    dets = [_det(conf=0.9, x0=0, y0=0, x1=20, y1=20), _det(conf=0.8, x0=150, y0=150, x1=180, y1=180)]
    validated, rejected = postprocess(dets, frame_width=200, frame_height=200)
    assert len(validated) == 2
    assert rejected == 0


def test_detections_per_frame_cap_is_enforced(monkeypatch):
    from app.cv import postprocessing

    monkeypatch.setattr(postprocessing.settings, "CV_MAX_DETECTIONS_PER_FRAME", 2)
    dets = [_det(conf=0.9 - i * 0.05, x0=i * 20, y0=0, x1=i * 20 + 10, y1=10) for i in range(5)]
    validated, _rejected = postprocess(dets, frame_width=500, frame_height=50)
    assert len(validated) == 2
    # Keeps the highest-confidence ones.
    assert validated[0].confidence > validated[1].confidence


def test_empty_input_returns_empty_output():
    validated, rejected = postprocess([], frame_width=100, frame_height=100)
    assert validated == []
    assert rejected == 0
