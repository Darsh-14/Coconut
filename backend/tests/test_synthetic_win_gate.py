"""Safety and leakage tests for the synthetic-only supervised CONTEST gate."""

from __future__ import annotations

from copy import deepcopy

from app.models.schemas import ClaimVerdict, Dispute, EvidenceItem
from app.services.decision_aggregator import AggregationResult
from app.services.synthetic_win_gate import (
    SyntheticWinModel,
    apply_synthetic_win_gate,
    dispute_features,
)


def _dispute(**updates) -> Dispute:
    value = {
        "dispute_id": "disp_synthetic_gate_test",
        "payment_id": "pay_PENDING_gate_test",
        "phase": "chargeback",
        "reason_code": "goods_not_received",
        "claim_text": "The customer states that the parcel was not delivered.",
        "amount": 250000,
        "currency": "INR",
        "raised_at": "2026-01-01T00:00:00Z",
        "respond_by": "2026-01-08T00:00:00Z",
        "evidence_bundle": [
            {
                "type": "delivery_proof",
                "content": "The signed carrier record confirms delivery to the recipient.",
                "source_ref": "private-source-name",
            },
            {
                "type": "communication_log",
                "content": "The recipient confirmed arrival in the support conversation.",
            },
        ],
        "ground_truth_label": "contest_win",
        "rail": "card",
    }
    value.update(updates)
    return Dispute.model_validate(value)


def _result(recommendation: str = "CONTEST") -> AggregationResult:
    return AggregationResult(
        recommendation=recommendation,
        confidence=0.8,
        driving_verdicts=[
            ClaimVerdict(evidence_index=0, label="support", confidence=0.8)
        ],
        rationale="NLI rule passed.",
    )


def test_features_ignore_ground_truth_identifiers_and_source_refs():
    original = _dispute()
    changed = deepcopy(original.model_dump(mode="python"))
    changed.update(
        {
            "dispute_id": "disp_synthetic_other",
            "payment_id": "pay_PENDING_other",
            "ground_truth_label": "should_accept",
        }
    )
    changed["evidence_bundle"][0]["source_ref"] = "completely-different-source"

    assert dispute_features(original, 512) == dispute_features(
        Dispute.model_validate(changed), 512
    )


def test_gate_can_demote_but_never_promote(monkeypatch):
    low_model = SyntheticWinModel(
        dimension=128,
        intercept=-10.0,
        weights=(0.0,) * 128,
        threshold=0.5,
        model_version="test-low",
    )
    monkeypatch.setattr(
        "app.services.synthetic_win_gate.load_synthetic_win_model", lambda: low_model
    )
    demoted, evaluation = apply_synthetic_win_gate(_result(), _dispute())
    assert demoted.recommendation == "NEEDS_HUMAN_REVIEW"
    assert evaluation.applied is True

    unchanged, evaluation = apply_synthetic_win_gate(_result("ACCEPT"), _dispute())
    assert unchanged.recommendation == "ACCEPT"
    assert evaluation.applied is False


def test_gate_is_disabled_for_non_synthetic_disputes(monkeypatch):
    monkeypatch.setattr(
        "app.services.synthetic_win_gate.load_synthetic_win_model",
        lambda: (_ for _ in ()).throw(AssertionError("model should not load")),
    )
    result = _result()
    unchanged, evaluation = apply_synthetic_win_gate(
        result, _dispute(dispute_id="merchant_history_case")
    )
    assert unchanged is result
    assert evaluation.applied is False
