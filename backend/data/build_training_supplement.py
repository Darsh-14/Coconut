"""Write 24 authored contrast cases for training only; no API, inference or model fitting.

Twelve scenarios each have two different evidence bundles. Labels are scenario assumptions,
not bank outcomes. Related pairs must stay in training, never become evaluation samples.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.models.schemas import Dispute  # noqa: E402

# reason, claim, first evidence type, second evidence type, supported bundle, adverse bundle
SCENARIOS = [
    ("goods_not_received", "Issuer reports that the parcel remained in a collection locker and was never received.", "delivery_proof", "communication_log",
     ("Locker access log links the order's collection code to a completed door-open and parcel-removal event.", "The purchaser's authenticated chat confirms collecting this parcel from the locker that afternoon."),
     ("The locker record ends with allocation of a compartment; there is no collection or door-open event.", "The carrier confirms that the parcel was returned to the warehouse after the collection period expired.")),
    ("goods_not_received", "The cardholder disputes receipt of a replacement sent after the first shipment was damaged.", "delivery_proof", "communication_log",
     ("Replacement tracking identifies the replacement order and records signed delivery at the updated address.", "The customer identifies the replacement serial number in a message confirming that it arrived undamaged."),
     ("The delivery certificate belongs to the damaged original shipment and does not identify a replacement.", "The warehouse confirms that the promised replacement was never dispatched.")),
    ("goods_not_received", "The customer alleges that only one of two separately shipped cartons arrived.", "delivery_proof", "order_history",
     ("Two carrier records show separate carton identifiers, each collected using the recipient's one-time code.", "The dispatch manifest maps both carton identifiers to every line item in this order with matching weights."),
     ("Only the first carton has a delivery scan; the second was declared lost in transit.", "The manifest places the disputed item exclusively in the missing second carton.")),
    ("duplicate_charge", "Issuer reports that a reservation deposit and final invoice charged twice for the same service.", "order_history", "communication_log",
     ("The final settled invoice explicitly deducts the earlier deposit; the two net captures sum to the agreed price.", "The customer acknowledged the itemised deposit deduction before paying the outstanding balance."),
     ("The deposit settled successfully, but the final capture charges the entire service price without a deposit credit.", "The merchant's billing team confirms that the deposit was mistakenly omitted from the final calculation.")),
    ("duplicate_charge", "The cardholder reports two settled charges after checkout displayed a timeout.", "order_history", "other",
     ("The gateway export identifies one settled capture and one failed authorization with no settlement entry.", "The settlement reconciliation lists this order exactly once and matches the single final invoice."),
     ("Two distinct capture identifiers for the same order appear in the settlement export for the full amount.", "The reconciliation exception records a repeated checkout retry without an idempotency key and no reversal.")),
    ("duplicate_charge", "Issuer describes a second instalment as a duplicate of the first payment.", "order_history", "communication_log",
     ("The signed payment schedule lists two separate instalment dates and each capture matches one instalment.", "Before purchase, the customer accepted the two-instalment total in the authenticated order conversation."),
     ("Both settled captures are assigned to instalment one; instalment two is still unpaid in the ledger.", "Billing support confirms that the first instalment was processed twice and that no refund was issued.")),
    ("goods_not_received", "Issuer disputes an order redirected to a staffed collection counter.", "delivery_proof", "communication_log",
     ("The counter's release record includes the order number, recipient signature and matching collection code.", "The buyer requested collection at this counter and subsequently confirmed taking the parcel home."),
     ("The release record shows a different order number and a different collection code from the disputed order.", "The counter supervisor confirms that the customer's parcel was still on the shelf when the dispute was filed.")),
    ("goods_not_received", "The customer says a split digital licence order was never activated on their account.", "delivery_proof", "communication_log",
     ("Entitlement logs map both purchased licence identifiers to the authenticated purchaser account and record activation.", "The account's support ticket lists both licence identifiers and confirms successful access before the claim."),
     ("Entitlement logs show both licence allocations failed and no active licence exists for the purchaser account.", "Support confirmed an activation outage affecting this order and promised a refund that remains unprocessed.")),
    ("duplicate_charge", "Issuer reports duplicate billing for a seat upgrade and the original booking.", "order_history", "communication_log",
     ("The upgrade invoice charges only the documented fare difference and references the original booking payment.", "The passenger accepted the incremental upgrade amount in the booking portal before authorizing payment."),
     ("The upgrade captured the full upgraded fare while retaining the original fare with no credit or reversal.", "Support confirms that the upgrade should have charged only the fare difference and acknowledges the overcharge.")),
    ("goods_not_received", "The cardholder says a scheduled furniture delivery was signed by someone at the wrong building.", "delivery_proof", "communication_log",
     ("Delivery evidence contains the booked building and unit, the customer's collection code and a signed installation sheet.", "The purchaser confirmed installation in the same unit and requested care instructions for the delivered furniture."),
     ("The installation sheet identifies an adjacent building and an unrelated unit; there is no recipient code.", "The delivery team acknowledged the address mismatch and has not recovered or redelivered the furniture.")),
    ("duplicate_charge", "Issuer disputes a second charge when a single order was moved to another pickup branch.", "order_history", "other",
     ("The first branch's authorization was voided before settlement; only the receiving branch captured the order amount.", "The reconciled settlement file links one net payment to the branch-transfer order with no second credit."),
     ("Both branches captured the complete order amount against the same branch-transfer reference.", "The reconciliation report confirms two settled credits and no refund or void for either payment.")),
    ("goods_not_received", "The customer disputes a delivery that the courier marked complete after a failed access attempt.", "delivery_proof", "communication_log",
     ("A subsequent delivery attempt is recorded with a verified recipient code and a photo at the order's address.", "The customer's message explicitly confirms receiving this order on the second attempt."),
     ("The final event records failed building access; the delivered status was a manual scan without recipient verification.", "The courier's investigation confirms the parcel remained in the vehicle and was returned to the depot.")),
]


def build_records() -> list[dict]:
    records = []
    for index, (reason, claim, type_a, type_b, support, adverse) in enumerate(SCENARIOS):
        for variant, evidence in enumerate((support, adverse)):
            number = index * 2 + variant
            value = {
                "dispute_id": f"disp_synthetic_supplement_v1_{number:03d}",
                "payment_id": f"pay_PENDING_supplement_{number:03d}",
                "phase": "chargeback", "rail": "card", "reason_code": reason,
                "claim_text": claim, "amount": 249900, "currency": "INR",
                "raised_at": "2026-01-01T00:00:00Z", "respond_by": "2026-01-15T00:00:00Z",
                "ground_truth_label": "contest_win" if variant == 0 else "contest_loss",
                "evidence_bundle": [
                    {"type": type_a, "content": evidence[0]},
                    {"type": type_b, "content": evidence[1]},
                ],
            }
            records.append(Dispute.model_validate(value).model_dump(mode="json"))
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/training_supplement.json")
    args = parser.parse_args()
    rows = build_records()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create avoids overwriting someone else's authored cases.
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"Wrote {len(rows)} training-only cases across {len(SCENARIOS)} paired scenarios: {args.output}")
