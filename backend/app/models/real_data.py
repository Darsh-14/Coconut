"""Privacy-safe contract for offline, historical dispute research data.

This module is deliberately separate from :mod:`app.models.schemas`: historical merchant
exports are research inputs, not objects accepted by Coconut's public API.  In particular,
``merchant_action`` and ``final_outcome`` remain separate observations.  A processor may
report an accepted dispute as ``lost``; treating that row as evidence that contesting would
have lost is a counterfactual-label error.

Only HMAC-pseudonymised identifiers and redacted free text belong in this model.  The
corresponding importer lives in ``data/import_real_disputes.py`` and never calls a network
API.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.real_features import RealStructuredSignals

REAL_DATA_SCHEMA_VERSION = "1.0"
PSEUDONYM_PATTERN = r"^coc_v1_[0-9a-f]{24}$"
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

SourceKind = Literal["merchant_export", "processor_export", "joined_export"]
MerchantAction = Literal["contested", "accepted", "expired", "withdrawn", "no_action"]
FinalOutcome = Literal["won", "lost", "partial", "closed", "pending"]
RealDisputePhase = Literal[
    "fraud", "retrieval", "chargeback", "pre_arbitration", "arbitration"
]
RealPaymentRail = Literal["card", "upi", "rupay", "wallet", "netbanking", "other"]
RealEvidenceType = Literal[
    "delivery_proof",
    "communication_log",
    "device_signal",
    "order_history",
    "refund_record",
    "billing_record",
    "processor_record",
    "other",
]
EvidenceAdjudication = Literal["support", "contradict", "neutral", "insufficient"]
AnnotationProvenance = Literal[
    "single_human", "double_human_consensus", "expert_adjudication"
]
BinaryContestOutcome = Literal["contest_win", "contest_loss"]


# Conservative, intentionally obvious patterns.  These are a final contract guard, not a
# substitute for the importer's transformations.  False negatives are still possible, so a
# human data-governance review remains necessary before sharing any derived dataset.
_SENSITIVE_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "email address",
        re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+"),
    ),
    (
        "UPI VPA",
        re.compile(r"(?i)(?<![\w.-])[a-z0-9][a-z0-9._-]{1,255}@[a-z]{2,64}(?![\w.-])"),
    ),
    (
        "phone number",
        re.compile(r"(?<!\d)(?:\+?91[\s.-]?)?[6-9]\d{4}[\s.-]?\d{5}(?!\d)"),
    ),
    (
        "card-like number",
        re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"),
    ),
    (
        "IP address",
        re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"),
    ),
    (
        "processor reference",
        re.compile(
            r"(?i)\b(?:pay|disp|dp|order|ord|rfnd|refund|cust|inv|setl|trf)_[a-z0-9]{6,}\b"
        ),
    ),
    (
        "credential-like value",
        re.compile(
            r"(?i)(?:rzp_(?:live|test)_[a-z0-9]+|sk_(?:live|test)_[a-z0-9]+|"
            r"sk-ant-[a-z0-9_-]+|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
        ),
    ),
)


def sensitive_text_kind(value: str) -> str | None:
    """Return the first obvious sensitive-data category still visible in ``value``."""

    for kind, pattern in _SENSITIVE_TEXT_PATTERNS:
        if pattern.search(value):
            return kind
    return None


class _FrozenContract(BaseModel):
    """Shared strict/immutable Pydantic configuration for derived research artefacts."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class RealEvidenceItem(_FrozenContract):
    """One evidence observation, containing only redacted text and a pseudonymised ref."""

    type: RealEvidenceType
    content_redacted: str = Field(min_length=1, max_length=50_000)
    source_ref: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN)
    # Optional *human annotation*, never inferred from the case outcome.  Requiring its
    # method/version alongside the label prevents an unauditable label from silently entering
    # an NLI fine-tuning corpus.
    adjudicated_label: EvidenceAdjudication | None = None
    annotation_provenance: AnnotationProvenance | None = None
    annotation_version: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )

    @field_validator("content_redacted")
    @classmethod
    def content_must_be_redacted(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content_redacted must not be blank")
        sensitive_kind = sensitive_text_kind(value)
        if sensitive_kind:
            raise ValueError(
                f"content_redacted still contains an obvious {sensitive_kind}; import it again"
            )
        return value

    @model_validator(mode="after")
    def annotation_metadata_must_be_complete(self) -> "RealEvidenceItem":
        values = (
            self.adjudicated_label,
            self.annotation_provenance,
            self.annotation_version,
        )
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError(
                "adjudicated_label, annotation_provenance, and annotation_version "
                "must be supplied together"
            )
        return self


class RealDisputeRecord(_FrozenContract):
    """A normalized historical dispute suitable for offline evaluation or training.

    ``decision_at`` is the prediction cutoff: every feature/evidence value in the row must
    have been knowable by that instant.  ``resolved_at`` and ``final_outcome`` are labels
    observed later and must never be exposed to a predictor.
    """

    schema_version: Literal["1.0"] = REAL_DATA_SCHEMA_VERSION
    source_kind: SourceKind

    merchant_ref: str = Field(pattern=PSEUDONYM_PATTERN)
    dispute_ref: str = Field(pattern=PSEUDONYM_PATTERN)
    leakage_group_ref: str = Field(pattern=PSEUDONYM_PATTERN)
    payment_ref: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN)
    order_ref: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN)
    customer_ref: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN)

    created_at: datetime
    decision_at: datetime
    respond_by: datetime | None = None
    resolved_at: datetime | None = None

    phase: RealDisputePhase
    reason_code: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    rail: RealPaymentRail
    amount: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    claim_text_redacted: str = Field(min_length=1, max_length=20_000)
    evidence: tuple[RealEvidenceItem, ...] = ()
    structured_signals: RealStructuredSignals | None = None

    # These two fields intentionally are not collapsed into a single "ground truth" value.
    merchant_action: MerchantAction
    final_outcome: FinalOutcome
    evidence_submitted: bool
    recovered_amount: int | None = Field(default=None, ge=0)
    representment_cost: int | None = Field(default=None, ge=0)

    @field_validator("created_at", "decision_at", "respond_by", "resolved_at", mode="before")
    @classmethod
    def timestamp_input_must_be_rfc3339(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str) or not RFC3339_PATTERN.fullmatch(value):
            raise ValueError("timestamps must be RFC3339 strings with an explicit timezone")
        return value

    @field_validator("created_at", "decision_at", "respond_by", "resolved_at")
    @classmethod
    def timestamp_must_be_aware_and_utc(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone offset")
        return value.astimezone(UTC)

    @field_validator("claim_text_redacted")
    @classmethod
    def claim_must_be_redacted(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim_text_redacted must not be blank")
        sensitive_kind = sensitive_text_kind(value)
        if sensitive_kind:
            raise ValueError(
                f"claim_text_redacted still contains an obvious {sensitive_kind}; import it again"
            )
        return value

    @field_validator("evidence_submitted", mode="before")
    @classmethod
    def evidence_submitted_must_be_boolean(cls, value: object) -> object:
        if not isinstance(value, bool):
            raise ValueError("evidence_submitted must be a JSON boolean")
        return value

    @model_validator(mode="after")
    def validate_timeline_and_outcome(self) -> "RealDisputeRecord":
        if self.decision_at < self.created_at:
            raise ValueError("decision_at must be on or after created_at")
        if self.respond_by is not None and self.respond_by <= self.created_at:
            raise ValueError("respond_by must be after created_at")

        if self.final_outcome == "pending":
            if self.resolved_at is not None:
                raise ValueError("pending disputes must not have resolved_at")
            if self.recovered_amount is not None:
                raise ValueError("pending disputes must not have recovered_amount")
        else:
            if self.resolved_at is None:
                raise ValueError("a non-pending final_outcome requires resolved_at")
            if self.resolved_at < self.decision_at:
                raise ValueError("resolved_at must be on or after decision_at")

        if self.recovered_amount is not None and self.recovered_amount > self.amount:
            raise ValueError("recovered_amount cannot exceed amount")
        if (
            self.structured_signals is not None
            and self.structured_signals.observed_at > self.decision_at
        ):
            raise ValueError("structured_signals.observed_at must be on or before decision_at")
        return self

    @property
    def binary_contest_outcome(self) -> BinaryContestOutcome | None:
        """Return a supervised label only where the contest action was actually observed.

        An accepted/expired/withdrawn dispute has no observed ``P(win | contest)`` label,
        even when the processor's terminal status happens to be ``lost``.
        """

        if self.merchant_action != "contested":
            return None
        if self.final_outcome == "won":
            return "contest_win"
        if self.final_outcome == "lost":
            return "contest_loss"
        return None

    @property
    def is_binary_training_eligible(self) -> bool:
        return self.binary_contest_outcome is not None


__all__ = [
    "AnnotationProvenance",
    "BinaryContestOutcome",
    "EvidenceAdjudication",
    "FinalOutcome",
    "MerchantAction",
    "PSEUDONYM_PATTERN",
    "RFC3339_PATTERN",
    "REAL_DATA_SCHEMA_VERSION",
    "RealDisputePhase",
    "RealDisputeRecord",
    "RealEvidenceItem",
    "RealEvidenceType",
    "RealPaymentRail",
    "RealStructuredSignals",
    "SourceKind",
    "sensitive_text_kind",
]
