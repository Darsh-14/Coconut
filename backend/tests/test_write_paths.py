"""Filing disputes and editing their evidence.

Until these endpoints existed the queue was a fixed seed: the app could only ever show
what shipped in a committed JSON file. Two properties here are load-bearing rather than
incidental, and are tested first:

  1. ground_truth_label can never be set through a request. It is an evaluation-only
     field, and a public write endpoint that could set it would let whoever files a
     dispute shape the reported precision.
  2. Changing an evidence bundle invalidates any standing decision. ClaimVerdict joins to
     evidence by INDEX, so a mutated bundle silently re-points every verdict at the wrong
     item unless something detects it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_session
from app.main import app


@pytest.fixture()
def client(tmp_path):
    """A fresh, empty database per test: these tests create rows and count them."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'w.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


def file_dispute(client, **overrides) -> dict:
    body = {
        "reason_code": "goods_not_received",
        "claim_text": "Cardholder asserts the merchandise was never delivered.",
        "amount": 249900,
    }
    body.update(overrides)
    response = client.post("/disputes", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def add_evidence(client, dispute_id, **overrides) -> dict:
    body = {
        "type": "delivery_proof",
        "content": "Courier POD signed at the registered address.",
        "source_ref": "pod_test_1",
    }
    body.update(overrides)
    response = client.post(f"/disputes/{dispute_id}/evidence", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# -- the two load-bearing properties -----------------------------------------------------


def test_ground_truth_can_never_be_set_through_the_api(client):
    """Otherwise whoever files a dispute could shape the reported metrics."""
    dispute = file_dispute(client, ground_truth_label="contest_win")
    assert dispute["ground_truth_label"] is None

    detail = client.get(f"/disputes/{dispute['dispute_id']}").json()
    assert detail["dispute"]["ground_truth_label"] is None


def test_changing_evidence_invalidates_a_standing_decision(client, monkeypatch):
    """A verdict list that no longer matches the bundle must be detectable."""
    dispute = file_dispute(client)
    dispute_id = dispute["dispute_id"]
    add_evidence(client, dispute_id)

    # A decision, without paying for real inference.
    _stub_decision(client, monkeypatch, dispute_id)
    assert client.get(f"/disputes/{dispute_id}").json()["decision_is_stale"] is False

    add_evidence(client, dispute_id, type="communication_log", source_ref="chat_1")
    assert client.get(f"/disputes/{dispute_id}").json()["decision_is_stale"] is True


def test_removing_evidence_also_invalidates_it(client, monkeypatch):
    dispute = file_dispute(client)
    dispute_id = dispute["dispute_id"]
    add_evidence(client, dispute_id)
    add_evidence(client, dispute_id, type="order_history", source_ref="oms_1")
    _stub_decision(client, monkeypatch, dispute_id)

    client.delete(f"/disputes/{dispute_id}/evidence/0")
    assert client.get(f"/disputes/{dispute_id}").json()["decision_is_stale"] is True


def _stub_decision(client, monkeypatch, dispute_id: str) -> None:
    """Run /decide with the model stubbed out -- these tests are about bookkeeping."""
    from app.models.schemas import ClaimVerdict

    monkeypatch.setattr(
        "app.api.routes.get_verification_engine",
        lambda: _FakeEngine(),
    )
    response = client.post(f"/disputes/{dispute_id}/decide")
    assert response.status_code == 200, response.text
    assert ClaimVerdict(**response.json()["claim_verdicts"][0])


class _FakeEngine:
    def verify_bundle(self, claim_text, evidence, reason_code):
        from app.models.schemas import ClaimVerdict

        return [
            ClaimVerdict(
                evidence_index=i, label="support", confidence=0.9, highlighted_span=None
            )
            for i, _ in enumerate(evidence)
        ]


# -- filing ------------------------------------------------------------------------------


def test_a_filed_dispute_joins_the_queue(client):
    before = len(client.get("/disputes").json())
    dispute = file_dispute(client)
    after = client.get("/disputes").json()

    assert len(after) == before + 1
    assert dispute["dispute_id"] in {row["dispute_id"] for row in after}


def test_ids_are_minted_by_the_server_and_do_not_collide(client):
    ids = {file_dispute(client)["dispute_id"] for _ in range(3)}
    assert len(ids) == 3
    assert all(i.startswith("disp_manual_") for i in ids)


def test_a_filed_id_can_never_reach_razorpay(client):
    """disp_manual_ is not disp_synthetic_, and the guard must not care."""
    from app.services.razorpay_client import may_reach_razorpay

    dispute = file_dispute(client)
    assert may_reach_razorpay(dispute["dispute_id"]) is False


def test_defaults_fill_in_a_realistic_response_window(client):
    from datetime import datetime

    dispute = file_dispute(client)
    raised = datetime.fromisoformat(dispute["raised_at"].replace("Z", "+00:00"))
    respond = datetime.fromisoformat(dispute["respond_by"].replace("Z", "+00:00"))
    assert (respond - raised).days == 14


def test_a_placeholder_payment_is_minted_when_none_is_given(client):
    dispute = file_dispute(client)
    assert dispute["payment_id"].startswith("pay_PENDING_")
    assert client.get(f"/disputes/{dispute['dispute_id']}").json()["payment_is_real"] is False


@pytest.mark.parametrize(
    "bad, why",
    [
        ({"reason_code": "not_a_real_code"}, "unknown reason code"),
        ({"claim_text": "too short"}, "claim below the minimum length"),
        ({"amount": 0}, "zero amount"),
        ({"amount": -100}, "negative amount"),
        ({"phase": "not_a_phase"}, "unknown phase"),
        ({"rail": "bitcoin"}, "unknown rail"),
    ],
)
def test_invalid_filings_are_rejected(client, bad, why):
    body = {
        "reason_code": "goods_not_received",
        "claim_text": "Cardholder asserts the merchandise was never delivered.",
        "amount": 249900,
    }
    body.update(bad)
    assert client.post("/disputes", json=body).status_code == 422, why


def test_a_deadline_before_the_claim_is_rejected(client):
    body = {
        "reason_code": "goods_not_received",
        "claim_text": "Cardholder asserts the merchandise was never delivered.",
        "amount": 249900,
        "raised_at": "2026-08-20T10:00:00Z",
        "respond_by": "2026-08-01T10:00:00Z",
    }
    assert client.post("/disputes", json=body).status_code == 422


# -- evidence ----------------------------------------------------------------------------


def test_evidence_is_appended_in_order(client):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id, content="First.", source_ref="a")
    result = add_evidence(client, dispute_id, content="Second.", source_ref="b")

    contents = [item["content"] for item in result["evidence_bundle"]]
    assert contents == ["First.", "Second."]


def test_added_evidence_immediately_has_an_openable_record(client):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id, content="Courier POD signed.", source_ref="pod_9")

    doc = client.get(f"/disputes/{dispute_id}/evidence/0/document").json()
    assert doc["body"] == "Courier POD signed."
    assert doc["kind"] == "proof_of_delivery"


def test_blank_evidence_is_rejected(client):
    dispute_id = file_dispute(client)["dispute_id"]
    for blank in ["", "   ", "\n"]:
        response = client.post(
            f"/disputes/{dispute_id}/evidence",
            json={"type": "other", "content": blank},
        )
        assert response.status_code == 422


def test_removing_an_out_of_range_index_is_404(client):
    dispute_id = file_dispute(client)["dispute_id"]
    assert client.delete(f"/disputes/{dispute_id}/evidence/0").status_code == 404


def test_evidence_on_an_unknown_dispute_is_404(client):
    response = client.post(
        "/disputes/disp_nope/evidence", json={"type": "other", "content": "x"}
    )
    assert response.status_code == 404
