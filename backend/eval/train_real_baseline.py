"""Train and evaluate an offline hashed-feature baseline on real dispute exports.

The script consumes the immutable chronological files produced by
``data/split_real_disputes.py``.  It never calls a payment provider, never mutates the
application database, and never writes source text or identifiers to its model artifact.

Only records with ``merchant_action=contested``, ``final_outcome`` of ``won``/``lost``
and a valid ``resolved_at`` timestamp are eligible.  Consequently this estimates
P(win | merchant contested); it is not a counterfactual model for accepted disputes.

Typical usage (from ``backend``)::

    python eval/train_real_baseline.py \
      --splits-dir data/private/splits \
      --output eval/artifacts/real/baseline-v1.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from app.models.real_data import RealDisputeRecord  # noqa: E402
from app.models.real_features import STRUCTURED_SIGNAL_NAMES  # noqa: E402
from real_metrics import (  # noqa: E402
    ThresholdSelection,
    evaluate_selective_classifier,
    round_floats,
    select_precision_threshold,
)

ARTIFACT_VERSION = "coconut.real-win-baseline.v1"
FEATURE_SCHEMA_VERSION = "coconut.real-win-features.v1"
SPLIT_ORDER = ("train", "validation", "calibration", "test")
DEFAULT_FILES = {name: f"{name}.jsonl" for name in SPLIT_ORDER}
OUTCOMES = {"won": 1, "lost": 0}
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,39}")
MAX_TEXT_CHARS = 20_000
MAX_TEXT_TOKENS = 512
HASH_PERSON = b"coconut-real-v1"


class BaselineDataError(ValueError):
    """Raised when an input would compromise validity or data isolation."""


@dataclass(frozen=True)
class TrainingConfig:
    dimension: int = 1024
    epochs: int = 120
    learning_rate: float = 0.35
    l2: float = 0.002
    target_precision: float = 0.80
    min_calibration_support: int = 30
    min_tail_coverage: float = 0.05
    min_test_support: int = 30
    confidence: float = 0.95
    calibration_bins: int = 10

    def validate(self) -> None:
        if not 32 <= self.dimension <= 65_536:
            raise BaselineDataError("dimension must be between 32 and 65536")
        if not 1 <= self.epochs <= 10_000:
            raise BaselineDataError("epochs must be between 1 and 10000")
        if not 0.0 < self.learning_rate <= 10.0:
            raise BaselineDataError("learning_rate must be in (0, 10]")
        if self.l2 < 0.0:
            raise BaselineDataError("l2 cannot be negative")
        if not 0.0 < self.target_precision <= 1.0:
            raise BaselineDataError("target_precision must be in (0, 1]")
        if self.min_calibration_support < 1 or self.min_test_support < 1:
            raise BaselineDataError("support requirements must be positive")
        if not 0.0 <= self.min_tail_coverage <= 1.0:
            raise BaselineDataError("min_tail_coverage must be in [0, 1]")
        if not 0.0 < self.confidence < 1.0:
            raise BaselineDataError("confidence must be in (0, 1)")
        if self.calibration_bins < 2:
            raise BaselineDataError("calibration_bins must be at least two")


@dataclass
class EligibleSplit:
    records: list[dict[str, Any]]
    labels: np.ndarray
    exclusions: dict[str, int]

    @property
    def summary(self) -> dict[str, object]:
        return {
            "input_count": len(self.records) + sum(self.exclusions.values()),
            "eligible_count": len(self.records),
            "won": int(self.labels.sum()),
            "lost": int(len(self.labels) - self.labels.sum()),
            "excluded": dict(sorted(self.exclusions.items())),
        }


@dataclass
class SparseDesign:
    """Minimal CSR-like matrix, avoiding a new scipy/sklearn dependency."""

    n_rows: int
    n_cols: int
    indptr: np.ndarray
    indices: np.ndarray
    data: np.ndarray
    row_indices: np.ndarray

    @classmethod
    def from_records(cls, records: Sequence[Mapping[str, Any]], dimension: int) -> "SparseDesign":
        indptr = [0]
        indices: list[int] = []
        values: list[float] = []
        for record in records:
            features = record_to_hashed_features(record, dimension)
            for index, value in sorted(features.items()):
                indices.append(index)
                values.append(value)
            indptr.append(len(indices))
        pointers = np.asarray(indptr, dtype=np.int64)
        index_array = np.asarray(indices, dtype=np.int32)
        value_array = np.asarray(values, dtype=np.float64)
        row_indices = np.repeat(
            np.arange(len(records), dtype=np.int32), np.diff(pointers)
        )
        return cls(
            n_rows=len(records),
            n_cols=dimension,
            indptr=pointers,
            indices=index_array,
            data=value_array,
            row_indices=row_indices,
        )

    def matvec(self, weights: np.ndarray) -> np.ndarray:
        if weights.shape != (self.n_cols,):
            raise BaselineDataError("weight vector has the wrong feature dimension")
        result = np.zeros(self.n_rows, dtype=np.float64)
        if self.data.size:
            np.add.at(result, self.row_indices, self.data * weights[self.indices])
        return result

    def transpose_matvec(self, row_values: np.ndarray) -> np.ndarray:
        if row_values.shape != (self.n_rows,):
            raise BaselineDataError("row vector has the wrong length")
        result = np.zeros(self.n_cols, dtype=np.float64)
        if self.data.size:
            np.add.at(
                result,
                self.indices,
                self.data * row_values[self.row_indices],
            )
        return result


@dataclass
class HashedLogisticModel:
    dimension: int
    weights: np.ndarray
    intercept: float
    epochs: int
    learning_rate: float
    l2: float
    final_log_loss: float

    def predict(self, records: Sequence[Mapping[str, Any]]) -> np.ndarray:
        design = SparseDesign.from_records(records, self.dimension)
        logits = np.clip(design.matvec(self.weights) + self.intercept, -35.0, 35.0)
        return 1.0 / (1.0 + np.exp(-logits))

    def to_artifact(self) -> dict[str, object]:
        # Feature names/vocabulary are intentionally absent.  Signed feature hashing plus
        # a numeric vector cannot expose claim/evidence text in the artifact.
        return {
            "model_type": "signed_feature_hashing_logistic_regression",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "dimension": self.dimension,
            "intercept": round(self.intercept, 10),
            "weights": [round(float(value), 10) for value in self.weights],
            "epochs": self.epochs,
            "learning_rate": self.learning_rate,
            "l2": self.l2,
            "final_train_log_loss": round(self.final_log_loss, 10),
            "contains_vocabulary_or_raw_text": False,
        }


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BaselineDataError(f"{field} must be a non-empty ISO-8601 timestamp")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise BaselineDataError(f"invalid {field} timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BaselineDataError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def filter_eligible(records: Sequence[Mapping[str, Any]]) -> EligibleSplit:
    """Keep only actually contested disputes with observed, matured outcomes."""

    eligible: list[dict[str, Any]] = []
    labels: list[int] = []
    exclusions: Counter[str] = Counter()
    for source in records:
        record = dict(source)
        if str(record.get("merchant_action", "")).strip().lower() != "contested":
            exclusions["not_actually_contested"] += 1
            continue
        outcome = str(record.get("final_outcome", "")).strip().lower()
        if outcome not in OUTCOMES:
            exclusions["outcome_not_matured_won_or_lost"] += 1
            continue
        try:
            resolved_at = _parse_timestamp(record.get("resolved_at"), "resolved_at")
            decision_at = _parse_timestamp(record.get("decision_at"), "decision_at")
        except BaselineDataError:
            exclusions["missing_or_invalid_maturity_timestamp"] += 1
            continue
        if resolved_at < decision_at:
            exclusions["resolution_precedes_decision"] += 1
            continue
        eligible.append(record)
        labels.append(OUTCOMES[outcome])
    return EligibleSplit(
        records=eligible,
        labels=np.asarray(labels, dtype=np.int8),
        exclusions=dict(exclusions),
    )


def _category(value: object) -> str:
    normalized = str(value or "unknown").strip().lower()
    normalized = re.sub(r"[^a-z0-9_.:-]+", "_", normalized)
    return normalized[:80] or "unknown"


def _text_tokens(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    return TOKEN_RE.findall(value[:MAX_TEXT_CHARS].lower())[:MAX_TEXT_TOKENS]


def _hash_feature(name: str, dimension: int) -> tuple[int, float]:
    digest = hashlib.blake2b(
        name.encode("utf-8"), digest_size=16, person=HASH_PERSON
    ).digest()
    index = int.from_bytes(digest[:8], "little") % dimension
    sign = 1.0 if digest[8] & 1 else -1.0
    return index, sign


def _add_feature(target: Counter[int], name: str, value: float, dimension: int) -> None:
    index, sign = _hash_feature(name, dimension)
    target[index] += sign * float(value)


def record_to_hashed_features(
    record: Mapping[str, Any], dimension: int = 1024
) -> dict[int, float]:
    """Extract only whitelisted pre-decision fields into a signed hashed vector.

    In particular, ``final_outcome``, ``merchant_action``, ``resolved_at``, recovery/cost
    fields and every identifier are never inspected here.  This whitelist is the primary
    protection against target and merchant-identity leakage.
    """

    if dimension < 1:
        raise BaselineDataError("dimension must be positive")
    features: Counter[int] = Counter()
    _add_feature(features, "record=normalized", 1.0, dimension)

    for field in ("phase", "reason_code", "rail", "currency"):
        _add_feature(features, f"{field}={_category(record.get(field))}", 1.0, dimension)

    try:
        amount = max(0.0, float(record.get("amount", 0.0)))
    except (TypeError, ValueError):
        amount = 0.0
    # The contract fixes amounts in minor units; log buckets preserve broad amount effects
    # without letting large-value cases dominate the linear score.
    amount_bucket = int(math.floor(math.log10(amount + 1.0) * 4.0))
    _add_feature(features, f"amount_log10_quarter={amount_bucket}", 1.0, dimension)

    for token in _text_tokens(record.get("claim_text_redacted")):
        _add_feature(features, f"claim_token={token}", 1.0, dimension)

    raw_evidence = record.get("evidence", [])
    evidence = (
        raw_evidence
        if isinstance(raw_evidence, Sequence) and not isinstance(raw_evidence, (str, bytes))
        else []
    )
    _add_feature(features, f"evidence_count={min(len(evidence), 20)}", 1.0, dimension)
    for item in evidence[:50]:
        if not isinstance(item, Mapping):
            continue
        evidence_type = _category(item.get("type"))
        _add_feature(features, f"evidence_type={evidence_type}", 1.0, dimension)
        for token in _text_tokens(item.get("content_redacted")):
            _add_feature(features, f"evidence_token={token}", 1.0, dimension)

    raw_signals = record.get("structured_signals")
    signals = raw_signals if isinstance(raw_signals, Mapping) else {}
    for name in STRUCTURED_SIGNAL_NAMES:
        value = signals.get(name)
        state = "true" if value is True else "false" if value is False else "unknown"
        _add_feature(features, f"signal:{name}={state}", 1.0, dimension)

    # Log-scaled term frequency and row normalization stop long evidence blobs from
    # dominating simply because they contain more words.
    transformed = {
        index: math.copysign(1.0 + math.log(abs(value)), value)
        for index, value in features.items()
        if value != 0.0
    }
    norm = math.sqrt(sum(value * value for value in transformed.values())) or 1.0
    return {index: value / norm for index, value in transformed.items()}


def fit_logistic_baseline(
    records: Sequence[Mapping[str, Any]],
    labels: Sequence[int] | np.ndarray,
    config: TrainingConfig,
) -> HashedLogisticModel:
    """Fit deterministic full-batch L2 logistic regression."""

    config.validate()
    y = np.asarray(labels, dtype=np.float64)
    if len(records) != y.size or y.size < 2:
        raise BaselineDataError("training requires at least two labelled records")
    if not np.all(np.isin(y, (0.0, 1.0))):
        raise BaselineDataError("training labels must be binary")
    if np.unique(y).size != 2:
        raise BaselineDataError("training requires both won and lost outcomes")

    design = SparseDesign.from_records(records, config.dimension)
    weights = np.zeros(config.dimension, dtype=np.float64)
    prevalence = float(np.clip(y.mean(), 1e-6, 1.0 - 1e-6))
    intercept = math.log(prevalence / (1.0 - prevalence))

    for epoch in range(config.epochs):
        logits = np.clip(design.matvec(weights) + intercept, -35.0, 35.0)
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        errors = probabilities - y
        gradient = design.transpose_matvec(errors) / y.size + config.l2 * weights
        intercept_gradient = float(errors.mean())
        step = config.learning_rate / math.sqrt(1.0 + epoch / 20.0)
        weights -= step * gradient
        intercept -= step * intercept_gradient

    final_logits = np.clip(design.matvec(weights) + intercept, -35.0, 35.0)
    final_probabilities = 1.0 / (1.0 + np.exp(-final_logits))
    epsilon = 1e-12
    final_loss = -float(
        np.mean(
            y * np.log(np.clip(final_probabilities, epsilon, 1.0))
            + (1.0 - y)
            * np.log(np.clip(1.0 - final_probabilities, epsilon, 1.0))
        )
    ) + 0.5 * config.l2 * float(np.dot(weights, weights))
    return HashedLogisticModel(
        dimension=config.dimension,
        weights=weights,
        intercept=intercept,
        epochs=config.epochs,
        learning_rate=config.learning_rate,
        l2=config.l2,
        final_log_loss=final_loss,
    )


def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise BaselineDataError(f"missing split file: {path}")
    if path.suffix.lower() == ".jsonl":
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise BaselineDataError(
                        f"invalid JSON in {path.name} line {line_number}"
                    ) from exc
                if not isinstance(value, dict):
                    raise BaselineDataError(
                        f"{path.name} line {line_number} is not an object"
                    )
                records.append(value)
        return records

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BaselineDataError(f"invalid JSON in {path.name}") from exc
    if isinstance(payload, dict):
        payload = payload.get("records")
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise BaselineDataError(f"{path.name} must contain a JSON array of objects")
    return [dict(item) for item in payload]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_normalized_splits(
    splits: Mapping[str, Sequence[Mapping[str, Any]]]
) -> dict[str, list[dict[str, Any]]]:
    """Revalidate all rows against the strict privacy contract before feature access."""

    validated: dict[str, list[dict[str, Any]]] = {}
    for name in SPLIT_ORDER:
        if name not in splits:
            raise BaselineDataError(f"missing split: {name}")
        validated[name] = []
        for index, raw in enumerate(splits[name], 1):
            try:
                record = RealDisputeRecord.model_validate(raw)
            except ValidationError as exc:
                details = "; ".join(
                    f"{'.'.join(str(part) for part in error.get('loc', ())) or 'record'}: "
                    f"{error['msg']}"
                    for error in exc.errors(include_url=False, include_input=False)
                )
                raise BaselineDataError(
                    f"{name} record {index} violates the normalized privacy contract "
                    f"({details})"
                ) from None
            validated[name].append(record.model_dump(mode="json"))
    return validated


def audit_split_integrity(
    splits: Mapping[str, Sequence[Mapping[str, Any]]]
) -> dict[str, object]:
    """Refuse group leakage, duplicate disputes, or non-chronological boundaries."""

    missing = [name for name in SPLIT_ORDER if name not in splits]
    if missing:
        raise BaselineDataError(f"missing split(s): {', '.join(missing)}")

    seen_groups: dict[str, str] = {}
    seen_disputes: dict[str, str] = {}
    summaries: dict[str, dict[str, object]] = {}
    previous_latest: datetime | None = None
    previous_name: str | None = None

    for name in SPLIT_ORDER:
        records = splits[name]
        if not records:
            raise BaselineDataError(f"{name} split is empty")
        timestamps: list[datetime] = []
        groups: set[str] = set()
        for index, record in enumerate(records, 1):
            group = str(record.get("leakage_group_ref", "")).strip()
            dispute = str(record.get("dispute_ref", "")).strip()
            if not group:
                raise BaselineDataError(
                    f"{name} record {index} lacks leakage_group_ref"
                )
            if not dispute:
                raise BaselineDataError(f"{name} record {index} lacks dispute_ref")
            if group in seen_groups and seen_groups[group] != name:
                raise BaselineDataError(
                    f"leakage group occurs in both {seen_groups[group]} and {name}"
                )
            if dispute in seen_disputes:
                raise BaselineDataError(
                    f"duplicate dispute occurs in {seen_disputes[dispute]} and {name}"
                )
            seen_groups[group] = name
            seen_disputes[dispute] = name
            groups.add(group)
            timestamps.append(_parse_timestamp(record.get("decision_at"), "decision_at"))

        earliest, latest = min(timestamps), max(timestamps)
        if previous_latest is not None and earliest < previous_latest:
            raise BaselineDataError(
                f"chronology violation: {name} begins before {previous_name} ends"
            )
        summaries[name] = {
            "records": len(records),
            "groups": len(groups),
            "decision_at_min": earliest.isoformat(),
            "decision_at_max": latest.isoformat(),
        }
        previous_latest = latest
        previous_name = name
    return {"status": "passed", "splits": summaries}


def _validate_classes(split: EligibleSplit, name: str) -> None:
    if split.labels.size == 0:
        raise BaselineDataError(f"{name} has no eligible matured contested records")
    if np.unique(split.labels).size != 2:
        raise BaselineDataError(f"{name} needs both won and lost eligible outcomes")


def _claim_assessment(
    test_metrics: Mapping[str, Any], config: TrainingConfig
) -> tuple[dict[str, object], list[str]]:
    interval = test_metrics["precision_interval"]
    predicted_contest = int(interval["total"])
    warnings: list[str] = []
    if predicted_contest < config.min_test_support:
        warnings.append(
            "Locked-test CONTEST support is below the predeclared minimum; no precision "
            "claim is statistically supported."
        )
        return (
            {
                "status": "insufficient_test_support",
                "claimable_precision": None,
                "predicted_contest": predicted_contest,
                "required_support": config.min_test_support,
                "target_precision": config.target_precision,
            },
            warnings,
        )
    if float(interval["lower"]) >= config.target_precision:
        return (
            {
                "status": "target_demonstrated_on_locked_test",
                "claimable_precision": test_metrics["precision"],
                "target_precision": config.target_precision,
                "confidence": config.confidence,
                "lower_confidence_bound": interval["lower"],
                "predicted_contest": predicted_contest,
            },
            warnings,
        )
    warnings.append(
        "The locked-test precision interval does not demonstrate the requested target; "
        "report the observed estimate and interval, not a target-achievement claim."
    )
    return (
        {
            "status": "target_not_demonstrated_on_locked_test",
            "claimable_precision": None,
            "observed_precision": test_metrics["precision"],
            "target_precision": config.target_precision,
            "confidence": config.confidence,
            "lower_confidence_bound": interval["lower"],
            "predicted_contest": predicted_contest,
        },
        warnings,
    )


def train_and_evaluate(
    splits: Mapping[str, Sequence[Mapping[str, Any]]],
    config: TrainingConfig,
    *,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Train, calibrate, then evaluate once on the untouched test split."""

    config.validate()
    # This second validation boundary is intentional.  Calling the trainer on handcrafted
    # dictionaries must not bypass the importer's redaction/extra-field protections.
    normalized_splits = validate_normalized_splits(splits)
    integrity = audit_split_integrity(normalized_splits)
    eligible = {
        name: filter_eligible(normalized_splits[name]) for name in SPLIT_ORDER
    }
    for name in SPLIT_ORDER:
        _validate_classes(eligible[name], name)

    model = fit_logistic_baseline(
        eligible["train"].records, eligible["train"].labels, config
    )

    # Validation is diagnostic only: no hyperparameter or operating-point search uses it.
    validation_scores = model.predict(eligible["validation"].records)

    # Operating points are selected on the independent calibration split.  The test split
    # is not scored until both thresholds are frozen.
    calibration_scores = model.predict(eligible["calibration"].records)
    contest_selection = select_precision_threshold(
        eligible["calibration"].labels,
        calibration_scores,
        target_precision=config.target_precision,
        min_support=config.min_calibration_support,
        min_coverage=config.min_tail_coverage,
        confidence=config.confidence,
        positive_tail=True,
    )
    accept_selection: ThresholdSelection | None = None
    if contest_selection.threshold is not None:
        accept_selection = select_precision_threshold(
            eligible["calibration"].labels,
            calibration_scores,
            target_precision=config.target_precision,
            min_support=config.min_calibration_support,
            min_coverage=config.min_tail_coverage,
            confidence=config.confidence,
            positive_tail=False,
            upper_bound=contest_selection.threshold,
        )

    warnings = [
        "This observational model estimates P(win | merchant_action=contested); it does "
        "not identify what would have happened to disputes the merchant accepted.",
        "No raw claim/evidence text, identifiers, or feature vocabulary is stored in this artifact.",
    ]
    if contest_selection.threshold is None:
        warnings.append(
            "Calibration data cannot support the requested CONTEST precision at the "
            "predeclared support and coverage; no CONTEST operating point is approved."
        )
    if accept_selection is None or accept_selection.threshold is None:
        warnings.append(
            "Calibration data cannot support a separate ACCEPT tail; non-CONTEST cases "
            "remain deferred."
        )

    contest_threshold = contest_selection.threshold
    accept_threshold = (
        accept_selection.threshold if accept_selection is not None else None
    )
    calibration_metrics = evaluate_selective_classifier(
        eligible["calibration"].labels,
        calibration_scores,
        contest_threshold=contest_threshold,
        accept_threshold=accept_threshold,
        confidence=config.confidence,
        calibration_bins=config.calibration_bins,
    )
    validation_metrics = evaluate_selective_classifier(
        eligible["validation"].labels,
        validation_scores,
        contest_threshold=contest_threshold,
        accept_threshold=accept_threshold,
        confidence=config.confidence,
        calibration_bins=config.calibration_bins,
    )

    # Locked test evaluation happens last and is never fed back into training/calibration.
    test_scores = model.predict(eligible["test"].records)
    test_metrics = evaluate_selective_classifier(
        eligible["test"].labels,
        test_scores,
        contest_threshold=contest_threshold,
        accept_threshold=accept_threshold,
        confidence=config.confidence,
        calibration_bins=config.calibration_bins,
    )
    claim, claim_warnings = _claim_assessment(test_metrics, config)
    if contest_threshold is None:
        claim = {
            "status": "unsupported_calibration_operating_point",
            "claimable_precision": None,
            "target_precision": config.target_precision,
        }
    warnings.extend(claim_warnings)

    artifact = {
        "artifact_version": ARTIFACT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "offline_research_only_not_runtime_decisioning",
        "estimand": "P(final_outcome=won | merchant_action=contested, matured)",
        "config": asdict(config),
        "data_provenance": dict(provenance or {}),
        "split_integrity": integrity,
        "eligibility": {name: eligible[name].summary for name in SPLIT_ORDER},
        "model": model.to_artifact(),
        "operating_points": {
            "contest": contest_selection.to_dict(),
            "accept": accept_selection.to_dict() if accept_selection else None,
            "selected_without_test_access": True,
        },
        "metrics": {
            "validation": validation_metrics,
            "calibration": calibration_metrics,
            "locked_test": test_metrics,
        },
        "precision_claim": claim,
        "warnings": warnings,
    }
    return round_floats(artifact, digits=8)  # type: ignore[return-value]


def _paths_from_args(args: argparse.Namespace) -> dict[str, Path]:
    if args.splits_dir is not None:
        explicit = [args.train, args.validation, args.calibration, args.test]
        if any(path is not None for path in explicit):
            raise BaselineDataError(
                "use either --splits-dir or all four explicit split paths, not both"
            )
        return {
            name: args.splits_dir / filename for name, filename in DEFAULT_FILES.items()
        }
    explicit_paths = {
        "train": args.train,
        "validation": args.validation,
        "calibration": args.calibration,
        "test": args.test,
    }
    if any(path is None for path in explicit_paths.values()):
        raise BaselineDataError(
            "provide --splits-dir or each of --train/--validation/--calibration/--test"
        )
    return {name: Path(path) for name, path in explicit_paths.items()}


def validate_split_manifest(
    manifest_path: Path,
    paths: Mapping[str, Path],
    file_details: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Verify that every consumed byte still matches the splitter's lock manifest."""

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineDataError(f"cannot parse split manifest: {manifest_path.name}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("splits"), dict):
        raise BaselineDataError("split manifest lacks a splits object")

    manifest_splits = manifest["splits"]
    for name in SPLIT_ORDER:
        expected = manifest_splits.get(name)
        actual = file_details[name]
        if not isinstance(expected, dict):
            raise BaselineDataError(f"split manifest lacks {name} metadata")
        if expected.get("file") != paths[name].name:
            raise BaselineDataError(f"manifest filename mismatch for {name}")
        if expected.get("sha256") != actual["sha256"]:
            raise BaselineDataError(f"manifest SHA-256 mismatch for {name}")
        if expected.get("record_count") != actual["records"]:
            raise BaselineDataError(f"manifest record count mismatch for {name}")

    locked = manifest.get("locked_test")
    if not isinstance(locked, dict):
        raise BaselineDataError("split manifest lacks the locked_test declaration")
    if locked.get("file") != paths["test"].name:
        raise BaselineDataError("locked-test filename does not match test split")
    if locked.get("sha256") != file_details["test"]["sha256"]:
        raise BaselineDataError("locked-test SHA-256 does not match test split")
    if manifest.get("total_records") != sum(
        int(file_details[name]["records"]) for name in SPLIT_ORDER
    ):
        raise BaselineDataError("manifest total_records does not match split files")
    return manifest


def _build_provenance(paths: Mapping[str, Path], splits_dir: Path | None) -> dict[str, Any]:
    files = {
        name: {
            "format": path.suffix.lower().lstrip("."),
            "sha256": sha256_file(path),
            "records": len(load_records(path)),
        }
        for name, path in paths.items()
    }
    provenance: dict[str, Any] = {
        "split_files": files,
        "aggregate_sha256": hashlib.sha256(
            "".join(files[name]["sha256"] for name in SPLIT_ORDER).encode("ascii")
        ).hexdigest(),
        "python_version": sys.version.split()[0],
        "numpy_version": np.__version__,
        "raw_text_or_identifiers_embedded": False,
    }
    if splits_dir is not None:
        manifest = splits_dir / "manifest.json"
        if not manifest.is_file():
            raise BaselineDataError(
                "--splits-dir requires the manifest.json produced by the safe splitter"
            )
        manifest_payload = validate_split_manifest(manifest, paths, files)
        provenance["manifest"] = {
            "filename": manifest.name,
            "sha256": sha256_file(manifest),
            "algorithm": manifest_payload.get("algorithm"),
            "locked_test_sha256": manifest_payload["locked_test"]["sha256"],
        }
    provenance["code_sha256"] = {
        "trainer": sha256_file(Path(__file__)),
        "metrics": sha256_file(EVAL_ROOT / "real_metrics.py"),
    }
    return provenance


def write_artifact(path: Path, artifact: Mapping[str, Any], overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise BaselineDataError(f"refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--splits-dir", type=Path)
    parser.add_argument("--train", type=Path)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--test", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dimension", type=int, default=1024)
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--learning-rate", type=float, default=0.35)
    parser.add_argument("--l2", type=float, default=0.002)
    parser.add_argument("--target-precision", type=float, default=0.80)
    parser.add_argument("--min-calibration-support", type=int, default=30)
    parser.add_argument("--min-tail-coverage", type=float, default=0.05)
    parser.add_argument("--min-test-support", type=int, default=30)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--calibration-bins", type=int, default=10)
    parser.add_argument(
        "--allow-insufficient-test-for-smoke",
        action="store_true",
        help="Return success for pipeline smoke data; the artifact still refuses the claim.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = TrainingConfig(
            dimension=args.dimension,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            l2=args.l2,
            target_precision=args.target_precision,
            min_calibration_support=args.min_calibration_support,
            min_tail_coverage=args.min_tail_coverage,
            min_test_support=args.min_test_support,
            confidence=args.confidence,
            calibration_bins=args.calibration_bins,
        )
        config.validate()
        paths = _paths_from_args(args)
        splits = {name: load_records(path) for name, path in paths.items()}
        provenance = _build_provenance(paths, args.splits_dir)
        artifact = train_and_evaluate(splits, config, provenance=provenance)
        write_artifact(args.output, artifact, overwrite=args.overwrite)
    except (BaselineDataError, OSError) as exc:
        parser.error(str(exc))

    claim_status = artifact["precision_claim"]["status"]
    print(f"Wrote offline baseline artifact: {args.output}")
    print(f"Precision claim status: {claim_status}")
    if claim_status in {
        "insufficient_test_support",
        "unsupported_calibration_operating_point",
    } and not args.allow_insufficient_test_for_smoke:
        print(
            "Refusing a precision claim: add representative data or use the explicitly "
            "labelled smoke-only override.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
