"""Fast deterministic checks for the offline real-data metric definitions."""

from __future__ import annotations

import pytest

from eval.real_metrics import (
    MetricInputError,
    average_precision,
    evaluate_selective_classifier,
    select_precision_threshold,
    wilson_interval,
)


def test_wilson_interval_exposes_uncertainty_of_existing_9_of_13_result():
    interval = wilson_interval(9, 13)

    assert interval.lower == pytest.approx(0.424, abs=0.001)
    assert interval.upper == pytest.approx(0.873, abs=0.001)


def test_average_precision_treats_equal_scores_as_one_threshold():
    # Both top observations are tied, so reversing their input order must not change AP.
    first = average_precision([1, 0, 1, 0], [0.8, 0.8, 0.2, 0.1])
    second = average_precision([0, 1, 1, 0], [0.8, 0.8, 0.2, 0.1])

    assert first == pytest.approx(second)
    assert first == pytest.approx(7 / 12)


def test_selective_metrics_do_not_hide_deferred_wins():
    metrics = evaluate_selective_classifier(
        [1, 1, 1, 0, 0, 0],
        [0.9, 0.6, 0.5, 0.8, 0.4, 0.1],
        contest_threshold=0.75,
        accept_threshold=0.25,
    )

    assert metrics["confusion_matrix"] == {
        "tp_contest_won": 1,
        "fp_contest_lost": 1,
        "fn_accept_won": 0,
        "tn_accept_lost": 1,
        "deferred_won": 2,
        "deferred_lost": 1,
    }
    assert metrics["precision"] == pytest.approx(0.5)
    assert metrics["recall"] == pytest.approx(1.0)  # selective, explicitly labelled
    assert metrics["population_auto_win_capture"] == pytest.approx(1 / 3)
    assert metrics["model_coverage"] == pytest.approx(0.5)
    assert metrics["selective_accuracy"] == pytest.approx(2 / 3)


def test_threshold_requires_confidence_support_and_coverage():
    labels = [1] * 40 + [0] * 10 + [1] * 10 + [0] * 40
    scores = [0.9] * 40 + [0.8] * 10 + [0.7] * 10 + [0.1] * 40

    supported = select_precision_threshold(
        labels,
        scores,
        target_precision=0.75,
        min_support=30,
        min_coverage=0.25,
        confidence=0.95,
    )
    unsupported = select_precision_threshold(
        labels,
        scores,
        target_precision=0.95,
        min_support=30,
        min_coverage=0.25,
        confidence=0.95,
    )

    assert supported.status == "supported"
    assert supported.threshold == pytest.approx(0.9)
    assert supported.predicted_count == 40
    assert supported.precision_interval is not None
    assert supported.precision_interval.lower >= 0.75
    assert unsupported.status == "unsupported"
    assert unsupported.threshold is None


def test_overlapping_abstention_thresholds_are_rejected():
    with pytest.raises(MetricInputError, match="lower"):
        evaluate_selective_classifier(
            [0, 1], [0.2, 0.8], contest_threshold=0.5, accept_threshold=0.5
        )
