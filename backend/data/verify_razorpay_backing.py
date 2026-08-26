"""Run CLAUDE.md Section 13 phase-2 acceptance test against the live test-mode API.

The acceptance criterion is: "Can create a test order, fetch it back, and confirm a
synthetic dispute's payment_id resolves to it."

This script checks all three parts and reports each independently, because the third has a
genuine external dependency: Razorpay exposes no API to create a payment, so a real
`pay_...` id only exists once someone completes a Checkout. Parts 1 and 2 are fully
automatic; part 3 passes once any backing payment link has been paid with a test card.

Usage:
    python data/verify_razorpay_backing.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.razorpay_client import (  # noqa: E402
    RazorpayClient,
    RazorpayError,
    is_placeholder_payment_id,
)

WORKING_SET = BACKEND_ROOT / "data" / "synthetic_disputes.json"
BACKING_MAP = BACKEND_ROOT / "data" / "razorpay_backing.json"

PASS = "PASS"
FAIL = "FAIL"
PENDING = "PENDING"


def main() -> int:
    if not BACKING_MAP.is_file():
        print("No backing map found. Run data/backfill_razorpay_backing.py first.")
        return 1

    backing = json.loads(BACKING_MAP.read_text(encoding="utf-8"))
    disputes = {d["dispute_id"]: d for d in json.loads(WORKING_SET.read_text(encoding="utf-8"))}
    client = RazorpayClient()

    print("Phase 2 acceptance test (CLAUDE.md Section 13)\n")
    results: list[tuple[str, str, str]] = []

    # -- 1. a real test-mode order exists ---------------------------------
    with_orders = {d: e for d, e in backing.items() if e.get("order_id")}
    results.append(
        (
            "1. create a real test-mode order",
            PASS if with_orders else FAIL,
            f"{len(with_orders)} order(s) created via client.order.create",
        )
    )
    if not with_orders:
        _report(results)
        return 1

    # -- 2. it fetches back from the live API -----------------------------
    sample_id, sample = next(iter(with_orders.items()))
    try:
        fetched = client.fetch_order(sample["order_id"])
        round_trips = fetched.get("id") == sample["order_id"]
        detail = (
            f"{sample['order_id']} -> status={fetched.get('status')}, "
            f"amount={fetched.get('amount')}, receipt={fetched.get('receipt')}"
        )
    except RazorpayError as exc:
        round_trips, detail = False, str(exc)
    results.append(("2. fetch that order back", PASS if round_trips else FAIL, detail))

    # -- 3. a dispute's payment_id resolves to a real payment -------------
    real_backed = {
        d: e
        for d, e in backing.items()
        if e.get("payment_id") and not is_placeholder_payment_id(e["payment_id"])
    }
    if real_backed:
        dispute_id, entry = next(iter(real_backed.items()))
        try:
            payment = client.fetch_payment(entry["payment_id"])
            resolves = bool(payment) and payment.get("id") == entry["payment_id"]
            on_record = disputes.get(dispute_id, {}).get("payment_id")
            detail = (
                f"{dispute_id}.payment_id={on_record} -> "
                f"status={payment.get('status')}, amount={payment.get('amount')}"
            )
            if on_record != entry["payment_id"]:
                resolves = False
                detail += "  (MISMATCH: dispute record not updated)"
        except RazorpayError as exc:
            resolves, detail = False, str(exc)
        results.append(
            ("3. dispute payment_id resolves to a real payment", PASS if resolves else FAIL, detail)
        )
    else:
        unpaid = [
            (d, e["payment_link_url"])
            for d, e in backing.items()
            if e.get("payment_link_url") and not e.get("payment_id")
        ]
        detail = (
            "No real payment yet. Razorpay has no API to create one -- pay any link below "
            "with test card 4111 1111 1111 1111 (any future expiry, any CVV), then re-run "
            "backfill_razorpay_backing.py --refresh-payments-only."
        )
        results.append(("3. dispute payment_id resolves to a real payment", PENDING, detail))
        for dispute_id, url in unpaid[:5]:
            print(f"    pay to complete: {dispute_id}  {url}")
        print()

    _report(results)
    return 0 if all(status != FAIL for _, status, _ in results) else 1


def _report(results: list[tuple[str, str, str]]) -> None:
    width = max(len(name) for name, _, _ in results)
    for name, status, detail in results:
        print(f"  [{status:^7}] {name.ljust(width)}")
        print(f"            {detail}")
    print()
    if any(s == PENDING for _, s, _ in results):
        print("  Overall: parts 1-2 pass; part 3 pending a completed test checkout.")
    elif all(s == PASS for _, s, _ in results):
        print("  Overall: PASS")
    else:
        print("  Overall: FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
