"""Pydantic data contracts.

These are transcribed from CLAUDE.md Section 6 and are the authoritative shape of every
object crossing the API boundary. Field names, types and Literal members must not drift
from the spec -- the frontend and the evaluation harness both depend on them exactly.

Validators added here only *reject invalid data*; they never change the contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# --- vocabularies -----------------------------------------------------------------------

EvidenceType = Literal[
    "delivery_proof",
    "communication_log",
    "device_signal",
    "order_history",
    "other",
]

DisputePhase = Literal["fraud", "retrieval", "chargeback", "pre_arbitration", "arbitration"]

GroundTruthLabel = Literal["contest_win", "contest_loss", "should_accept"]

VerdictLabel = Literal["support", "contradict", "neutral"]

Recommendation = Literal["CONTEST", "ACCEPT", "NEEDS_HUMAN_REVIEW"]

# The reason codes Section 9 rotates through. Kept as a tuple (not a Literal) because
# real acquirers emit codes outside any fixed list, and Dispute.reason_code stays a free
# string so ingesting an unknown code degrades gracefully instead of hard-failing.
KNOWN_REASON_CODES: tuple[str, ...] = (
    "goods_not_received",
    "goods_not_as_described",
    "duplicate_charge",
    "unrecognized_transaction",
    "subscription_cancelled",
    "credit_not_processed",
)


# --- core contracts ---------------------------------------------------------------------


class EvidenceItem(BaseModel):
    type: EvidenceType
    content: str
    source_ref: Optional[str] = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("evidence content must not be empty")
        return v


class Dispute(BaseModel):
    dispute_id: str
    payment_id: str  # links to a REAL test-mode Razorpay payment (Section 7)
    phase: DisputePhase
    reason_code: str
    claim_text: str
    amount: int  # paise
    currency: str = "INR"
    raised_at: datetime
    respond_by: datetime
    evidence_bundle: list[EvidenceItem]
    ground_truth_label: Optional[GroundTruthLabel] = None

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount (paise) must be positive")
        return v

    @field_validator("claim_text")
    @classmethod
    def claim_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("claim_text must not be empty")
        return v

    @model_validator(mode="after")
    def respond_by_must_follow_raised_at(self) -> "Dispute":
        if self.respond_by <= self.raised_at:
            raise ValueError("respond_by must be after raised_at")
        return self

    @property
    def amount_inr(self) -> float:
        """Amount in rupees. Display helper only -- paise remains the stored unit."""
        return self.amount / 100


class ClaimVerdict(BaseModel):
    evidence_index: int
    label: VerdictLabel
    confidence: float = Field(ge=0.0, le=1.0)
    highlighted_span: Optional[str] = None


class Decision(BaseModel):
    dispute_id: str
    recommendation: Recommendation
    confidence: float = Field(ge=0.0, le=1.0)
    claim_verdicts: list[ClaimVerdict]
    drafted_packet: Optional[str] = None
    decided_at: datetime
    model_version: str = "cross-encoder/nli-deberta-v3-base"


class AuditLogEntry(BaseModel):
    id: int
    dispute_id: str
    decision: Decision
    approved_by_human: bool = False
    approved_at: Optional[datetime] = None
    submitted_to_razorpay: bool = False
    # Logged, never sent. See Section 7: the dispute_id does not exist on Razorpay's side,
    # so we record the exact payload we *would* have sent instead of making the call.
    would_be_razorpay_payload: Optional[dict] = None


class EvalMetrics(BaseModel):
    precision: float
    recall: float
    f1: float
    confusion_matrix: dict  # {"tp","fp","fn","tn","flagged_human"}
    false_positive_cost_estimate_inr: float
    coverage: float  # fraction NOT flagged to human
    n_evaluated: int


__all__ = [
    "KNOWN_REASON_CODES",
    "AuditLogEntry",
    "ClaimVerdict",
    "Decision",
    "Dispute",
    "DisputePhase",
    "EvalMetrics",
    "EvidenceItem",
    "EvidenceType",
    "GroundTruthLabel",
    "Recommendation",
    "VerdictLabel",
]
