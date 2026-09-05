"""Compare the frozen synthetic CONTEST gate against the shipped NLI baseline.

This uses the integrity-checked NLI score cache, so it reproduces the expensive model's
decisions without another transformer pass.  The gate artifact must already be trained and
frozen; this script never changes weights or thresholds after reading held-out labels.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.schemas import Dispute  # noqa: E402
from app.services.conformal_calibrator import (  # noqa: E402
    DEFAULT_ALPHA,
    DEFAULT_DELTA,
    calibrate_threshold,
    calibration_pairs,
    load_scores,
)
from app.services.synthetic_win_gate import (  # noqa: E402
    ARTIFACT_PATH,
    predict_probability,
)
from real_metrics import wilson_interval  # noqa: E402

HELD_OUT_PATH = BACKEND_ROOT / "eval" / "held_out_set.json"


def _metrics(decisions: Sequence[tuple[str, str]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    wins = sum(label == "contest_win" for _, label in decisions)
    for decision, label in decisions:
        positive = label == "contest_win"
        if decision == "CONTEST":
            counts["tp" if positive else "fp"] += 1
        elif decision == "ACCEPT":
            counts["fn" if positive else "tn"] += 1
        elif decision == "NO_ACTION_NEEDED":
            counts["auto_resolved"] += 1
        else:
            counts["flagged_human"] += 1
    tp, fp, fn, tn = counts["tp"], counts["fp"], counts["fn"], counts["tn"]
    support = tp + fp
    automated = tp + fp + fn + tn
    precision = tp / support if support else 0.0
    selective_recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (
        2 * precision * selective_recall / (precision + selective_recall)
        if precision + selective_recall
        else 0.0
    )
    interval = wilson_interval(tp, support).to_dict()
    return {
        "precision": precision,
        "precision_wilson_95": interval,
        "contest_support": support,
        "selective_recall": selective_recall,
        "f1": f1,
        "selective_accuracy": (tp + tn) / automated if automated else 0.0,
        "model_coverage": automated / len(decisions) if decisions else 0.0,
        "population_auto_win_capture": tp / wins if wins else 0.0,
        "confusion": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "flagged_human": counts["flagged_human"],
            "auto_resolved": counts["auto_resolved"],
        },
    }


def compare(artifact_path: Path = ARTIFACT_PATH) -> dict[str, Any]:
    cache = load_scores()
    if cache is None:
        raise RuntimeError("NLI score cache is missing or incompatible")
    from app.services.synthetic_win_gate import _parse_artifact
    model = _parse_artifact(json.loads(artifact_path.read_text(encoding="utf-8")))
    if model is None:
        raise RuntimeError("synthetic win-gate artifact is missing or incompatible")
    threshold = calibrate_threshold(
        calibration_pairs(cache), DEFAULT_ALPHA, DEFAULT_DELTA
    )
    if threshold is None:
        raise RuntimeError("the shipped NLI risk budget has no supported threshold")
    artifact_metadata = json.loads(artifact_path.read_text(encoding="utf-8"))
    held_out_unused = bool(
        artifact_metadata.get("training", {}).get(
            "held_out_labels_used_for_training_or_selection"
        )
        is False
    )

    records = [
        Dispute.model_validate(value)
        for value in json.loads(HELD_OUT_PATH.read_text(encoding="utf-8"))
    ]
    record_by_id = {record.dispute_id: record for record in records}
    baseline: list[tuple[str, str]] = []
    gated: list[tuple[str, str]] = []
    for row in cache["test"]:
        record = record_by_id[row["dispute_id"]]
        label = str(row["label"])
        if row["urcs_auto_reject"]:
            baseline_decision = "NO_ACTION_NEEDED"
        elif row["max_contradict"] is not None and row["max_contradict"] >= threshold:
            baseline_decision = "ACCEPT"
        elif row["score"] is not None and row["score"] >= threshold:
            baseline_decision = "CONTEST"
        else:
            baseline_decision = "NEEDS_HUMAN_REVIEW"
        gated_decision = baseline_decision
        if baseline_decision == "CONTEST" and predict_probability(record, model) < model.threshold:
            gated_decision = "NEEDS_HUMAN_REVIEW"
        baseline.append((baseline_decision, label))
        gated.append((gated_decision, label))

    return {
        "evaluation": "synthetic held-out empirical comparison",
        "records": len(gated),
        "nli_threshold": threshold,
        "gate_threshold": model.threshold,
        "gate_model_version": model.model_version,
        "artifact_declares_held_out_unused_for_selection": held_out_unused,
        "baseline": _metrics(baseline),
        "gated": _metrics(gated),
        "limitations": [
            "This measures performance only on Coconut's synthetic held-out set.",
            "The held-out set was evaluated in earlier project phases, so this is not a pristine first-use test.",
            "Higher precision obtained through deferral must always be reported with support and coverage.",
        ],
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()
    try:
        report = compare(args.artifact)
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
        print(f"Synthetic gate evaluation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
