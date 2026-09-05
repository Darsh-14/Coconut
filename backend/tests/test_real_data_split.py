"""Fast guards for the strict chronological/group-aware real-data splitter."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.models.real_data import RealDisputeRecord
from data.split_real_disputes import (
    DEFAULT_RATIOS,
    SPLIT_NAMES,
    SplitError,
    load_normalized,
    parse_ratios,
    split_records,
    write_splits,
)


def _ref(index: int) -> str:
    return f"coc_v1_{index:024x}"


def _record(index: int, day: int, *, group: int | None = None) -> RealDisputeRecord:
    decision_at = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return RealDisputeRecord.model_validate(
        {
            "schema_version": "1.0",
            "source_kind": "merchant_export",
            "merchant_ref": _ref(900),
            "dispute_ref": _ref(index),
            "leakage_group_ref": _ref(group if group is not None else index + 10_000),
            "payment_ref": _ref(index + 20_000),
            "order_ref": _ref(index + 30_000),
            "customer_ref": None,
            "created_at": (decision_at - timedelta(days=1)).isoformat(),
            "decision_at": decision_at.isoformat(),
            "respond_by": (decision_at + timedelta(days=3)).isoformat(),
            "resolved_at": (decision_at + timedelta(days=10)).isoformat(),
            "phase": "chargeback",
            "reason_code": "goods_not_received",
            "rail": "card",
            "amount": 25_000 + index,
            "currency": "INR",
            "claim_text_redacted": "Issuer reports that the merchandise was not received.",
            "evidence": [
                {
                    "type": "delivery_proof",
                    "content_redacted": "Carrier marked the parcel delivered to [REDACTED].",
                }
            ],
            "merchant_action": "contested",
            "final_outcome": "won" if index % 2 else "lost",
            "evidence_submitted": True,
            "recovered_amount": 25_000 + index if index % 2 else 0,
            "representment_cost": 1_500,
        }
    )


def test_split_is_strictly_chronological_and_group_disjoint():
    records = [_record(index, index) for index in range(1, 21)]
    # A second dispute from one early group must travel with its sibling.
    records.append(_record(101, 5, group=10_005))

    splits = split_records(records, DEFAULT_RATIOS)

    assert set(splits) == set(SPLIT_NAMES)
    owners: dict[str, str] = {}
    for name in SPLIT_NAMES:
        assert splits[name]
        for record in splits[name]:
            assert owners.setdefault(record.leakage_group_ref, name) == name
    for left, right in zip(SPLIT_NAMES, SPLIT_NAMES[1:]):
        assert max(row.decision_at for row in splits[left]) <= min(
            row.decision_at for row in splits[right]
        )


def test_spanning_group_fails_instead_of_weakening_temporal_safety():
    records = [
        _record(1, 1, group=500),
        _record(2, 10, group=500),
        _record(3, 2),
        _record(4, 3),
        _record(5, 4),
    ]

    with pytest.raises(SplitError, match="strictly chronological"):
        split_records(records)


def test_manifest_fingerprints_locked_test_and_refuses_overwrite(tmp_path: Path):
    input_path = tmp_path / "normalized.jsonl"
    records = [_record(index, index) for index in range(1, 21)]
    input_path.write_text(
        "".join(
            json.dumps(row.model_dump(mode="json"), sort_keys=True) + "\n"
            for row in records
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "splits"
    splits = split_records(records)

    manifest = write_splits(splits, output_dir, DEFAULT_RATIOS, input_path)

    test_bytes = (output_dir / "test.jsonl").read_bytes()
    expected = hashlib.sha256(test_bytes).hexdigest()
    assert manifest["locked_test"]["sha256"] == expected
    assert "input_file" not in manifest
    assert manifest["input_format"] == "jsonl"
    assert json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))[
        "locked_test"
    ]["sha256"] == expected
    with pytest.raises(SplitError, match="refusing to overwrite"):
        write_splits(splits, output_dir, DEFAULT_RATIOS, input_path)


def test_validation_error_does_not_echo_unredacted_input(tmp_path: Path):
    private_value = "private.person@example.com"
    raw = _record(1, 1).model_dump(mode="json")
    raw["claim_text_redacted"] = private_value
    path = tmp_path / "unsafe.jsonl"
    path.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    with pytest.raises(SplitError) as caught:
        load_normalized(path)
    assert private_value not in str(caught.value)


@pytest.mark.parametrize(
    "value",
    ["0.6,0.2,0.2", "0.6,0.2,0.1,0.2", "0.6,0.2,0.2,0", "words"],
)
def test_invalid_ratios_are_rejected(value: str):
    with pytest.raises(SplitError):
        parse_ratios(value)
