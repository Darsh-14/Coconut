"""SQLAlchemy ORM models.

Three tables mirroring the Section 6 contracts: the disputes queue, the decisions produced
for them, and the append-only audit log.

Only the WORKING set is ever seeded into this database. eval/held_out_set.json is read
directly by /evaluate and never enters the queue -- keeping it out of the DB is a structural
guarantee against the held-out records leaking into development (CLAUDE.md Section 9).

Timestamps are stored as UTC. SQLite has no native timezone type, so values come back naive;
`as_utc()` re-attaches UTC on read rather than letting a naive datetime escape into API
responses where it would serialise without an offset.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.database import Base
from app.models.schemas import (
    AuditLogEntry,
    ClaimVerdict,
    Decision,
    Dispute,
    EvidenceItem,
    URCSForecast,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Re-attach UTC to a naive datetime read back from SQLite."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class DisputeRow(Base):
    """A synthetic dispute in the merchant's queue."""

    __tablename__ = "disputes"

    dispute_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # paise
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    raised_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    respond_by: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    evidence_bundle: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    ground_truth_label: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Addendum 2. `rail` defaults so a database written before this column existed still
    # reads back as card-rail rather than failing.
    rail: Mapped[str] = mapped_column(String(8), nullable=False, default="card")
    payer_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # The real test-mode order created to back this dispute with a genuine payment
    # (Section 7). Set when a merchant starts the backing flow; the resulting pay_... id
    # replaces the pay_PENDING_ placeholder in payment_id once Razorpay reports it.
    razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Bumped whenever the evidence bundle changes. A ClaimVerdict joins to evidence by
    # INDEX, so mutating the bundle silently re-points every standing verdict at the wrong
    # item -- a verdict about a courier POD suddenly labelling a chat transcript. Recording
    # the revision on both sides makes that detectable instead of invisible.
    evidence_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    decisions: Mapped[list["DecisionRow"]] = relationship(
        back_populates="dispute",
        cascade="all, delete-orphan",
        order_by="DecisionRow.decided_at",
    )
    audit_entries: Mapped[list["AuditLogRow"]] = relationship(
        back_populates="dispute",
        cascade="all, delete-orphan",
        order_by="AuditLogRow.id",
    )

    __table_args__ = (
        Index("ix_disputes_respond_by", "respond_by"),
        # The URCS cap counters filter by payer on every /decide.
        Index("ix_disputes_payer_ref", "payer_ref"),
    )

    # -- conversion ---------------------------------------------------------

    @classmethod
    def from_schema(cls, dispute: Dispute) -> "DisputeRow":
        return cls(
            dispute_id=dispute.dispute_id,
            payment_id=dispute.payment_id,
            phase=dispute.phase,
            reason_code=dispute.reason_code,
            claim_text=dispute.claim_text,
            amount=dispute.amount,
            currency=dispute.currency,
            raised_at=dispute.raised_at,
            respond_by=dispute.respond_by,
            evidence_bundle=[e.model_dump() for e in dispute.evidence_bundle],
            ground_truth_label=dispute.ground_truth_label,
            rail=dispute.rail,
            payer_ref=dispute.payer_ref,
        )

    def to_schema(self) -> Dispute:
        return Dispute(
            dispute_id=self.dispute_id,
            payment_id=self.payment_id,
            phase=self.phase,
            reason_code=self.reason_code,
            claim_text=self.claim_text,
            amount=self.amount,
            currency=self.currency,
            raised_at=as_utc(self.raised_at),
            respond_by=as_utc(self.respond_by),
            evidence_bundle=[EvidenceItem(**e) for e in self.evidence_bundle],
            ground_truth_label=self.ground_truth_label,
            rail=self.rail or "card",
            payer_ref=self.payer_ref,
        )

    def evidence_items(self) -> list[EvidenceItem]:
        return [EvidenceItem(**e) for e in self.evidence_bundle]

    @property
    def latest_decision(self) -> Optional["DecisionRow"]:
        return self.decisions[-1] if self.decisions else None

    def computed_status(self) -> str:
        """Section 8's computed status: pending | decided | approved | submitted."""
        if not self.decisions:
            return "pending"
        approved = [a for a in self.audit_entries if a.approved_by_human]
        if any(a.submitted_to_razorpay for a in approved):
            return "submitted"
        if approved:
            return "approved"
        return "decided"


class DecisionRow(Base):
    """A recommendation produced for a dispute. Multiple re-runs are kept, not overwritten."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dispute_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("disputes.dispute_id", ondelete="CASCADE"), nullable=False
    )
    recommendation: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    claim_verdicts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    drafted_packet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    # Addendum 2: the full URCSForecast that was in force when this decision was made.
    # Stored on the decision rather than the audit entry because the audit entry already
    # references a decision -- this way the forecast is available for a NO_ACTION_NEEDED
    # case whether or not a human ever actions it.
    urcs_forecast: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # The dispute's evidence_revision when this decision was computed. If the dispute has
    # moved on, the verdicts no longer describe the current bundle and must not be shown
    # against it.
    evidence_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # A human's in-progress edit of drafted_packet, saved as they type so navigating away
    # does not discard it. Held on the DECISION rather than the dispute: re-assessing
    # produces a new draft, and carrying an edit of the old one across would silently show
    # a merchant text they wrote against different verdicts. Distinct from
    # AuditLogRow.edited_packet, which is the immutable text they actually approved.
    edited_packet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    dispute: Mapped[DisputeRow] = relationship(back_populates="decisions")
    audit_entries: Mapped[list["AuditLogRow"]] = relationship(back_populates="decision")

    __table_args__ = (Index("ix_decisions_dispute_id", "dispute_id"),)

    @classmethod
    def from_schema(
        cls,
        decision: Decision,
        rationale: str = "",
        urcs_forecast: Optional["URCSForecast"] = None,
        evidence_revision: int = 0,
    ) -> "DecisionRow":
        return cls(
            dispute_id=decision.dispute_id,
            recommendation=decision.recommendation,
            confidence=decision.confidence,
            claim_verdicts=[v.model_dump() for v in decision.claim_verdicts],
            drafted_packet=decision.drafted_packet,
            rationale=rationale or None,
            decided_at=decision.decided_at,
            model_version=decision.model_version,
            urcs_forecast=urcs_forecast.model_dump(mode="json") if urcs_forecast else None,
            evidence_revision=evidence_revision,
        )

    def to_schema(self) -> Decision:
        return Decision(
            dispute_id=self.dispute_id,
            recommendation=self.recommendation,
            confidence=self.confidence,
            claim_verdicts=[ClaimVerdict(**v) for v in self.claim_verdicts],
            drafted_packet=self.drafted_packet,
            decided_at=as_utc(self.decided_at),
            model_version=self.model_version,
        )


class AuditLogRow(Base):
    """Append-only record of human approval and what would have been sent to Razorpay.

    `would_be_razorpay_payload` is the honest artefact required by Section 7: the exact
    request we would have made, stored rather than sent, because the dispute is synthetic.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dispute_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("disputes.dispute_id", ondelete="CASCADE"), nullable=False
    )
    decision_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("decisions.id", ondelete="CASCADE"), nullable=False
    )
    approved_by_human: Mapped[bool] = mapped_column(default=False, nullable=False)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    submitted_to_razorpay: Mapped[bool] = mapped_column(default=False, nullable=False)
    would_be_razorpay_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, nullable=True
    )
    edited_packet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    dispute: Mapped[DisputeRow] = relationship(back_populates="audit_entries")
    decision: Mapped[DecisionRow] = relationship(back_populates="audit_entries")

    __table_args__ = (Index("ix_audit_dispute_id", "dispute_id"),)

    def to_schema(self) -> AuditLogEntry:
        decision = self.decision.to_schema()
        if self.edited_packet:
            decision = decision.model_copy(update={"drafted_packet": self.edited_packet})
        return AuditLogEntry(
            id=self.id,
            dispute_id=self.dispute_id,
            decision=decision,
            approved_by_human=self.approved_by_human,
            approved_at=as_utc(self.approved_at),
            submitted_to_razorpay=self.submitted_to_razorpay,
            would_be_razorpay_payload=self.would_be_razorpay_payload,
        )


__all__ = ["AuditLogRow", "DecisionRow", "DisputeRow", "as_utc", "utcnow"]
