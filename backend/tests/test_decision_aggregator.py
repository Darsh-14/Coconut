"""Phase-4 acceptance tests (CLAUDE.md Section 13 / Section 14), updated for Addendum 3.

Section 14: "pure logic tests against the rule, no model needed". Every verdict here is
hand-constructed, so these run in milliseconds.

WHAT CHANGED: Addendum 3 supersedes Section 10's hard-coded 0.7 and 0.65 with a single
conformally calibrated threshold, and the comparison became `>=` rather than `>`. These
tests therefore pass an explicit `threshold` rather than relying on global calibration
state -- which also keeps them independent of whatever budget happens to be active.

What did NOT change, and is still pinned here: unanimity, the >= 2 distinct evidence types
requirement, and min-not-average confidence. Those are structural design choices, not
tuned numbers, so calibration does not touch them.
"""

from __future__ import annotations

import pytest

from app.models.schemas import ClaimVerdict, EvidenceItem
from app.services.decision_aggregator import (
    MIN_DISTINCT_SUPPORTING_EVIDENCE_TYPES,
    aggregate,
    build_decision,
)

# A fixed threshold for these tests, so they exercise the rule rather than whatever risk
# budget happens to be calibrated in this process.
T = 0.70


def verdict(index: int, label: str, confidence: float) -> ClaimVerdict:
    return ClaimVerdict(evidence_index=index, label=label, confidence=confidence)


def bundle(*types: str) -> list[EvidenceItem]:
    return [EvidenceItem(type=t, content=f"evidence of type {t}") for t in types]


# -- branch 1: ACCEPT ------------------------------------------------------------------


def test_strong_contradiction_forces_accept():
    verdicts = [verdict(0, "support", 0.99), verdict(1, "contradict", 0.95)]
    result = aggregate(verdicts, bundle("delivery_proof", "communication_log"), threshold=T)
    assert result.recommendation == "ACCEPT"
    assert result.confidence == 0.95


def test_contradiction_exactly_at_the_threshold_triggers_accept():
    """Addendum 3 uses `>=`, not Section 10's strict `>`. The boundary is inclusive now,
    and that is a deliberate change rather than an off-by-one."""
    verdicts = [verdict(0, "contradict", T)]
    result = aggregate(verdicts, bundle("delivery_proof"), threshold=T)
    assert result.recommendation == "ACCEPT"


def test_contradiction_just_below_the_threshold_does_not_trigger_accept():
    verdicts = [verdict(0, "contradict", T - 0.001)]
    result = aggregate(verdicts, bundle("delivery_proof"), threshold=T)
    assert result.recommendation == "NEEDS_HUMAN_REVIEW"


def test_contradiction_just_above_the_threshold_triggers_accept():
    verdicts = [verdict(0, "contradict", T + 0.001)]
    result = aggregate(verdicts, bundle("delivery_proof"), threshold=T)
    assert result.recommendation == "ACCEPT"


def test_accept_confidence_is_the_min_of_the_contradicting_verdicts_only():
    """The min is taken across the verdicts that DROVE the decision, not all verdicts."""
    verdicts = [
        verdict(0, "support", 0.20),  # lower, but did not drive the ACCEPT
        verdict(1, "contradict", 0.90),
        verdict(2, "contradict", 0.80),
    ]
    result = aggregate(verdicts, bundle("delivery_proof", "order_history", "device_signal"), threshold=T)
    assert result.recommendation == "ACCEPT"
    assert result.confidence == 0.80


def test_accept_wins_over_contest_when_both_could_apply():
    """Branch order matters: a strong contradiction outranks unanimous-looking support."""
    verdicts = [verdict(0, "contradict", 0.99), verdict(1, "contradict", 0.99)]
    result = aggregate(verdicts, bundle("delivery_proof", "order_history"), threshold=T)
    assert result.recommendation == "ACCEPT"


# -- branch 2: CONTEST -----------------------------------------------------------------


def test_unanimous_strong_corroborated_support_yields_contest():
    verdicts = [verdict(0, "support", 0.90), verdict(1, "support", 0.80)]
    result = aggregate(verdicts, bundle("delivery_proof", "communication_log"), threshold=T)
    assert result.recommendation == "CONTEST"
    assert result.confidence == 0.80, "overall confidence is the weakest link"


def test_contest_requires_two_distinct_evidence_types():
    """Two strong verdicts on the SAME evidence type is not corroboration."""
    verdicts = [verdict(0, "support", 0.95), verdict(1, "support", 0.95)]
    result = aggregate(verdicts, bundle("delivery_proof", "delivery_proof"), threshold=T)
    assert result.recommendation == "NEEDS_HUMAN_REVIEW"
    assert "evidence type" in result.rationale


def test_contest_requires_the_weakest_link_to_clear_the_threshold():
    verdicts = [verdict(0, "support", 0.60), verdict(1, "support", 0.60)]
    result = aggregate(verdicts, bundle("delivery_proof", "order_history"), threshold=T)
    assert result.recommendation == "NEEDS_HUMAN_REVIEW"
    assert "weakest item" in result.rationale


def test_weakest_link_exactly_at_the_threshold_contests():
    """Inclusive boundary, matching the contradict branch."""
    verdicts = [verdict(0, "support", T), verdict(1, "support", T)]
    result = aggregate(verdicts, bundle("delivery_proof", "order_history"), threshold=T)
    assert result.recommendation == "CONTEST"


def test_a_single_neutral_verdict_blocks_contest():
    """Section 10 requires ALL verdicts to be support."""
    verdicts = [
        verdict(0, "support", 0.95),
        verdict(1, "support", 0.95),
        verdict(2, "neutral", 0.90),
    ]
    result = aggregate(verdicts, bundle("delivery_proof", "order_history", "device_signal"), threshold=T)
    assert result.recommendation == "NEEDS_HUMAN_REVIEW"


def test_a_strong_item_can_no_longer_carry_a_weak_one():
    """Deliberate change from Section 10, pinned so nobody restores it by accident.

    Under the old average rule this bundle contested: mean 0.77 cleared 0.65 even though
    one item sat at 0.55. Calibration is run on the weakest link, so the weakest link is
    what the threshold has to gate on -- otherwise the guarantee would be calibrated
    against one quantity and enforced against another.
    """
    verdicts = [verdict(0, "support", 0.99), verdict(1, "support", 0.55)]
    result = aggregate(verdicts, bundle("delivery_proof", "order_history"), threshold=T)
    assert result.recommendation == "NEEDS_HUMAN_REVIEW"
    assert result.confidence == 0.55


def test_three_types_satisfies_the_corroboration_floor():
    verdicts = [verdict(i, "support", 0.85) for i in range(3)]
    result = aggregate(verdicts, bundle("delivery_proof", "communication_log", "device_signal"), threshold=T)
    assert result.recommendation == "CONTEST"


# -- branch 3: NEEDS_HUMAN_REVIEW ------------------------------------------------------


def test_mixed_evidence_needs_human_review():
    verdicts = [verdict(0, "support", 0.90), verdict(1, "neutral", 0.70)]
    result = aggregate(verdicts, bundle("delivery_proof", "order_history"), threshold=T)
    assert result.recommendation == "NEEDS_HUMAN_REVIEW"
    assert "mixed" in result.rationale


def test_weak_contradiction_does_not_accept_but_blocks_contest():
    """A contradiction below 0.7 is too weak to accept on, and not support either."""
    verdicts = [verdict(0, "support", 0.95), verdict(1, "contradict", 0.50)]
    result = aggregate(verdicts, bundle("delivery_proof", "order_history"), threshold=T)
    assert result.recommendation == "NEEDS_HUMAN_REVIEW"


def test_all_neutral_needs_human_review():
    verdicts = [verdict(0, "neutral", 0.60), verdict(1, "neutral", 0.55)]
    result = aggregate(verdicts, bundle("delivery_proof", "order_history"), threshold=T)
    assert result.recommendation == "NEEDS_HUMAN_REVIEW"
    assert result.confidence == 0.55


def test_empty_verdicts_needs_human_review():
    result = aggregate([], [], threshold=T)
    assert result.recommendation == "NEEDS_HUMAN_REVIEW"
    assert result.confidence == 0.0
    assert result.driving_verdicts == []


def test_single_supporting_verdict_cannot_contest_alone():
    """One evidence item can never reach two distinct types."""
    result = aggregate([verdict(0, "support", 0.99)], bundle("delivery_proof"), threshold=T)
    assert result.recommendation == "NEEDS_HUMAN_REVIEW"


# -- robustness ------------------------------------------------------------------------


def test_out_of_range_evidence_index_fails_safe_to_human_review():
    """A mismatched verdict/bundle pairing must not silently produce a CONTEST."""
    verdicts = [verdict(0, "support", 0.95), verdict(99, "support", 0.95)]
    result = aggregate(verdicts, bundle("delivery_proof"), threshold=T)
    assert result.recommendation == "NEEDS_HUMAN_REVIEW"


# -- Decision contract -----------------------------------------------------------------


def test_build_decision_returns_the_section_6_contract():
    verdicts = [verdict(0, "support", 0.90), verdict(1, "support", 0.80)]
    decision = build_decision(
        dispute_id="disp_synthetic_0001",
        verdicts=verdicts,
        evidence_bundle=bundle("delivery_proof", "communication_log"),
        threshold=T,
    )
    assert decision.dispute_id == "disp_synthetic_0001"
    assert decision.recommendation == "CONTEST"
    assert decision.confidence == 0.80
    assert len(decision.claim_verdicts) == 2
    assert decision.model_version == "cross-encoder/nli-deberta-v3-base"
    assert decision.decided_at is not None


def test_build_decision_carries_the_drafted_packet():
    decision = build_decision(
        dispute_id="disp_synthetic_0002",
        verdicts=[verdict(0, "support", 0.9), verdict(1, "support", 0.9)],
        evidence_bundle=bundle("delivery_proof", "order_history"),
        drafted_packet="Representment text.",
    )
    assert decision.drafted_packet == "Representment text."


@pytest.mark.parametrize(
    "labels,confidences,types,expected",
    [
        (["support", "support"], [0.9, 0.9], ["delivery_proof", "order_history"], "CONTEST"),
        (["support", "contradict"], [0.9, 0.9], ["delivery_proof", "order_history"], "ACCEPT"),
        (["neutral", "neutral"], [0.9, 0.9], ["delivery_proof", "order_history"], "NEEDS_HUMAN_REVIEW"),
        (["support", "support"], [0.9, 0.9], ["delivery_proof", "delivery_proof"], "NEEDS_HUMAN_REVIEW"),
    ],
)
def test_rule_table(labels, confidences, types, expected):
    verdicts = [verdict(i, l, c) for i, (l, c) in enumerate(zip(labels, confidences))]
    assert aggregate(verdicts, bundle(*types), threshold=T).recommendation == expected
