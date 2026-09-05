"""Train Coconut's synthetic-only CONTEST safety gate with out-of-fold calibration."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.schemas import Dispute  # noqa: E402
from app.services.synthetic_win_gate import (  # noqa: E402
    ARTIFACT_PATH,
    ARTIFACT_SCHEMA_VERSION,
    FEATURE_SCHEMA_VERSION,
    SyntheticWinModel,
    dispute_features,
    predict_probability,
)

WORKING_SET = BACKEND_ROOT / "data" / "synthetic_disputes.json"
NLI_SCORE_CACHE = BACKEND_ROOT / "eval" / ".conformal_scores.json"
TRAINING_SEED = "coconut-synthetic-win-gate-v1"


class TrainingError(ValueError):
    pass


@dataclass(frozen=True)
class TrainingConfig:
    dimension: int = 16384
    folds: int = 5
    epochs: int = 500
    learning_rate: float = 0.45
    l2: float = 0.003
    target_precision: float = 0.90
    min_support: int = 8


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _folds(records: Sequence[Dispute], fold_count: int) -> list[int]:
    assignments = [0] * len(records)
    by_label: dict[str, list[tuple[str, int]]] = {}
    for index, record in enumerate(records):
        label = str(record.ground_truth_label)
        digest = hashlib.sha256(
            f"{TRAINING_SEED}:{record.dispute_id}".encode("utf-8")
        ).hexdigest()
        by_label.setdefault(label, []).append((digest, index))
    for values in by_label.values():
        for rank, (_, index) in enumerate(sorted(values)):
            assignments[index] = rank % fold_count
    return assignments


def _matrix(records: Sequence[Dispute], dimension: int) -> np.ndarray:
    matrix = np.zeros((len(records), dimension), dtype=np.float64)
    for row, record in enumerate(records):
        for column, value in dispute_features(record, dimension).items():
            matrix[row, column] = value
    return matrix


def _fit(
    records: Sequence[Dispute], labels: np.ndarray, config: TrainingConfig
) -> SyntheticWinModel:
    if len(records) < 2 or len(np.unique(labels)) != 2:
        raise TrainingError("training data must contain both positive and negative labels")
    x = _matrix(records, config.dimension)
    positives = int(labels.sum())
    negatives = len(labels) - positives
    sample_weights = np.where(
        labels == 1,
        len(labels) / (2.0 * positives),
        len(labels) / (2.0 * negatives),
    )
    sample_weights /= sample_weights.sum()
    weights = np.zeros(config.dimension, dtype=np.float64)
    intercept = math.log((positives + 0.5) / (negatives + 0.5))
    for _ in range(config.epochs):
        logits = np.clip(x @ weights + intercept, -35.0, 35.0)
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        residual = (probabilities - labels) * sample_weights
        weights -= config.learning_rate * (x.T @ residual + config.l2 * weights)
        intercept -= config.learning_rate * float(residual.sum())
    return SyntheticWinModel(
        dimension=config.dimension,
        intercept=float(intercept),
        weights=tuple(float(value) for value in weights),
        threshold=0.5,
        model_version="unpersisted",
    )


def _eligible_ids(records: Sequence[Dispute]) -> set[str]:
    try:
        payload = json.loads(NLI_SCORE_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingError("the NLI score cache is unavailable; rebuild it first") from exc
    rows = payload.get("calibration") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise TrainingError("the NLI score cache has no calibration rows")
    source_labels = {record.dispute_id: record.ground_truth_label for record in records}
    cache_labels = {
        row.get("dispute_id"): row.get("label")
        for row in rows
        if isinstance(row, dict)
    }
    if cache_labels != source_labels:
        raise TrainingError("the NLI score cache does not match the working dataset")
    return {
        str(row["dispute_id"])
        for row in rows
        if row.get("score") is not None and not row.get("urcs_auto_reject", False)
    }


def _wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    p = successes / total
    denominator = 1.0 + z * z / total
    centre = p + z * z / (2.0 * total)
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total)
    return (centre - margin) / denominator, (centre + margin) / denominator


def _select_threshold(
    scores: Sequence[float], labels: Sequence[int], target: float, min_support: int
) -> tuple[float, dict[str, float | int]]:
    candidates: list[tuple[int, int, float]] = []
    for threshold in sorted(set(scores), reverse=True):
        chosen = [index for index, score in enumerate(scores) if score >= threshold]
        support = len(chosen)
        true_positives = sum(labels[index] for index in chosen)
        precision = true_positives / support if support else 0.0
        if support >= min_support and precision >= target:
            candidates.append((support, true_positives, threshold))
    if not candidates:
        raise TrainingError(
            f"no out-of-fold threshold reaches {target:.0%} precision with support >= {min_support}"
        )
    support, true_positives, threshold = max(candidates)
    lower, upper = _wilson(true_positives, support)
    return threshold, {
        "precision": true_positives / support,
        "support": support,
        "true_positives": true_positives,
        "false_positives": support - true_positives,
        "wilson_95_lower": lower,
        "wilson_95_upper": upper,
    }


def load_supplement(path: Path | None, working: Sequence[Dispute]) -> list[Dispute]:
    """Extra cases are training-only in every fold, never calibration/test observations."""
    if path is None:
        return []
    extra = [Dispute.model_validate(v) for v in json.loads(path.read_text(encoding="utf-8"))]
    reserved = [*working, *[
        Dispute.model_validate(v)
        for v in json.loads((BACKEND_ROOT / "eval/held_out_set.json").read_text(encoding="utf-8"))
    ]]
    ids = {r.dispute_id for r in reserved}
    # Compare input text only; held-out labels never participate in fitting/selection.
    def signature(record):
        return " ".join((record.claim_text + " " + " ".join(
            e.content for e in record.evidence_bundle
        )).lower().split())
    texts = {signature(r) for r in reserved}
    for record in extra:
        if record.ground_truth_label is None or not record.dispute_id.startswith("disp_synthetic_"):
            raise TrainingError("supplement must contain labelled synthetic cases only")
        if record.dispute_id in ids or signature(record) in texts:
            raise TrainingError("supplement overlaps an existing record or contains duplicates")
        ids.add(record.dispute_id)
        texts.add(signature(record))
    return extra


def train(config: TrainingConfig, supplement: Path | None = None) -> dict:
    if not 0.0 < config.target_precision <= 1.0:
        raise TrainingError("target precision must be in (0, 1]")
    if config.min_support < 1:
        raise TrainingError("minimum support must be positive")
    values = json.loads(WORKING_SET.read_text(encoding="utf-8"))
    records = [Dispute.model_validate(value) for value in values]
    records = [record for record in records if record.ground_truth_label is not None]
    if len({record.dispute_id for record in records}) != len(records):
        raise TrainingError("working dataset contains duplicate dispute IDs")
    extra = load_supplement(supplement, records)
    extra_labels = np.asarray([int(r.ground_truth_label == "contest_win") for r in extra])
    labels = np.asarray(
        [1 if record.ground_truth_label == "contest_win" else 0 for record in records],
        dtype=np.float64,
    )
    fold_assignments = _folds(records, config.folds)
    eligible_ids = _eligible_ids(records)
    oof_scores = np.zeros(len(records), dtype=np.float64)
    for fold in range(config.folds):
        train_indices = [index for index, assigned in enumerate(fold_assignments) if assigned != fold]
        test_indices = [index for index, assigned in enumerate(fold_assignments) if assigned == fold]
        model = _fit(
            [records[index] for index in train_indices] + extra,
            np.concatenate((labels[train_indices], extra_labels)), config
        )
        for index in test_indices:
            oof_scores[index] = predict_probability(records[index], model)

    eligible_indices = [
        index for index, record in enumerate(records) if record.dispute_id in eligible_ids
    ]
    threshold, threshold_metrics = _select_threshold(
        [float(oof_scores[index]) for index in eligible_indices],
        [int(labels[index]) for index in eligible_indices],
        config.target_precision,
        config.min_support,
    )
    final_model = _fit(records + extra, np.concatenate((labels, extra_labels)), config)
    ranked_eligible = sorted(
        ((float(oof_scores[index]), int(labels[index])) for index in eligible_indices),
        reverse=True,
    )
    precision_by_support = {
        str(support): sum(label for _, label in ranked_eligible[:support]) / support
        for support in (5, 10, 15, 20, 25, 30, 35, len(ranked_eligible))
        if 0 < support <= len(ranked_eligible)
    }
    source_hash = _sha256(WORKING_SET)
    supplement_hash = _sha256(supplement) if supplement else None
    if supplement_hash:
        source_hash = hashlib.sha256((source_hash + supplement_hash).encode()).hexdigest()
    model_version = f"synthetic-hashed-logistic@{source_hash[:12]}"
    artifact = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "model_type": "balanced_hashed_logistic_regression",
        "model_version": model_version,
        "synthetic_only": True,
        "can_only_demote_contest": True,
        "dimension": config.dimension,
        "intercept": round(final_model.intercept, 12),
        "weights": [round(value, 12) for value in final_model.weights],
        "decision_threshold": round(threshold, 12),
        "training": {
            "source": "data/synthetic_disputes.json",
            "source_sha256": source_hash,
            "records": len(records),
            "supplement_sha256": supplement_hash,
            "supplement_records": len(extra),
            "total_fit_records": len(records) + len(extra),
            "supplement_policy": "training only in every fold; excluded from OOF metrics",
            "positive_contest_wins": int(labels.sum()),
            "negative_loss_or_accept": int(len(labels) - labels.sum()),
            "folds": config.folds,
            "fold_assignment": "label-stratified SHA-256 rank modulo folds",
            "epochs": config.epochs,
            "learning_rate": config.learning_rate,
            "l2": config.l2,
            "nli_structurally_eligible_records": len(eligible_indices),
            "threshold_selected_from": "out-of-fold predictions on working set only",
            "target_precision": config.target_precision,
            "minimum_support": config.min_support,
            "selected_operating_point": threshold_metrics,
            "oof_precision_by_ranked_support": precision_by_support,
            "held_out_labels_used_for_training_or_selection": False,
        },
        "limitations": [
            "Trained and calibrated on synthetic data; not evidence of real-merchant performance.",
            "The working set was used for feature development, so out-of-fold metrics are developmental.",
            "Held-out support must be reported with confidence intervals and coverage.",
        ],
    }
    return artifact


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ARTIFACT_PATH)
    parser.add_argument("--supplement", type=Path, help="Optional training-only synthetic JSON array")
    parser.add_argument("--target-precision", type=float, default=0.90)
    parser.add_argument("--min-support", type=int, default=8)
    args = parser.parse_args(argv)
    if args.supplement and args.output.resolve() == ARTIFACT_PATH.resolve():
        parser.error("with --supplement, use --output eval/synthetic_win_gate_candidate.json to preserve the demo model")
    config = TrainingConfig(
        target_precision=args.target_precision,
        min_support=args.min_support,
    )
    try:
        artifact = train(config, args.supplement)
    except (TrainingError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Synthetic gate training failed: {exc}", file=sys.stderr)
        return 2
    payload = (json.dumps(artifact, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(args.output.resolve(), payload)
    selected = artifact["training"]["selected_operating_point"]
    print(
        f"OOF operating point: precision={selected['precision']:.3f} "
        f"support={selected['support']} TP={selected['true_positives']} "
        f"FP={selected['false_positives']} threshold={artifact['decision_threshold']:.4f}"
    )
    print(
        f"Wilson 95% CI: {selected['wilson_95_lower']:.3f}-"
        f"{selected['wilson_95_upper']:.3f}"
    )
    print(f"Wrote: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
