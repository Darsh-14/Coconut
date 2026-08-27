"""Razorpay webhook intake.

Two properties are load-bearing and are tested first, because getting either wrong turns
this into an unauthenticated write path into the merchant's queue:

  1. With no secret configured the endpoint refuses everything. "Accept unsigned events
     when no secret is set" is the tempting alternative and it is a hole.
  2. The signature is checked against the RAW request body. Verifying a re-serialised body
     is a classic way to make the check meaningless, because the bytes that were signed
     and the bytes that were checked are then not the same bytes.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_session
from app.db.models import DisputeRow
from app.main import app
from app.models.schemas import Dispute, EvidenceItem

SECRET = "whsec_test_secret"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", SECRET)
    from app.config import get_settings

    get_settings.cache_clear()

    engine = create_engine(f"sqlite:///{(tmp_path / 'wh.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with factory() as session:
        session.add(_backed_dispute())
        session.commit()

    def override():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        c._factory = factory  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    engine.dispose()
    get_settings.cache_clear()


def _backed_dispute() -> DisputeRow:
    from datetime import datetime, timedelta, timezone

    raised = datetime.now(timezone.utc) - timedelta(days=2)
    row = DisputeRow.from_schema(
        Dispute(
            dispute_id="disp_synthetic_8001",
            payment_id="pay_PENDING_8001",
            phase="chargeback",
            reason_code="goods_not_received",
            claim_text="Cardholder says it never arrived.",
            amount=249900,
            raised_at=raised,
            respond_by=raised + timedelta(days=14),
            evidence_bundle=[EvidenceItem(type="delivery_proof", content="POD signed.")],
        )
    )
    row.razorpay_order_id = "order_BACKING01"
    return row


def sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def payment_event(payment_id="pay_REAL01", order_id="order_BACKING01", event="payment.captured"):
    return {
        "event": event,
        "payload": {"payment": {"entity": {"id": payment_id, "order_id": order_id}}},
    }


def post(client, payload, signature=None, secret=SECRET):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature or sign(body, secret)},
    )


# -- the two load-bearing properties -------------------------------------------------------


def test_without_a_configured_secret_everything_is_refused(client, monkeypatch):
    """An open webhook is an unauthenticated write path into the queue."""
    monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()

    response = post(client, payment_event())
    assert response.status_code == 503
    assert "never accepted" in response.json()["detail"]

    # and nothing was written
    with client._factory() as s:
        assert s.get(DisputeRow, "disp_synthetic_8001").payment_id == "pay_PENDING_8001"


def test_a_wrong_signature_is_rejected(client):
    assert post(client, payment_event(), secret="not-the-secret").status_code == 401


def test_a_missing_signature_is_rejected(client):
    body = json.dumps(payment_event()).encode()
    assert client.post("/webhooks/razorpay", content=body).status_code == 401


def test_a_signature_for_different_bytes_is_rejected(client):
    """The signature must cover the body that actually arrived, not a plausible one."""
    signed_for = json.dumps(payment_event(payment_id="pay_ONE")).encode()
    actually_sent = json.dumps(payment_event(payment_id="pay_TWO")).encode()

    response = client.post(
        "/webhooks/razorpay",
        content=actually_sent,
        headers={"X-Razorpay-Signature": sign(signed_for)},
    )
    assert response.status_code == 401


def test_whitespace_changes_invalidate_the_signature(client):
    """Proof the raw bytes are verified rather than a re-serialised parse of them."""
    payload = payment_event()
    compact = json.dumps(payload, separators=(",", ":")).encode()
    spaced = json.dumps(payload, indent=2).encode()

    response = client.post(
        "/webhooks/razorpay",
        content=spaced,
        headers={"X-Razorpay-Signature": sign(compact)},
    )
    assert response.status_code == 401


# -- promoting a payment ---------------------------------------------------------------------


@pytest.mark.parametrize("event", ["payment.captured", "payment.authorized"])
def test_a_completed_payment_is_promoted_onto_its_dispute(client, event):
    response = post(client, payment_event(event=event))
    assert response.status_code == 200

    body = response.json()
    assert body["acted"] is True
    assert body["dispute_id"] == "disp_synthetic_8001"

    with client._factory() as s:
        assert s.get(DisputeRow, "disp_synthetic_8001").payment_id == "pay_REAL01"


def test_replaying_the_same_event_does_not_overwrite(client):
    """Razorpay retries. A second delivery must not clobber the id it already set."""
    post(client, payment_event())
    second = post(client, payment_event(payment_id="pay_DIFFERENT"))

    assert second.json()["acted"] is False
    with client._factory() as s:
        assert s.get(DisputeRow, "disp_synthetic_8001").payment_id == "pay_REAL01"


def test_a_payment_for_an_unknown_order_is_acknowledged_not_an_error(client):
    """The account takes payments this system knows nothing about. Erroring would make
    Razorpay retry forever into a case there is nothing to do about."""
    response = post(client, payment_event(order_id="order_SOMETHINGELSE"))
    assert response.status_code == 200
    assert response.json()["acted"] is False


def test_an_event_without_a_payment_entity_is_handled(client):
    response = post(client, {"event": "payment.captured", "payload": {}})
    assert response.status_code == 200
    assert response.json()["acted"] is False


# -- what it refuses to do -------------------------------------------------------------------


def test_dispute_events_are_acknowledged_but_never_ingested(client):
    """Section 3: disputes here are synthetic. Creating a real-looking one from a webhook
    would blur exactly the boundary Section 7 exists to keep sharp."""
    before = None
    with client._factory() as s:
        before = s.query(DisputeRow).count()

    response = post(
        client,
        {
            "event": "payment.dispute.created",
            "payload": {"dispute": {"entity": {"id": "disp_REAL123", "amount": 5000}}},
        },
    )

    assert response.status_code == 200
    assert response.json()["acted"] is False
    assert "synthetic" in response.json()["reason"]

    with client._factory() as s:
        assert s.query(DisputeRow).count() == before, "no dispute may be created"
        assert s.get(DisputeRow, "disp_REAL123") is None


def test_an_unknown_event_type_is_acknowledged_not_a_500(client):
    response = post(client, {"event": "subscription.charged", "payload": {}})
    assert response.status_code == 200
    assert response.json()["acted"] is False


def test_a_signed_but_malformed_body_is_a_400(client):
    body = b"{not json"
    response = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sign(body)},
    )
    assert response.status_code == 400
