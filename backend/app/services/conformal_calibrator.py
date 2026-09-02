"""Hoeffding-corrected risk budgeting for the decision threshold.

WHY THIS REPLACES SECTION 10's NUMBERS
---------------------------------------
Section 10 hard-codes 0.7 and 0.65. Nothing justifies those numbers -- they were picked.
In a track whose bar is measured precision on a held-out set, "I picked them" is a bad
answer.

This prototype removes the hand-picked threshold. You choose a *risk budget* -- the
maximum false-positive rate you can live with -- and it searches for a threshold whose
calibration-set estimate plus a Hoeffding correction clears that budget. The system then
reports what that budget costs in coverage.

This is deliberately not described as a formal finite-sample guarantee. The current
prototype searches a threshold grid without a family-wise multiple-testing procedure and
uses development data rather than a calibration split held apart from score design. The
test split is an honest empirical check, but it cannot repair those two assumptions.

That reframes the claim from "we got 62% precision" to "name the false-positive rate you
can tolerate and the system will show whether this development sample supports it, plus
what that operating point costs in coverage".

THE METHOD (Hoeffding-corrected prototype)
-------------------------------------------
For a candidate threshold lambda, the empirical risk on calibration data is the
false-positive rate among the disputes the system would auto-contest at that threshold:

    R(lambda) = |{ s(x) >= lambda and y != contest_win }| / |{ s(x) >= lambda }|

Select the SMALLEST lambda whose Hoeffding-corrected risk clears the budget, because
smaller lambda means more coverage:

    lambda_hat = min { lambda : R(lambda) + sqrt(log(1/delta) / (2 n_lambda)) <= alpha }

If no lambda qualifies, return None. The caller must report that the budget is
unachievable rather than quietly falling back to a default -- an unachievable budget is a
real finding, and hiding it would defeat the entire point of the feature.

WHAT THE RESULT IS, AND IS NOT
------------------------------
At the selected threshold, the reported calibration statistic is the empirical
false-positive rate plus a Hoeffding correction. It is not a formal deployment guarantee.
In particular:

  1. The score and aggregation rule were developed on the same synthetic working set used
     for calibration; a formal method needs an independent calibration sample.
  2. Searching 50 thresholds needs an FWER-controlling procedure such as fixed-sequence
     testing or a multiple-testing correction before making a simultaneous claim.
  3. Real dispute drift breaks exchangeability with the synthetic data.
  4. The measured quantity is false-positive rate only -- not recall or money recovered.

Grounding: split conformal prediction (Vovk et al. 2005; Papadopoulos et al. 2002),
conformal risk control (Bates et al. 2021; Angelopoulos et al. 2024), selective
classification and deferral (Chow's rejection rule; El-Yaniv & Wiener 2010; Geifman &
El-Yaniv 2017).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
from importlib.metadata import PackageNotFoundError, version as package_version
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
#   On this data the tightest achievable budget is ~0.71. Not because the arithmetic is
#   wrong,
#   but because the confidence score it calibrates has almost no dynamic range -- the
#   model-eligible contest scores cluster at 0.500 (p25 0.498, median 0.500, p75 0.502,
#   only 1 of 42 above 0.55), and precision does not improve as the threshold rises. It sits near 0.50
#   at every cut. That is the same AUC ~0.57 ceiling documented in ARCHITECTURE.md,
#   surfacing here as an unachievable risk budget.
#
# Booting below the floor would leave the system deferring every case, so the default sits
# just above it. The number is meant to be uncomfortable: it advertises the limitation
# instead of hiding it behind a threshold nobody can justify.
DEFAULT_ALPHA = 0.75

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCORE_CACHE = BACKEND_ROOT / "eval" / ".conformal_scores.json"
CALIBRATION_SOURCE = BACKEND_ROOT / "data" / "synthetic_disputes.json"
TEST_SOURCE = BACKEND_ROOT / "eval" / "held_out_set.json"
SCORE_CACHE_SCHEMA_VERSION = 3
STRUCTURAL_RULE_VERSION = "unanimous-support-min-confidence-v1"

# The cache stores the output of this exact pipeline. Hashing the implementation files
# makes a scoring change fail closed even when somebody forgets to bump a hand-maintained
# version string. Newlines are normalised so a Windows-built cache remains valid in the
# Linux container after Git checks the same sources out with LF endings.
PIPELINE_SOURCES = (
    BACKEND_ROOT / "app" / "models" / "schemas.py",
    BACKEND_ROOT / "app" / "services" / "verification_engine.py",
    BACKEND_ROOT / "app" / "services" / "decision_aggregator.py",
    BACKEND_ROOT / "app" / "services" / "urcs_forecaster.py",
    BACKEND_ROOT / "app" / "services" / "npci_rules.py",
    BACKEND_ROOT / "eval" / "build_conformal_cache.py",
)

# These packages can change tokenisation, logits or numeric results. Their base versions
# are recorded in the artifact and pinned in requirements.txt. A local suffix such as
# torch's ``+cpu`` describes the build, not a different public release, so it is removed.
INFERENCE_DEPENDENCIES = (
    "numpy",
    "sentence-transformers",
    "transformers",
    "torch",
    "tokenizers",
    "sentencepiece",
    "protobuf",
)
GROUND_TRUTH_LABELS = {"contest_win", "contest_loss", "should_accept"}


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
        f"Prototype risk check at {1 - delta:.0%} nominal confidence: the selected "
        f"threshold's calibration estimate plus Hoeffding correction is at most "
        f"{alpha:.0%}. This is not a formal deployment guarantee because the threshold "
        "grid lacks a multiple-testing correction and the calibration set was reused "
        "during development."
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
    logger.info(
        "active risk-budget threshold = %s (alpha=%.2f, delta=%.2f)",
        threshold,
        alpha,
        delta,
    )


def clear_active_threshold() -> None:
    """Fail closed before a bootstrap attempt or after calibration state is invalidated."""
    with _lock:
        _active.update(
            {"threshold": None, "alpha": None, "delta": DEFAULT_DELTA, "calibrated": False}
        )


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


def _normalised_text_sha256(path: Path) -> str:
    """Hash text reproducibly across Git's Windows/Linux newline conversions."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _labelled_record_count(path: Path) -> int:
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"{path} must contain a JSON array")
    return sum(
        1
        for record in records
        if isinstance(record, dict) and record.get("ground_truth_label") is not None
    )


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_identity_sha256(path: Path) -> str:
    """Bind cached row identities and labels to the source, not only its row count."""
    records = json.loads(path.read_text(encoding="utf-8"))
    identities = sorted(
        (record["dispute_id"], record["ground_truth_label"])
        for record in records
        if isinstance(record, dict) and record.get("ground_truth_label") is not None
    )
    return _canonical_sha256(identities)


def cache_rows_sha256(calibration: object, test: object) -> str:
    """Checksum the score-bearing portion of an artifact for corruption detection."""
    return _canonical_sha256({"calibration": calibration, "test": test})


def _inference_dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for distribution in INFERENCE_DEPENDENCIES:
        try:
            raw = package_version(distribution)
        except PackageNotFoundError:
            # A missing required inference dependency should make a cache generated in a
            # complete environment incompatible, without crashing a liveness endpoint.
            raw = "missing"
        versions[distribution] = raw.split("+", 1)[0]
    return versions


def expected_cache_metadata() -> dict:
    """Metadata binding a cache to weights, inputs, code and inference dependencies."""
    from app.services.verification_engine import MODEL_VERSION

    return {
        "schema_version": SCORE_CACHE_SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "source_sha256": {
            "calibration": _normalised_text_sha256(CALIBRATION_SOURCE),
            "test": _normalised_text_sha256(TEST_SOURCE),
        },
        "source_record_count": {
            "calibration": _labelled_record_count(CALIBRATION_SOURCE),
            "test": _labelled_record_count(TEST_SOURCE),
        },
        "source_identity_sha256": {
            "calibration": _source_identity_sha256(CALIBRATION_SOURCE),
            "test": _source_identity_sha256(TEST_SOURCE),
        },
        "structural_rule_version": STRUCTURAL_RULE_VERSION,
        "pipeline_sha256": {
            path.relative_to(BACKEND_ROOT).as_posix(): _normalised_text_sha256(path)
            for path in PIPELINE_SOURCES
        },
        "inference_dependency_versions": _inference_dependency_versions(),
    }


def _probability(value: object) -> bool:
    return (
        value is None
        or (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and 0.0 <= float(value) <= 1.0
        )
    )


def _validate_split(rows: object, split: str, expected_count: int) -> Optional[str]:
    if not isinstance(rows, list):
        return f"{split} is not a list"
    if len(rows) != expected_count:
        return f"{split} has {len(rows)} rows; expected {expected_count}"

    ids: set[str] = set()
    for index, row in enumerate(rows):
        location = f"{split}[{index}]"
        if not isinstance(row, dict):
            return f"{location} is not an object"
        dispute_id = row.get("dispute_id")
        if not isinstance(dispute_id, str) or not dispute_id.strip():
            return f"{location}.dispute_id is invalid"
        if dispute_id in ids:
            return f"{split} contains duplicate dispute id {dispute_id}"
        ids.add(dispute_id)
        if row.get("label") not in GROUND_TRUTH_LABELS:
            return f"{location}.label is invalid"
        if not _probability(row.get("score")):
            return f"{location}.score is invalid"
        if not _probability(row.get("max_contradict")):
            return f"{location}.max_contradict is invalid"
        if row.get("score") is not None and row.get("max_contradict") is not None:
            return (
                f"{location} cannot have both a contest score and a contradict score"
            )
        if not isinstance(row.get("urcs_auto_reject"), bool):
            return f"{location}.urcs_auto_reject is invalid"
    return None


def validate_cache_payload(payload: object, expected: dict) -> Optional[str]:
    """Return a human-readable incompatibility reason, or None for a usable cache."""
    if not isinstance(payload, dict):
        return "top-level JSON value is not an object"

    mismatched = [key for key, value in expected.items() if payload.get(key) != value]
    if mismatched:
        return f"metadata mismatch: {', '.join(mismatched)}"

    counts = expected["source_record_count"]
    for split in ("calibration", "test"):
        reason = _validate_split(payload.get(split), split, counts[split])
        if reason:
            return reason

    calibration_ids = {row["dispute_id"] for row in payload["calibration"]}
    test_ids = {row["dispute_id"] for row in payload["test"]}
    overlap = calibration_ids & test_ids
    if overlap:
        return f"calibration and test overlap at {sorted(overlap)[0]}"

    for split in ("calibration", "test"):
        identities = sorted(
            (row["dispute_id"], row["label"]) for row in payload[split]
        )
        if _canonical_sha256(identities) != expected["source_identity_sha256"][split]:
            return f"{split} dispute ids or labels do not match the source dataset"

    checksum = payload.get("rows_sha256")
    if not isinstance(checksum, str) or checksum != cache_rows_sha256(
        payload["calibration"], payload["test"]
    ):
        return "score-row checksum mismatch"
    return None


def load_scores() -> Optional[dict]:
    """The cached per-record contest scores, split into calibration and test halves.

    Built by `python eval/build_conformal_cache.py`, which is one NLI pass over the
    working and held-out sets. Cached because calibrating at a new alpha must be instant --
    the whole point of the slider is that it responds -- and because the scores do not
    depend on alpha at all.
    """
    if not SCORE_CACHE.exists():
        return None
    try:
        payload = json.loads(SCORE_CACHE.read_text(encoding="utf-8"))
        expected = expected_cache_metadata()
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        logger.warning("conformal score cache at %s is unreadable (%s)", SCORE_CACHE, exc)
        return None
    reason = validate_cache_payload(payload, expected)
    if reason:
        logger.warning(
            "conformal score cache at %s is stale or incompatible: %s",
            SCORE_CACHE,
            reason,
        )
        return None
    return payload


def calibration_pairs(cache: dict) -> list[tuple[float, str]]:
    """(score, label) for records structurally eligible for CONTEST.

    Records with `score is None` can never be auto-contested at any threshold. Neither can
    URCS auto-rejections: the deterministic NPCI rule short-circuits before model
    aggregation. Including either group would estimate risk on cases the model never
    contests.
    """
    return [
        (r["score"], r["label"])
        for r in cache["calibration"]
        if r.get("score") is not None and not r.get("urcs_auto_reject", False)
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
    # A repeated bootstrap must never retain a once-valid threshold when its current
    # artifact is missing or incompatible.
    clear_active_threshold()

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
            "no compatible risk-score cache; the aggregator will defer every case until "
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
    "cache_rows_sha256",
    "calibrate_threshold",
    "calibration_pairs",
    "clear_active_threshold",
    "empirical_fp_rate",
    "expected_cache_metadata",
    "get_active_calibrated_threshold",
    "guarantee_statement",
    "has_calibrated",
    "hoeffding_slack",
    "last_persisted_budget",
    "load_scores",
    "set_active_threshold",
    "smallest_achievable_alpha",
    "validate_cache_payload",
]
