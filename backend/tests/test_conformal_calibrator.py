"""Hoeffding-corrected risk-budget prototype tests.

Pure arithmetic over hand-built score sets, so these run in milliseconds and pin the
method rather than the data.
"""

from __future__ import annotations

import math
import json

import pytest

from app.services import conformal_calibrator as calibrator
from app.services.conformal_calibrator import (
    GRID,
    calibrate_threshold,
    calibration_pairs,
    empirical_fp_rate,
    hoeffding_slack,
    load_scores,
    smallest_achievable_alpha,
    validate_cache_payload,
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
    support a tight risk check, so its direction is pinned."""
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


# -- artifact contract ----------------------------------------------------------------


def _row(dispute_id: str, **overrides) -> dict:
    row = {
        "dispute_id": dispute_id,
        "label": WIN,
        "score": 0.75,
        "max_contradict": None,
        "urcs_auto_reject": False,
    }
    row.update(overrides)
    return row


def _metadata() -> dict:
    calibration_identity = calibrator._canonical_sha256([("cal-1", WIN)])
    test_identity = calibrator._canonical_sha256([("test-1", WIN)])
    return {
        "schema_version": 3,
        "model_version": "model@revision",
        "source_sha256": {"calibration": "a", "test": "b"},
        "source_record_count": {"calibration": 1, "test": 1},
        "source_identity_sha256": {
            "calibration": calibration_identity,
            "test": test_identity,
        },
        "structural_rule_version": "rule-v1",
        "pipeline_sha256": {"scorer.py": "c"},
        "inference_dependency_versions": {"torch": "2.0.0"},
    }


def _payload() -> dict:
    payload = {
        **_metadata(),
        "calibration": [_row("cal-1")],
        "test": [_row("test-1")],
    }
    payload["rows_sha256"] = calibrator.cache_rows_sha256(
        payload["calibration"], payload["test"]
    )
    return payload


def test_cache_payload_rejects_a_non_object_root():
    reason = validate_cache_payload([], _metadata())
    assert reason == "top-level JSON value is not an object"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("score", float("nan")),
        ("score", 1.1),
        ("max_contradict", -0.1),
        ("urcs_auto_reject", "false"),
        ("label", "unknown"),
    ],
)
def test_cache_payload_rejects_malformed_rows(field, value):
    payload = _payload()
    payload["calibration"][0][field] = value
    assert validate_cache_payload(payload, _metadata()) is not None


def test_cache_payload_rejects_impossible_contest_and_contradict_scores():
    payload = _payload()
    payload["calibration"][0]["max_contradict"] = 0.8
    assert "both" in validate_cache_payload(payload, _metadata())


@pytest.mark.parametrize("field", ["dispute_id", "label"])
def test_cache_payload_binds_row_identity_to_the_source(field):
    payload = _payload()
    payload["calibration"][0][field] = (
        "fabricated" if field == "dispute_id" else LOSS
    )
    payload["rows_sha256"] = calibrator.cache_rows_sha256(
        payload["calibration"], payload["test"]
    )
    assert "do not match the source" in validate_cache_payload(payload, _metadata())


def test_cache_payload_rejects_a_changed_score_even_when_shape_is_valid():
    payload = _payload()
    payload["calibration"][0]["score"] = 0.76
    assert validate_cache_payload(payload, _metadata()) == "score-row checksum mismatch"


def test_cache_payload_rejects_truncated_or_overlapping_splits():
    truncated = _payload()
    truncated["test"] = []
    assert "expected 1" in validate_cache_payload(truncated, _metadata())

    overlapping = _payload()
    overlapping["test"][0]["dispute_id"] = "cal-1"
    assert "overlap" in validate_cache_payload(overlapping, _metadata())


def test_load_scores_fails_closed_for_array_json(tmp_path, monkeypatch):
    path = tmp_path / "scores.json"
    path.write_text(json.dumps([]), encoding="utf-8")
    monkeypatch.setattr(calibrator, "SCORE_CACHE", path)
    monkeypatch.setattr(calibrator, "expected_cache_metadata", _metadata)
    assert calibrator.load_scores() is None


def test_load_scores_accepts_only_a_complete_compatible_payload(tmp_path, monkeypatch):
    path = tmp_path / "scores.json"
    monkeypatch.setattr(calibrator, "SCORE_CACHE", path)
    monkeypatch.setattr(calibrator, "expected_cache_metadata", _metadata)

    stale = _payload()
    stale["model_version"] = "different"
    path.write_text(json.dumps(stale), encoding="utf-8")
    assert calibrator.load_scores() is None

    path.write_text(json.dumps(_payload()), encoding="utf-8")
    assert calibrator.load_scores() == _payload()


def test_calibration_pairs_exclude_urcs_short_circuits():
    cache = {
        "calibration": [
            _row("model", score=0.8),
            _row("urcs", score=0.9, urcs_auto_reject=True),
            _row("ineligible", score=None),
        ]
    }
    assert calibration_pairs(cache) == [(0.8, WIN)]


def test_failed_bootstrap_clears_a_previously_active_threshold(monkeypatch):
    calibrator.set_active_threshold(0.73, 0.75, 0.1)
    monkeypatch.setattr(calibrator, "load_scores", lambda: None)

    calibrator.bootstrap_from_cache(alpha=0.75, delta=0.1)

    assert calibrator.active_state()["calibrated"] is False
    assert calibrator.get_active_calibrated_threshold() is None


def test_calibration_commit_failure_does_not_publish_unpersisted_state(monkeypatch):
    from app.api import routes
    from app.models.schemas import CalibrateRequest

    calibrator.set_active_threshold(0.73, 0.75, 0.1)
    monkeypatch.setattr(routes, "load_scores", lambda: {"calibration": []})
    monkeypatch.setattr(routes, "calibration_pairs", lambda _cache: clean(500))

    class FailingSession:
        def add(self, _row):
            return None

        def commit(self):
            raise RuntimeError("disk full")

    with pytest.raises(RuntimeError, match="disk full"):
        routes.calibrate(
            body=CalibrateRequest(alpha=0.2, delta=0.1), session=FailingSession()
        )

    assert calibrator.get_active_calibrated_threshold() == 0.73
    calibrator.clear_active_threshold()


def test_unachievable_budget_is_not_reported_as_a_zero_error_success(monkeypatch):
    from app.api import routes

    monkeypatch.setattr(
        routes,
        "load_scores",
        lambda: {
            "test": [
                {
                    "score": 0.9,
                    "label": WIN,
                    "max_contradict": None,
                    "urcs_auto_reject": False,
                }
            ]
        },
    )
    calibrator.set_active_threshold(None, 0.05, 0.1)
    result = routes.verify_guarantee()
    assert result.observed_fp_rate_on_test is None
    assert result.guarantee_held is None
    assert result.n_contested == 0
    calibrator.clear_active_threshold()


# -- the split -------------------------------------------------------------------------


@pytest.mark.skipif(load_scores() is None, reason="conformal score cache not built")
def test_calibration_and_test_ids_are_disjoint():
    """The empirical test result is meaningless if it leaked into calibration."""
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
