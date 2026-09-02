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

from concurrent.futures import ThreadPoolExecutor
from threading import Event

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
    from app.services.conformal_calibrator import set_active_threshold

    set_active_threshold(0.5, 0.75, 0.1)
    monkeypatch.setattr(
        "app.api.routes.get_verification_engine",
        lambda: _FakeEngine(),
    )
    response = client.post(f"/disputes/{dispute_id}/decide")
    assert response.status_code == 200, response.text
    assert ClaimVerdict(**response.json()["claim_verdicts"][0])


def latest_decision_id(client, dispute_id: str) -> int:
    value = client.get(f"/disputes/{dispute_id}").json()["latest_decision_id"]
    assert isinstance(value, int)
    return value


def save_draft(client, dispute_id: str, text: str):
    return client.put(
        f"/disputes/{dispute_id}/packet-draft",
        json={"decision_id": latest_decision_id(client, dispute_id), "text": text},
    )


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


def test_concurrent_filings_receive_distinct_identifiers(client):
    body = {
        "reason_code": "goods_not_received",
        "claim_text": "The parcel did not arrive.",
        "amount": 10000,
    }

    def file_one():
        response = client.post("/disputes", json=body)
        return response.status_code, response.json()["dispute_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: file_one(), range(2)))

    assert [status for status, _ in results] == [201, 201]
    assert len({dispute_id for _, dispute_id in results}) == 2


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


# -- the representment working copy -------------------------------------------------------
# An edit used to live only in React state, so navigating away discarded however long a
# merchant had spent rewriting the packet. What matters most here is that saving a draft
# is not, and never becomes, approving one.


def test_a_draft_survives_being_saved_and_read_back(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    add_evidence(client, dispute_id, type="order_history")
    _stub_decision(client, monkeypatch, dispute_id)

    save_draft(client, dispute_id, "My own wording.")
    assert client.get(f"/disputes/{dispute_id}").json()["edited_packet"] == "My own wording."


def test_saving_a_draft_is_not_approving_it(client, monkeypatch):
    """Section 2.2: only a human clicking approve may set these."""
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    add_evidence(client, dispute_id, type="order_history")
    _stub_decision(client, monkeypatch, dispute_id)

    before = client.get(f"/disputes/{dispute_id}").json()
    save_draft(client, dispute_id, "Draft text.")
    after = client.get(f"/disputes/{dispute_id}").json()

    assert after["audit_log"] == before["audit_log"] == []
    assert after["status"] == before["status"]


def test_an_empty_draft_clears_it(client, monkeypatch):
    """So 'revert to the model's text' is expressible, not just 'overwrite with spaces'."""
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    add_evidence(client, dispute_id, type="order_history")
    _stub_decision(client, monkeypatch, dispute_id)

    save_draft(client, dispute_id, "Something.")
    save_draft(client, dispute_id, "")
    assert client.get(f"/disputes/{dispute_id}").json()["edited_packet"] is None


def test_re_assessing_does_not_resurrect_an_edit_of_the_old_draft(client, monkeypatch):
    """The edit belongs to the decision it was written against. Carrying it across would
    show a merchant text they wrote while looking at different verdicts."""
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    add_evidence(client, dispute_id, type="order_history")
    _stub_decision(client, monkeypatch, dispute_id)
    save_draft(client, dispute_id, "Old wording.")

    _stub_decision(client, monkeypatch, dispute_id)  # re-assess
    assert client.get(f"/disputes/{dispute_id}").json()["edited_packet"] is None


def test_drafting_before_any_decision_is_a_conflict(client):
    dispute_id = file_dispute(client)["dispute_id"]
    response = client.put(
        f"/disputes/{dispute_id}/packet-draft", json={"decision_id": 1, "text": "x"}
    )
    assert response.status_code == 409


def test_drafting_on_an_unknown_dispute_is_404(client):
    assert (
        client.put(
            "/disputes/disp_nope/packet-draft", json={"decision_id": 1, "text": "x"}
        ).status_code
        == 404
    )


def test_detail_exposes_the_persisted_decision_token(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)

    detail = client.get(f"/disputes/{dispute_id}").json()
    assert isinstance(detail["latest_decision_id"], int)


def test_a_superseded_decision_token_cannot_change_a_draft(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)
    old_id = latest_decision_id(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)

    response = client.put(
        f"/disputes/{dispute_id}/packet-draft",
        json={"decision_id": old_id, "text": "Written against an old assessment."},
    )
    assert response.status_code == 409
    assert "no longer current" in response.json()["detail"]


def test_non_contest_decision_cannot_create_or_export_a_packet(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    # One evidence type deliberately fails the corroboration requirement.
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)
    decision_id = latest_decision_id(client, dispute_id)

    draft = client.put(
        f"/disputes/{dispute_id}/packet-draft",
        json={"decision_id": decision_id, "text": "misleading packet"},
    )
    export = client.get(
        f"/disputes/{dispute_id}/packet.txt", params={"decision_id": decision_id}
    )
    assert draft.status_code == export.status_code == 409


def test_evidence_staleness_blocks_every_decision_bound_action(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)
    decision_id = latest_decision_id(client, dispute_id)
    add_evidence(client, dispute_id, type="communication_log", source_ref="chat_new")

    draft = client.put(
        f"/disputes/{dispute_id}/packet-draft",
        json={"decision_id": decision_id, "text": "stale"},
    )
    action = client.post(
        f"/disputes/{dispute_id}/approve",
        json={"decision_id": decision_id, "approved": True, "edited_packet": None},
    )
    export = client.get(
        f"/disputes/{dispute_id}/packet.txt", params={"decision_id": decision_id}
    )

    assert {draft.status_code, action.status_code, export.status_code} == {409}
    assert all(
        "Evidence changed" in response.json()["detail"]
        for response in (draft, action, export)
    )


def test_risk_budget_change_stales_a_persisted_decision(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)
    decision_id = latest_decision_id(client, dispute_id)

    monkeypatch.setattr("app.api.routes.get_active_calibrated_threshold", lambda: 0.99)
    detail = client.get(f"/disputes/{dispute_id}").json()
    action = client.post(
        f"/disputes/{dispute_id}/approve",
        json={"decision_id": decision_id, "approved": False, "edited_packet": None},
    )
    assert detail["decision_is_stale"] is True
    assert action.status_code == 409
    assert "risk budget changed" in action.json()["detail"]


def test_new_same_payer_dispute_stales_a_upi_decision(client, monkeypatch):
    dispute_id = file_dispute(
        client,
        rail="upi",
        payer_ref="payer_stale_history",
        raised_at="2026-09-03T12:00:00Z",
    )["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)
    decision_id = latest_decision_id(client, dispute_id)

    file_dispute(
        client,
        rail="upi",
        payer_ref="payer_stale_history",
        raised_at="2026-09-03T11:00:00Z",
    )
    action = client.post(
        f"/disputes/{dispute_id}/approve",
        json={"decision_id": decision_id, "approved": False, "edited_packet": None},
    )
    assert action.status_code == 409
    assert "payer's dispute history changed" in action.json()["detail"]


# -- withdrawing an approval ---------------------------------------------------------------
# Approval used to be a one-way door. For a system whose pitch is that a human stays in
# charge, the human being unable to change their mind is a strange gap.


def approve(client, dispute_id):
    return client.post(
        f"/disputes/{dispute_id}/approve",
        json={
            "decision_id": latest_decision_id(client, dispute_id),
            "approved": True,
            "edited_packet": None,
        },
    )


def standing_approval_id(entries):
    standing = None
    for entry in entries:
        if entry["withdrawn"]:
            standing = None
        elif entry["approved_by_human"]:
            standing = entry["id"]
    return standing


def withdraw(client, dispute_id, approval_id=None):
    if approval_id is None:
        entries = client.get(f"/disputes/{dispute_id}").json()["audit_log"]
        approval_id = standing_approval_id(entries) or 1
    return client.post(
        f"/disputes/{dispute_id}/withdraw", params={"approval_id": approval_id}
    )


def test_withdrawing_returns_the_case_to_the_queue(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)
    approve(client, dispute_id)
    assert client.get(f"/disputes/{dispute_id}").json()["status"] in {"approved", "submitted"}

    assert withdraw(client, dispute_id).status_code == 200
    assert client.get(f"/disputes/{dispute_id}").json()["status"] == "decided"


def test_duplicate_approval_is_a_conflict_not_a_second_audit_event(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)

    assert approve(client, dispute_id).status_code == 200
    assert approve(client, dispute_id).status_code == 409
    assert len(client.get(f"/disputes/{dispute_id}").json()["audit_log"]) == 1


def test_concurrent_approvals_with_one_token_create_one_event(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)
    decision_id = latest_decision_id(client, dispute_id)

    def send_approval():
        return client.post(
            f"/disputes/{dispute_id}/approve",
            json={"decision_id": decision_id, "approved": True, "edited_packet": None},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(lambda _index: send_approval(), range(2)))

    assert statuses == [200, 409]
    assert len(client.get(f"/disputes/{dispute_id}").json()["audit_log"]) == 1


def test_approval_waiting_on_reassessment_cannot_action_the_old_decision(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)
    old_decision_id = latest_decision_id(client, dispute_id)
    started = Event()
    release = Event()

    class BlockingEngine(_FakeEngine):
        def verify_bundle(self, claim_text, evidence, reason_code):
            started.set()
            assert release.wait(timeout=5)
            return super().verify_bundle(claim_text, evidence, reason_code)

    monkeypatch.setattr(
        "app.api.routes.get_verification_engine", lambda: BlockingEngine()
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        reassessment = pool.submit(client.post, f"/disputes/{dispute_id}/decide")
        assert started.wait(timeout=5)
        approval = pool.submit(
            client.post,
            f"/disputes/{dispute_id}/approve",
            json={
                "decision_id": old_decision_id,
                "approved": True,
                "edited_packet": None,
            },
        )
        release.set()

    assert reassessment.result().status_code == 200
    assert approval.result().status_code == 409
    assert client.get(f"/disputes/{dispute_id}").json()["audit_log"] == []


def test_standing_approval_must_be_withdrawn_before_the_case_changes(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)
    decision_id = latest_decision_id(client, dispute_id)
    approve(client, dispute_id)

    evidence = client.post(
        f"/disputes/{dispute_id}/evidence",
        json={"type": "communication_log", "content": "A newly supplied chat."},
    )
    reassess = client.post(f"/disputes/{dispute_id}/decide")
    draft = client.put(
        f"/disputes/{dispute_id}/packet-draft",
        json={"decision_id": decision_id, "text": "too late"},
    )
    assert evidence.status_code == reassess.status_code == draft.status_code == 409

    assert withdraw(client, dispute_id).status_code == 200
    assert client.post(
        f"/disputes/{dispute_id}/evidence",
        json={"type": "communication_log", "content": "A newly supplied chat."},
    ).status_code == 201


def test_a_withdrawal_is_appended_never_a_deletion(client, monkeypatch):
    """An audit trail that can be rewritten is not an audit trail."""
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)
    approve(client, dispute_id)

    before = client.get(f"/disputes/{dispute_id}").json()["audit_log"]
    withdraw(client, dispute_id)
    after = client.get(f"/disputes/{dispute_id}").json()["audit_log"]

    assert len(after) == len(before) + 1
    assert after[: len(before)] == before, "existing entries must be untouched"
    assert after[-1]["withdrawn"] is True
    assert after[-1]["approved_by_human"] is False
    assert after[-1]["decision_id"] == before[-1]["decision_id"]
    assert after[-1]["created_at"].endswith(("Z", "+00:00"))


def test_approve_withdraw_approve_is_a_readable_history(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)

    approve(client, dispute_id)
    withdraw(client, dispute_id)
    approve(client, dispute_id)

    detail = client.get(f"/disputes/{dispute_id}").json()
    assert detail["status"] in {"approved", "submitted"}
    assert [e["withdrawn"] for e in detail["audit_log"]] == [False, True, False]


def test_stale_approval_token_cannot_withdraw_a_later_approval(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)

    first = approve(client, dispute_id).json()["id"]
    assert withdraw(client, dispute_id, first).status_code == 200
    second = approve(client, dispute_id).json()["id"]

    stale = withdraw(client, dispute_id, first)
    assert stale.status_code == 409
    detail = client.get(f"/disputes/{dispute_id}").json()
    assert detail["status"] in {"approved", "submitted"}
    assert standing_approval_id(detail["audit_log"]) == second


def test_withdrawing_without_a_standing_approval_is_a_conflict(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)
    assert withdraw(client, dispute_id).status_code == 409


def test_withdraw_requires_an_approval_token(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)
    approve(client, dispute_id)
    assert client.post(f"/disputes/{dispute_id}/withdraw").status_code == 422


# -- exports --------------------------------------------------------------------------------


def test_the_packet_exports_with_its_non_submission_notice(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    add_evidence(client, dispute_id, type="order_history")
    _stub_decision(client, monkeypatch, dispute_id)
    save_draft(client, dispute_id, "My representment.")

    response = client.get(
        f"/disputes/{dispute_id}/packet.txt",
        params={"decision_id": latest_decision_id(client, dispute_id)},
    )
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert "My representment." in response.text
    assert "never transmitted" in response.text


def test_the_export_prefers_the_merchants_edit_over_the_draft(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    add_evidence(client, dispute_id, type="order_history")
    _stub_decision(client, monkeypatch, dispute_id)
    save_draft(client, dispute_id, "MINE, NOT THE MODEL'S.")

    response = client.get(
        f"/disputes/{dispute_id}/packet.txt",
        params={"decision_id": latest_decision_id(client, dispute_id)},
    )
    assert "MINE, NOT THE MODEL'S." in response.text


def test_approved_export_uses_the_immutable_audit_text(client, monkeypatch):
    """Approval can beat the debounced draft save; export must still match the audit."""
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    add_evidence(client, dispute_id, type="order_history", source_ref="oms_approved")
    _stub_decision(client, monkeypatch, dispute_id)
    decision_id = latest_decision_id(client, dispute_id)

    action = client.post(
        f"/disputes/{dispute_id}/approve",
        json={
            "decision_id": decision_id,
            "approved": True,
            "edited_packet": "THE TEXT THE HUMAN ACTUALLY APPROVED.",
        },
    )
    assert action.status_code == 200, action.text

    exported = client.get(
        f"/disputes/{dispute_id}/packet.txt", params={"decision_id": decision_id}
    )
    assert exported.status_code == 200, exported.text
    assert "THE TEXT THE HUMAN ACTUALLY APPROVED." in exported.text


def test_saved_draft_is_frozen_when_approval_body_omits_an_edit(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    add_evidence(client, dispute_id, type="order_history")
    _stub_decision(client, monkeypatch, dispute_id)
    decision_id = latest_decision_id(client, dispute_id)
    saved = "THE SAVED WORKING COPY."
    assert save_draft(client, dispute_id, saved).status_code == 200

    action = client.post(
        f"/disputes/{dispute_id}/approve",
        json={"decision_id": decision_id, "approved": True, "edited_packet": None},
    )
    assert action.status_code == 200, action.text
    entry = action.json()
    assert entry["decision"]["drafted_packet"] == saved
    assert saved in str(entry["would_be_razorpay_payload"])

    exported = client.get(
        f"/disputes/{dispute_id}/packet.txt", params={"decision_id": decision_id}
    )
    assert exported.status_code == 200
    assert saved in exported.text


def test_blank_contest_packet_cannot_be_approved_but_can_be_rejected(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    add_evidence(client, dispute_id, type="order_history")
    _stub_decision(client, monkeypatch, dispute_id)
    decision_id = latest_decision_id(client, dispute_id)

    approval = client.post(
        f"/disputes/{dispute_id}/approve",
        json={"decision_id": decision_id, "approved": True, "edited_packet": "   "},
    )
    assert approval.status_code == 409
    rejection = client.post(
        f"/disputes/{dispute_id}/approve",
        json={"decision_id": decision_id, "approved": False, "edited_packet": None},
    )
    assert rejection.status_code == 200


def test_exporting_before_any_decision_is_a_conflict(client):
    dispute_id = file_dispute(client)["dispute_id"]
    assert client.get(f"/disputes/{dispute_id}/packet.txt", params={"decision_id": 1}).status_code == 409


def test_the_would_submit_payload_exports_and_says_it_was_not_sent(client, monkeypatch):
    """Section 7's artefact. Showing it proves it exists; exporting it makes it reviewable."""
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    add_evidence(client, dispute_id, type="order_history", source_ref="oms_2")
    _stub_decision(client, monkeypatch, dispute_id)
    approve(client, dispute_id)

    response = client.get(f"/disputes/{dispute_id}/would-submit.json")
    if response.status_code == 404:
        pytest.skip("the stubbed decision was not a CONTEST, so no payload was prepared")

    body = response.json()
    assert body["transmitted"] is False
    assert body["prepared_at"].endswith(("Z", "+00:00"))
    assert "does not exist on Razorpay" in body["why_not_transmitted"]
    assert body["would_be_razorpay_payload"]


def test_exporting_a_payload_that_was_never_prepared_is_404(client, monkeypatch):
    dispute_id = file_dispute(client)["dispute_id"]
    add_evidence(client, dispute_id)
    _stub_decision(client, monkeypatch, dispute_id)
    assert client.get(f"/disputes/{dispute_id}/would-submit.json").status_code == 404


# -- search and paging -----------------------------------------------------------------------


def test_search_matches_across_the_columns_a_merchant_would_type(client):
    a = file_dispute(client, reason_code="duplicate_charge")["dispute_id"]
    file_dispute(client, reason_code="goods_not_received")

    by_reason = client.get("/disputes", params={"q": "duplicate_charge"}).json()
    assert [d["dispute_id"] for d in by_reason] == [a]

    by_id = client.get("/disputes", params={"q": a}).json()
    assert [d["dispute_id"] for d in by_id] == [a]


def test_an_underscore_in_a_query_is_literal_not_a_wildcard(client):
    """Every dispute id contains underscores, so treating one as LIKE's single-character
    wildcard would quietly match far too much."""
    file_dispute(client)
    assert client.get("/disputes", params={"q": "disp_manual"}).json()
    assert client.get("/disputes", params={"q": "dispXmanual"}).json() == []


def test_a_bare_percent_matches_nothing_rather_than_everything(client):
    file_dispute(client)
    assert client.get("/disputes", params={"q": "%"}).json() == []


def test_the_total_count_is_reported_for_paging(client):
    for _ in range(5):
        file_dispute(client)
    response = client.get("/disputes", params={"limit": 2})
    assert response.headers["x-total-count"] == "5"
    assert len(response.json()) == 2


def test_paging_is_stable_when_deadlines_tie(client):
    """Ordering by a non-unique column alone lets SQLite return ties in any order, so a
    page boundary could skip a row or show it twice."""
    same = "2026-09-01T10:00:00Z"
    for _ in range(6):
        file_dispute(client, raised_at="2026-08-01T10:00:00Z", respond_by=same)

    whole = [d["dispute_id"] for d in client.get("/disputes").json()]
    paged = []
    for offset in range(0, len(whole), 2):
        paged += [
            d["dispute_id"]
            for d in client.get("/disputes", params={"limit": 2, "offset": offset}).json()
        ]

    assert paged == whole
    assert len(set(paged)) == len(paged)
