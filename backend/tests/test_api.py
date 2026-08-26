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
        "/disputes/disp_synthetic_9002/approve", json={"approved": True, "edited_packet": None}
    )
    assert response.status_code == 409


# -- POST /decide (Section 14's required integration test) -----------------------------


@pytest.mark.slow
def test_decide_returns_a_well_formed_decision(client):
    response = client.post("/disputes/disp_synthetic_9001/decide")
    assert response.status_code == 200
    decision = response.json()

    assert decision["dispute_id"] == "disp_synthetic_9001"
    assert decision["recommendation"] in {"CONTEST", "ACCEPT", "NEEDS_HUMAN_REVIEW"}
    assert 0.0 <= decision["confidence"] <= 1.0
    assert decision["model_version"] == "cross-encoder/nli-deberta-v3-base"
    assert decision["decided_at"]

    assert len(decision["claim_verdicts"]) == 2
    for verdict in decision["claim_verdicts"]:
        assert verdict["label"] in {"support", "contradict", "neutral"}
        assert 0.0 <= verdict["confidence"] <= 1.0
    assert [v["evidence_index"] for v in decision["claim_verdicts"]] == [0, 1]


@pytest.mark.slow
def test_decide_persists_and_advances_status(client):
    client.post("/disputes/disp_synthetic_9001/decide")
    detail = client.get("/disputes/disp_synthetic_9001").json()
    assert detail["latest_decision"] is not None
    assert detail["status"] in {"decided", "approved", "submitted"}
    assert detail["decision_rationale"], "the rationale should explain the outcome"


@pytest.mark.slow
def test_highlighted_spans_come_from_the_evidence(client):
    """An explanation that is not verbatim from the evidence is not an explanation."""
    decision = client.post("/disputes/disp_synthetic_9001/decide").json()
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
    decision = client.post("/disputes/disp_synthetic_9001/decide").json()

    response = client.post(
        "/disputes/disp_synthetic_9001/approve",
        json={"approved": True, "edited_packet": None},
    )
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
    client.post("/disputes/disp_synthetic_9001/decide")
    entry = client.post(
        "/disputes/disp_synthetic_9001/approve",
        json={"approved": False, "edited_packet": None},
    ).json()

    assert entry["approved_by_human"] is False
    assert entry["approved_at"] is None
    assert entry["submitted_to_razorpay"] is False
    assert entry["would_be_razorpay_payload"] is None


@pytest.mark.slow
def test_edited_packet_is_what_gets_recorded(client):
    """The human edits the draft; the audit trail must show the edit, not the draft."""
    client.post("/disputes/disp_synthetic_9001/decide")
    entry = client.post(
        "/disputes/disp_synthetic_9001/approve",
        json={"approved": True, "edited_packet": "Counsel-revised representment text."},
    ).json()
    assert entry["decision"]["drafted_packet"] == "Counsel-revised representment text."


@pytest.mark.slow
def test_audit_trail_accumulates(client):
    client.post("/disputes/disp_synthetic_9001/decide")
    client.post(
        "/disputes/disp_synthetic_9001/approve", json={"approved": True, "edited_packet": None}
    )
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
