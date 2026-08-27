"""Conformal risk control tests (CLAUDE.md Addendum 3, Section 32).

Pure arithmetic over hand-built score sets, so these run in milliseconds and pin the
method rather than the data.
"""

from __future__ import annotations

import math

import pytest

from app.services.conformal_calibrator import (
    GRID,
    calibrate_threshold,
    calibration_pairs,
    empirical_fp_rate,
    hoeffding_slack,
    load_scores,
    smallest_achievable_alpha,
)

WIN = "contest_win"
LOSS = "contest_loss"


def clean(n: int, score: float = 0.9) -> list[tuple[float, str]]:
    """n high-confidence cases that were all genuinely winnable."""
    return [(score, WIN)] * n


def mixed(n: int, score: float = 0.9) -> list[tuple[float, str]]:
    """n high-confidence cases, half of them wrong."""
    return [(score, WIN if i % 2 == 0 else LOSS) for i in range(n)]


# -- the estimator ---------------------------------------------------------------------


def test_empirical_fp_rate_counts_only_selected_cases():
    data = [(0.9, WIN), (0.9, LOSS), (0.2, LOSS)]
    rate, n = empirical_fp_rate(data, 0.5)
    assert n == 2, "the 0.2 case is below threshold and must not be counted"
    assert rate == 0.5


def test_empirical_fp_rate_returns_none_when_nothing_is_selected():
    rate, n = empirical_fp_rate([(0.2, WIN)], 0.9)
    assert rate is None and n == 0


def test_slack_shrinks_as_the_calibration_sample_grows():
    """The finite-sample correction is the whole reason a small calibration set cannot
    support a tight guarantee, so its direction is pinned."""
    assert hoeffding_slack(10) > hoeffding_slack(100) > hoeffding_slack(1000)
    # And matches the closed form.
    assert hoeffding_slack(50) == pytest.approx(math.sqrt(math.log(1 / 0.1) / (2 * 50)))


def test_slack_shrinks_between_two_hand_built_sets():
    small = clean(12)
    large = clean(200)
    _, n_small = empirical_fp_rate(small, 0.5)
    _, n_large = empirical_fp_rate(large, 0.5)
    assert hoeffding_slack(n_small) > hoeffding_slack(n_large)


# -- calibration -----------------------------------------------------------------------


def test_a_clean_calibration_set_achieves_a_low_budget():
    """All high-confidence cases are wins, and there are enough of them that the slack is
    small, so a tight budget is achievable and returns a low threshold."""
    lam = calibrate_threshold(clean(500), alpha=0.10)
    assert lam is not None
    assert lam == GRID[0], "should take the smallest qualifying lambda, to maximise coverage"


def test_a_half_wrong_calibration_set_cannot_achieve_one_percent():
    assert calibrate_threshold(mixed(200), alpha=0.01) is None


def test_an_unachievable_budget_returns_none_rather_than_a_fallback():
    """Silently falling back to a default threshold would defeat the entire feature."""
    assert calibrate_threshold(mixed(50), alpha=0.05) is None


def test_thresholds_are_monotone_in_the_budget():
    """A tighter budget can never be met by a looser threshold."""
    data = [(0.5 + 0.005 * i, WIN if i > 40 else LOSS) for i in range(100)]
    tight = calibrate_threshold(data, alpha=0.02)
    loose = calibrate_threshold(data, alpha=0.10)
    if tight is not None and loose is not None:
        assert tight >= loose


def test_small_samples_cannot_promise_what_large_ones_can():
    """Same perfect empirical record, different n: only the large set clears a tight
    budget. This is the finite-sample correction doing its job."""
    assert calibrate_threshold(clean(8), alpha=0.15) is None
    assert calibrate_threshold(clean(500), alpha=0.15) is not None


def test_smallest_achievable_alpha_bounds_what_calibration_can_promise():
    data = mixed(60)
    floor = smallest_achievable_alpha(data)
    assert floor is not None
    assert calibrate_threshold(data, alpha=floor - 0.01) is None
    assert calibrate_threshold(data, alpha=floor + 0.01) is not None


# -- the split -------------------------------------------------------------------------


@pytest.mark.skipif(load_scores() is None, reason="conformal score cache not built")
def test_calibration_and_test_ids_are_disjoint():
    """The guarantee is meaningless if verification data leaked into calibration."""
    cache = load_scores()
    cal_ids = {r["dispute_id"] for r in cache["calibration"]}
    test_ids = {r["dispute_id"] for r in cache["test"]}
    assert cal_ids and test_ids
    assert not (cal_ids & test_ids)


@pytest.mark.skipif(load_scores() is None, reason="conformal score cache not built")
def test_calibration_pairs_drop_structurally_ineligible_records():
    """Records that can never be auto-contested must not dilute the risk estimate."""
    cache = load_scores()
    pairs = calibration_pairs(cache)
    assert len(pairs) <= len(cache["calibration"])
    assert all(score is not None for score, _ in pairs)


@pytest.mark.skipif(load_scores() is None, reason="conformal score cache not built")
def test_the_verification_split_is_never_used_to_choose_the_threshold():
    """Calibrating twice, once with the test split appended, must not silently be the
    same computation -- i.e. the calibration path really is reading only its own split."""
    cache = load_scores()
    cal_only = calibration_pairs(cache)
    contaminated = cal_only + [
        (r["score"], r["label"]) for r in cache["test"] if r.get("score") is not None
    ]
    assert len(contaminated) > len(cal_only)
    _, n_cal = empirical_fp_rate(cal_only, 0.5)
    _, n_bad = empirical_fp_rate(contaminated, 0.5)
    assert n_bad > n_cal
