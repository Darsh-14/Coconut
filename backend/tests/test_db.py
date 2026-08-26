"""Persistence-layer tests (CLAUDE.md Section 13, phase 4).

Runs against a throwaway SQLite file so the developer's recourse.db is never touched.

The load-bearing test is test_held_out_records_are_never_seeded: the working/held-out split
is only meaningful if held-out records genuinely cannot reach the queue, and a structural
check is worth more than a convention.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import BACKEND_ROOT
from app.db.database import Base
from app.db.models import AuditLogRow, DecisionRow, DisputeRow, as_utc
from app.models.schemas import ClaimVerdict, Decision, Dispute, EvidenceItem


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as s:
        yield s
    engine.dispose()


def make_dispute(dispute_id: str = "disp_synthetic_0001") -> Dispute:
    raised = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    return Dispute(
        dispute_id=dispute_id,
        payment_id="pay_PENDING_0001",
        phase="chargeback",
        reason_code="goods_not_received",
        claim_text="Cardholder asserts the merchandise was never delivered.",
        amount=249900,
        raised_at=raised,
        respond_by=raised + timedelta(days=21),
        evidence_bundle=[
            EvidenceItem(type="delivery_proof", content="Signed for on 14 July.", source_ref="pod_1"),
            EvidenceItem(type="order_history", content="Nine prior orders."),
        ],
        ground_truth_label="contest_win",
    )


# -- round-tripping --------------------------------------------------------------------


def test_dispute_round_trips_through_the_database(session):
    original = make_dispute()
    session.add(DisputeRow.from_schema(original))
    session.commit()

    row = session.get(DisputeRow, original.dispute_id)
    restored = row.to_schema()

    assert restored.dispute_id == original.dispute_id
    assert restored.amount == original.amount
    assert restored.claim_text == original.claim_text
    assert len(restored.evidence_bundle) == 2
    assert restored.evidence_bundle[0].type == "delivery_proof"
    assert restored.evidence_bundle[0].source_ref == "pod_1"
    assert restored.ground_truth_label == "contest_win"


def test_timestamps_come_back_timezone_aware(session):
    """SQLite drops tzinfo; a naive datetime would serialise without an offset in the API."""
    original = make_dispute()
    session.add(DisputeRow.from_schema(original))
    session.commit()

    restored = session.get(DisputeRow, original.dispute_id).to_schema()
    assert restored.raised_at.tzinfo is not None
    assert restored.respond_by.tzinfo is not None
    assert restored.raised_at == original.raised_at


def test_as_utc_leaves_aware_datetimes_alone():
    aware = datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert as_utc(aware) is aware
    assert as_utc(None) is None


def test_decision_round_trips(session):
    dispute = make_dispute()
    session.add(DisputeRow.from_schema(dispute))
    session.commit()

    decision = Decision(
        dispute_id=dispute.dispute_id,
        recommendation="CONTEST",
        confidence=0.81,
        claim_verdicts=[
            ClaimVerdict(evidence_index=0, label="support", confidence=0.9, highlighted_span="Signed for."),
            ClaimVerdict(evidence_index=1, label="support", confidence=0.81),
        ],
        drafted_packet="Draft text.",
        decided_at=datetime.now(timezone.utc),
    )
    session.add(DecisionRow.from_schema(decision, rationale="because"))
    session.commit()

    row = session.query(DecisionRow).one()
    restored = row.to_schema()
    assert restored.recommendation == "CONTEST"
    assert restored.confidence == 0.81
    assert len(restored.claim_verdicts) == 2
    assert restored.claim_verdicts[0].highlighted_span == "Signed for."
    assert row.rationale == "because"


# -- computed status (Section 8) -------------------------------------------------------


def _add_decision(session, dispute_id: str) -> DecisionRow:
    row = DecisionRow(
        dispute_id=dispute_id,
        recommendation="CONTEST",
        confidence=0.8,
        claim_verdicts=[],
        decided_at=datetime.now(timezone.utc),
        model_version="test",
    )
    session.add(row)
    session.commit()
    return row


def test_status_is_pending_without_a_decision(session):
    session.add(DisputeRow.from_schema(make_dispute()))
    session.commit()
    assert session.get(DisputeRow, "disp_synthetic_0001").computed_status() == "pending"


def test_status_is_decided_after_a_decision(session):
    session.add(DisputeRow.from_schema(make_dispute()))
    session.commit()
    _add_decision(session, "disp_synthetic_0001")
    session.expire_all()
    assert session.get(DisputeRow, "disp_synthetic_0001").computed_status() == "decided"


def test_status_is_approved_then_submitted(session):
    session.add(DisputeRow.from_schema(make_dispute()))
    session.commit()
    decision = _add_decision(session, "disp_synthetic_0001")

    entry = AuditLogRow(
        dispute_id="disp_synthetic_0001",
        decision_id=decision.id,
        approved_by_human=True,
        approved_at=datetime.now(timezone.utc),
        submitted_to_razorpay=False,
    )
    session.add(entry)
    session.commit()
    session.expire_all()
    assert session.get(DisputeRow, "disp_synthetic_0001").computed_status() == "approved"

    entry.submitted_to_razorpay = True
    session.commit()
    session.expire_all()
    assert session.get(DisputeRow, "disp_synthetic_0001").computed_status() == "submitted"


def test_rejected_approval_does_not_count_as_approved(session):
    """approved=false must leave the dispute in `decided`, not advance it."""
    session.add(DisputeRow.from_schema(make_dispute()))
    session.commit()
    decision = _add_decision(session, "disp_synthetic_0001")
    session.add(
        AuditLogRow(
            dispute_id="disp_synthetic_0001",
            decision_id=decision.id,
            approved_by_human=False,
        )
    )
    session.commit()
    session.expire_all()
    assert session.get(DisputeRow, "disp_synthetic_0001").computed_status() == "decided"


# -- audit log -------------------------------------------------------------------------


def test_audit_entry_stores_the_would_be_payload(session):
    session.add(DisputeRow.from_schema(make_dispute()))
    session.commit()
    decision = _add_decision(session, "disp_synthetic_0001")

    payload = {"method": "PATCH", "path": "/v1/disputes/disp_synthetic_0001/contest"}
    session.add(
        AuditLogRow(
            dispute_id="disp_synthetic_0001",
            decision_id=decision.id,
            approved_by_human=True,
            approved_at=datetime.now(timezone.utc),
            submitted_to_razorpay=True,
            would_be_razorpay_payload=payload,
        )
    )
    session.commit()

    entry = session.query(AuditLogRow).one().to_schema()
    assert entry.would_be_razorpay_payload == payload
    assert entry.submitted_to_razorpay is True
    assert entry.approved_by_human is True


def test_edited_packet_overrides_the_drafted_packet_in_the_audit_view(session):
    """A human's edit is what was approved, so that is what the audit entry must show."""
    session.add(DisputeRow.from_schema(make_dispute()))
    session.commit()
    decision = DecisionRow(
        dispute_id="disp_synthetic_0001",
        recommendation="CONTEST",
        confidence=0.8,
        claim_verdicts=[],
        drafted_packet="Original draft.",
        decided_at=datetime.now(timezone.utc),
        model_version="test",
    )
    session.add(decision)
    session.commit()
    session.add(
        AuditLogRow(
            dispute_id="disp_synthetic_0001",
            decision_id=decision.id,
            approved_by_human=True,
            edited_packet="Human-edited text.",
        )
    )
    session.commit()

    assert session.query(AuditLogRow).one().to_schema().decision.drafted_packet == (
        "Human-edited text."
    )


def test_deleting_a_dispute_cascades(session):
    session.add(DisputeRow.from_schema(make_dispute()))
    session.commit()
    decision = _add_decision(session, "disp_synthetic_0001")
    session.add(
        AuditLogRow(dispute_id="disp_synthetic_0001", decision_id=decision.id)
    )
    session.commit()

    session.delete(session.get(DisputeRow, "disp_synthetic_0001"))
    session.commit()

    assert session.query(DecisionRow).count() == 0
    assert session.query(AuditLogRow).count() == 0


# -- the held-out guarantee ------------------------------------------------------------


def test_held_out_records_are_never_seeded():
    """The seeder must load only the working set, structurally excluding held-out data."""
    from app.db import seed as seed_module

    assert seed_module.WORKING_SET.name == "synthetic_disputes.json"
    source = (BACKEND_ROOT / "app" / "db" / "seed.py").read_text(encoding="utf-8")
    assert "held_out_set.json" not in source.replace("held_out_set.json is", "")

    working = {d["dispute_id"] for d in json.loads(seed_module.WORKING_SET.read_text("utf-8"))}
    held_out_path = BACKEND_ROOT / "eval" / "held_out_set.json"
    held_out = {d["dispute_id"] for d in json.loads(held_out_path.read_text("utf-8"))}
    assert not (working & held_out), "working and held-out sets share dispute ids"
