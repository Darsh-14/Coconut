"""API integration tests (CLAUDE.md Section 13 phase 5 / Section 14).

Section 14 requires an integration test hitting /disputes/{id}/decide against a seeded
dispute and asserting a well-formed Decision comes back, plus a smoke test that /evaluate
runs end to end and returns metrics within sane bounds.

Runs against a temporary database so the developer's recourse.db is untouched. The model
is real (not mocked) for the decide test -- mocking it would defeat the purpose of an
integration test -- so that test is slow.

The most important assertions here are the Section 7 ones in the approve tests: that
approving a CONTEST stores a would_be_razorpay_payload and never transmits it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_session
from app.db.models import DisputeRow
from app.main import app
from app.models.schemas import Dispute, EvidenceItem


# Set by the client fixture so tests can reset rows directly. The database is
# module-scoped, so backing tests must not depend on the order they run in.
_session_factory = None


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("api") / "test.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def override_session():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_session
    global _session_factory
    _session_factory = factory

    with factory() as session:
        for dispute in _seed_disputes():
            session.add(DisputeRow.from_schema(dispute))
        session.commit()

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    engine.dispose()


def _seed_disputes() -> list[Dispute]:
    raised = datetime.now(timezone.utc) - timedelta(days=3)
    strong = Dispute(
        dispute_id="disp_synthetic_9001",
        payment_id="pay_TUSjwsBKtOQpWj",  # a real one, to exercise payment_is_real
        phase="chargeback",
        reason_code="goods_not_received",
        claim_text=(
            "Cardholder asserts that the merchandise associated with this transaction was "
            "never delivered to the address on file."
        ),
        amount=249900,
        raised_at=raised,
        respond_by=raised + timedelta(days=21),
        evidence_bundle=[
            EvidenceItem(
                type="delivery_proof",
                content=(
                    "The recipient signed for the parcel on 14 July 2026 at 11:42 and the "
                    "delivery OTP was entered from the registered mobile ending 8830, with "
                    "a doorstep photograph showing the flat number on record."
                ),
                source_ref="pod_9001",
            ),
            EvidenceItem(
                type="communication_log",
                content=(
                    "The customer replied 'received, thanks' to the delivery confirmation "
                    "SMS on 14 July 2026 at 13:31."
                ),
                source_ref="sms_9001",
            ),
        ],
        ground_truth_label="contest_win",
    )
    weak = Dispute(
        dispute_id="disp_synthetic_9002",
        payment_id="pay_PENDING_9002",
        phase="chargeback",
        reason_code="goods_not_received",
        claim_text="Cardholder states the ordered item did not arrive.",
        amount=89900,
        raised_at=raised,
        respond_by=raised + timedelta(hours=30),  # inside the 48h red band
        evidence_bundle=[
            EvidenceItem(
                type="delivery_proof",
                content="The order was handed to the courier and marked dispatched.",
            )
        ],
        ground_truth_label="contest_loss",
    )
    return [strong, weak]


def _withdraw_standing_approval(client, dispute_id: str) -> None:
    detail = client.get(f"/disputes/{dispute_id}").json()
    if detail["status"] in {"approved", "submitted"}:
        standing = None
        for entry in detail["audit_log"]:
            if entry["withdrawn"]:
                standing = None
            elif entry["approved_by_human"]:
                standing = entry["id"]
        assert standing is not None
        response = client.post(
            f"/disputes/{dispute_id}/withdraw", params={"approval_id": standing}
        )
        assert response.status_code == 200, response.text


def _decide(client, dispute_id: str):
    """Start from an actionable case even when this module-scoped fixture has history."""
    _withdraw_standing_approval(client, dispute_id)
    return client.post(f"/disputes/{dispute_id}/decide")


def _approve(client, dispute_id: str, approved: bool, edited_packet=None):
    detail = client.get(f"/disputes/{dispute_id}").json()
    return client.post(
        f"/disputes/{dispute_id}/approve",
        json={
            "decision_id": detail["latest_decision_id"],
            "approved": approved,
            "edited_packet": edited_packet,
        },
    )


# -- GET /disputes ---------------------------------------------------------------------


def test_list_disputes_returns_the_queue(client):
    response = client.get("/disputes")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    ids = {row["dispute_id"] for row in body}
    assert ids == {"disp_synthetic_9001", "disp_synthetic_9002"}


def test_queue_is_ordered_by_urgency(client):
    body = client.get("/disputes").json()
    assert body[0]["dispute_id"] == "disp_synthetic_9002", "soonest respond_by must come first"


def test_queue_rows_match_the_section_8_shape(client):
    row = client.get("/disputes").json()[0]
    for field in (
        "dispute_id", "phase", "reason_code", "amount", "currency", "respond_by", "status"
    ):
        assert field in row, f"Section 8 requires {field}"


def test_queue_flags_which_payments_are_real(client):
    rows = {r["dispute_id"]: r for r in client.get("/disputes").json()}
    assert rows["disp_synthetic_9001"]["payment_is_real"] is True
    assert rows["disp_synthetic_9002"]["payment_is_real"] is False


def test_undecided_disputes_are_pending(client):
    rows = {r["dispute_id"]: r for r in client.get("/disputes").json()}
    assert rows["disp_synthetic_9002"]["status"] == "pending"


# -- GET /disputes/{id} ----------------------------------------------------------------


def test_get_dispute_detail(client):
    body = client.get("/disputes/disp_synthetic_9001").json()
    assert body["dispute"]["dispute_id"] == "disp_synthetic_9001"
    assert len(body["dispute"]["evidence_bundle"]) == 2
    assert body["audit_log"] == []


def test_unknown_dispute_returns_404(client):
    assert client.get("/disputes/disp_does_not_exist").status_code == 404


def test_approve_before_decide_is_rejected(client):
    """Approving something that was never assessed must not silently create an entry."""
    response = client.post(
        "/disputes/disp_synthetic_9002/approve",
        json={"decision_id": 1, "approved": True, "edited_packet": None},
    )
    assert response.status_code == 409


# -- POST /decide (Section 14's required integration test) -----------------------------


@pytest.mark.slow
def test_decide_returns_a_well_formed_decision(client):
    response = _decide(client, "disp_synthetic_9001")
    assert response.status_code == 200
    decision = response.json()

    assert decision["dispute_id"] == "disp_synthetic_9001"
    assert decision["recommendation"] in {"CONTEST", "ACCEPT", "NEEDS_HUMAN_REVIEW"}
    assert 0.0 <= decision["confidence"] <= 1.0
    assert decision["model_version"] == (
        "cross-encoder/nli-deberta-v3-base@6c749ce3425cd33b46d187e45b92bbf96ee12ec7"
    )
    assert decision["decided_at"]

    assert len(decision["claim_verdicts"]) == 2
    for verdict in decision["claim_verdicts"]:
        assert verdict["label"] in {"support", "contradict", "neutral"}
        assert 0.0 <= verdict["confidence"] <= 1.0
    assert [v["evidence_index"] for v in decision["claim_verdicts"]] == [0, 1]


@pytest.mark.slow
def test_decide_persists_and_advances_status(client):
    _decide(client, "disp_synthetic_9001")
    detail = client.get("/disputes/disp_synthetic_9001").json()
    assert detail["latest_decision"] is not None
    assert detail["status"] in {"decided", "approved", "submitted"}
    assert detail["decision_rationale"], "the rationale should explain the outcome"


@pytest.mark.slow
def test_highlighted_spans_come_from_the_evidence(client):
    """An explanation that is not verbatim from the evidence is not an explanation."""
    decision = _decide(client, "disp_synthetic_9001").json()
    detail = client.get("/disputes/disp_synthetic_9001").json()
    contents = [e["content"] for e in detail["dispute"]["evidence_bundle"]]
    for verdict in decision["claim_verdicts"]:
        span = verdict.get("highlighted_span")
        if span:
            assert any(span in c for c in contents)


# -- POST /approve, and Section 7's handling -------------------------------------------


@pytest.mark.slow
def test_approving_records_the_would_be_payload_and_does_not_transmit(client):
    """Section 7: build the payload, store it, never send it."""
    decision = _decide(client, "disp_synthetic_9001").json()

    response = _approve(client, "disp_synthetic_9001", True)
    assert response.status_code == 200
    entry = response.json()

    assert entry["approved_by_human"] is True
    assert entry["approved_at"] is not None

    if decision["recommendation"] == "CONTEST":
        payload = entry["would_be_razorpay_payload"]
        assert payload is not None, "a CONTEST approval must log what it would have sent"
        assert entry["submitted_to_razorpay"] is True
        assert "NOT transmitted" in payload["_recourse_note"]
        assert payload["amount"] == 249900
    else:
        assert entry["would_be_razorpay_payload"] is None


@pytest.mark.slow
def test_rejecting_stores_no_payload(client):
    _decide(client, "disp_synthetic_9001")
    entry = _approve(client, "disp_synthetic_9001", False).json()

    assert entry["approved_by_human"] is False
    assert entry["approved_at"] is None
    assert entry["submitted_to_razorpay"] is False
    assert entry["would_be_razorpay_payload"] is None


@pytest.mark.slow
def test_edited_packet_is_what_gets_recorded(client):
    """The human edits the draft; the audit trail must show the edit, not the draft."""
    _decide(client, "disp_synthetic_9001")
    entry = _approve(
        client, "disp_synthetic_9001", True, "Counsel-revised representment text."
    ).json()
    assert entry["decision"]["drafted_packet"] == "Counsel-revised representment text."


@pytest.mark.slow
def test_audit_trail_accumulates(client):
    _decide(client, "disp_synthetic_9001")
    _approve(client, "disp_synthetic_9001", True)
    detail = client.get("/disputes/disp_synthetic_9001").json()
    assert len(detail["audit_log"]) >= 1
    assert detail["status"] in {"approved", "submitted"}


# -- POST /evaluate (Section 14's smoke test) ------------------------------------------


@pytest.mark.slow
def test_evaluate_returns_sane_metrics(client):
    """Section 14: metrics within sane bounds, and non-placeholder."""
    response = client.post("/evaluate", params={"limit": 12})
    assert response.status_code == 200
    metrics = response.json()

    for field in ("precision", "recall", "f1", "coverage"):
        assert 0.0 <= metrics[field] <= 1.0, f"{field} out of bounds"

    cm = metrics["confusion_matrix"]
    for key in ("tp", "fp", "fn", "tn", "flagged_human"):
        assert key in cm and isinstance(cm[key], int)

    assert metrics["n_evaluated"] == 12
    assert sum(cm.values()) == metrics["n_evaluated"], "every record must land in exactly one cell"
    assert metrics["false_positive_cost_estimate_inr"] == pytest.approx(cm["fp"] * 1500)

    expected_coverage = (metrics["n_evaluated"] - cm["flagged_human"]) / metrics["n_evaluated"]
    assert metrics["coverage"] == pytest.approx(expected_coverage, abs=1e-4)


# --- evidence documents -----------------------------------------------------------------
# The bundle's source_ref values used to resolve to nothing. These pin that they now open,
# and that opening one cannot become a way to show text the engine never scored.


def test_evidence_document_opens_the_record_behind_a_source_ref(client):
    response = client.get("/disputes/disp_synthetic_9001/evidence/0/document")
    assert response.status_code == 200

    doc = response.json()
    assert doc["source_ref"] == "pod_9001"
    assert doc["kind"] == "proof_of_delivery"
    assert doc["evidence_index"] == 0
    assert doc["system_of_record"]


def test_document_body_matches_the_evidence_the_engine_scored(client):
    detail = client.get("/disputes/disp_synthetic_9001").json()
    scored = detail["dispute"]["evidence_bundle"][0]["content"]

    doc = client.get("/disputes/disp_synthetic_9001/evidence/0/document").json()
    assert doc["body"] == scored, "the document must not reword or extend the evidence"


def test_document_hash_is_verifiable_by_the_reader(client):
    import hashlib

    doc = client.get("/disputes/disp_synthetic_9001/evidence/0/document").json()
    assert doc["content_hash"] == hashlib.sha256(doc["body"].encode("utf-8")).hexdigest()


def test_evidence_without_a_source_ref_still_opens(client):
    response = client.get("/disputes/disp_synthetic_9002/evidence/0/document")
    assert response.status_code == 200
    assert response.json()["source_ref"] is None


def test_out_of_range_evidence_index_is_404_not_500(client):
    assert client.get("/disputes/disp_synthetic_9001/evidence/99/document").status_code == 404


def test_unknown_dispute_evidence_is_404(client):
    assert client.get("/disputes/disp_nope/evidence/0/document").status_code == 404


def test_evidence_downloads_as_an_attachment(client):
    response = client.get("/disputes/disp_synthetic_9001/evidence/0/download")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert "pod_9001.txt" in response.headers["content-disposition"]

    body = response.text
    assert "The recipient signed for the parcel" in body
    assert "Synthetic record" in body, "an exported record must carry its own disclaimer"


# --- risk-budget calibration -----------------------------------------------------------


def test_calibration_and_empirical_verification_are_callable(client):
    calibrated = client.post("/calibrate", json={"alpha": 0.75, "delta": 0.1})
    assert calibrated.status_code == 200, calibrated.text
    result = calibrated.json()
    assert result["achievable"] is True
    assert result["calibrated_threshold"] is not None
    assert result["calibration_set_size"] > 0

    checked = client.get("/verify-guarantee")
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["alpha"] == 0.75
    assert body["n_test"] > 0
    assert body["n_contested"] >= 0


def test_unachievable_budget_is_explicitly_not_evaluable(client):
    calibrated = client.post("/calibrate", json={"alpha": 0.05, "delta": 0.1})
    assert calibrated.status_code == 200, calibrated.text
    assert calibrated.json()["achievable"] is False

    checked = client.get("/verify-guarantee").json()
    assert checked["observed_fp_rate_on_test"] is None
    assert checked["guarantee_held"] is None
    assert checked["n_contested"] == 0

    # Leave the module-scoped app usable for later tests or interactive debugging.
    assert client.post("/calibrate", json={"alpha": 0.75, "delta": 0.1}).status_code == 200


# --- backing a dispute with a real test-mode payment -------------------------------------
# Razorpay is stubbed here: the suite must not make network calls, and the behaviour worth
# pinning is ours -- when we do and do not claim a payment is real.


class FakeRazorpay:
    """Stands in for RazorpayClient, recording what it was asked to do."""

    def __init__(self, payments=None, order_status="created"):
        self.payments = payments or []
        self.order_status = order_status
        self.created_orders = []

    def create_backing_order(self, amount_paise, receipt):
        order_id = f"order_FAKE{len(self.created_orders)}"
        self.created_orders.append((order_id, amount_paise, receipt))
        return {"id": order_id, "amount": amount_paise, "currency": "INR",
                "status": self.order_status}

    def fetch_order(self, order_id):
        return {"id": order_id, "amount": 249900, "currency": "INR",
                "status": self.order_status}

    def fetch_order_payments(self, order_id):
        return self.payments


@pytest.fixture
def unbacked_dispute():
    """Return disp_synthetic_9002 to its unbacked state before and after each test.

    The database is module-scoped, so without this a test that promotes a payment would
    silently change what later tests see -- and the failure would look like a bug in the
    endpoint rather than in the fixtures.
    """
    dispute_id = "disp_synthetic_9002"

    def reset():
        with _session_factory() as session:
            row = session.get(DisputeRow, dispute_id)
            row.payment_id = "pay_PENDING_9002"
            row.razorpay_order_id = None
            session.commit()

    reset()
    yield dispute_id
    reset()


@pytest.fixture
def fake_razorpay(monkeypatch):
    def install(**kwargs):
        fake = FakeRazorpay(**kwargs)
        monkeypatch.setattr("app.api.routes.get_razorpay_client", lambda: fake)
        return fake

    return install


def test_backing_order_is_created_for_a_placeholder_payment(client, fake_razorpay, unbacked_dispute):
    fake = fake_razorpay()
    response = client.post("/disputes/disp_synthetic_9002/backing-order")
    assert response.status_code == 200

    body = response.json()
    assert body["order_id"].startswith("order_")
    assert body["reused"] is False
    assert len(fake.created_orders) == 1


def test_backing_order_exposes_only_the_publishable_key(client, fake_razorpay, unbacked_dispute):
    """The secret must never reach the browser. Asserted against the raw response body,
    not just the parsed keys, so it cannot leak inside some other field."""
    import json

    from app.config import get_settings

    fake_razorpay()
    response = client.post("/disputes/disp_synthetic_9002/backing-order")
    body = response.json()

    assert body["key_id"].startswith("rzp_test_")
    assert body["key_id"] == get_settings().razorpay_key_id
    assert get_settings().razorpay_key_secret not in response.text
    assert "secret" not in json.dumps(body).lower()


def test_a_second_request_reuses_the_existing_order(client, fake_razorpay, unbacked_dispute):
    """Otherwise every button press litters the Razorpay account with a new order."""
    fake = fake_razorpay()
    client.post("/disputes/disp_synthetic_9002/backing-order")
    second = client.post("/disputes/disp_synthetic_9002/backing-order").json()
    assert second["reused"] is True
    assert len(fake.created_orders) == 1


def test_an_already_backed_dispute_refuses_a_new_order(client, fake_razorpay):
    fake_razorpay()
    response = client.post("/disputes/disp_synthetic_9001/backing-order")
    assert response.status_code == 409


def test_status_reports_real_for_a_dispute_that_already_has_one(client, fake_razorpay):
    fake_razorpay()
    body = client.get("/disputes/disp_synthetic_9001/backing-status").json()
    assert body["payment_is_real"] is True
    assert body["payment_id"] == "pay_TUSjwsBKtOQpWj"


def test_no_payment_is_claimed_before_checkout_completes(client, fake_razorpay, unbacked_dispute):
    fake_razorpay(payments=[])
    client.post("/disputes/disp_synthetic_9002/backing-order")
    body = client.get("/disputes/disp_synthetic_9002/backing-status").json()
    assert body["payment_is_real"] is False
    assert body["payment_id"].startswith("pay_PENDING_")


def test_a_failed_payment_attempt_is_never_promoted(client, fake_razorpay, unbacked_dispute):
    """A dead id on the dispute would make the 'real payment' claim false -- which is the
    one thing this whole flow exists to make true."""
    fake_razorpay(payments=[{"id": "pay_FAILED1", "status": "failed"}])
    client.post("/disputes/disp_synthetic_9002/backing-order")
    body = client.get("/disputes/disp_synthetic_9002/backing-status").json()
    assert body["payment_is_real"] is False
    assert body["payments_seen"] == 1
    assert "pay_FAILED1" not in body["payment_id"]


@pytest.mark.parametrize("state", ["captured", "authorized"])
def test_a_completed_payment_is_promoted_onto_the_dispute(client, fake_razorpay, unbacked_dispute, state):
    fake_razorpay(payments=[{"id": f"pay_REAL_{state}", "status": state}])
    client.post("/disputes/disp_synthetic_9002/backing-order")

    body = client.get("/disputes/disp_synthetic_9002/backing-status").json()
    assert body["payment_is_real"] is True
    assert body["payment_id"] == f"pay_REAL_{state}"

    # and it sticks, on the dispute itself
    detail = client.get("/disputes/disp_synthetic_9002").json()
    assert detail["dispute"]["payment_id"] == f"pay_REAL_{state}"
    assert detail["payment_is_real"] is True


