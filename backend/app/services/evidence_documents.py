"""Render an evidence item as the record its `source_ref` implies.

WHY THIS EXISTS
---------------
Every evidence item carries a `source_ref` -- `pod_ORD_88992`, `zendesk_ticket_122019`,
`settlement_20260703.csv`. Before this, those were dangling strings: 551 references across
the two datasets, none of which resolved to anything a merchant could open. A reviewer
clicking one got nothing, which is precisely what makes a system read as a mock-up.

THE HONESTY CONSTRAINT -- READ THIS BEFORE EXTENDING
-----------------------------------------------------
This module renders. It does NOT author.

The evidence `content` is the substance, and it is reproduced verbatim and in full. What
this adds is only provenance framing: which system of record the reference belongs to,
which dispute and payment it is attached to, and a hash tying the rendered document to the
exact bytes the verification engine scored.

Inventing extra detail here -- a courier name, a tracking scan, a signature -- would be
fabricating evidence in a system whose entire argument is that it does not overstate what
the evidence supports. A document that says more than the evidence said would let a
merchant contest on a fact the model never saw. So: no new claims, ever, and no LLM in
this path.

The `content_hash` is the check on that promise. It is the SHA-256 of the content string
the engine scored, so a reviewer can confirm the document and the verdict describe the
same text.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from app.models.schemas import (
    Dispute,
    EvidenceDocument,
    EvidenceField,
    EvidenceItem,
)

# --- what kind of record this is --------------------------------------------------------
# `kind` follows the DECLARED evidence type, never the reference string.
#
# This is deliberate. The evidence type is the field the decision rule counts (Section 10
# requires >= 2 distinct supporting types), and it is what the case page shows next to
# each item. If `kind` were inferred from the reference instead, a bundle item declared
# `order_history` whose ref happens to read `rider_cash_recon_...` would open a document
# headed "Delivery record" -- the document and the case page disagreeing about the same
# item, which reads as a bug and undermines exactly the audit property this view exists to
# provide. So the type decides the kind, and the reference only refines the label naming
# the system it came from.

KIND_FOR_TYPE: dict[str, str] = {
    "delivery_proof": "proof_of_delivery",
    "communication_log": "support_transcript",
    "device_signal": "device_report",
    "order_history": "order_record",
    "other": "generic",
}

# Default system label per kind, used when the reference tells us nothing more specific.
DEFAULT_SYSTEM: dict[str, str] = {
    "proof_of_delivery": "Delivery evidence record",
    "support_transcript": "Customer communication log",
    "device_report": "Device and session signal",
    "order_record": "Order management system",
    "generic": "Merchant record",
}

# Tokens that identify the system of record, matched anywhere in the reference rather than
# only at the start -- real refs look like `delhivery_track_DL4471902` and `return_pod_44`,
# where the informative token is not the first one. Longest token wins, so `return_pod`
# beats `pod`. These refine the label only; they can never change the kind.
SYSTEM_TOKENS: dict[str, str] = {
    "pod": "Courier proof-of-delivery record",
    "return_pod": "Courier return-to-origin record",
    "epod": "Courier proof-of-delivery record",
    "track": "Courier tracking system",
    "courier": "Courier tracking system",
    "gps": "Courier GPS trace",
    "wms": "Warehouse management system",
    "dispatch": "Warehouse dispatch record",
    "packlist": "Warehouse packing list",
    "locker": "Parcel locker system",
    "weighbridge": "Weighbridge log",
    "cash_recon": "Cash-on-delivery reconciliation",
    "zendesk": "Zendesk support desk",
    "ticket": "Customer support desk",
    "chat": "Live chat transcript",
    "sms": "SMS gateway log",
    "esp": "Email service provider log",
    "email": "Email service provider log",
    "call": "Call recording index",
    "incident": "Incident tracker",
    "consent": "Consent record",
    "oms": "Order management system",
    "order": "Order management system",
    "invoice": "Invoicing system",
    "ledger": "Accounting ledger",
    "settlement": "Settlement export",
    "refund": "Refund ledger",
    "billing": "Billing system",
    "mandate": "Mandate registry",
    "sub": "Subscription registry",
    "usage": "Usage metering",
    "serial": "Serial number registry",
    "job": "Service job record",
    "fp": "Device fingerprint service",
    "device": "Device fingerprint service",
    "risk_engine": "Risk engine output",
    "velocity": "Velocity rule output",
    "acs": "3-D Secure ACS log",
    "auth": "Authentication log",
    "biometric": "Biometric authentication log",
    "telemetry": "Client telemetry",
    "address_graph": "Address graph cluster",
    "listing": "Storefront content snapshot",
    "product_page": "Storefront content snapshot",
    "policy_snapshot": "Policy snapshot",
    "terms": "Terms snapshot",
}

_TOKEN_SPLIT = re.compile(r"[_\-.]+")


def classify(source_ref: Optional[str], evidence_type: str) -> tuple[str, str]:
    """(kind, system-of-record label).

    The kind comes from the declared evidence type -- see the note above. The reference is
    consulted only to name the system, and when it says nothing recognisable the kind's
    default label is used, which is still accurate, just less specific.
    """
    kind = KIND_FOR_TYPE.get(evidence_type, "generic")

    ref = (source_ref or "").lower()
    tokens = {t for t in _TOKEN_SPLIT.split(ref) if t}
    # Also consider adjacent token pairs, so `cash_recon` and `return_pod` can match.
    parts = [t for t in _TOKEN_SPLIT.split(ref) if t]
    tokens |= {f"{a}_{b}" for a, b in zip(parts, parts[1:])}

    best = ""
    for token in tokens:
        if token in SYSTEM_TOKENS and len(token) > len(best):
            best = token

    system = SYSTEM_TOKENS[best] if best else DEFAULT_SYSTEM[kind]
    return kind, system


def content_hash(content: str) -> str:
    """SHA-256 of the exact text the verification engine scored."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def humanise_ref(source_ref: Optional[str]) -> str:
    """`pod_ORD_88992` -> `Pod ORD 88992`. Used as the document title only."""
    if not source_ref:
        return "Untitled record"
    stem = source_ref.rsplit(".", 1)[0] if "." in source_ref else source_ref
    parts = [p for p in _TOKEN_SPLIT.split(stem) if p]
    return " ".join(p if p.isupper() or p.isdigit() else p.capitalize() for p in parts)


def body_format_for(source_ref: Optional[str], evidence_type: str) -> str:
    """How to lay the body out. Independent of `kind`: a settlement CSV attached as
    order_history is still an order record, it just renders as a table."""
    ref = (source_ref or "").lower()
    if ref.endswith(".csv"):
        return "csv"
    if evidence_type == "communication_log":
        return "transcript"
    return "text"


SYNTHETIC_NOTICE = (
    "Synthetic record. The statement in this record is reproduced verbatim from the "
    "dispute's evidence bundle and is the exact text the verification engine scored -- "
    "confirm it with the content hash. No detail has been added to it."
)


def render_document(
    dispute: Dispute, index: int, item: EvidenceItem
) -> EvidenceDocument:
    """Build the openable record for one evidence item.

    `index` is the item's position in the bundle, which is also the key `ClaimVerdict`
    joins on, so a caller can line the document up against its verdict.
    """
    kind, system = classify(item.source_ref, item.type)

    fields = [
        EvidenceField(label="Reference", value=item.source_ref or "(none recorded)"),
        EvidenceField(label="System of record", value=system),
        EvidenceField(label="Evidence type", value=item.type.replace("_", " ")),
        EvidenceField(label="Attached to dispute", value=dispute.dispute_id),
        EvidenceField(label="Backing payment", value=dispute.payment_id),
        EvidenceField(
            label="Dispute raised", value=dispute.raised_at.strftime("%d %b %Y, %H:%M UTC")
        ),
        EvidenceField(label="Content hash (SHA-256)", value=content_hash(item.content)),
    ]

    return EvidenceDocument(
        dispute_id=dispute.dispute_id,
        evidence_index=index,
        source_ref=item.source_ref,
        kind=kind,  # type: ignore[arg-type]
        title=humanise_ref(item.source_ref),
        system_of_record=system,
        fields=fields,
        body=item.content,
        body_format=body_format_for(item.source_ref, item.type),  # type: ignore[arg-type]
        content_hash=content_hash(item.content),
        synthetic_notice=SYNTHETIC_NOTICE,
    )


__all__ = [
    "SYNTHETIC_NOTICE",
    "classify",
    "content_hash",
    "humanise_ref",
    "render_document",
]
