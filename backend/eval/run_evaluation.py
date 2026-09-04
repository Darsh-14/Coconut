"""Evaluation harness. Implements CLAUDE.md Section 11's metric definitions literally.

Runs the full pipeline (verification engine -> decision aggregator) over
eval/held_out_set.json and reports precision, recall, F1, the raw confusion matrix,
false-positive cost and coverage.

CONTEST is the positive class. Per Section 11:

    TP  model says CONTEST, ground truth contest_win
    FP  model says CONTEST, ground truth contest_loss or should_accept
    FN  model says ACCEPT,  ground truth contest_win
    TN  model says ACCEPT,  ground truth contest_loss or should_accept

    NEEDS_HUMAN_REVIEW and deterministic URCS outcomes are EXCLUDED from
    precision/recall/F1. Model coverage counts only CONTEST/ACCEPT decisions made on the
    evidence: (n_evaluated - n_flagged_human - n_auto_resolved) / n_evaluated.

The held-out set was not inspected or tuned against during development (Section 9); every
threshold in the verification engine was chosen on data/synthetic_disputes.json.

Usage:
    python eval/run_evaluation.py
    python eval/run_evaluation.py --limit 20      # quick smoke run
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Optional, Sequence

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.models.schemas import Dispute, EvalMetrics  # noqa: E402
from app.services.conformal_calibrator import (  # noqa: E402
    active_state,
    bootstrap_from_cache,
    has_calibrated,
)
from app.services.decision_aggregator import aggregate  # noqa: E402
from app.services.synthetic_win_gate import apply_synthetic_win_gate  # noqa: E402
from app.services.verification_engine import (  # noqa: E402
    VerificationEngine,
    get_verification_engine,
)

HELD_OUT_PATH = BACKEND_ROOT / "eval" / "held_out_set.json"

# Ground truth values that make CONTEST the wrong call.
NEGATIVE_LABELS = {"contest_loss", "should_accept"}


def load_held_out(path: Path = HELD_OUT_PATH) -> list[Dispute]:
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} not found. Run: python data/generate_synthetic_disputes.py --source curated"
        )
    return [Dispute.model_validate(r) for r in json.loads(path.read_text(encoding="utf-8"))]


def run_evaluation(
    records: Optional[Sequence[Dispute]] = None,
    engine: Optional[VerificationEngine] = None,
    representment_cost_inr: Optional[float] = None,
    progress: bool = False,
) -> EvalMetrics:
    """Score the pipeline over the held-out set and return Section 11's metrics."""
    records = list(records) if records is not None else load_held_out()
    engine = engine or get_verification_engine()

    # Run standalone, this process has never been through the API's startup hook, so no
    # threshold is calibrated and the aggregator would defer every single record. Bootstrap
    # from the cached scores exactly as the app does.
    if not has_calibrated():
        bootstrap_from_cache()
    calibration = active_state()
    if representment_cost_inr is None:
        representment_cost_inr = get_settings().assumed_representment_cost_inr

    counts = Counter()
    n_evaluated = 0

    for index, record in enumerate(records, 1):
        # Records without a ground truth label cannot be scored.
        if record.ground_truth_label is None:
            continue
        n_evaluated += 1

        verdicts = engine.verify_bundle(
            record.claim_text, record.evidence_bundle, record.reason_code
        )
        # The held-out file is the payer history for its own records: NPCI's window is
        # counted within the set being evaluated, never across the split boundary.
        result = aggregate(verdicts, record.evidence_bundle, record, records)
        result, _ = apply_synthetic_win_gate(result, record)

        is_positive = record.ground_truth_label == "contest_win"
        if result.recommendation == "CONTEST":
            counts["tp" if is_positive else "fp"] += 1
        elif result.recommendation == "ACCEPT":
            counts["fn" if is_positive else "tn"] += 1
        elif result.recommendation == "NO_ACTION_NEEDED":
            # URCS resolves these without the merchant. Excluded from precision and recall
            # exactly as NEEDS_HUMAN_REVIEW is -- scoring them as wins would credit the
            # model for work NPCI's rules engine did.
            counts["auto_resolved"] += 1
        else:  # NEEDS_HUMAN_REVIEW
            counts["flagged_human"] += 1

        if progress and index % 20 == 0:
            print(f"  ...{index}/{len(records)}", flush=True)

    tp, fp, fn, tn = counts["tp"], counts["fp"], counts["fn"], counts["tn"]
    flagged_human = counts["flagged_human"]
    auto_resolved = counts["auto_resolved"]

    # Guard divide-by-zero, per Section 11.
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    # Coverage is the share the system decides *on the merits*. Cap-breach cases are not
    # a decision it made, so they come out of the numerator alongside human referrals.
    decided_on_merits = n_evaluated - flagged_human - auto_resolved
    coverage = decided_on_merits / n_evaluated if n_evaluated else 0.0

    return EvalMetrics(
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        confusion_matrix={
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "flagged_human": flagged_human,
        },
        false_positive_cost_estimate_inr=round(fp * representment_cost_inr, 2),
        coverage=round(coverage, 4),
        n_evaluated=n_evaluated,
        auto_resolved=auto_resolved,
        alpha=calibration.get("alpha"),
        calibrated_threshold=calibration.get("threshold"),
        # The observed false-positive rate among auto-contested cases is 1 - precision.
        # This legacy field reports whether that observation stayed under alpha.
        guarantee_held=(
            None
            if calibration.get("alpha") is None or (tp + fp) == 0
            else (1.0 - precision) <= calibration["alpha"]
        ),
    )


def format_report(metrics: EvalMetrics) -> str:
    cm = metrics.confusion_matrix
    decided = metrics.n_evaluated - cm["flagged_human"] - metrics.auto_resolved
    return "\n".join(
        [
            "",
            "=== Coconut evaluation (held-out set) ===",
            f"  n_evaluated   : {metrics.n_evaluated}",
            f"  decided on merits: {decided}   to human: {cm['flagged_human']}"
            f"   URCS auto-resolved: {metrics.auto_resolved}",
            "",
            "  confusion matrix (raw counts, CONTEST is the positive class)",
            f"    TP {cm['tp']:<4} model CONTEST, truth contest_win",
            f"    FP {cm['fp']:<4} model CONTEST, truth contest_loss/should_accept",
            f"    FN {cm['fn']:<4} model ACCEPT,  truth contest_win",
            f"    TN {cm['tn']:<4} model ACCEPT,  truth contest_loss/should_accept",
            "",
            f"  precision     : {metrics.precision:.3f}",
            f"  recall        : {metrics.recall:.3f}",
            f"  f1            : {metrics.f1:.3f}",
            f"  model coverage: {metrics.coverage:.3f}  "
            f"(fraction decided on the evidence)",
            f"  FP cost est.  : Rs {metrics.false_positive_cost_estimate_inr:,.0f}",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, default=None, help="Evaluate only the first N.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a report.")
    args = parser.parse_args()

    records = load_held_out()
    if args.limit:
        records = records[: args.limit]

    if not args.json:
        print(f"Evaluating {len(records)} held-out records (loading model may take a moment)...")

    metrics = run_evaluation(records, progress=not args.json)

    if args.json:
        print(metrics.model_dump_json(indent=2))
    else:
        print(format_report(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
