"""Pure metric tests: known values, undefined
cases, missing labels, imbalance, invalid inputs."""
from __future__ import annotations

import math

import pytest

from app.analytics import metrics as m


def test_known_classification_values_and_confusion_matrix():
    y = ["a", "a", "a", "b", "b", "c"]
    p = ["a", "a", "b", "b", "b", "a"]
    r = m.classification_report(y, p)
    assert r["labels"] == ["a", "b", "c"]
    assert r["confusion_matrix"] == [[2, 1, 0], [0, 2, 0], [1, 0, 0]]
    assert r["accuracy"]["value"] == pytest.approx(4 / 6, abs=1e-6)
    assert r["per_class"]["a"]["precision"]["value"] == pytest.approx(2 / 3, abs=1e-6)
    assert r["per_class"]["a"]["recall"]["value"] == pytest.approx(2 / 3, abs=1e-6)
    assert r["per_class"]["b"]["precision"]["value"] == pytest.approx(2 / 3, abs=1e-6)
    assert r["per_class"]["b"]["recall"]["value"] == 1.0


def test_class_never_predicted_has_undefined_precision_and_f1_not_zero():
    r = m.classification_report(["a", "b", "c"], ["a", "b", "a"])
    c = r["per_class"]["c"]
    assert c["precision"]["defined"] is False and c["precision"]["value"] is None
    assert "never predicted" in c["precision"]["reason"]
    assert c["recall"]["value"] == 0.0  # defined: class occurs but was missed
    assert c["f1"]["defined"] is False
    assert "c" in r["macro_f1"]["excluded_classes"]


def test_class_absent_from_labels_has_undefined_recall():
    r = m.classification_report(["a", "a"], ["a", "b"], labels=["a", "b"])
    assert r["per_class"]["b"]["recall"]["defined"] is False
    assert any("no labelled samples" in w for w in r["warnings"])


def test_missing_true_labels_are_excluded_and_counted_not_guessed():
    r = m.classification_report(["a", None, "b", None], ["a", "a", "b", "b"])
    assert r["labelled_sample_count"] == 2 and r["excluded_missing_label"] == 2
    assert r["accuracy"]["value"] == 1.0
    assert any("no true label" in w for w in r["warnings"])


def test_empty_dataset_makes_every_metric_undefined():
    r = m.classification_report([], [])
    assert r["accuracy"]["defined"] is False and r["macro_f1"]["defined"] is False
    assert any("every metric is undefined" in w for w in r["warnings"])
    r2 = m.classification_report([None, None], ["a", "b"])
    assert r2["accuracy"]["defined"] is False and r2["excluded_missing_label"] == 2


def test_class_imbalance_is_warned():
    y = ["neg"] * 95 + ["pos"] * 5
    r = m.classification_report(y, ["neg"] * 100)
    assert r["accuracy"]["value"] == 0.95
    assert r["per_class"]["pos"]["recall"]["value"] == 0.0
    assert any("class imbalance" in w for w in r["warnings"])


def test_unknown_label_and_length_mismatch_are_input_errors():
    with pytest.raises(m.MetricInputError):
        m.classification_report(["a", "b"], ["a", "z"], labels=["a", "b"])
    with pytest.raises(m.MetricInputError):
        m.classification_report(["a", "b"], ["a"])
    with pytest.raises(m.MetricInputError):
        m.classification_report(["a"], [None])


def test_roc_auc_known_values_ties_and_undefined():
    perfect = m.probability_report(["p", "p", "n", "n"], [0.9, 0.8, 0.2, 0.1], "p")
    assert perfect["roc_auc"]["value"] == 1.0
    inverted = m.probability_report(["p", "p", "n", "n"], [0.1, 0.2, 0.8, 0.9], "p")
    assert inverted["roc_auc"]["value"] == 0.0
    tied = m.probability_report(["p", "n"], [0.5, 0.5], "p")
    assert tied["roc_auc"]["value"] == 0.5
    one_class = m.probability_report(["p", "p"], [0.9, 0.8], "p")
    assert one_class["roc_auc"]["defined"] is False and "positive and one negative" in one_class["roc_auc"]["reason"]


def test_brier_and_log_loss_known_values():
    r = m.probability_report(["p", "n"], [0.8, 0.3], "p")
    assert r["brier_score"]["value"] == pytest.approx(((0.2) ** 2 + (0.3) ** 2) / 2, abs=1e-6)
    assert r["log_loss"]["value"] == pytest.approx(-(math.log(0.8) + math.log(0.7)) / 2, abs=1e-6)


def test_log_loss_stays_finite_for_overconfident_wrong_probability():
    r = m.probability_report(["p", "n"], [0.0, 1.0], "p")
    assert math.isfinite(r["log_loss"]["value"]) and r["log_loss"]["value"] > 10


def test_invalid_probabilities_are_rejected():
    for bad in (1.2, -0.1, float("nan"), float("inf")):
        with pytest.raises(m.MetricInputError):
            m.probability_report(["p", "n"], [bad, 0.5], "p")


def test_missing_probability_is_excluded_never_invented():
    r = m.probability_report(["p", "n", "p"], [0.9, None, 0.7], "p")
    assert r["scored_sample_count"] == 2 and r["excluded_missing_probability"] == 1
    assert any("none was invented" in w for w in r["warnings"])


def test_no_scoreable_probability_samples_is_all_undefined():
    r = m.probability_report(["p"], [None], "p")
    for k in ("brier_score", "log_loss", "roc_auc"):
        assert r[k]["defined"] is False


def test_sample_cap():
    with pytest.raises(m.MetricInputError):
        m.classification_report(["a"] * (m.MAX_SAMPLES + 1), ["a"] * (m.MAX_SAMPLES + 1))


def test_every_metric_carries_a_definition():
    r = m.classification_report(["a", "b"], ["a", "b"])
    assert r["accuracy"]["definition"] and r["per_class"]["a"]["f1"]["definition"]
