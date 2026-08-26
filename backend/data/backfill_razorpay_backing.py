"""Back a subset of synthetic disputes with real test-mode Razorpay artefacts (Section 7).

What is genuinely possible over the Razorpay API, and what is not:

  Orders   CAN be created over the API. `client.order.create(...)` returns a real
           test-mode order with a real `order_id` that fetches back. This script creates
           them and records them.

  Payments CANNOT be fabricated over the API. A payment only comes into existence when
           someone completes a Checkout interaction against an order; Razorpay exposes no
           endpoint to mint one. So `payment_id` cannot be backfilled purely by a script.

This script therefore does two things:

  1. Creates a real test-mode order per selected dispute, fetches it back to prove it
     resolves, and records the mapping in data/razorpay_backing.json.
  2. Checks each order for a real payment (via order.payments). If someone has completed a
     test checkout for that order, the real `pay_...` id is written into the dispute's
     `payment_id` field, replacing the `pay_PENDING_...` placeholder.

Run it again after completing test checkouts to pick up newly-real payment ids.

The mapping is kept in a separate file rather than added to the Dispute records because
Section 6 fixes the Dispute schema and Section 9 forbids extra fields on those records.

Usage:
    python data/backfill_razorpay_backing.py --limit 25
    python data/backfill_razorpay_backing.py --limit 25 --refresh-payments-only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.razorpay_client import (  # noqa: E402
    RazorpayClient,
    RazorpayError,
    is_placeholder_payment_id,
)

WORKING_SET = BACKEND_ROOT / "data" / "synthetic_disputes.json"
HELD_OUT_SET = BACKEND_ROOT / "eval" / "held_out_set.json"
BACKING_MAP = BACKEND_ROOT / "data" / "razorpay_backing.json"


def load_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_backing() -> dict[str, dict[str, Any]]:
    if BACKING_MAP.is_file():
        return json.loads(BACKING_MAP.read_text(encoding="utf-8"))
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--limit", type=int, default=25, help="How many disputes to back with real orders."
    )
    parser.add_argument(
        "--refresh-payments-only",
        action="store_true",
        help="Skip order creation; only re-check existing orders for completed payments.",
    )
    parser.add_argument(
        "--with-payment-links",
        action="store_true",
        help=(
            "Also create real test-mode payment links. Completing one with a test card "
            "yields a genuine payment_id that a later run will link."
        ),
    )
    parser.add_argument(
        "--max-payment-links",
        type=int,
        default=5,
        help="Cap on payment links created per run (Razorpay rate-limits these).",
    )
    parser.add_argument(
        "--link-delay-seconds",
        type=float,
        default=2.0,
        help="Pause between payment-link creations to stay under the rate limit.",
    )
    args = parser.parse_args()

    try:
        client = RazorpayClient()
    except Exception as exc:
        print(f"Could not initialise the Razorpay client: {exc}", file=sys.stderr)
        print("Populate RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in .env first.", file=sys.stderr)
        return 1

    disputes = load_json(WORKING_SET)
    backing = load_backing()
    created = 0
    payments_found = 0
    links_created = 0
    failures = 0

    targets = disputes[: args.limit]
    print(f"Backing {len(targets)} disputes with real test-mode Razorpay orders\n")

    for dispute in targets:
        dispute_id = dispute["dispute_id"]
        entry = backing.get(dispute_id, {})

        # 1. Create the order if we do not already have one.
        if not entry.get("order_id") and not args.refresh_payments_only:
            # dispute ids look like disp_synthetic_0173; keep the numeric suffix only.
            receipt = f"rcpt_{dispute_id.rsplit('_', 1)[-1]}"
            try:
                order = client.create_backing_order(dispute["amount"], receipt)
            except RazorpayError as exc:
                print(f"  {dispute_id}: order.create FAILED -- {exc}")
                failures += 1
                continue

            # Fetch it back: this is the acceptance test's "create, then fetch it back".
            try:
                fetched = client.fetch_order(order["id"])
            except RazorpayError as exc:
                print(f"  {dispute_id}: order.fetch FAILED -- {exc}")
                failures += 1
                continue

            entry = {
                "order_id": fetched["id"],
                "receipt": fetched.get("receipt"),
                "amount": fetched.get("amount"),
                "currency": fetched.get("currency"),
                "status": fetched.get("status"),
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "payment_id": None,
            }
            backing[dispute_id] = entry
            created += 1
            print(f"  {dispute_id}: order {fetched['id']} created and fetched back OK")

        # 2. Create a payment link, so a real payment is actually obtainable.
        # Razorpay rate-limits payment-link creation harder than order creation, so these
        # are capped and throttled rather than fired off once per dispute.
        if (
            args.with_payment_links
            and not entry.get("payment_link_id")
            and links_created < args.max_payment_links
        ):
            if links_created:
                time.sleep(args.link_delay_seconds)
            try:
                link = client.create_payment_link(
                    amount_paise=dispute["amount"],
                    description=f"Recourse test backing for {dispute_id}",
                    reference_id=f"ref_{dispute_id.rsplit('_', 1)[-1]}_{int(datetime.now().timestamp())}",
                )
            except RazorpayError as exc:
                print(f"  {dispute_id}: payment_link.create FAILED -- {exc}")
            else:
                entry["payment_link_id"] = link["id"]
                entry["payment_link_url"] = link.get("short_url")
                links_created += 1
                print(f"  {dispute_id}: payment link {link.get('short_url')}")

        # 3. Look for a real payment, against the order and against the payment link.
        order_id = entry.get("order_id")
        if not entry.get("payment_id"):
            real_payment_id = None

            if order_id:
                try:
                    payments = client.fetch_order_payments(order_id)
                except RazorpayError as exc:
                    print(f"  {dispute_id}: order.payments FAILED -- {exc}")
                    payments = []
                captured = [
                    p for p in payments if p.get("status") in {"captured", "authorized"}
                ]
                if captured:
                    real_payment_id = captured[0]["id"]

            if not real_payment_id and entry.get("payment_link_id"):
                try:
                    link = client.fetch_payment_link(entry["payment_link_id"])
                except RazorpayError as exc:
                    print(f"  {dispute_id}: payment_link.fetch FAILED -- {exc}")
                    link = {}
                for p in link.get("payments") or []:
                    if p.get("status") in {"captured", "authorized"}:
                        real_payment_id = p.get("payment_id") or p.get("id")
                        break

            if real_payment_id:
                entry["payment_id"] = real_payment_id
                dispute["payment_id"] = real_payment_id
                payments_found += 1
                print(f"  {dispute_id}: real payment {real_payment_id} linked")

        backing[dispute_id] = entry

    write_json(BACKING_MAP, backing)
    write_json(WORKING_SET, disputes)

    still_placeholder = sum(1 for d in disputes if is_placeholder_payment_id(d["payment_id"]))

    print("\n--- summary ---")
    print(f"  orders created this run : {created}")
    print(f"  payment links created   : {links_created}")
    print(f"  real payments linked    : {payments_found}")
    print(f"  failures                : {failures}")
    print(f"  disputes still on a placeholder payment_id: {still_placeholder}/{len(disputes)}")
    print(f"\n  backing map -> {BACKING_MAP.relative_to(BACKEND_ROOT)}")

    if payments_found == 0:
        print(
            "\n  No real payments found yet. This is expected: Razorpay has no API to create\n"
            "  a payment -- one only exists once a Checkout is completed. To get a real\n"
            "  payment_id, run with --with-payment-links, open a printed link, pay it with\n"
            "  the test card 4111 1111 1111 1111 (any future expiry, any CVV), then re-run\n"
            "  with --refresh-payments-only."
        )
    unpaid_links = [
        (d, e["payment_link_url"])
        for d, e in backing.items()
        if e.get("payment_link_url") and not e.get("payment_id")
    ]
    if unpaid_links:
        print("\n  Unpaid test payment links (pay one to get a real payment_id):")
        for dispute_id, url in unpaid_links[:5]:
            print(f"    {dispute_id}  {url}")

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
