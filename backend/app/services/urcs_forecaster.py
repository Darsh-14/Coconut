"""Forecast what NPCI's URCS will do with a UPI chargeback, before the merchant acts.

THE IDEA
--------
Every commercial chargeback-AI product is architected around card-network mechanics --
Visa VAMP, Mastercard ECM, card reason-code taxonomies, and a human adjudicator at the
network. India's UPI rails work differently in a way that is mechanical, not cosmetic: a
meaningful share of dispute outcomes is decided by a deterministic rules engine (URCS),
not by human judgement.

Deterministic means *predictable exactly, in advance* -- not statistically. So this module
is a pure function over counters. No model, no LLM, no inference. It reads the payer's
dispute history, compares it against the caps in npci_rules.py, and reports whether URCS
is expected to auto-reject the chargeback on the merchant's behalf.

If it will, the merchant should spend nothing defending it. That is the whole point.

WHAT THIS DELIBERATELY DOES NOT CLAIM
-------------------------------------
`AUTO_ACCEPT` is never returned. URCS's auto-acceptance branch (UPI OC No. 213 FY 2024-25)
turns on the beneficiary bank's TCC or RET in the settlement cycle *following* chargeback
initiation -- state this system has no visibility into whatsoever. Returning
PROCEEDS_TO_MERCHANT and saying so plainly in the explanation is the honest output. A
fuller-looking enum here would be a lie with four branches instead of three.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from app.models.schemas import Dispute, DisputeBudget, URCSForecast
from app.services.npci_rules import NPCI_RULES


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; comparing those to aware ones raises."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _merchant_key(dispute: Dispute) -> str:
    """The payee side of the payer-payee pair.

    This is a single-merchant demo, so every dispute in the system belongs to the same
    payee. Keying on a constant keeps CD2 semantically correct here and leaves one obvious
    place to swap in a real payee VPA when there is more than one merchant.
    """
    return "merchant"


def forecast_urcs_disposition(
    dispute: Dispute,
    dispute_history: Iterable[Dispute],
) -> URCSForecast:
    """Predict URCS's disposition for `dispute`, given the payer's recent disputes.

    `dispute_history` is every other dispute the system knows about; this function does the
    windowing itself so callers cannot get the window wrong.
    """
    window = NPCI_RULES["cap_window"]
    customer_cap = NPCI_RULES["cap_per_customer_30d"]
    pair_cap = NPCI_RULES["cap_per_payer_payee_30d"]
    verified_on = NPCI_RULES["verified_on"]

    raised_at = _as_utc(dispute.raised_at)
    window_start = raised_at - window
    payer_ref = dispute.payer_ref or ""

    # --- rail gate --------------------------------------------------------------------
    # URCS governs UPI only. RuPay disputes clear through NPCI's RGCS with different
    # timelines and codes; card disputes clear through the schemes. Guessing across rails
    # would be worse than abstaining.
    if dispute.rail != "upi" or not payer_ref:
        reason = (
            "no payer reference is recorded, so the payer's dispute history cannot be counted"
            if dispute.rail == "upi"
            else f"this dispute settles on the {dispute.rail} rail, which URCS does not govern"
        )
        return URCSForecast(
            predicted_disposition="UNKNOWN",
            predicted_reason_code=None,
            rgnb_re_raise_possible=False,
            budget=DisputeBudget(
                payer_ref=payer_ref,
                customer_disputes_30d=0,
                payer_payee_disputes_30d=0,
                customer_cap_remaining=customer_cap,
                payer_payee_cap_remaining=pair_cap,
                window_resets_at=raised_at + window,
            ),
            explanation=f"NPCI's UPI dispute caps do not apply: {reason}.",
            rules_verified_on=verified_on,
        )

    # --- count the window -------------------------------------------------------------
    merchant = _merchant_key(dispute)
    customer_count = 0
    pair_count = 0

    for other in dispute_history:
        if other.dispute_id == dispute.dispute_id:
            continue
        if other.rail != "upi" or other.payer_ref != payer_ref:
            continue
        other_raised = _as_utc(other.raised_at)
        # Half-open window: a dispute exactly 30 days old has aged out.
        if not (window_start < other_raised <= raised_at):
            continue
        customer_count += 1
        if _merchant_key(other) == merchant:
            pair_count += 1

    budget = DisputeBudget(
        payer_ref=payer_ref,
        customer_disputes_30d=customer_count,
        payer_payee_disputes_30d=pair_count,
        customer_cap_remaining=max(0, customer_cap - customer_count),
        payer_payee_cap_remaining=max(0, pair_cap - pair_count),
        window_resets_at=raised_at + window,
    )

    # --- apply the caps ---------------------------------------------------------------
    # CD1 is checked first: it is the broader cap, and when both trip URCS rejects on the
    # customer-level code. Order is asserted by a test so a refactor cannot silently swap it.
    disposition: str
    code: Optional[str]

    if customer_count >= customer_cap:
        disposition, code = "AUTO_REJECT", "CD1"
        explanation = (
            f"This payer has raised {customer_count} of a permitted {customer_cap} disputes "
            f"across all merchants in the last 30 days; URCS is expected to auto-reject "
            f"under CD1."
        )
    elif pair_count >= pair_cap:
        disposition, code = "AUTO_REJECT", "CD2"
        explanation = (
            f"This payer has raised {pair_count} of a permitted {pair_cap} disputes against "
            f"this merchant in the last 30 days; URCS is expected to auto-reject under CD2."
        )
    else:
        disposition, code = "PROCEEDS_TO_MERCHANT", None
        explanation = (
            f"Within NPCI's caps ({customer_count}/{customer_cap} for this payer, "
            f"{pair_count}/{pair_cap} against this merchant), so URCS passes this to the "
            f"merchant to answer. Whether it is instead auto-accepted depends on the "
            f"beneficiary bank's TCC or return in the next settlement cycle, which is not "
            f"visible from here."
        )

    return URCSForecast(
        predicted_disposition=disposition,  # type: ignore[arg-type]
        predicted_reason_code=code,
        rgnb_re_raise_possible=(
            disposition == "AUTO_REJECT" and bool(NPCI_RULES["rgnb_available"])
        ),
        budget=budget,
        explanation=explanation,
        rules_verified_on=verified_on,
    )


__all__ = ["forecast_urcs_disposition"]
