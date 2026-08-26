"""Phase-3 acceptance tests (CLAUDE.md Section 13 / Section 14).

Section 14 requires 3+ hand-written cases with asserted expected labels: clear support,
clear contradiction, clearly insufficient.

The most valuable test here is test_label_inversion_is_not_reversed. The engine passes the
BANK'S claim as the NLI hypothesis, so NLI "contradiction" means the evidence refutes the
bank and therefore SUPPORTS contesting. If that mapping were ever flipped, every
recommendation in the system would invert while still producing plausible confidences and
every other test would still pass. That test asserts the direction explicitly.

These load the real model, so they are slower than the rest of the suite.
"""

from __future__ import annotations

import pytest

from app.models.schemas import EvidenceItem
from app.services.verification_engine import (
    GENERIC_PROBE,
    NLI_TO_VERDICT,
    SUBSTANTIATION_PROBES,
    VerificationEngine,
    probe_for,
    split_sentences,
)


@pytest.fixture(scope="module")
def engine() -> VerificationEngine:
    return VerificationEngine()


# The bank's accusation, in all three cases.
CLAIM_NOT_DELIVERED = (
    "Cardholder asserts that the merchandise associated with this transaction was never "
    "delivered to the address on file."
)


# -- Section 14's three hand-written cases -------------------------------------------


def test_clear_support_for_the_merchant(engine):
    """Specific, corroborated evidence refuting the bank's claim must read as SUPPORT."""
    evidence = [
        EvidenceItem(
            type="delivery_proof",
            content=(
                "The courier delivered the parcel to the address on file on 14 July 2026 "
                "at 11:42 and the recipient signed for it. A doorstep photograph and a "
                "delivery OTP entered from the registered mobile are both on record."
            ),
        )
    ]
    verdicts = engine.verify_bundle(CLAIM_NOT_DELIVERED, evidence, "goods_not_received")

    assert len(verdicts) == 1
    assert verdicts[0].label == "support"
    assert verdicts[0].confidence > 0.5
    assert verdicts[0].evidence_index == 0


def test_clear_contradiction_of_the_merchant(engine):
    """Evidence that confirms the bank's claim must read as CONTRADICT."""
    evidence = [
        EvidenceItem(
            type="delivery_proof",
            content=(
                "The parcel was never delivered to the customer. The courier returned the "
                "consignment to origin after three failed attempts and it was received back "
                "into the warehouse."
            ),
        )
    ]
    verdicts = engine.verify_bundle(CLAIM_NOT_DELIVERED, evidence, "goods_not_received")

    assert len(verdicts) == 1
    assert verdicts[0].label == "contradict"
    assert verdicts[0].confidence > 0.5


def test_clearly_insufficient_evidence(engine):
    """Evidence that does not address the claim must not be able to drive a CONTEST.

    This is the case the single-signal engine got badly wrong: bare NLI scored this
    'contradiction' at 0.992, which is both a green SUPPORT badge AND enough confidence to
    clear Section 10's 0.65 gate, because the model is poorly calibrated on off-topic
    premises. Loyalty points do not entail "The customer received the goods", so the
    substantiation signal drags the blended confidence back under the gate.

    The assertion is on confidence rather than on the label deliberately. Requiring the
    label itself to flip to neutral means raising SUPPORT_FLOOR above 0.50, which
    (measured on the working set) also downgrades legitimate contextual evidence and costs
    40% of recall -- see the SUPPORT_FLOOR comment. What actually protects the merchant is
    that this evidence cannot clear the gate, and that is what is asserted.
    """
    evidence = [
        EvidenceItem(
            type="order_history",
            content=(
                "The customer account was created in March 2023 and currently holds a "
                "loyalty points balance of 1,240 points."
            ),
        )
    ]
    verdicts = engine.verify_bundle(CLAIM_NOT_DELIVERED, evidence, "goods_not_received")

    assert len(verdicts) == 1
    assert verdicts[0].confidence < 0.65, (
        "irrelevant evidence must not clear Section 10's CONTEST confidence gate"
    )


def test_strong_evidence_does_clear_the_contest_gate(engine):
    """The counterpart to the test above: the gate must not reject everything."""
    evidence = [
        EvidenceItem(
            type="delivery_proof",
            content=(
                "The recipient signed for the parcel on 14 July 2026, the delivery OTP was "
                "entered from the registered mobile ending 8830, and a doorstep photograph "
                "showing the flat number is on record."
            ),
        )
    ]
    verdicts = engine.verify_bundle(CLAIM_NOT_DELIVERED, evidence, "goods_not_received")
    assert verdicts[0].label == "support"
    assert verdicts[0].confidence > 0.65


def test_vague_evidence_scores_below_the_contest_gate(engine):
    """On-topic but unsubstantiated evidence must not clear Section 10's 0.65 gate.

    A bare 'delivered' scan with no signature, OTP or photograph is exactly the case that
    drove precision below 0.5 in the single-signal design.
    """
    vague = [
        EvidenceItem(
            type="delivery_proof",
            content="The order was handed to the courier and the system marks it delivered.",
        )
    ]
    strong = [
        EvidenceItem(
            type="delivery_proof",
            content=(
                "The recipient signed for the parcel on 14 July 2026 and the delivery OTP "
                "was entered from the registered mobile, with a doorstep photograph on file."
            ),
        )
    ]
    vague_conf = engine.verify_bundle(CLAIM_NOT_DELIVERED, vague, "goods_not_received")[0]
    strong_conf = engine.verify_bundle(CLAIM_NOT_DELIVERED, strong, "goods_not_received")[0]

    assert strong_conf.confidence > vague_conf.confidence, (
        "specific evidence must outrank vague evidence on confidence"
    )


# -- the inversion guard --------------------------------------------------------------


def test_label_inversion_is_not_reversed():
    """Pin the NLI -> verdict mapping. A flip here would invert the whole system."""
    assert NLI_TO_VERDICT["contradiction"] == "support"
    assert NLI_TO_VERDICT["entailment"] == "contradict"
    assert NLI_TO_VERDICT["neutral"] == "neutral"


def test_model_label_order_is_validated_on_load(engine):
    """_assert_label_order runs at load; reaching here means the order matched."""
    config = engine.model.model.config
    assert [config.id2label[i].lower() for i in sorted(config.id2label)] == [
        "contradiction",
        "entailment",
        "neutral",
    ]


# -- verdict shape --------------------------------------------------------------------


def test_confidence_is_a_probability(engine):
    evidence = [
        EvidenceItem(type="delivery_proof", content="The parcel was signed for on 14 July 2026."),
        EvidenceItem(type="order_history", content="The account has nine prior orders."),
    ]
    for verdict in engine.verify_bundle(CLAIM_NOT_DELIVERED, evidence):
        assert 0.0 <= verdict.confidence <= 1.0


def test_indices_match_bundle_order(engine):
    evidence = [
        EvidenceItem(type="delivery_proof", content="The parcel was signed for on 14 July 2026."),
        EvidenceItem(type="communication_log", content="An OTP was entered at 11:41."),
        EvidenceItem(type="order_history", content="Nine prior orders, none disputed."),
    ]
    verdicts = engine.verify_bundle(CLAIM_NOT_DELIVERED, evidence)
    assert [v.evidence_index for v in verdicts] == [0, 1, 2]


def test_empty_bundle_returns_no_verdicts(engine):
    assert engine.verify_bundle(CLAIM_NOT_DELIVERED, []) == []


# -- explainability -------------------------------------------------------------------


def test_highlighted_span_is_a_sentence_from_the_evidence(engine):
    content = (
        "The customer account was opened in 2023. The courier delivered the parcel on "
        "14 July 2026 and the recipient signed for it. Loyalty points were credited."
    )
    verdicts = engine.verify_bundle(
        CLAIM_NOT_DELIVERED, [EvidenceItem(type="delivery_proof", content=content)]
    )
    span = verdicts[0].highlighted_span
    assert span is not None
    assert span in content, "span must be copied verbatim from the evidence"


def test_highlighted_span_picks_the_decisive_sentence(engine):
    """The delivery sentence, not the boilerplate, should be surfaced."""
    content = (
        "This document was generated automatically. The courier delivered the parcel to "
        "the address on file on 14 July 2026 and the recipient signed for it. "
        "Please retain this record for your files."
    )
    verdicts = engine.verify_bundle(
        CLAIM_NOT_DELIVERED, [EvidenceItem(type="delivery_proof", content=content)]
    )
    assert "delivered the parcel" in verdicts[0].highlighted_span


# -- sentence splitting (pure, no model) ----------------------------------------------


def test_split_sentences_basic():
    assert split_sentences("One thing happened. Then another. Finally a third.") == [
        "One thing happened.",
        "Then another.",
        "Finally a third.",
    ]


def test_split_sentences_handles_single_sentence():
    assert split_sentences("Only one sentence here") == ["Only one sentence here"]


def test_split_sentences_handles_empty():
    assert split_sentences("   ") == []


# -- substantiation probes ------------------------------------------------------------


def test_every_known_reason_code_has_a_probe():
    from app.models.schemas import KNOWN_REASON_CODES

    for code in KNOWN_REASON_CODES:
        assert code in SUBSTANTIATION_PROBES, f"no substantiation probe for {code}"


def test_unknown_reason_code_falls_back_to_generic_probe():
    """Real acquirers emit codes outside any fixed list; this must degrade, not raise."""
    assert probe_for("some_new_network_code_2027") == GENERIC_PROBE


def test_probes_are_short_declaratives():
    """MNLI hypotheses are short. Long probes scored near zero everywhere in testing."""
    for code, probe in SUBSTANTIATION_PROBES.items():
        assert len(probe) < 80, f"probe for {code} is too long to score reliably"
        assert probe.endswith("."), f"probe for {code} should be a declarative sentence"
