"""Representment packet drafting for CONTEST decisions.

Two paths, same interface:

  TEMPLATE (always available, no API key, deterministic, instant)
      Assembles the packet from the supporting verdicts and their highlighted spans.
      Because the verification engine already identified WHICH sentence substantiates the
      merchant's position, the template has real material to cite -- it is not filler.

  CLAUDE (used when ANTHROPIC_API_KEY is set; added in phase 6)
      Rewrites the same facts into more fluent prose.

The template path is the default rather than a degraded fallback. An Anthropic API key
needs paid credits, and a live demo that depends on a network call to draft text is a
demo that can fail on stage. The facts cited are identical either way; only the prose
differs.

CLAUDE.md Section 3 restricts LLM usage to (a) offline dataset generation and (b) drafting
the packet AFTER the decision is made. Nothing here influences the recommendation -- this
module only ever runs on a decision that is already CONTEST.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from app.models.schemas import ClaimVerdict, Dispute

logger = logging.getLogger("recourse.packet")

# Human-readable names for evidence types, for the drafted prose.
EVIDENCE_TYPE_LABELS: dict[str, str] = {
    "delivery_proof": "proof of delivery",
    "communication_log": "customer communication records",
    "device_signal": "device and session telemetry",
    "order_history": "order and account history",
    "other": "supporting documentation",
}

# What the merchant is asserting, per reason code, in representment language.
REASON_ASSERTIONS: dict[str, str] = {
    "goods_not_received": (
        "the merchandise was delivered to the cardholder at the address on file"
    ),
    "goods_not_as_described": (
        "the merchandise supplied conformed to the description presented at the point of sale"
    ),
    "duplicate_charge": (
        "the disputed transaction is not a duplicate and corresponds to a distinct order"
    ),
    "unrecognized_transaction": (
        "the transaction was authorised by the cardholder and the benefit was received"
    ),
    "subscription_cancelled": (
        "the disputed charge was raised before any valid cancellation took effect"
    ),
    "credit_not_processed": (
        "the credit owed to the cardholder was processed and settled"
    ),
}

DEFAULT_ASSERTION = "the disputed transaction was valid and correctly charged"


def _format_inr(paise: int) -> str:
    return f"Rs {paise / 100:,.2f}"


def build_template_packet(
    dispute: Dispute,
    verdicts: Sequence[ClaimVerdict],
    rationale: str = "",
) -> str:
    """Assemble a representment packet from the supporting evidence. Deterministic."""
    supporting = [v for v in verdicts if v.label == "support"]
    assertion = REASON_ASSERTIONS.get(dispute.reason_code, DEFAULT_ASSERTION)

    lines: list[str] = [
        f"REPRESENTMENT — Dispute {dispute.dispute_id}",
        f"Transaction: {dispute.payment_id} · {_format_inr(dispute.amount)} {dispute.currency}",
        f"Reason code: {dispute.reason_code} · Phase: {dispute.phase}",
        "",
        "THE CLAIM",
        dispute.claim_text,
        "",
        "THE MERCHANT'S POSITION",
        (
            f"We respectfully contest this dispute. The evidence on file establishes that "
            f"{assertion}. The specific items relied upon are set out below."
        ),
        "",
        "EVIDENCE RELIED UPON",
    ]

    for position, verdict in enumerate(supporting, 1):
        if not (0 <= verdict.evidence_index < len(dispute.evidence_bundle)):
            continue
        item = dispute.evidence_bundle[verdict.evidence_index]
        label = EVIDENCE_TYPE_LABELS.get(item.type, item.type.replace("_", " "))

        lines.append(f"{position}. {label.title()}"
                     + (f" (ref: {item.source_ref})" if item.source_ref else ""))
        lines.append(f"   {item.content}")
        if verdict.highlighted_span:
            lines.append(f"   Most material: \"{verdict.highlighted_span.strip()}\"")
        lines.append(f"   Assessed confidence: {verdict.confidence:.0%}")
        lines.append("")

    distinct_types = {
        dispute.evidence_bundle[v.evidence_index].type
        for v in supporting
        if 0 <= v.evidence_index < len(dispute.evidence_bundle)
    }
    weakest = min((v.confidence for v in supporting), default=0.0)

    lines.extend(
        [
            "WHY THIS EVIDENCE IS SUFFICIENT",
            (
                f"The merchant's position is corroborated across {len(distinct_types)} "
                f"independent categories of evidence "
                f"({', '.join(sorted(EVIDENCE_TYPE_LABELS.get(t, t) for t in distinct_types))}), "
                f"rather than resting on a single record. Each item was assessed "
                f"individually against the specific claim raised."
            ),
            "",
            (
                f"Overall confidence is reported as {weakest:.0%}, which is the confidence of "
                f"the weakest item relied upon rather than an average. A chain of evidence is "
                f"only as strong as its weakest link, and we state it on that basis."
            ),
            "",
            "REQUESTED OUTCOME",
            (
                f"We request that the dispute be resolved in the merchant's favour and the "
                f"transaction of {_format_inr(dispute.amount)} be upheld."
            ),
        ]
    )

    if rationale:
        lines.extend(["", "AUTOMATED ASSESSMENT NOTE", rationale])

    lines.extend(
        [
            "",
            "---",
            "Drafted by Recourse for human review. Not submitted to any party until a "
            "reviewer approves it.",
        ]
    )

    return "\n".join(lines)


def generate_packet(
    dispute: Dispute,
    verdicts: Sequence[ClaimVerdict],
    rationale: str = "",
    prefer_llm: bool = True,
) -> Optional[str]:
    """Draft a representment packet for a CONTEST decision.

    Returns None when there is nothing to argue from. Falls back to the template whenever
    the LLM path is unavailable or fails: a drafting failure must never lose a decision.
    """
    if not any(v.label == "support" for v in verdicts):
        logger.info("no supporting verdicts for %s; no packet drafted", dispute.dispute_id)
        return None

    template = build_template_packet(dispute, verdicts, rationale)

    if prefer_llm:
        try:
            from app.services.packet_llm import draft_with_llm

            drafted = draft_with_llm(dispute, verdicts, template)
            if drafted:
                return drafted
        except Exception as exc:  # never let drafting break a decision
            logger.warning(
                "LLM drafting failed for %s (%s); using template", dispute.dispute_id, exc
            )

    return template


__all__ = [
    "EVIDENCE_TYPE_LABELS",
    "REASON_ASSERTIONS",
    "build_template_packet",
    "generate_packet",
]
