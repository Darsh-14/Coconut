"""Statistically honest metrics for the offline real-dispute baseline.

This module deliberately has no dependency on the running Coconut application.  It
evaluates an abstaining classifier over *matured, actually contested* disputes where
``1`` means that the merchant ultimately won and ``0`` means that it lost.

The distinction between selective recall and population win capture is important:
deferred cases are excluded from the former and included in the latter.  Reporting only
selective recall can make a low-coverage model look much more useful than it is.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import NormalDist
from typing import Iterable, Sequence

import numpy as np


class MetricInputError(ValueError):
    """Raised when a metric would otherwise be undefined or misleading."""


@dataclass(frozen=True)
class WilsonInterval:
    lower: float
    upper: float
    confidence: float
    successes: int
    total: int

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


@dataclass(frozen=True)
class ThresholdSelection:
    """A pre-test operating-point selection made only on calibration data."""

    status: str
    threshold: float | None
    target_precision: float
    min_support: int
    min_coverage: float
    predicted_count: int
    eligible_count: int
    observed_precision: float | None
    coverage: float
    precision_interval: WilsonInterval | None

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        if self.precision_interval is not None:
            result["precision_interval"] = self.precision_interval.to_dict()
        return result


def _as_arrays(
    y_true: Sequence[int] | np.ndarray,
    scores: Sequence[float] | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    labels = np.asarray(y_true, dtype=np.int8)
    probabilities = np.asarray(scores, dtype=np.float64)
    if labels.ndim != 1 or probabilities.ndim != 1:
        raise MetricInputError("labels and scores must be one-dimensional")
    if labels.size != probabilities.size:
        raise MetricInputError("labels and scores must have the same length")
    if labels.size == 0:
        raise MetricInputError("at least one labelled example is required")
    if not np.all(np.isin(labels, (0, 1))):
        raise MetricInputError("labels must contain only 0 (lost) and 1 (won)")
    if not np.all(np.isfinite(probabilities)):
        raise MetricInputError("scores must all be finite")
    if np.any((probabilities < 0.0) | (probabilities > 1.0)):
        raise MetricInputError("scores must be probabilities in [0, 1]")
    return labels, probabilities


def wilson_interval(
    successes: int,
    total: int,
    confidence: float = 0.95,
) -> WilsonInterval:
    """Return a two-sided Wilson score interval for a binomial proportion."""

    if total < 0 or successes < 0 or successes > total:
        raise MetricInputError("require 0 <= successes <= total")
    if not 0.0 < confidence < 1.0:
        raise MetricInputError("confidence must be between zero and one")
    if total == 0:
        return WilsonInterval(0.0, 1.0, confidence, successes, total)

    z = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    proportion = successes / total
    denominator = 1.0 + (z * z) / total
    centre = (proportion + (z * z) / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + (z * z) / (4.0 * total * total)
        )
        / denominator
    )
    return WilsonInterval(
        lower=max(0.0, centre - margin),
        upper=min(1.0, centre + margin),
        confidence=confidence,
        successes=successes,
        total=total,
    )


def average_precision(
    y_true: Sequence[int] | np.ndarray,
    scores: Sequence[float] | np.ndarray,
) -> float | None:
    """Compute tie-aware average precision (the step-wise area under the PR curve)."""

    labels, probabilities = _as_arrays(y_true, scores)
    positive_count = int(labels.sum())
    if positive_count == 0:
        return None

    order = np.argsort(-probabilities, kind="mergesort")
    sorted_labels = labels[order]
    sorted_scores = probabilities[order]
    cumulative_tp = np.cumsum(sorted_labels)
    cumulative_count = np.arange(1, labels.size + 1)

    # Evaluate only after the final member of a tied-score group.  Arbitrarily ordering
    # ties would make the result depend on input order.
    group_ends = np.r_[sorted_scores[1:] != sorted_scores[:-1], True]
    tp_at_threshold = cumulative_tp[group_ends]
    count_at_threshold = cumulative_count[group_ends]
    recall = tp_at_threshold / positive_count
    precision = tp_at_threshold / count_at_threshold
    recall_increment = np.diff(np.r_[0.0, recall])
    return float(np.sum(recall_increment * precision))


def brier_score(
    y_true: Sequence[int] | np.ndarray,
    scores: Sequence[float] | np.ndarray,
) -> float:
    labels, probabilities = _as_arrays(y_true, scores)
    return float(np.mean((probabilities - labels) ** 2))


def calibration_summary(
    y_true: Sequence[int] | np.ndarray,
    scores: Sequence[float] | np.ndarray,
    n_bins: int = 10,
) -> dict[str, object]:
    """Return fixed-width calibration bins and expected calibration error."""

    if n_bins < 2:
        raise MetricInputError("n_bins must be at least two")
    labels, probabilities = _as_arrays(y_true, scores)
    # A score of exactly 1.0 belongs in the last rather than an eleventh bin.
    bin_index = np.minimum((probabilities * n_bins).astype(int), n_bins - 1)
    bins: list[dict[str, float | int]] = []
    ece = 0.0
    for index in range(n_bins):
        selected = bin_index == index
        count = int(selected.sum())
        if count == 0:
            continue
        mean_score = float(probabilities[selected].mean())
        observed_rate = float(labels[selected].mean())
        ece += (count / labels.size) * abs(mean_score - observed_rate)
        bins.append(
            {
                "lower": index / n_bins,
                "upper": (index + 1) / n_bins,
                "count": count,
                "mean_score": mean_score,
                "observed_win_rate": observed_rate,
            }
        )
    return {"expected_calibration_error": float(ece), "bins": bins}


def select_precision_threshold(
    y_true: Sequence[int] | np.ndarray,
    scores: Sequence[float] | np.ndarray,
    *,
    target_precision: float,
    min_support: int,
    min_coverage: float,
    confidence: float = 0.95,
    positive_tail: bool = True,
    upper_bound: float | None = None,
) -> ThresholdSelection:
    """Select the widest calibration tail whose Wilson lower bound meets the target.

    For ``positive_tail=True``, examples with ``score >= threshold`` are proposed for
    CONTEST and precision means win rate.  For ``positive_tail=False``, examples with
    ``score <= threshold`` are proposed for ACCEPT and precision means loss rate.  The
    latter may optionally be constrained below a previously selected contest threshold.

    Looking only at point precision makes tiny, lucky samples appear production-ready.
    This selector therefore requires both minimum support/coverage *and* a Wilson lower
    confidence bound at or above the requested target.
    """

    labels, probabilities = _as_arrays(y_true, scores)
    if not 0.0 < target_precision <= 1.0:
        raise MetricInputError("target_precision must be in (0, 1]")
    if min_support < 1:
        raise MetricInputError("min_support must be at least one")
    if not 0.0 <= min_coverage <= 1.0:
        raise MetricInputError("min_coverage must be in [0, 1]")

    thresholds = np.unique(probabilities)
    # Largest selected population first: lowest positive-tail threshold or highest
    # negative-tail threshold.  The first qualifying candidate is therefore the maximum
    # coverage operating point, not a cherry-picked maximum precision point.
    thresholds = np.sort(thresholds)
    if not positive_tail:
        thresholds = thresholds[::-1]

    best_seen: tuple[int, int, float, WilsonInterval, float] | None = None
    for threshold_value in thresholds:
        threshold = float(threshold_value)
        if upper_bound is not None and threshold >= upper_bound:
            continue
        selected = probabilities >= threshold if positive_tail else probabilities <= threshold
        count = int(selected.sum())
        coverage = count / labels.size
        correct = int(labels[selected].sum()) if positive_tail else int((1 - labels[selected]).sum())
        interval = wilson_interval(correct, count, confidence)

        if best_seen is None or count > best_seen[0]:
            best_seen = (count, correct, coverage, interval, threshold)
        if count < min_support or coverage < min_coverage:
            continue
        observed = correct / count
        if interval.lower >= target_precision:
            return ThresholdSelection(
                status="supported",
                threshold=threshold,
                target_precision=target_precision,
                min_support=min_support,
                min_coverage=min_coverage,
                predicted_count=count,
                eligible_count=int(labels.size),
                observed_precision=observed,
                coverage=coverage,
                precision_interval=interval,
            )

    if best_seen is None:
        count, correct, coverage = 0, 0, 0.0
        interval = None
    else:
        count, correct, coverage, interval, _ = best_seen
    return ThresholdSelection(
        status="unsupported",
        threshold=None,
        target_precision=target_precision,
        min_support=min_support,
        min_coverage=min_coverage,
        predicted_count=count,
        eligible_count=int(labels.size),
        observed_precision=(correct / count if count else None),
        coverage=coverage,
        precision_interval=interval,
    )


def evaluate_selective_classifier(
    y_true: Sequence[int] | np.ndarray,
    scores: Sequence[float] | np.ndarray,
    *,
    contest_threshold: float | None,
    accept_threshold: float | None = None,
    confidence: float = 0.95,
    calibration_bins: int = 10,
) -> dict[str, object]:
    """Evaluate CONTEST/ACCEPT/defer decisions without hiding deferred positives."""

    labels, probabilities = _as_arrays(y_true, scores)
    if contest_threshold is not None and not 0.0 <= contest_threshold <= 1.0:
        raise MetricInputError("contest_threshold must be in [0, 1]")
    if accept_threshold is not None and not 0.0 <= accept_threshold <= 1.0:
        raise MetricInputError("accept_threshold must be in [0, 1]")
    if (
        contest_threshold is not None
        and accept_threshold is not None
        and accept_threshold >= contest_threshold
    ):
        raise MetricInputError("accept_threshold must be lower than contest_threshold")

    contest = (
        probabilities >= contest_threshold
        if contest_threshold is not None
        else np.zeros(labels.size, dtype=bool)
    )
    accept = (
        probabilities <= accept_threshold
        if accept_threshold is not None
        else np.zeros(labels.size, dtype=bool)
    )
    deferred = ~(contest | accept)

    positive = labels == 1
    negative = ~positive
    tp = int((contest & positive).sum())
    fp = int((contest & negative).sum())
    fn = int((accept & positive).sum())
    tn = int((accept & negative).sum())
    deferred_positive = int((deferred & positive).sum())
    deferred_negative = int((deferred & negative).sum())
    predicted_contest = tp + fp
    predicted_accept = tn + fn
    decided = predicted_contest + predicted_accept
    positive_count = int(positive.sum())

    precision = tp / predicted_contest if predicted_contest else None
    selective_recall = tp / (tp + fn) if (tp + fn) else None
    population_capture = tp / positive_count if positive_count else None
    selective_accuracy = (tp + tn) / decided if decided else None
    interval = wilson_interval(tp, predicted_contest, confidence)

    return {
        "n_evaluated": int(labels.size),
        "n_won": positive_count,
        "n_lost": int(negative.sum()),
        "confusion_matrix": {
            "tp_contest_won": tp,
            "fp_contest_lost": fp,
            "fn_accept_won": fn,
            "tn_accept_lost": tn,
            "deferred_won": deferred_positive,
            "deferred_lost": deferred_negative,
        },
        "precision": precision,
        "precision_interval": interval.to_dict(),
        # This is explicitly selective: deferred cases are absent from its denominator.
        "recall": selective_recall,
        "recall_scope": "automated_terminal_decisions_only",
        "population_auto_win_capture": population_capture,
        "model_coverage": decided / labels.size,
        "contest_coverage": predicted_contest / labels.size,
        "accept_coverage": predicted_accept / labels.size,
        "selective_accuracy": selective_accuracy,
        "pr_auc_average_precision": average_precision(labels, probabilities),
        "brier_score": brier_score(labels, probabilities),
        "calibration": calibration_summary(labels, probabilities, calibration_bins),
    }


def round_floats(value: object, digits: int = 8) -> object:
    """Recursively round JSON-bound floats without converting ``None`` or integers."""

    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, dict):
        return {key: round_floats(item, digits) for key, item in value.items()}
    if isinstance(value, list):
        return [round_floats(item, digits) for item in value]
    if isinstance(value, tuple):
        return [round_floats(item, digits) for item in value]
    return value


def finite_probabilities(values: Iterable[float]) -> list[float]:
    """Small public validation helper used by callers that stream scores."""

    result = [float(value) for value in values]
    if not result or not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in result):
        raise MetricInputError("expected one or more finite probabilities in [0, 1]")
    return result
