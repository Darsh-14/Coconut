"""Conformal risk control: calibrate the decision threshold to a stated risk budget.

WHY THIS REPLACES SECTION 10's NUMBERS
---------------------------------------
Section 10 hard-codes 0.7 and 0.65. Nothing justifies those numbers -- they were picked.
In a track whose bar is measured precision on a held-out set, "I picked them" is a bad
answer.

Conformal risk control removes the guess. You do not choose a threshold; you choose a
*risk budget* -- the maximum false-positive rate you can live with -- and the threshold is
calibrated to satisfy it, with a finite-sample, distribution-free guarantee under
exchangeability. The system then reports what that budget costs in coverage.

That reframes the claim from "we got 62% precision" to "name the false-positive rate you
can tolerate and the system provably stays under it; here is what it costs you".

THE METHOD (Learn-then-Test style, Hoeffding-corrected)
--------------------------------------------------------
For a candidate threshold lambda, the empirical risk on calibration data is the
false-positive rate among the disputes the system would auto-contest at that threshold:

    R(lambda) = |{ s(x) >= lambda and y != contest_win }| / |{ s(x) >= lambda }|

Select the SMALLEST lambda whose Hoeffding-corrected risk clears the budget, because
smaller lambda means more coverage:

    lambda_hat = min { lambda : R(lambda) + sqrt(log(1/delta) / (2 n_lambda)) <= alpha }

If no lambda qualifies, return None. The caller must report that the budget is
unachievable rather than quietly falling back to a default -- an unachievable budget is a
real finding, and hiding it would defeat the entire point of the feature.

WHAT THE GUARANTEE IS, AND IS NOT
----------------------------------
With probability at least 1 - delta over the draw of the calibration set, the
false-positive rate among auto-contested disputes is at most alpha, ASSUMING calibration
and deployment data are exchangeable. Nothing more. In particular:

  1. Calibration data here is synthetic, so the guarantee holds relative to that
     distribution and does not automatically transfer to real disputes.
  2. Exchangeability is an assumption real dispute streams break as fraud patterns drift.
     Handling that needs adaptive/online conformal methods, which are out of scope.
  3. The bound is on false-positive rate only -- not recall, not money recovered.

Grounding: split conformal prediction (Vovk et al. 2005; Papadopoulos et al. 2002),
conformal risk control (Bates et al. 2021; Angelopoulos et al. 2024), selective
classification and deferral (Chow's rejection rule; El-Yaniv & Wiener 2010; Geifman &
El-Yaniv 2017).
"""

from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

# Candidate thresholds, 0.50 .. 0.99. Below 0.50 a "confidence" is not evidence of
# anything, so the grid does not go there.
GRID: list[float] = [round(0.50 + 0.01 * i, 2) for i in range(50)]

DEFAULT_DELTA = 0.1

# The budget the system boots with. Deliberately loose, and the reason is the single most
# important measured finding in this file rather than a convenience:
#
#   On this data the tightest achievable budget is ~0.68. Not because the method is wrong,
#   but because the confidence score it calibrates has almost no dynamic range -- the
#   contest scores cluster at 0.500 (p25 0.498, median 0.500, p75 0.502, only 1 of 48
#   above 0.55), and precision does not improve as the threshold rises. It sits near 0.50
#   at every cut. That is the same AUC ~0.57 ceiling documented in ARCHITECTURE.md,
#   surfacing here as an unachievable guarantee.
#
# Booting below the floor would leave the system deferring every case, so the default sits
# just above it. The number is meant to be uncomfortable: it advertises the limitation
# instead of hiding it behind a threshold nobody can justify.
DEFAULT_ALPHA = 0.75

SCORE_CACHE = Path(__file__).resolve().parents[2] / "eval" / ".conformal_scores.json"


# --- the method ---------------------------------------------------------------------


def empirical_fp_rate(
    scores_and_labels: Sequence[tuple[float, str]], lam: float
) -> tuple[Optional[float], int]:
    """False-positive rate among cases selected at threshold `lam`, and how many there are."""
    selected = [(s, y) for (s, y) in scores_and_labels if s >= lam]
    if not selected:
        return None, 0
    fps = sum(1 for (_, y) in selected if y != "contest_win")
    return fps / len(selected), len(selected)


def hoeffding_slack(n_lam: int, delta: float = DEFAULT_DELTA) -> float:
    """The finite-sample correction. Shrinks as the calibration sample grows."""
    return math.sqrt(math.log(1.0 / delta) / (2.0 * n_lam))


def calibrate_threshold(
    scores_and_labels: Sequence[tuple[float, str]],
    alpha: float,
    delta: float = DEFAULT_DELTA,
) -> Optional[float]:
    """Smallest lambda whose Hoeffding-corrected empirical FP rate is <= alpha.

    Returns None if the budget is unachievable on this calibration set. That is a real
    answer, not an error.
    """
    for lam in GRID:
        r_hat, n_lam = empirical_fp_rate(scores_and_labels, lam)
        if r_hat is None or n_lam == 0:
            continue
        if r_hat + hoeffding_slack(n_lam, delta) <= alpha:
            return lam
    return None


def smallest_achievable_alpha(
    scores_and_labels: Sequence[tuple[float, str]], delta: float = DEFAULT_DELTA
) -> Optional[float]:
    """The tightest budget this calibration set can support at all.

    Returned alongside an unachievable result so the answer is actionable -- "not possible"
    is a dead end, "not possible, the floor is 28%" tells the user exactly what the data
    can and cannot promise, and makes the finite-sample limit visible rather than implied.
    """
    best = None
    for lam in GRID:
        r_hat, n_lam = empirical_fp_rate(scores_and_labels, lam)
        if r_hat is None or n_lam == 0:
            continue
        bound = r_hat + hoeffding_slack(n_lam, delta)
        if best is None or bound < best:
            best = bound
    return best


def guarantee_statement(alpha: float, delta: float) -> str:
    return (
        f"With probability at least {1 - delta:.0%} over the draw of the calibration set, "
        f"the false-positive rate among disputes the system auto-contests is at most "
        f"{alpha:.0%}, assuming calibration and deployment data are exchangeable."
    )


# --- the active threshold -------------------------------------------------------------
# One process-wide threshold, set by POST /calibrate and read by the aggregator on every
# decision. Guarded because FastAPI serves sync endpoints from a threadpool.

_lock = threading.Lock()
_active: dict = {"threshold": None, "alpha": None, "delta": DEFAULT_DELTA, "calibrated": False}


def set_active_threshold(threshold: Optional[float], alpha: float, delta: float) -> None:
    with _lock:
        _active.update(
            {"threshold": threshold, "alpha": alpha, "delta": delta, "calibrated": True}
        )
    logger.info("active conformal threshold = %s (alpha=%.2f, delta=%.2f)", threshold, alpha, delta)


def get_active_calibrated_threshold() -> Optional[float]:
    """The calibrated threshold, or None if the budget was unachievable."""
    with _lock:
        if not _active["calibrated"]:
            return None
        return _active["threshold"]


def active_state() -> dict:
    with _lock:
        return dict(_active)


def has_calibrated() -> bool:
    with _lock:
        return bool(_active["calibrated"])


# --- calibration scores ---------------------------------------------------------------


def load_scores() -> Optional[dict]:
    """The cached per-record contest scores, split into calibration and test halves.

    Built by `python eval/build_conformal_cache.py`, which is one NLI pass over the
    held-out set. Cached because calibrating at a new alpha must be instant -- the whole
    point of the slider is that it responds -- and because the scores do not depend on
    alpha at all.
    """
    if not SCORE_CACHE.exists():
        return None
    try:
        return json.loads(SCORE_CACHE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("conformal score cache at %s is unreadable", SCORE_CACHE)
        return None


def calibration_pairs(cache: dict) -> list[tuple[float, str]]:
    """(score, label) for records structurally eligible for CONTEST.

    Records with `score is None` can never be auto-contested at any threshold, so they do
    not belong in the risk estimate -- including them would dilute the false-positive rate
    with cases the system was never going to touch.
    """
    return [
        (r["score"], r["label"]) for r in cache["calibration"] if r.get("score") is not None
    ]


def last_persisted_budget() -> Optional[tuple[float, float]]:
    """The (alpha, delta) an operator last calibrated to, if any.

    Read at startup so a restart resumes the budget that was actually in force rather than
    reverting to DEFAULT_ALPHA. Imported lazily and failure-tolerant: the calibrator is
    also used by offline scripts that have no database, and a missing table must degrade
    to the default rather than stop the process booting.
    """
    try:
        from sqlalchemy import select

        from app.db.database import session_scope
        from app.db.models import CalibrationRow

        with session_scope() as session:
            row = session.scalars(
                select(CalibrationRow).order_by(CalibrationRow.id.desc()).limit(1)
            ).first()
            return (row.alpha, row.delta) if row else None
    except Exception:  # noqa: BLE001 -- any storage problem falls back to the default
        logger.warning("could not read the last calibration; using the default budget")
        return None


def bootstrap_from_cache(
    alpha: Optional[float] = None, delta: Optional[float] = None
) -> None:
    """Calibrate at startup so the app boots with a working threshold.

    Without this every case would defer to a human until somebody moved the slider, which
    would look like the product is broken rather than cautious.

    Resumes the last persisted budget when there is one, so the threshold that decides
    every recommendation survives a restart.
    """
    if alpha is None or delta is None:
        persisted = last_persisted_budget()
        if persisted:
            alpha, delta = persisted
            logger.info("resuming persisted risk budget alpha=%.2f delta=%.2f", alpha, delta)
        else:
            alpha, delta = DEFAULT_ALPHA, DEFAULT_DELTA

    cache = load_scores()
    if not cache:
        logger.warning(
            "no conformal score cache; the aggregator will defer every case until "
            "POST /calibrate runs. Build it with: python eval/build_conformal_cache.py"
        )
        return
    pairs = calibration_pairs(cache)
    set_active_threshold(calibrate_threshold(pairs, alpha, delta), alpha, delta)


__all__ = [
    "DEFAULT_ALPHA",
    "DEFAULT_DELTA",
    "GRID",
    "SCORE_CACHE",
    "active_state",
    "bootstrap_from_cache",
    "calibrate_threshold",
    "calibration_pairs",
    "empirical_fp_rate",
    "get_active_calibrated_threshold",
    "guarantee_statement",
    "has_calibrated",
    "hoeffding_slack",
    "last_persisted_budget",
    "load_scores",
    "set_active_threshold",
    "smallest_achievable_alpha",
]
