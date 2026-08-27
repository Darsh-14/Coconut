"""Razorpay SDK wrapper.

Two hard rules live here, both from CLAUDE.md:

1. Test mode only (Section 2.1). Enforced upstream in config.py, which refuses to build
   Settings for a non-`rzp_test_` key, so this module cannot be constructed against live
   credentials.

2. Synthetic disputes never touch the network (Sections 3 and 7). Every dispute-side call
   goes through _dispute_call(), which inspects the dispute_id first. Synthetic ids are
   logged with the exact payload that *would* have been sent and return without calling
   Razorpay -- the dispute does not exist on Razorpay's side, so the call would only ever
   produce a confusing 400.

The dispute method signatures below were read from the installed package
(razorpay/resources/dispute.py) rather than guessed, per Section 3:

    dispute.fetch(dispute_id, data={}, **kwargs)     GET    /v1/disputes/{id}
    dispute.accept(dispute_id, data={}, **kwargs)    POST   /v1/disputes/{id}/accept
    dispute.contest(dispute_id, data={}, **kwargs)   PATCH  /v1/disputes/{id}/contest
    dispute.all(data={}, **kwargs)                   GET    /v1/disputes
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import razorpay

from app.config import Settings, get_settings

logger = logging.getLogger("recourse.razorpay")

# Synthetic dispute ids are minted by data/generate_synthetic_disputes.py with this prefix.
SYNTHETIC_DISPUTE_PREFIX = "disp_synthetic_"
# Placeholder payment ids, before phase-2 backfill.
PENDING_PAYMENT_PREFIX = "pay_PENDING_"

DisputeAction = Literal["fetch", "accept", "contest"]


def is_synthetic_dispute_id(dispute_id: str) -> bool:
    """True when the dispute exists only inside Recourse and not on Razorpay's side."""
    return dispute_id.startswith(SYNTHETIC_DISPUTE_PREFIX)


def is_placeholder_payment_id(payment_id: str) -> bool:
    """True when the payment id has not yet been backfilled with a real test-mode id."""
    return payment_id.startswith(PENDING_PAYMENT_PREFIX)


class RazorpayError(RuntimeError):
    """Wraps any failure talking to Razorpay, with the operation named for the caller."""


@dataclass
class DisputeCallResult:
    """Outcome of a dispute-side operation.

    `submitted` is the honest record of whether a network call actually happened. For a
    synthetic dispute it is always False and `would_be_payload` carries what we would have
    sent -- this is what the audit log stores and the UI labels "would submit to Razorpay".
    """

    action: DisputeAction
    dispute_id: str
    submitted: bool
    would_be_payload: dict[str, Any] = field(default_factory=dict)
    response: Optional[dict[str, Any]] = None
    reason: str = ""


class RazorpayClient:
    """Thin, logged wrapper around the official SDK."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        # Reaching here means config.py already validated the rzp_test_ prefix.
        self._client = razorpay.Client(
            auth=(self.settings.razorpay_key_id, self.settings.razorpay_key_secret)
        )
        logger.info(
            "Razorpay client initialised in TEST mode (key %s...)",
            self.settings.razorpay_key_id[:14],
        )

    # -- orders and payments (real API calls) -------------------------------

    def create_backing_order(self, amount_paise: int, receipt: str) -> dict[str, Any]:
        """Create a real test-mode order to back a synthetic dispute (Section 7).

        Orders are fully creatable over the API. Payments are not: Razorpay has no endpoint
        to fabricate a payment, since a payment requires a real Checkout interaction. See
        backfill_payment_ids.py for how this is handled honestly.
        """
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": {"purpose": "recourse-synthetic-dispute-backing"},
        }
        logger.info("order.create %s", payload)
        try:
            order = self._client.order.create(payload)
        except Exception as exc:
            raise RazorpayError(f"order.create failed for receipt {receipt}: {exc}") from exc
        logger.info("order.create -> %s", order.get("id"))
        return order

    def fetch_order(self, order_id: str) -> dict[str, Any]:
        """Fetch an order back, proving the id resolves against the real test-mode API."""
        logger.info("order.fetch %s", order_id)
        try:
            return self._client.order.fetch(order_id)
        except Exception as exc:
            raise RazorpayError(f"order.fetch failed for {order_id}: {exc}") from exc

    def fetch_order_payments(self, order_id: str) -> list[dict[str, Any]]:
        """List any real payments made against an order via Checkout.

        Returns an empty list when nobody has completed a test checkout for the order,
        which is the normal case for an order created purely over the API.
        """
        logger.info("order.payments %s", order_id)
        try:
            result = self._client.order.payments(order_id)
        except Exception as exc:
            raise RazorpayError(f"order.payments failed for {order_id}: {exc}") from exc
        return result.get("items", []) if isinstance(result, dict) else []

    def create_payment_link(
        self, *, amount_paise: int, description: str, reference_id: str
    ) -> dict[str, Any]:
        """Create a real test-mode payment link.

        Razorpay has no API to fabricate a payment, so this is the supported route to a
        genuine `pay_...` id: the link is real, and completing it with a test card produces
        a real payment that backfill_razorpay_backing.py can then link to a dispute.
        """
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "description": description[:2048],
            "reference_id": reference_id,
            "notes": {"purpose": "recourse-synthetic-dispute-backing"},
        }
        logger.info("payment_link.create %s", payload)
        try:
            link = self._client.payment_link.create(payload)
        except Exception as exc:
            raise RazorpayError(
                f"payment_link.create failed for {reference_id}: {exc}"
            ) from exc
        logger.info("payment_link.create -> %s (%s)", link.get("id"), link.get("short_url"))
        return link

    def fetch_payment_link(self, payment_link_id: str) -> dict[str, Any]:
        """Fetch a payment link, including any payments made against it."""
        logger.info("payment_link.fetch %s", payment_link_id)
        try:
            return self._client.payment_link.fetch(payment_link_id)
        except Exception as exc:
            raise RazorpayError(
                f"payment_link.fetch failed for {payment_link_id}: {exc}"
            ) from exc

    def fetch_payment(self, payment_id: str) -> Optional[dict[str, Any]]:
        """Fetch a payment. Returns None for a not-yet-backfilled placeholder id.

        Guarded so the UI can call this for any dispute without needing to know whether
        the payment id is real yet.
        """
        if is_placeholder_payment_id(payment_id):
            logger.info("payment.fetch skipped: %s is a placeholder id", payment_id)
            return None
        logger.info("payment.fetch %s", payment_id)
        try:
            return self._client.payment.fetch(payment_id)
        except Exception as exc:
            raise RazorpayError(f"payment.fetch failed for {payment_id}: {exc}") from exc

    # -- disputes (guarded; synthetic ids never hit the network) ------------

    def _dispute_call(
        self, action: DisputeAction, dispute_id: str, data: Optional[dict[str, Any]] = None
    ) -> DisputeCallResult:
        """Single choke point for every dispute-side operation.

        Section 7: for a synthetic dispute we build the exact payload, log it, and return
        without calling Razorpay. There is deliberately no flag to force the call.
        """
        payload = dict(data or {})
        would_be = {
            "method": {"fetch": "GET", "accept": "POST", "contest": "PATCH"}[action],
            "path": f"/v1/disputes/{dispute_id}"
            + ("" if action == "fetch" else f"/{action}"),
            "dispute_id": dispute_id,
            "body": payload,
        }

        if is_synthetic_dispute_id(dispute_id):
            reason = (
                f"{dispute_id} is synthetic and does not exist on Razorpay's side; "
                "logging the payload instead of sending it (CLAUDE.md Section 7)."
            )
            logger.info("dispute.%s WOULD SEND (not sent): %s | %s", action, would_be, reason)
            return DisputeCallResult(
                action=action,
                dispute_id=dispute_id,
                submitted=False,
                would_be_payload=would_be,
                response=None,
                reason=reason,
            )

        logger.info("dispute.%s SENDING: %s", action, would_be)
        try:
            method = getattr(self._client.dispute, action)
            response = method(dispute_id, payload) if payload else method(dispute_id)
        except Exception as exc:
            raise RazorpayError(f"dispute.{action} failed for {dispute_id}: {exc}") from exc
        return DisputeCallResult(
            action=action,
            dispute_id=dispute_id,
            submitted=True,
            would_be_payload=would_be,
            response=response,
            reason="sent to Razorpay",
        )

    def fetch_dispute(self, dispute_id: str) -> DisputeCallResult:
        return self._dispute_call("fetch", dispute_id)

    def accept_dispute(self, dispute_id: str) -> DisputeCallResult:
        """Accept a dispute. Never auto-invoked -- requires human approval (Section 2.2)."""
        return self._dispute_call("accept", dispute_id)

    def contest_dispute(self, dispute_id: str, payload: dict[str, Any]) -> DisputeCallResult:
        """Contest a dispute. Never auto-invoked -- requires human approval (Section 2.2)."""
        return self._dispute_call("contest", dispute_id, payload)


_client_lock = threading.Lock()
_client_singleton: Optional["RazorpayClient"] = None


def get_razorpay_client() -> "RazorpayClient":
    """One shared client per process, built lazily.

    Lazy because constructing it reads settings, and settings hard-fail on a non-test key
    -- which must surface at startup via config validation, not on an unrelated import.
    Locked because FastAPI serves sync endpoints from a threadpool.
    """
    global _client_singleton
    with _client_lock:
        if _client_singleton is None:
            _client_singleton = RazorpayClient()
        return _client_singleton


def build_contest_payload(
    *, dispute_id: str, amount_paise: int, packet_text: str, evidence_refs: list[str]
) -> dict[str, Any]:
    """Build the representment body we would send to dispute.contest.

    Shaped after Razorpay's documented contest payload (summary plus evidence references).
    This is what gets stored in AuditLogEntry.would_be_razorpay_payload and shown in the UI
    labelled "would submit to Razorpay".
    """
    return {
        "amount": amount_paise,
        "summary": packet_text,
        "shipping_proof": evidence_refs or None,
        "action": "submit",
        "_recourse_note": (
            f"Representment drafted by Recourse for {dispute_id}. Human-approved. "
            "NOT transmitted: the dispute is synthetic."
        ),
    }


__all__ = [
    "PENDING_PAYMENT_PREFIX",
    "SYNTHETIC_DISPUTE_PREFIX",
    "DisputeCallResult",
    "RazorpayClient",
    "RazorpayError",
    "build_contest_payload",
    "get_razorpay_client",
    "is_placeholder_payment_id",
    "is_synthetic_dispute_id",
]
