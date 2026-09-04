"""Strict pre-decision structured features for offline real-data research.

Every signal is tri-state: ``True``, ``False``, or ``None`` (unknown). Unknown must not be
collapsed to false because a missing integration is not negative evidence. ``observed_at``
is checked against the prediction cutoff by :class:`RealDisputeRecord`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


STRUCTURED_SIGNAL_NAMES = (
    "carrier_status_delivered",
    "pod_document_available",
    "delivery_address_match",
    "recipient_match",
    "signature_present",
    "otp_present",
    "multi_unit_address_ambiguity",
    "refund_initiated",
    "refund_completed",
    "refund_to_original_method",
    "refund_amount_matches",
    "refund_completed_before_claim",
    "renewal_notice_generated",
    "renewal_notice_delivered",
    "renewal_notice_bounced",
    "cancellation_before_renewal",
    "post_renewal_usage",
    "multiple_settled_captures",
    "reversal_present",
    "three_ds_authenticated",
    "device_matches_prior_history",
)


class RealStructuredSignals(BaseModel):
    """Signals computed by an authorised source system before ``decision_at``."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    observed_at: datetime
    source_version: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )

    carrier_status_delivered: StrictBool | None = None
    pod_document_available: StrictBool | None = None
    delivery_address_match: StrictBool | None = None
    recipient_match: StrictBool | None = None
    signature_present: StrictBool | None = None
    otp_present: StrictBool | None = None
    multi_unit_address_ambiguity: StrictBool | None = None
    refund_initiated: StrictBool | None = None
    refund_completed: StrictBool | None = None
    refund_to_original_method: StrictBool | None = None
    refund_amount_matches: StrictBool | None = None
    refund_completed_before_claim: StrictBool | None = None
    renewal_notice_generated: StrictBool | None = None
    renewal_notice_delivered: StrictBool | None = None
    renewal_notice_bounced: StrictBool | None = None
    cancellation_before_renewal: StrictBool | None = None
    post_renewal_usage: StrictBool | None = None
    multiple_settled_captures: StrictBool | None = None
    reversal_present: StrictBool | None = None
    three_ds_authenticated: StrictBool | None = None
    device_matches_prior_history: StrictBool | None = None

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_aware_and_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone offset")
        return value.astimezone(UTC)


__all__ = ["RealStructuredSignals", "STRUCTURED_SIGNAL_NAMES"]
