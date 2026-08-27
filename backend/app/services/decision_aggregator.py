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
    Dispute,
    EvidenceItem,
    Recommendation,
    URCSForecast,
)
from app.services.conformal_calibrator import get_active_calibrated_threshold
from app.services.urcs_forecaster import forecast_urcs_disposition
from app.services.verification_engine import MODEL_NAME

logger = logging.getLogger("recourse.aggregator")

# --- thresholds ---
#
# Section 10's two numeric thresholds are SUPERSEDED by Addendum 3: they are no longer
# used to decide anything. Both branches now compare against a single threshold
# calibrated to a stated risk budget by conformal_calibrator.py, so the number is derived
# from data rather than chosen. The originals are kept only as the historical record of
# what the spec first prescribed, and are referenced by nothing in the decision path.
LEGACY_CONTRADICT_CONFIDENCE_THRESHOLD = 0.7
LEGACY_SUPPORT_AVERAGE_CONFIDENCE_THRESHOLD = 0.65

# Still in force. This one is a structural design choice -- corroboration across
# independent evidence types -- not a tuned number, so calibration does not touch it.
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
    # Present only for UPI disputes. Addendum 2: NPCI's rules engine decides a real share
    # of UPI outcomes deterministically, so the forecast travels with the decision.
    urcs_forecast: Optional[URCSForecast] = None


def aggregate(
    verdicts: Sequence[ClaimVerdict],
    evidence_bundle: Sequence[EvidenceItem],
    dispute: Optional[Dispute] = None,
    dispute_history: Optional[Sequence[Dispute]] = None,
    threshold: Optional[float] = None,
) -> AggregationResult:
    """Apply the decision rule to a bundle's verdicts.

    `threshold` is the conformally calibrated lambda. Omit it and the active calibrated
    threshold is used; pass it explicitly to evaluate a bundle at a specific budget
    without touching global state, which is what the tests and /verify-guarantee do.

    When `dispute` is supplied and settles on UPI rails, NPCI's deterministic caps are
    checked *first* (Addendum 2, Section 24). If URCS is expected to auto-reject the
    chargeback, no amount of evidence quality matters -- the merchant should spend nothing
    on it. Deterministic rules before the model, which is the same ordering Razorpay's own
    Bumblebee system describes.

    Both new arguments are optional so every existing caller keeps working unchanged.
    """
    # Addendum 3 supersedes Section 10's 0.7 and 0.65. Both branches now use one
    # threshold calibrated to a stated risk budget, so the number is derived rather than
    # picked. The structural rules -- unanimity, >= 2 distinct evidence types, and min-
    # rather-than-average confidence -- are design choices, not arbitrary constants, and
    # they stay exactly as Section 10 wrote them.
    if threshold is None:
        threshold = get_active_calibrated_threshold()

    forecast = None
    if dispute is not None:
        forecast = forecast_urcs_disposition(dispute, dispute_history or [])
        if forecast.predicted_disposition == "AUTO_REJECT":
            return AggregationResult(
                recommendation="NO_ACTION_NEEDED",
                # The rule is deterministic, so this is certainty about NPCI's behaviour,
                # not a model's belief about the evidence.
                confidence=1.0,
                driving_verdicts=[],
                rationale=(
                    f"{forecast.explanation} No representment is needed: NPCI will reject "
                    f"this on the merchant's behalf. The remitting bank may still re-raise "
                    f"it in good faith under RGNB."
                    if forecast.rgnb_re_raise_possible
                    else forecast.explanation
                ),
                urcs_forecast=forecast,
            )

    if threshold is None:
        # Either nothing has been calibrated yet, or the requested risk budget is
        # unachievable on the calibration data. Both mean the same thing: the system
        # cannot promise the stated false-positive rate, so it decides nothing. Silently
        # falling back to a default threshold would defeat the entire point.
        return AggregationResult(
            recommendation="NEEDS_HUMAN_REVIEW",
            confidence=0.0,
            driving_verdicts=[],
            rationale=(
                "No calibrated threshold is in force, so the system cannot guarantee the "
                "requested false-positive rate and declines to decide."
            ),
            urcs_forecast=forecast,
        )

    if not verdicts:
        return AggregationResult(
            recommendation="NEEDS_HUMAN_REVIEW",
            confidence=0.0,
            driving_verdicts=[],
            rationale="No evidence was supplied, so there is nothing to verify.",
            urcs_forecast=forecast,
        )

    # --- branch 1: any strongly contradicting evidence means give up and accept ---
    contradicting = [
        v
        for v in verdicts
        if v.label == "contradict" and v.confidence >= threshold
    ]
    if contradicting:
        confidence = min(v.confidence for v in contradicting)
        indices = ", ".join(str(v.evidence_index) for v in contradicting)
        return AggregationResult(
            recommendation="ACCEPT",
            confidence=confidence,
            driving_verdicts=contradicting,
            rationale=(
                f"Evidence item(s) {indices} actively support the bank's claim at or "
                f"above the calibrated threshold {threshold:.2f}. Contesting on this "
                f"record would likely fail and incur representment cost."
            ),
            urcs_forecast=forecast,
        )

    # --- branch 2: unanimous, sufficiently strong, corroborated support means contest ---
    supporting = [v for v in verdicts if v.label == "support"]
    if len(supporting) == len(verdicts):
        # The score the threshold is calibrated against is the weakest link, not the
        # average -- that is the quantity conformal calibration was run on, so it has to
        # be the quantity compared here.
        weakest_link = min(v.confidence for v in supporting)
        distinct_types = _distinct_supporting_types(supporting, evidence_bundle)

        if (
            weakest_link >= threshold
            and len(distinct_types) >= MIN_DISTINCT_SUPPORTING_EVIDENCE_TYPES
        ):
            return AggregationResult(
                recommendation="CONTEST",
                confidence=min(v.confidence for v in supporting),
                driving_verdicts=list(supporting),
                rationale=(
                    f"All {len(verdicts)} evidence item(s) support the merchant, the "
                    f"weakest of them at {weakest_link:.2f} clears the calibrated "
                    f"threshold {threshold:.2f}, and the support is "
                    f"corroborated across {len(distinct_types)} evidence types "
                    f"({', '.join(sorted(distinct_types))}). Overall confidence is the "
                    f"weakest link in that chain."
                ),
                urcs_forecast=forecast,
            )

        # Unanimous but not strong enough: say precisely which condition failed.
        reasons = []
        if weakest_link < threshold:
            reasons.append(
                f"its weakest item at {weakest_link:.2f} falls below the calibrated "
                f"threshold {threshold:.2f}"
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
            urcs_forecast=forecast,
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
        urcs_forecast=forecast,
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
    dispute: Optional[Dispute] = None,
    dispute_history: Optional[Sequence[Dispute]] = None,
    threshold: Optional[float] = None,
) -> Decision:
    """Aggregate and wrap the outcome in the Section 6 Decision contract.

    Pass `dispute` and `dispute_history` to have NPCI's UPI caps checked first; omit them
    and the behaviour is exactly Section 10 as before.
    """
    result = aggregate(verdicts, evidence_bundle, dispute, dispute_history, threshold)
    return Decision(
        dispute_id=dispute_id,
        recommendation=result.recommendation,
        confidence=round(result.confidence, 4),
        claim_verdicts=list(verdicts),
        drafted_packet=drafted_packet,
        decided_at=decided_at or datetime.now(timezone.utc),
        model_version=MODEL_NAME,
        calibrated_threshold_used=threshold if threshold is not None else get_active_calibrated_threshold(),
    )


__all__ = [
    "LEGACY_CONTRADICT_CONFIDENCE_THRESHOLD",
    "MIN_DISTINCT_SUPPORTING_EVIDENCE_TYPES",
    "LEGACY_SUPPORT_AVERAGE_CONFIDENCE_THRESHOLD",
    "AggregationResult",
    "aggregate",
    "build_decision",
]
