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

# NO_ACTION_NEEDED is Addendum 2's addition: URCS is expected to reject the chargeback on
# the merchant's behalf, so spending representment effort would be waste. It is distinct
# from ACCEPT (concede on the merits) and from NEEDS_HUMAN_REVIEW (we cannot tell).
Recommendation = Literal["CONTEST", "ACCEPT", "NEEDS_HUMAN_REVIEW", "NO_ACTION_NEEDED"]

# UPI and RuPay clear through NPCI; card rails clear through Visa/Mastercard. The
# distinction is mechanical, not cosmetic -- only UPI is governed by URCS's cap rules.
PaymentRail = Literal["upi", "rupay", "card"]

URCSDisposition = Literal[
    "AUTO_REJECT", "AUTO_ACCEPT", "PROCEEDS_TO_MERCHANT", "UNKNOWN"
]

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
    # Addendum 2. Defaulted so every pre-existing record still validates unchanged.
    rail: PaymentRail = "card"
    payer_ref: Optional[str] = None  # stable pseudonymous payer identifier

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
    # Addendum 3: a decision is only reproducible if you know which threshold produced it.
    calibrated_threshold_used: Optional[float] = None


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
    # Cap-breach cases URCS resolves without the merchant. Excluded from precision and
    # recall exactly as NEEDS_HUMAN_REVIEW is -- counting them as wins would inflate the
    # headline number for work the system did not do.
    auto_resolved: int = 0
    # Addendum 3: the risk budget in force, the threshold it produced, and whether the
    # guarantee actually held on the test split.
    alpha: Optional[float] = None
    calibrated_threshold: Optional[float] = None
    guarantee_held: Optional[bool] = None


class DisputeBudget(BaseModel):
    """How much of the payer's NPCI dispute allowance is already spent."""

    payer_ref: str
    customer_disputes_30d: int
    payer_payee_disputes_30d: int
    customer_cap_remaining: int
    payer_payee_cap_remaining: int
    window_resets_at: datetime


class URCSForecast(BaseModel):
    """What NPCI's rules engine is expected to do with this chargeback, and why."""

    predicted_disposition: URCSDisposition
    predicted_reason_code: Optional[str] = None  # "CD1" | "CD2" | None
    rgnb_re_raise_possible: bool
    budget: DisputeBudget
    explanation: str
    rules_verified_on: str


class CalibrationResult(BaseModel):
    """Outcome of calibrating the decision threshold to a stated risk budget."""

    alpha: float  # requested maximum false-positive rate
    delta: float  # confidence level
    calibrated_threshold: Optional[float]
    achievable: bool
    calibration_set_size: int
    n_above_threshold: int
    empirical_fp_rate_on_calibration: Optional[float]
    hoeffding_slack: Optional[float]
    guarantee_statement: str
    # The tightest budget this calibration set can support, so an unachievable request is
    # actionable rather than a dead end.
    smallest_achievable_alpha: Optional[float] = None


class GuaranteeVerification(BaseModel):
    """Computed on the TEST split, never the calibration split."""

    alpha: float
    observed_fp_rate_on_test: float
    guarantee_held: bool
    coverage: float  # fraction auto-decided rather than deferred to a human
    n_test: int


class CalibrateRequest(BaseModel):
    """Body of POST /calibrate."""

    alpha: float = Field(gt=0.0, lt=1.0)
    delta: float = Field(default=0.1, gt=0.0, lt=1.0)


# --- API request/response shapes (Section 8) --------------------------------------------
# These are the transport shapes the endpoints exchange. The contracts above are the
# domain model and must not change; these compose them.

DisputeStatus = Literal["pending", "decided", "approved", "submitted"]


class DisputeSummary(BaseModel):
    """One row of GET /disputes."""

    dispute_id: str
    phase: DisputePhase
    reason_code: str
    amount: int
    currency: str
    respond_by: datetime
    status: DisputeStatus
    # Not in Section 8's example, but the queue is far more useful when a reviewer can see
    # at a glance which disputes rest on a real Razorpay payment and which do not.
    payment_id: str
    payment_is_real: bool
    # Also beyond Section 8's example, and for the same reason: without the standing
    # recommendation the queue cannot show what Recourse actually concluded, which is the
    # one thing a reviewer opens the queue to find out. Both are None until /decide runs.
    recommendation: Optional[Recommendation] = None
    confidence: Optional[float] = None
    # Addendum 2: the queue de-prioritises rows NPCI will reject on the merchant's behalf,
    # which needs the rail and the code that fired.
    rail: PaymentRail = "card"
    urcs_reason_code: Optional[str] = None


class DisputeDetail(BaseModel):
    """GET /disputes/{dispute_id}: the dispute, its latest decision, and its audit trail."""

    dispute: Dispute
    latest_decision: Optional[Decision] = None
    decision_rationale: Optional[str] = None
    audit_log: list[AuditLogEntry] = []
    status: DisputeStatus
    payment_is_real: bool


class ApproveRequest(BaseModel):
    """POST /disputes/{dispute_id}/approve."""

    approved: bool
    edited_packet: Optional[str] = None


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
