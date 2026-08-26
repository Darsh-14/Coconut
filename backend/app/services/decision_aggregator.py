"""Decision aggregation: turn a list of ClaimVerdict into a recommendation.

This implements CLAUDE.md Section 10 literally. The rule is deliberately a plain, readable
conditional rather than a learned model: a merchant disputing a chargeback needs to be able
to read why the system said what it said, and a judge needs to be able to check it.

    if any verdict has label == "contradict" and confidence > 0.7:
        ACCEPT
    elif all verdicts have label == "support"
         and average(confidence) > 0.65
         and count(distinct evidence.type among supporting verdicts) >= 2:
        CONTEST
    else:
        NEEDS_HUMAN_REVIEW

    overall_confidence = min(confidence across the verdicts that drove the decision)

On the min(): Section 10 calls for the minimum rather than the average, because a chain of
evidence is only as strong as its weakest link. That choice does real work here because the
verification engine puts evidentiary strength into `confidence` (see verification_engine's
module docstring) -- so the minimum is the strength of the flimsiest thing the merchant is
relying on, which is exactly what an opposing bank will attack first.

The thresholds are Section 10's, unchanged. They are not tuned here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from app.models.schemas import (
    ClaimVerdict,
    Decision,
    EvidenceItem,
    Recommendation,
)
from app.services.verification_engine import MODEL_NAME

logger = logging.getLogger("recourse.aggregator")

# --- Section 10's thresholds. Do not tune these without updating the spec. ---

CONTRADICT_CONFIDENCE_THRESHOLD = 0.7
SUPPORT_AVERAGE_CONFIDENCE_THRESHOLD = 0.65
MIN_DISTINCT_SUPPORTING_EVIDENCE_TYPES = 2


@dataclass
class AggregationResult:
    """A recommendation plus the reasoning that produced it.

    `rationale` and `driving_verdicts` exist so the audit trail and the UI can explain the
    outcome without re-deriving the rule.
    """

    recommendation: Recommendation
    confidence: float
    driving_verdicts: list[ClaimVerdict]
    rationale: str


def aggregate(
    verdicts: Sequence[ClaimVerdict],
    evidence_bundle: Sequence[EvidenceItem],
) -> AggregationResult:
    """Apply Section 10's rule to a bundle's verdicts."""
    if not verdicts:
        return AggregationResult(
            recommendation="NEEDS_HUMAN_REVIEW",
            confidence=0.0,
            driving_verdicts=[],
            rationale="No evidence was supplied, so there is nothing to verify.",
        )

    # --- branch 1: any strongly contradicting evidence means give up and accept ---
    contradicting = [
        v
        for v in verdicts
        if v.label == "contradict" and v.confidence > CONTRADICT_CONFIDENCE_THRESHOLD
    ]
    if contradicting:
        confidence = min(v.confidence for v in contradicting)
        indices = ", ".join(str(v.evidence_index) for v in contradicting)
        return AggregationResult(
            recommendation="ACCEPT",
            confidence=confidence,
            driving_verdicts=contradicting,
            rationale=(
                f"Evidence item(s) {indices} actively support the bank's claim with "
                f"confidence above {CONTRADICT_CONFIDENCE_THRESHOLD:.2f}. Contesting on "
                f"this record would likely fail and incur representment cost."
            ),
        )

    # --- branch 2: unanimous, sufficiently strong, corroborated support means contest ---
    supporting = [v for v in verdicts if v.label == "support"]
    if len(supporting) == len(verdicts):
        average_confidence = sum(v.confidence for v in supporting) / len(supporting)
        distinct_types = _distinct_supporting_types(supporting, evidence_bundle)

        if (
            average_confidence > SUPPORT_AVERAGE_CONFIDENCE_THRESHOLD
            and len(distinct_types) >= MIN_DISTINCT_SUPPORTING_EVIDENCE_TYPES
        ):
            return AggregationResult(
                recommendation="CONTEST",
                confidence=min(v.confidence for v in supporting),
                driving_verdicts=list(supporting),
                rationale=(
                    f"All {len(verdicts)} evidence item(s) support the merchant, average "
                    f"confidence {average_confidence:.2f} exceeds "
                    f"{SUPPORT_AVERAGE_CONFIDENCE_THRESHOLD:.2f}, and the support is "
                    f"corroborated across {len(distinct_types)} evidence types "
                    f"({', '.join(sorted(distinct_types))}). Overall confidence is the "
                    f"weakest link in that chain."
                ),
            )

        # Unanimous but not strong enough: say precisely which condition failed.
        reasons = []
        if average_confidence <= SUPPORT_AVERAGE_CONFIDENCE_THRESHOLD:
            reasons.append(
                f"average confidence {average_confidence:.2f} does not exceed "
                f"{SUPPORT_AVERAGE_CONFIDENCE_THRESHOLD:.2f}"
            )
        if len(distinct_types) < MIN_DISTINCT_SUPPORTING_EVIDENCE_TYPES:
            reasons.append(
                f"support rests on only {len(distinct_types)} evidence type"
                f"{'s' if len(distinct_types) != 1 else ''}, "
                f"below the {MIN_DISTINCT_SUPPORTING_EVIDENCE_TYPES} required for "
                f"corroboration"
            )
        return AggregationResult(
            recommendation="NEEDS_HUMAN_REVIEW",
            confidence=min(v.confidence for v in verdicts),
            driving_verdicts=list(verdicts),
            rationale=(
                "All evidence points the merchant's way, but " + " and ".join(reasons) + "."
            ),
        )

    # --- branch 3: everything else needs a human ---
    counts = {
        label: sum(1 for v in verdicts if v.label == label)
        for label in ("support", "contradict", "neutral")
    }
    return AggregationResult(
        recommendation="NEEDS_HUMAN_REVIEW",
        confidence=min(v.confidence for v in verdicts),
        driving_verdicts=list(verdicts),
        rationale=(
            f"The evidence is mixed ({counts['support']} supporting, "
            f"{counts['contradict']} contradicting, {counts['neutral']} neutral) and does "
            f"not resolve the claim either way. Routed to a human rather than guessed at."
        ),
    )


def _distinct_supporting_types(
    supporting: Sequence[ClaimVerdict], evidence_bundle: Sequence[EvidenceItem]
) -> set[str]:
    """Distinct evidence.type across the supporting verdicts.

    Verdicts carry an index into the bundle, not the type itself, so this joins the two.
    An out-of-range index is skipped rather than raising: it would mean a caller paired
    verdicts with the wrong bundle, and silently corrupting a decision is worse than
    under-counting corroboration (which fails safe, toward human review).
    """
    types: set[str] = set()
    for verdict in supporting:
        if 0 <= verdict.evidence_index < len(evidence_bundle):
            types.add(evidence_bundle[verdict.evidence_index].type)
        else:
            logger.warning(
                "verdict references evidence_index %s outside a bundle of %s items",
                verdict.evidence_index,
                len(evidence_bundle),
            )
    return types


def build_decision(
    *,
    dispute_id: str,
    verdicts: Sequence[ClaimVerdict],
    evidence_bundle: Sequence[EvidenceItem],
    drafted_packet: Optional[str] = None,
    decided_at: Optional[datetime] = None,
) -> Decision:
    """Aggregate and wrap the outcome in the Section 6 Decision contract."""
    result = aggregate(verdicts, evidence_bundle)
    return Decision(
        dispute_id=dispute_id,
        recommendation=result.recommendation,
        confidence=round(result.confidence, 4),
        claim_verdicts=list(verdicts),
        drafted_packet=drafted_packet,
        decided_at=decided_at or datetime.now(timezone.utc),
        model_version=MODEL_NAME,
    )


__all__ = [
    "CONTRADICT_CONFIDENCE_THRESHOLD",
    "MIN_DISTINCT_SUPPORTING_EVIDENCE_TYPES",
    "SUPPORT_AVERAGE_CONFIDENCE_THRESHOLD",
    "AggregationResult",
    "aggregate",
    "build_decision",
]
