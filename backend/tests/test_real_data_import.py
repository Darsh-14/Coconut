"""Focused privacy, label-integrity, and file-safety tests for real-data import."""

from __future__ import annotations

import csv
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.real_data import PSEUDONYM_PATTERN, RealDisputeRecord
from data.import_real_disputes import (
    HMAC_ENV_VAR,
    ImportPipelineError,
    UnsafeInputError,
    build_parser,
    import_file,
)


def _raw_record(**overrides):
    record = {
        "source_kind": "joined_export",
        "merchant_id": "merchant_private_001",
        "dispute_id": "disp_private_001",
        "leakage_group_id": "shipment_private_001",
        "payment_id": "pay_private_001",
        "order_id": "order_private_001",
        "customer_id": "customer_private_001",
        "created_at": "2025-01-01T09:00:00+05:30",
        "decision_at": "2025-01-02T09:00:00+05:30",
        "respond_by": "2025-01-08T09:00:00+05:30",
        "resolved_at": "2025-01-12T09:00:00+05:30",
        "phase": "chargeback",
        "reason_code": "goods_not_received",
        "rail": "card",
        "amount": 249900,
        "currency": "inr",
        "claim_text": (
            "Customer jane@example.com, +91 98765 43210 says order_private_001 was absent; "
            "VPA jane@okaxis, card 4111 1111 1111 1111, IP 192.168.1.20."
        ),
        "evidence": [
            {
                "type": "delivery_proof",
                "content": "Courier delivered pay_private_001 and called 9876543210.",
                "source_id": "pod_private_001",
                "adjudicated_label": "support",
                "annotation_provenance": "expert_adjudication",
                "annotation_version": "rubric-v1",
            }
        ],
        "merchant_action": "contested",
        "final_outcome": "won",
        "evidence_submitted": True,
        "recovered_amount": 249900,
        "representment_cost": 150000,
    }
    record.update(overrides)
    return record


@pytest.fixture
def hmac_env(monkeypatch):
    monkeypatch.setenv(HMAC_ENV_VAR, "a-cryptographically-random-demo-key-32bytes-minimum")


def _write_json(path: Path, records) -> None:
    path.write_text(json.dumps(records), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_import_pseudonymizes_ids_and_redacts_obvious_sensitive_text(tmp_path, hmac_env):
    source = tmp_path / "raw.json"
    output = tmp_path / "normalized.jsonl"
    _write_json(source, [_raw_record()])

    result = import_file(source, output)
    rows = _read_jsonl(output)

    assert result.input_count == result.output_count == 1
    row = rows[0]
    for field in (
        "merchant_ref",
        "dispute_ref",
        "leakage_group_ref",
        "payment_ref",
        "order_ref",
        "customer_ref",
    ):
        assert re.fullmatch(PSEUDONYM_PATTERN, row[field])
    assert re.fullmatch(PSEUDONYM_PATTERN, row["evidence"][0]["source_ref"])

    encoded = output.read_text(encoding="utf-8")
    for secret in (
        "merchant_private_001",
        "disp_private_001",
        "order_private_001",
        "pay_private_001",
        "jane@example.com",
        "98765 43210",
        "jane@okaxis",
        "4111 1111 1111 1111",
        "192.168.1.20",
    ):
        assert secret not in encoded
    assert "[REDACTED_EMAIL]" in row["claim_text_redacted"]
    assert "[REDACTED_PHONE]" in row["claim_text_redacted"]
    assert "[REDACTED_UPI]" in row["claim_text_redacted"]
    assert "[REDACTED_CARD]" in row["claim_text_redacted"]
    assert "[REDACTED_IP]" in row["claim_text_redacted"]
    assert row["currency"] == "INR"
    assert row["decision_at"].endswith("Z")


def test_import_preserves_only_pre_decision_structured_signals(tmp_path, hmac_env):
    raw = _raw_record(
        structured_signals={
            "observed_at": "2025-01-02T08:59:00+05:30",
            "source_version": "warehouse-v1",
            "carrier_status_delivered": True,
            "signature_present": None,
        }
    )
    source = tmp_path / "signals.json"
    output = tmp_path / "signals.jsonl"
    _write_json(source, [raw])
    import_file(source, output)
    signals = _read_jsonl(output)[0]["structured_signals"]
    assert signals["carrier_status_delivered"] is True
    assert signals["signature_present"] is None
    assert signals["observed_at"].endswith("Z")

    raw["structured_signals"]["observed_at"] = "2025-01-02T09:01:00+05:30"
    _write_json(source, [raw])
    with pytest.raises(ImportPipelineError, match="on or before decision_at"):
        import_file(source, tmp_path / "late.jsonl")


def test_import_is_deterministic_and_sorts_by_decision_time(tmp_path, hmac_env):
    later = _raw_record(dispute_id="disp_later", decision_at="2025-01-03T00:00:00Z")
    earlier = _raw_record(dispute_id="disp_earlier", decision_at="2025-01-02T00:00:00Z")
    source_a = tmp_path / "a.json"
    source_b = tmp_path / "b.json"
    output_a = tmp_path / "a.jsonl"
    output_b = tmp_path / "b.jsonl"
    _write_json(source_a, [later, earlier])
    _write_json(source_b, [earlier, later])

    result_a = import_file(source_a, output_a)
    result_b = import_file(source_b, output_b)

    assert output_a.read_bytes() == output_b.read_bytes()
    assert result_a.output_sha256 == result_b.output_sha256
    rows = _read_jsonl(output_a)
    assert rows[0]["decision_at"] < rows[1]["decision_at"]


def test_exact_duplicates_collapse_but_conflicts_fail(tmp_path, hmac_env):
    raw = _raw_record()
    source = tmp_path / "duplicates.json"
    output = tmp_path / "normalized.jsonl"
    _write_json(source, [raw, deepcopy(raw)])
    result = import_file(source, output)
    assert result.input_count == 2
    assert result.output_count == 1
    assert result.duplicate_count == 1

    conflict = deepcopy(raw)
    conflict["amount"] += 1
    conflict_source = tmp_path / "conflict.json"
    _write_json(conflict_source, [raw, conflict])
    with pytest.raises(ImportPipelineError, match="conflicts with duplicate"):
        import_file(conflict_source, tmp_path / "conflict.jsonl")


@pytest.mark.parametrize("forbidden_key", ["cvv", "cardNumber", "access-token", "api_secret"])
def test_recursively_rejects_payment_and_credential_keys(
    tmp_path, hmac_env, forbidden_key
):
    raw = _raw_record()
    raw["evidence"][0][forbidden_key] = "do-not-echo-this-value"
    source = tmp_path / "unsafe.json"
    _write_json(source, [raw])
    with pytest.raises(UnsafeInputError) as caught:
        import_file(source, tmp_path / "out.jsonl")
    assert forbidden_key in str(caught.value)
    assert "do-not-echo-this-value" not in str(caught.value)


def test_rejects_credential_like_values_without_echoing_them(tmp_path, hmac_env):
    credential = "rzp_live_this_must_never_be_written"
    source = tmp_path / "unsafe.json"
    _write_json(source, [_raw_record(claim_text=f"Observed credential {credential}")])
    with pytest.raises(UnsafeInputError) as caught:
        import_file(source, tmp_path / "out.jsonl")
    assert credential not in str(caught.value)


def test_missing_or_ambiguous_action_fails_without_echoing_raw_value(tmp_path, hmac_env):
    raw = _raw_record()
    raw.pop("merchant_action")
    source = tmp_path / "missing.json"
    _write_json(source, [raw])
    with pytest.raises(ImportPipelineError, match="merchant_action"):
        import_file(source, tmp_path / "missing.jsonl")

    private_bad_value = "reviewer-private-value@example.com"
    source_bad = tmp_path / "bad.json"
    _write_json(source_bad, [_raw_record(merchant_action=private_bad_value)])
    with pytest.raises(ImportPipelineError) as caught:
        import_file(source_bad, tmp_path / "bad.jsonl")
    assert private_bad_value not in str(caught.value)


def test_case_outcome_never_becomes_a_counterfactual_contest_label(tmp_path, hmac_env):
    source = tmp_path / "labels.json"
    _write_json(
        source,
        [
            _raw_record(dispute_id="accepted_case", merchant_action="accepted", final_outcome="lost"),
            _raw_record(dispute_id="lost_case", merchant_action="contested", final_outcome="lost"),
            _raw_record(dispute_id="won_case", merchant_action="contested", final_outcome="won"),
        ],
    )
    output = tmp_path / "labels.jsonl"
    import_file(source, output)
    records = [RealDisputeRecord.model_validate(row) for row in _read_jsonl(output)]
    labels = {record.binary_contest_outcome for record in records}
    assert labels == {None, "contest_loss", "contest_win"}
    accepted = next(record for record in records if record.merchant_action == "accepted")
    assert not accepted.is_binary_training_eligible


def test_evidence_annotation_is_optional_but_never_partially_provenanced(tmp_path, hmac_env):
    raw = _raw_record()
    raw["evidence"][0].pop("annotation_version")
    source = tmp_path / "partial-annotation.json"
    _write_json(source, [raw])
    with pytest.raises(ImportPipelineError, match="must be supplied together"):
        import_file(source, tmp_path / "out.jsonl")

    no_annotation = _raw_record()
    for field in ("adjudicated_label", "annotation_provenance", "annotation_version"):
        no_annotation["evidence"][0].pop(field)
    source_ok = tmp_path / "no-annotation.json"
    _write_json(source_ok, [no_annotation])
    import_file(source_ok, tmp_path / "no-annotation.jsonl")


def test_timeline_and_terminal_state_are_validated(tmp_path, hmac_env):
    invalid_cases = [
        _raw_record(decision_at="2024-12-31T00:00:00Z"),
        _raw_record(final_outcome="pending"),
        _raw_record(final_outcome="lost", resolved_at=None),
        _raw_record(recovered_amount=249901),
        _raw_record(created_at="2025-01-01T00:00:00"),
        _raw_record(created_at=1735689600),
    ]
    for index, raw in enumerate(invalid_cases):
        source = tmp_path / f"invalid-{index}.json"
        _write_json(source, [raw])
        with pytest.raises(ImportPipelineError):
            import_file(source, tmp_path / f"invalid-{index}.jsonl")


@pytest.mark.parametrize("bad_timestamp", [1735689600, 1735689600.0, "2025-01-01 00:00:00"])
def test_timestamps_require_explicit_rfc3339_strings(
    tmp_path, hmac_env, bad_timestamp
):
    source = tmp_path / "bad-time.json"
    _write_json(source, [_raw_record(created_at=bad_timestamp)])
    with pytest.raises(ImportPipelineError, match="RFC3339"):
        import_file(source, tmp_path / "bad-time.jsonl")


@pytest.mark.parametrize("bad_boolean", [0, 1, "0", "1", "yes", "no", "TRUE", ""])
def test_evidence_submitted_rejects_ambiguous_boolean_coercions(
    tmp_path, hmac_env, bad_boolean
):
    source = tmp_path / "bad-bool.json"
    _write_json(source, [_raw_record(evidence_submitted=bad_boolean)])
    with pytest.raises(ImportPipelineError, match="evidence_submitted"):
        import_file(source, tmp_path / "bad-bool.jsonl")


@pytest.mark.parametrize("ambiguous", [1, 0, "yes", "no"])
def test_evidence_submission_requires_an_explicit_boolean(
    tmp_path, hmac_env, ambiguous
):
    source = tmp_path / "ambiguous-bool.json"
    _write_json(source, [_raw_record(evidence_submitted=ambiguous)])

    with pytest.raises(ImportPipelineError, match="evidence_submitted"):
        import_file(source, tmp_path / "out.jsonl")


def test_csv_with_evidence_json_is_supported(tmp_path, hmac_env):
    raw = _raw_record()
    evidence = raw.pop("evidence")
    # CSV has no native boolean type; the contract intentionally accepts only lowercase
    # true/false rather than guessing from dialect-specific spellings.
    raw["evidence_submitted"] = "true"
    raw["evidence_json"] = json.dumps(evidence)
    source = tmp_path / "raw.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw))
        writer.writeheader()
        writer.writerow(raw)

    output = tmp_path / "normalized.json"
    result = import_file(source, output)
    rows = json.loads(output.read_text(encoding="utf-8"))
    assert result.output_count == 1
    assert rows[0]["evidence"][0]["adjudicated_label"] == "support"


def test_hmac_key_is_required_and_never_available_as_cli_option(tmp_path, monkeypatch):
    source = tmp_path / "raw.json"
    _write_json(source, [_raw_record()])
    monkeypatch.delenv(HMAC_ENV_VAR, raising=False)
    with pytest.raises(ImportPipelineError, match=HMAC_ENV_VAR):
        import_file(source, tmp_path / "out.jsonl")

    monkeypatch.setenv(HMAC_ENV_VAR, "too-short")
    with pytest.raises(ImportPipelineError, match="at least 32"):
        import_file(source, tmp_path / "out.jsonl")

    option_strings = {
        option
        for action in build_parser()._actions
        for option in action.option_strings
    }
    assert not any("key" in option or "salt" in option for option in option_strings)


def test_existing_output_is_preserved_without_explicit_force(tmp_path, hmac_env):
    source = tmp_path / "raw.json"
    output = tmp_path / "out.jsonl"
    _write_json(source, [_raw_record()])
    output.write_text("existing-content", encoding="utf-8")

    with pytest.raises(ImportPipelineError, match="already exists"):
        import_file(source, output)
    assert output.read_text(encoding="utf-8") == "existing-content"

    import_file(source, output, force=True)
    assert _read_jsonl(output)[0]["schema_version"] == "1.0"


def test_normalized_models_are_frozen(tmp_path, hmac_env):
    source = tmp_path / "raw.json"
    output = tmp_path / "out.jsonl"
    _write_json(source, [_raw_record()])
    import_file(source, output)
    record = RealDisputeRecord.model_validate(_read_jsonl(output)[0])

    with pytest.raises(ValidationError):
        record.amount = 1
    assert isinstance(record.evidence, tuple)


def test_importer_has_no_network_sdk_dependency():
    source = (Path(__file__).parents[1] / "data" / "import_real_disputes.py").read_text(
        encoding="utf-8"
    )
    assert "import razorpay" not in source
    assert "import requests" not in source
    assert "import httpx" not in source
