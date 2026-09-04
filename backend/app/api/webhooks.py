"""Razorpay webhook intake.

WHY THIS EXISTS
---------------
Every other way data enters this system is someone clicking something. A real merchant
integration does not work that way: Razorpay pushes events, and the merchant's system
reacts. This is that shape, and it is the piece that makes the backing-payment flow finish
itself -- a payment completed in Checkout arrives here as `payment.captured` and is
promoted onto its dispute without anyone reloading a page.

FAILING CLOSED, TWICE
---------------------
1. No RAZORPAY_WEBHOOK_SECRET configured -> every request is refused. The tempting
   alternative, "accept unsigned events when no secret is set", turns this into an
   unauthenticated write path into the merchant's queue for anyone who can reach the port.
   A disabled endpoint is a correct state; an open one is not.

2. Signature verified against the RAW request body, before the JSON is parsed. Verifying a
   re-serialised body is a classic way to make a signature check meaningless, because the
   bytes that were signed and the bytes that were checked are then not the same bytes.
   Comparison is constant-time (the SDK uses hmac.compare_digest).

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not ingest dispute events. Section 3 is explicit that disputes in this system are
synthetic, and quietly creating a real-looking dispute from a webhook would blur exactly
the real-versus-synthetic boundary Section 7 exists to keep sharp. Dispute events are
acknowledged and logged, never acted on. Acknowledging rather than erroring is deliberate:
Razorpay retries a non-2xx, and there is nothing to retry into.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.database import get_session
from app.db.models import DisputeRow
from app.services.razorpay_client import is_placeholder_payment_id

logger = logging.getLogger("coconut.webhooks")

router = APIRouter()

# Events we act on. Anything else is acknowledged and logged, so an unexpected event type
# never 500s and never silently changes state.
PAYMENT_EVENTS = {"payment.captured", "payment.authorized"}


def _verify(raw_body: bytes, signature: str, secret: str) -> bool:
    """Constant-time signature check against the exact bytes Razorpay signed."""
    import razorpay

    try:
        razorpay.Client(auth=("unused", "unused")).utility.verify_webhook_signature(
            raw_body.decode("utf-8"), signature, secret
        )
        return True
    except Exception:  # noqa: BLE001 -- the SDK raises on mismatch; any failure is a fail
        return False


@router.post("/webhooks/razorpay", tags=["webhooks"])
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(default=""),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Receive a signed Razorpay event.

    Async purely to read the raw body before parsing; everything after that is the same
    sync session work as the rest of the API.
    """
    settings = get_settings()

    if not settings.razorpay_webhook_secret:
        logger.warning("webhook received but RAZORPAY_WEBHOOK_SECRET is not set; refusing")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": (
                    "Webhook intake is disabled: RAZORPAY_WEBHOOK_SECRET is not "
                    "configured. Unsigned events are never accepted."
                )
            },
        )

    raw = await request.body()
    if not x_razorpay_signature or not _verify(raw, x_razorpay_signature, settings.razorpay_webhook_secret):
        logger.warning("webhook signature rejected (%d bytes)", len(raw))
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Signature verification failed."},
        )

    try:
        payload: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Body is not valid JSON."},
        )

    event = str(payload.get("event", ""))
    logger.info("webhook accepted: %s", event)

    if event in PAYMENT_EVENTS:
        return _handle_payment(payload, event, session)

    if event.startswith("payment.dispute"):
        # Acknowledged, never acted on -- see the module docstring.
        logger.info("ignoring %s: this system never ingests real Razorpay disputes", event)
        return JSONResponse(
            content={
                "status": "acknowledged",
                "event": event,
                "acted": False,
                "reason": (
                    "Disputes in this system are synthetic (CLAUDE.md Section 3). Dispute "
                    "events are logged, never ingested."
                ),
            }
        )

    return JSONResponse(content={"status": "acknowledged", "event": event, "acted": False})


def _handle_payment(payload: dict[str, Any], event: str, session: Session) -> JSONResponse:
    """Promote a completed payment onto the dispute whose backing order it settles."""
    entity = (
        payload.get("payload", {}).get("payment", {}).get("entity", {})
        if isinstance(payload.get("payload"), dict)
        else {}
    )
    payment_id = entity.get("id")
    order_id = entity.get("order_id")

    if not payment_id or not order_id:
        return JSONResponse(
            content={"status": "acknowledged", "event": event, "acted": False,
                     "reason": "No payment id or order id in the event."}
        )

    row = session.scalars(
        select(DisputeRow).where(DisputeRow.razorpay_order_id == order_id)
    ).first()
    if row is None:
        # Perfectly normal: the account may take payments this system knows nothing about.
        return JSONResponse(
            content={"status": "acknowledged", "event": event, "acted": False,
                     "reason": f"No dispute is backed by order {order_id}."}
        )

    if not is_placeholder_payment_id(row.payment_id):
        return JSONResponse(
            content={"status": "acknowledged", "event": event, "acted": False,
                     "reason": f"{row.dispute_id} is already backed by {row.payment_id}."}
        )

    previous = row.payment_id
    row.payment_id = payment_id
    session.commit()
    logger.info(
        "webhook promoted %s: %s -> real payment %s", row.dispute_id, previous, payment_id
    )
    return JSONResponse(
        content={
            "status": "ok",
            "event": event,
            "acted": True,
            "dispute_id": row.dispute_id,
            "payment_id": payment_id,
        }
    )


__all__ = ["PAYMENT_EVENTS", "router"]
