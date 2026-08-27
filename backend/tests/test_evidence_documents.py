"""Rendering an evidence item as an openable record.

The load-bearing property here is that the renderer does not author. Every other test in
this file is secondary to that one.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from app.models.schemas import Dispute, EvidenceItem
from app.services.evidence_documents import (
    classify,
    content_hash,
    humanise_ref,
    render_document,
)


def make_dispute(**overrides) -> Dispute:
    base = dict(
        dispute_id="disp_synthetic_0001",
        payment_id="pay_TUSjwsBKtOQpWj",
        phase="chargeback",
        reason_code="goods_not_received",
        claim_text="Cardholder states the goods never arrived.",
        amount=249900,
        raised_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        respond_by=datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc),
        evidence_bundle=[
            EvidenceItem(
                type="delivery_proof",
                content="Courier scan recorded delivery at the registered address.",
                source_ref="pod_ORD_88992",
            )
        ],
    )
    base.update(overrides)
    return Dispute(**base)


# -- the promise -------------------------------------------------------------------------


def test_body_is_the_evidence_content_verbatim():
    """The renderer must not add, trim, or reword a single character.

    A document that says more than the evidence said would let a merchant contest on a
    fact the model never scored. This is the whole constraint of the module.
    """
    content = "Courier scan recorded delivery at the registered address."
    dispute = make_dispute()
    doc = render_document(dispute, 0, dispute.evidence_bundle[0])
    assert doc.body == content


def test_content_hash_matches_the_scored_text():
    dispute = make_dispute()
    item = dispute.evidence_bundle[0]
    doc = render_document(dispute, 0, item)
    assert doc.content_hash == hashlib.sha256(item.content.encode("utf-8")).hexdigest()


def test_hash_changes_when_the_evidence_changes():
    """Otherwise the hash could not detect a document drifting from its verdict."""
    assert content_hash("a") != content_hash("b")


def test_every_document_carries_the_synthetic_notice():
    dispute = make_dispute()
    doc = render_document(dispute, 0, dispute.evidence_bundle[0])
    assert "Synthetic record" in doc.synthetic_notice


# -- classification ------------------------------------------------------------------------
# The load-bearing rule: `kind` follows the DECLARED evidence type, never the reference.
# Otherwise a document could contradict the type shown on the case page and counted by the
# Section 10 distinct-types rule.


@pytest.mark.parametrize(
    "evidence_type, expected_kind",
    [
        ("delivery_proof", "proof_of_delivery"),
        ("communication_log", "support_transcript"),
        ("device_signal", "device_report"),
        ("order_history", "order_record"),
        ("other", "generic"),
    ],
)
def test_kind_is_decided_by_the_declared_evidence_type(evidence_type, expected_kind):
    assert classify("anything_at_all_123", evidence_type)[0] == expected_kind


@pytest.mark.parametrize(
    "ref",
    [
        "rider_cash_recon_44120",  # reads like delivery
        "pod_ORD_88992",  # reads like delivery
        "zendesk_ticket_122019",  # reads like a conversation
        "fp_device_56661",  # reads like a device signal
    ],
)
def test_a_suggestive_reference_cannot_override_the_declared_type(ref):
    """These refs all *sound* like another category. The declared type still wins."""
    assert classify(ref, "order_history")[0] == "order_record"


@pytest.mark.parametrize(
    "ref, expected_system",
    [
        ("pod_ORD_88992", "Courier proof-of-delivery record"),
        ("return_pod_4471", "Courier return-to-origin record"),
        ("delhivery_track_DL4471902", "Courier tracking system"),
        ("rider_cash_recon_44120", "Cash-on-delivery reconciliation"),
        ("zendesk_ticket_122019", "Zendesk support desk"),
        ("esp_message_9944120", "Email service provider log"),
        ("oms_ord_44881", "Order management system"),
        ("settlement_20260703.csv", "Settlement export"),
        ("fp_device_56661", "Device fingerprint service"),
        ("risk_engine_88120", "Risk engine output"),
        ("listing_60091.html", "Storefront content snapshot"),
    ],
)
def test_the_reference_names_the_system_of_record(ref, expected_system):
    assert classify(ref, "other")[1] == expected_system


def test_informative_token_is_found_anywhere_in_the_reference():
    """Real refs put the useful token in the middle: `delhivery_track_DL4471902`."""
    assert classify("delhivery_track_DL4471902", "delivery_proof")[1] == "Courier tracking system"
    assert classify("acme_wms_dispatch_9", "delivery_proof")[1] == "Warehouse dispatch record"


def test_longer_token_wins_over_a_shorter_one_it_contains():
    assert classify("return_pod_881", "delivery_proof")[1] == "Courier return-to-origin record"
    assert classify("pod_881", "delivery_proof")[1] == "Courier proof-of-delivery record"


def test_an_unrecognised_reference_falls_back_to_an_accurate_generic_label():
    """Less specific, but never wrong -- and the kind is still correct."""
    kind, system = classify("something_nobody_anticipated_1234", "delivery_proof")
    assert kind == "proof_of_delivery"
    assert system == "Delivery evidence record"


def test_a_missing_reference_still_renders():
    dispute = make_dispute(
        evidence_bundle=[EvidenceItem(type="other", content="A note.", source_ref=None)]
    )
    doc = render_document(dispute, 0, dispute.evidence_bundle[0])
    assert doc.kind == "generic"
    assert "(none recorded)" in [f.value for f in doc.fields]


# -- presentation --------------------------------------------------------------------------


def test_titles_keep_identifiers_legible():
    assert humanise_ref("pod_ORD_88992") == "Pod ORD 88992"
    assert humanise_ref("settlement_20260703.csv") == "Settlement 20260703"
    assert humanise_ref(None) == "Untitled record"


def test_provenance_fields_tie_the_document_to_its_dispute():
    dispute = make_dispute()
    doc = render_document(dispute, 0, dispute.evidence_bundle[0])
    values = {f.label: f.value for f in doc.fields}
    assert values["Attached to dispute"] == "disp_synthetic_0001"
    assert values["Backing payment"] == "pay_TUSjwsBKtOQpWj"
    assert values["Reference"] == "pod_ORD_88992"
    assert values["Content hash (SHA-256)"] == doc.content_hash


def test_a_csv_reference_renders_as_a_table_without_changing_its_kind():
    """Layout and category are separate concerns: a settlement CSV filed as order history
    is still an order record, it just lays out as a table."""
    dispute = make_dispute(
        evidence_bundle=[
            EvidenceItem(
                type="order_history",
                content="date,amount\n2026-07-03,2499",
                source_ref="settlement_20260703.csv",
            )
        ]
    )
    doc = render_document(dispute, 0, dispute.evidence_bundle[0])
    assert doc.body_format == "csv"
    assert doc.kind == "order_record"


def test_communication_logs_lay_out_as_transcripts():
    dispute = make_dispute(
        evidence_bundle=[
            EvidenceItem(type="communication_log", content="Hi", source_ref="chat_1")
        ]
    )
    assert render_document(dispute, 0, dispute.evidence_bundle[0]).body_format == "transcript"


def test_evidence_index_is_carried_so_a_verdict_can_be_joined():
    dispute = make_dispute()
    doc = render_document(dispute, 0, dispute.evidence_bundle[0])
    assert doc.evidence_index == 0
