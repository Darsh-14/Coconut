"""Synthetic-only supervised safety gate for automatic CONTEST recommendations.

The gate is trained solely on Coconut's labelled synthetic working set.  It can demote an
otherwise eligible CONTEST to human review, but it can never create a CONTEST or ACCEPT on
its own.  It is deliberately disabled for non-synthetic dispute IDs so synthetic benchmark
learning cannot silently become a production claim.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from app.models.schemas import Dispute
from app.services.decision_aggregator import AggregationResult

logger = logging.getLogger("coconut.synthetic_win_gate")

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = BACKEND_ROOT / "eval" / "synthetic_win_gate.json"
ARTIFACT_SCHEMA_VERSION = 1
FEATURE_SCHEMA_VERSION = "coconut.synthetic-win-features.v2"
HASH_PERSON = b"coco-syn-gate-v1"
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,39}")
MAX_TEXT_CHARS = 30_000
MAX_TOKENS_PER_FIELD = 700
MAX_CHARACTERS_FOR_NGRAMS = 8_000

# Domain cues encode evidence completeness, not outcomes.  They are deliberately broad and
# interpretable; the trained weights still decide whether a cue is useful for each case mix.
QUALITY_CUE_GROUPS: dict[str, tuple[str, ...]] = {
    "strong_identity_or_delivery": (
        "signed by",
        "signature",
        "one-time password",
        " otp ",
        "exact delivery address",
        "recipient confirmed",
        "proof of delivery",
    ),
    "strong_refund_or_billing": (
        "original payment method",
        "refund completed",
        "bank reference",
        "different purchase",
        "separate order",
    ),
    "weak_or_missing_proof": (
        "no proof",
        "not available",
        "unavailable",
        "missing",
        "unsigned",
        "undated",
        "could not confirm",
        "does not identify",
        "does not show",
    ),
    "ambiguity_or_mismatch": (
        "ambiguous",
        "unclear",
        "mismatch",
        "different address",
        "generic",
        "unverified",
    ),
    "wrong_refund_destination": (
        "store credit",
        "store wallet",
        "voucher",
        "account balance",
    ),
    "failed_notice": ("bounced", "not delivered", "delivery failed"),
}


@dataclass(frozen=True)
class SyntheticWinModel:
    dimension: int
    intercept: float
    weights: tuple[float, ...]
    threshold: float
    model_version: str


@dataclass(frozen=True)
class SyntheticGateEvaluation:
    applied: bool
    probability: float | None = None
    threshold: float | None = None
    model_version: str | None = None


def _category(value: object) -> str:
    normalized = re.sub(r"[^a-z0-9_.:-]+", "_", str(value or "unknown").lower())
    return normalized[:80] or "unknown"


def _tokens(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    return TOKEN_RE.findall(value[:MAX_TEXT_CHARS].lower())[:MAX_TOKENS_PER_FIELD]


def _add_feature(features: Counter[int], name: str, value: float, dimension: int) -> None:
    digest = hashlib.blake2b(
        name.encode("utf-8"), digest_size=16, person=HASH_PERSON
    ).digest()
    index = int.from_bytes(digest[:8], "little") % dimension
    sign = 1.0 if digest[8] & 1 else -1.0
    features[index] += sign * value


def _add_text_features(
    features: Counter[int], tokens: list[str], prefix: str, dimension: int
) -> None:
    for token in tokens:
        _add_feature(features, f"{prefix}:unigram={token}", 1.0, dimension)
    for left, right in zip(tokens, tokens[1:]):
        _add_feature(features, f"{prefix}:bigram={left}_{right}", 1.0, dimension)
    for first, second, third in zip(tokens, tokens[1:], tokens[2:]):
        _add_feature(
            features,
            f"{prefix}:trigram={first}_{second}_{third}",
            1.0,
            dimension,
        )


def _add_character_features(
    features: Counter[int], value: str, prefix: str, dimension: int
) -> None:
    normalized = re.sub(r"\s+", " ", value.lower())[:MAX_CHARACTERS_FOR_NGRAMS]
    for size in (3, 4, 5):
        for index in range(max(0, len(normalized) - size + 1)):
            _add_feature(
                features,
                f"{prefix}:char{size}={normalized[index:index + size]}",
                0.35,
                dimension,
            )


def dispute_features(dispute: Dispute, dimension: int) -> dict[int, float]:
    """Extract only pre-decision fields; IDs and ``ground_truth_label`` are ignored."""

    if dimension < 128:
        raise ValueError("synthetic gate feature dimension must be at least 128")
    features: Counter[int] = Counter()
    _add_feature(features, "bias=normalized", 1.0, dimension)
    for name in ("phase", "reason_code", "rail", "currency"):
        _add_feature(features, f"{name}={_category(getattr(dispute, name))}", 1.0, dimension)
    amount_bucket = int(math.floor(math.log10(max(dispute.amount, 0) + 1.0) * 4.0))
    _add_feature(features, f"amount_log10_quarter={amount_bucket}", 1.0, dimension)

    claim_tokens = _tokens(dispute.claim_text)
    _add_text_features(features, claim_tokens, "claim", dimension)

    evidence = dispute.evidence_bundle[:50]
    _add_feature(features, f"evidence_count={min(len(evidence), 20)}", 1.0, dimension)
    distinct_types = {_category(item.type) for item in evidence}
    _add_feature(features, f"evidence_type_count={len(distinct_types)}", 1.0, dimension)
    reason = _category(dispute.reason_code)
    combined_evidence: list[str] = []
    for item in evidence:
        evidence_type = _category(item.type)
        _add_feature(features, f"evidence_type={evidence_type}", 1.0, dimension)
        item_tokens = _tokens(item.content)
        combined_evidence.append(item.content)
        _add_text_features(features, item_tokens, "evidence", dimension)
        for token in item_tokens:
            _add_feature(features, f"type={evidence_type}:token={token}", 1.0, dimension)
            _add_feature(features, f"reason={reason}:token={token}", 1.0, dimension)

    combined_text = " ".join(combined_evidence)
    _add_character_features(features, combined_text, "evidence", dimension)
    lowered = f" {re.sub(r'\s+', ' ', combined_text.lower())} "
    for group, phrases in QUALITY_CUE_GROUPS.items():
        matches = sum(lowered.count(phrase) for phrase in phrases)
        bucket = min(matches, 3)
        _add_feature(features, f"quality_cue={group}:count={bucket}", 1.0, dimension)
        _add_feature(features, f"reason={reason}:quality_cue={group}:count={bucket}", 1.0, dimension)

    transformed = {
        index: math.copysign(1.0 + math.log(abs(value)), value)
        for index, value in features.items()
        if value
    }
    norm = math.sqrt(sum(value * value for value in transformed.values())) or 1.0
    return {index: value / norm for index, value in transformed.items()}


def predict_probability(dispute: Dispute, model: SyntheticWinModel) -> float:
    score = model.intercept + sum(
        model.weights[index] * value
        for index, value in dispute_features(dispute, model.dimension).items()
    )
    score = max(-35.0, min(35.0, score))
    return 1.0 / (1.0 + math.exp(-score))


def _parse_artifact(value: object) -> SyntheticWinModel:
    if not isinstance(value, Mapping):
        raise ValueError("artifact must be an object")
    if value.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("artifact schema version is incompatible")
    if value.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise ValueError("artifact feature schema is incompatible")
    dimension = value.get("dimension")
    weights = value.get("weights")
    intercept = value.get("intercept")
    threshold = value.get("decision_threshold")
    model_version = value.get("model_version")
    if not isinstance(dimension, int) or not 128 <= dimension <= 65_536:
        raise ValueError("artifact dimension is invalid")
    if not isinstance(weights, list) or len(weights) != dimension:
        raise ValueError("artifact weights are invalid")
    numeric_weights = tuple(float(item) for item in weights)
    if not all(math.isfinite(item) for item in numeric_weights):
        raise ValueError("artifact weights must be finite")
    if not isinstance(intercept, (int, float)) or not math.isfinite(float(intercept)):
        raise ValueError("artifact intercept is invalid")
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not 0.0 <= float(threshold) <= 1.0
    ):
        raise ValueError("artifact decision threshold is invalid")
    if not isinstance(model_version, str) or not model_version.strip():
        raise ValueError("artifact model version is invalid")
    return SyntheticWinModel(
        dimension=dimension,
        intercept=float(intercept),
        weights=numeric_weights,
        threshold=float(threshold),
        model_version=model_version,
    )


@lru_cache(maxsize=1)
def load_synthetic_win_model() -> SyntheticWinModel | None:
    try:
        return _parse_artifact(json.loads(ARTIFACT_PATH.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("synthetic win-gate artifact is unavailable or invalid: %s", exc)
        return None


def apply_synthetic_win_gate(
    result: AggregationResult, dispute: Dispute | None
) -> tuple[AggregationResult, SyntheticGateEvaluation]:
    """Demote low-scoring synthetic CONTEST cases; never create an automatic decision."""

    if (
        result.recommendation != "CONTEST"
        or dispute is None
        or not dispute.dispute_id.startswith("disp_synthetic_")
    ):
        return result, SyntheticGateEvaluation(applied=False)

    model = load_synthetic_win_model()
    if model is None:
        return (
            AggregationResult(
                recommendation="NEEDS_HUMAN_REVIEW",
                confidence=0.0,
                driving_verdicts=result.driving_verdicts,
                rationale=(
                    "The synthetic supervised safety gate is unavailable, so this otherwise "
                    "eligible CONTEST is deferred rather than guessed."
                ),
                urcs_forecast=result.urcs_forecast,
            ),
            SyntheticGateEvaluation(applied=True),
        )

    probability = predict_probability(dispute, model)
    evaluation = SyntheticGateEvaluation(
        applied=True,
        probability=probability,
        threshold=model.threshold,
        model_version=model.model_version,
    )
    if probability >= model.threshold:
        return (
            AggregationResult(
                recommendation=result.recommendation,
                confidence=result.confidence,
                driving_verdicts=result.driving_verdicts,
                rationale=(
                    result.rationale
                    + f" The synthetic win gate also cleared its out-of-fold threshold "
                    f"({probability:.2f} >= {model.threshold:.2f})."
                ),
                urcs_forecast=result.urcs_forecast,
            ),
            evaluation,
        )
    return (
        AggregationResult(
            recommendation="NEEDS_HUMAN_REVIEW",
            confidence=min(result.confidence, 1.0 - probability),
            driving_verdicts=result.driving_verdicts,
            rationale=(
                "The evidence passed the NLI corroboration rule, but the synthetic-only "
                f"win gate scored {probability:.2f}, below its {model.threshold:.2f} "
                "out-of-fold threshold. The case is deferred to protect CONTEST precision."
            ),
            urcs_forecast=result.urcs_forecast,
        ),
        evaluation,
    )


__all__ = [
    "ARTIFACT_PATH",
    "ARTIFACT_SCHEMA_VERSION",
    "FEATURE_SCHEMA_VERSION",
    "SyntheticGateEvaluation",
    "SyntheticWinModel",
    "apply_synthetic_win_gate",
    "dispute_features",
    "load_synthetic_win_model",
    "predict_probability",
]
