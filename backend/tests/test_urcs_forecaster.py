"""URCS forecaster tests (CLAUDE.md Addendum 2, Section 24).

Pure counter logic, so these need no model and run in milliseconds. The cases that matter
are the boundaries: exactly at a cap, one short of it, and just outside the window.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.schemas import Dispute, EvidenceItem
from app.services.npci_rules import NPCI_RULES
from app.services.urcs_forecaster import forecast_urcs_disposition

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def make(
    dispute_id: str,
    *,
    rail: str = "upi",
    payer_ref: str | None = "payer_001",
    raised_at: datetime = NOW,
) -> Dispute:
    return Dispute(
        dispute_id=dispute_id,
        payment_id="pay_TEST",
        phase="chargeback",
        reason_code="goods_not_received",
        claim_text="Cardholder asserts the order never arrived.",
        amount=249900,
        raised_at=raised_at,
        respond_by=raised_at + timedelta(days=21),
        evidence_bundle=[EvidenceItem(type="delivery_proof", content="Delivered.")],
        rail=rail,  # type: ignore[arg-type]
        payer_ref=payer_ref,
    )


def history(n: int, *, payer_ref: str = "payer_001", offset_days: float = 1.0) -> list[Dispute]:
    """n prior disputes from the same payer, spread inside the 30-day window."""
    return [
        make(f"disp_prior_{i}", payer_ref=payer_ref, raised_at=NOW - timedelta(days=offset_days + i))
        for i in range(n)
    ]


# -- rail gating -----------------------------------------------------------------------


@pytest.mark.parametrize("rail", ["card", "rupay"])
def test_non_upi_rails_are_not_forecast(rail):
    """URCS governs UPI only. RuPay clears through RGCS; cards through the schemes."""
    forecast = forecast_urcs_disposition(make("d1", rail=rail), history(20))
    assert forecast.predicted_disposition == "UNKNOWN"
    assert forecast.predicted_reason_code is None
    assert forecast.rgnb_re_raise_possible is False
    assert rail in forecast.explanation


def test_upi_without_a_payer_reference_abstains():
    """No payer id means the window cannot be counted. Abstain rather than assume zero."""
    forecast = forecast_urcs_disposition(make("d1", payer_ref=None), history(20))
    assert forecast.predicted_disposition == "UNKNOWN"


# -- the caps --------------------------------------------------------------------------


def test_within_both_caps_proceeds_to_merchant():
    forecast = forecast_urcs_disposition(make("d1"), history(2))
    assert forecast.predicted_disposition == "PROCEEDS_TO_MERCHANT"
    assert forecast.predicted_reason_code is None
    assert forecast.rgnb_re_raise_possible is False
    assert forecast.budget.payer_payee_disputes_30d == 2
    assert forecast.budget.payer_payee_cap_remaining == 3


def test_exactly_at_the_cd2_cap_auto_rejects():
    """The 6th dispute against the same pair is the one that trips CD2, i.e. 5 already."""
    forecast = forecast_urcs_disposition(make("d1"), history(NPCI_RULES["cap_per_payer_payee_30d"]))
    assert forecast.predicted_disposition == "AUTO_REJECT"
    assert forecast.predicted_reason_code == "CD2"
    assert forecast.rgnb_re_raise_possible is True
    assert forecast.budget.payer_payee_cap_remaining == 0


def test_one_short_of_the_cd2_cap_still_proceeds():
    """Boundary: 4 prior disputes must not trip a cap of 5."""
    forecast = forecast_urcs_disposition(
        make("d1"), history(NPCI_RULES["cap_per_payer_payee_30d"] - 1)
    )
    assert forecast.predicted_disposition == "PROCEEDS_TO_MERCHANT"


def test_over_the_cd1_cap_auto_rejects():
    forecast = forecast_urcs_disposition(make("d1"), history(NPCI_RULES["cap_per_customer_30d"]))
    assert forecast.predicted_disposition == "AUTO_REJECT"
    assert forecast.predicted_reason_code == "CD1"


def test_cd1_is_checked_before_cd2_when_both_would_trip():
    """Both caps are breached at 10+ same-merchant disputes; URCS rejects on the broader
    customer-level code. Pinned because a refactor could silently swap the branches."""
    breaching = history(NPCI_RULES["cap_per_customer_30d"] + 3)
    forecast = forecast_urcs_disposition(make("d1"), breaching)
    assert forecast.budget.customer_disputes_30d >= NPCI_RULES["cap_per_customer_30d"]
    assert forecast.budget.payer_payee_disputes_30d >= NPCI_RULES["cap_per_payer_payee_30d"]
    assert forecast.predicted_reason_code == "CD1"


# -- the window ------------------------------------------------------------------------


def test_disputes_outside_the_window_do_not_count():
    """A dispute 31 days old has aged out; five of them must not trip CD2."""
    stale = [
        make(f"disp_old_{i}", raised_at=NOW - timedelta(days=31 + i))
        for i in range(NPCI_RULES["cap_per_payer_payee_30d"] + 2)
    ]
    forecast = forecast_urcs_disposition(make("d1"), stale)
    assert forecast.predicted_disposition == "PROCEEDS_TO_MERCHANT"
    assert forecast.budget.payer_payee_disputes_30d == 0


def test_exactly_thirty_days_old_has_aged_out():
    """Half-open window: the boundary itself is outside, not inside."""
    at_edge = [
        make(f"disp_edge_{i}", raised_at=NOW - NPCI_RULES["cap_window"])
        for i in range(NPCI_RULES["cap_per_payer_payee_30d"])
    ]
    assert (
        forecast_urcs_disposition(make("d1"), at_edge).predicted_disposition
        == "PROCEEDS_TO_MERCHANT"
    )


def test_a_different_payer_does_not_consume_this_payers_budget():
    others = history(NPCI_RULES["cap_per_customer_30d"] + 2, payer_ref="payer_999")
    forecast = forecast_urcs_disposition(make("d1", payer_ref="payer_001"), others)
    assert forecast.predicted_disposition == "PROCEEDS_TO_MERCHANT"
    assert forecast.budget.customer_disputes_30d == 0


def test_the_dispute_never_counts_against_itself():
    subject = make("disp_self")
    forecast = forecast_urcs_disposition(subject, [subject, *history(3)])
    assert forecast.budget.payer_payee_disputes_30d == 3


# -- honesty guarantees ----------------------------------------------------------------


def test_auto_accept_is_never_predicted():
    """URCS auto-acceptance depends on the beneficiary bank's TCC/RET in the next
    settlement cycle, which this system cannot see. Claiming it would be a fabrication."""
    for n in range(0, NPCI_RULES["cap_per_customer_30d"] + 4):
        forecast = forecast_urcs_disposition(make("d1"), history(n))
        assert forecast.predicted_disposition != "AUTO_ACCEPT"


def test_every_forecast_carries_its_rule_provenance():
    forecast = forecast_urcs_disposition(make("d1"), history(1))
    assert forecast.rules_verified_on == NPCI_RULES["verified_on"]
    assert forecast.rules_verified_on, "verified_on must not be blank"


def test_naive_timestamps_are_handled():
    """SQLite returns naive datetimes; comparing them to aware ones would raise."""
    naive = make("d1", raised_at=NOW.replace(tzinfo=None))
    forecast = forecast_urcs_disposition(naive, history(2))
    assert forecast.predicted_disposition == "PROCEEDS_TO_MERCHANT"


# -- integration with the decision path (Addendum 2, Section 25 acceptance test) --------


def test_aggregate_short_circuits_to_no_action_on_a_cap_breach():
    """A cap breach must bypass Section 10 entirely: no amount of evidence quality changes
    what the merchant should do, which is nothing."""
    from app.models.schemas import ClaimVerdict
    from app.services.decision_aggregator import aggregate

    dispute = make("disp_breach")
    # Evidence strong enough that Section 10 alone would say CONTEST.
    verdicts = [
        ClaimVerdict(evidence_index=0, label="support", confidence=0.95),
        ClaimVerdict(evidence_index=1, label="support", confidence=0.92),
    ]
    evidence = [
        EvidenceItem(type="delivery_proof", content="Signed for, OTP captured."),
        EvidenceItem(type="communication_log", content="Customer confirmed receipt."),
    ]

    without_caps = aggregate(verdicts, evidence, threshold=0.5)
    assert without_caps.recommendation == "CONTEST", "precondition: this bundle is a CONTEST"

    breaching = history(NPCI_RULES["cap_per_payer_payee_30d"])
    result = aggregate(verdicts, evidence, dispute, breaching)

    assert result.recommendation == "NO_ACTION_NEEDED"
    assert result.confidence == 1.0
    assert result.urcs_forecast is not None
    assert result.urcs_forecast.predicted_reason_code == "CD2"
    assert result.urcs_forecast.rgnb_re_raise_possible is True
    assert "RGNB" in result.rationale


def test_aggregate_without_a_dispute_skips_urcs():
    """An explicit threshold still applies when no dispute is available for URCS."""
    from app.models.schemas import ClaimVerdict
    from app.services.decision_aggregator import aggregate

    verdicts = [ClaimVerdict(evidence_index=0, label="contradict", confidence=0.9)]
    evidence = [EvidenceItem(type="delivery_proof", content="Never shipped.")]
    result = aggregate(verdicts, evidence, threshold=0.5)
    assert result.recommendation == "ACCEPT"
    assert result.urcs_forecast is None


def test_card_rail_disputes_still_reach_section_ten():
    """The short-circuit must not swallow non-UPI cases."""
    from app.models.schemas import ClaimVerdict
    from app.services.decision_aggregator import aggregate

    verdicts = [ClaimVerdict(evidence_index=0, label="contradict", confidence=0.9)]
    evidence = [EvidenceItem(type="delivery_proof", content="Never shipped.")]
    result = aggregate(
        verdicts,
        evidence,
        make("d1", rail="card"),
        history(20),
        threshold=0.5,
    )
    assert result.recommendation == "ACCEPT"
    assert result.urcs_forecast is not None
    assert result.urcs_forecast.predicted_disposition == "UNKNOWN"
