"""Tests for eligibility, leakage guards, and deterministic offline training."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from eval.train_real_baseline import (
    ARTIFACT_VERSION,
    BaselineDataError,
    TrainingConfig,
    audit_split_integrity,
    filter_eligible,
    fit_logistic_baseline,
    record_to_hashed_features,
    sha256_file,
    train_and_evaluate,
    validate_split_manifest,
)


def _record(index: int, outcome: str, *, action: str = "contested") -> dict:
    day = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
    positive = outcome == "won"
    return {
        "schema_version": "1.0",
        "source_kind": "merchant_export",
        "merchant_ref": f"coc_v1_{(10_000 + index):024x}",
        "dispute_ref": f"coc_v1_{(20_000 + index):024x}",
        "leakage_group_ref": f"coc_v1_{(30_000 + index):024x}",
        "created_at": (day - timedelta(days=2)).isoformat(),
        "decision_at": day.isoformat(),
        "resolved_at": (day + timedelta(days=7)).isoformat(),
        "phase": "chargeback",
        "reason_code": "goods_not_received" if positive else "duplicate",
        "rail": "card",
        "amount": 2000 + index,
        "currency": "INR",
        "claim_text_redacted": (
            "tracking confirms delivered receipt available"
            if positive
            else "no proof supplied customer complaint"
        ),
        "evidence": [
            {
                "type": "delivery_proof",
                "content_redacted": (
                    "carrier event delivered" if positive else "document unavailable"
                ),
                "source_ref": None,
            }
        ],
        "merchant_action": action,
        "final_outcome": outcome,
        "evidence_submitted": True,
        "recovered_amount": 2000 if positive else 0,
        "representment_cost": 100,
    }


def test_eligibility_keeps_only_actually_contested_matured_records():
    rows = [
        _record(0, "won"),
        _record(1, "lost", action="accepted"),
        _record(2, "pending"),
        {**_record(3, "lost"), "resolved_at": None},
    ]

    selected = filter_eligible(rows)

    assert selected.labels.tolist() == [1]
    assert selected.summary["excluded"] == {
        "missing_or_invalid_maturity_timestamp": 1,
        "not_actually_contested": 1,
        "outcome_not_matured_won_or_lost": 1,
    }


def test_features_are_invariant_to_label_post_decision_and_identity_fields():
    original = _record(4, "won")
    changed = deepcopy(original)
    changed.update(
        {
            "final_outcome": "lost",
            "merchant_action": "accepted",
            "resolved_at": "2030-01-01T00:00:00+00:00",
            "recovered_amount": 0,
            "representment_cost": 999999,
            "merchant_ref": f"coc_v1_{90001:024x}",
            "dispute_ref": f"coc_v1_{90002:024x}",
            "leakage_group_ref": f"coc_v1_{90003:024x}",
        }
    )

    assert record_to_hashed_features(original, 128) == record_to_hashed_features(
        changed, 128
    )


def test_structured_signal_false_is_not_collapsed_into_unknown():
    unknown = _record(5, "won")
    false_signal = deepcopy(unknown)
    false_signal["structured_signals"] = {
        "observed_at": false_signal["decision_at"],
        "source_version": "warehouse-v1",
        "carrier_status_delivered": False,
    }

    assert record_to_hashed_features(unknown, 4096) != record_to_hashed_features(
        false_signal, 4096
    )


def test_fit_is_deterministic():
    rows = [_record(index, "won" if index % 2 == 0 else "lost") for index in range(12)]
    labels = np.asarray([1 if row["final_outcome"] == "won" else 0 for row in rows])
    config = TrainingConfig(dimension=64, epochs=25, min_calibration_support=1)

    first = fit_logistic_baseline(rows, labels, config)
    second = fit_logistic_baseline(rows, labels, config)

    np.testing.assert_array_equal(first.weights, second.weights)
    np.testing.assert_array_equal(first.predict(rows), second.predict(rows))
    assert first.intercept == second.intercept


def test_split_audit_rejects_group_overlap_and_time_overlap():
    splits = {
        "train": [_record(0, "won")],
        "validation": [_record(10, "lost")],
        "calibration": [_record(20, "won")],
        "test": [_record(30, "lost")],
    }
    splits["validation"][0]["leakage_group_ref"] = splits["train"][0][
        "leakage_group_ref"
    ]
    with pytest.raises(BaselineDataError, match="leakage group"):
        audit_split_integrity(splits)

    splits["validation"][0]["leakage_group_ref"] = f"coc_v1_{99999:024x}"
    splits["calibration"][0]["decision_at"] = splits["train"][0]["decision_at"]
    with pytest.raises(BaselineDataError, match="chronology violation"):
        audit_split_integrity(splits)


def test_end_to_end_artifact_contains_no_source_text_or_identifiers():
    # Separable data makes a tiny smoke pipeline deterministic.  Low support/target values
    # are test-only; production CLI defaults remain deliberately strict.
    splits: dict[str, list[dict]] = {}
    start = 0
    for split_name in ("train", "validation", "calibration", "test"):
        splits[split_name] = [
            _record(index, "won" if local % 2 == 0 else "lost")
            for local, index in enumerate(range(start, start + 20))
        ]
        start += 30
    config = TrainingConfig(
        dimension=64,
        epochs=80,
        learning_rate=0.5,
        target_precision=0.50,
        min_calibration_support=2,
        min_tail_coverage=0.05,
        min_test_support=2,
        confidence=0.80,
        calibration_bins=4,
    )

    artifact = train_and_evaluate(splits, config, provenance={"fixture": "generated"})
    rendered = str(artifact)

    assert artifact["artifact_version"] == ARTIFACT_VERSION
    assert artifact["operating_points"]["selected_without_test_access"] is True
    assert artifact["model"]["contains_vocabulary_or_raw_text"] is False
    assert len(artifact["model"]["weights"]) == 64
    assert "tracking confirms delivered receipt available" not in rendered
    assert "coc_v1_" not in rendered
    assert artifact["metrics"]["locked_test"]["population_auto_win_capture"] is not None


def test_trainer_rejects_unredacted_or_extra_fields_before_feature_extraction():
    splits = {
        name: [_record(offset, "won"), _record(offset + 1, "lost")]
        for name, offset in zip(
            ("train", "validation", "calibration", "test"), (0, 10, 20, 30)
        )
    }
    private_value = "shopper.private@example.com"
    splits["train"][0]["claim_text_redacted"] = f"contact {private_value}"
    splits["train"][0]["raw_card_number"] = "not allowed even if fake"

    with pytest.raises(BaselineDataError, match="privacy contract") as caught:
        train_and_evaluate(
            splits,
            TrainingConfig(
                dimension=32,
                epochs=2,
                target_precision=0.1,
                min_calibration_support=1,
                min_test_support=1,
                confidence=0.8,
            ),
        )
    assert private_value not in str(caught.value)


def test_manifest_verification_fails_closed_on_changed_split(tmp_path):
    import json

    paths = {}
    details = {}
    for name, offset in zip(
        ("train", "validation", "calibration", "test"), (0, 10, 20, 30)
    ):
        path = tmp_path / f"{name}.jsonl"
        rows = [_record(offset, "won"), _record(offset + 1, "lost")]
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        paths[name] = path
        details[name] = {
            "filename": path.name,
            "sha256": sha256_file(path),
            "records": 2,
        }
    manifest = {
        "schema_version": "1.0",
        "algorithm": "strict-group-chronological-v1",
        "total_records": 8,
        "splits": {
            name: {
                "file": path.name,
                "sha256": details[name]["sha256"],
                "record_count": 2,
            }
            for name, path in paths.items()
        },
        "locked_test": {
            "file": "test.jsonl",
            "sha256": details["test"]["sha256"],
            "rule": "never tune on test",
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    validate_split_manifest(manifest_path, paths, details)
    details["test"]["sha256"] = "0" * 64
    with pytest.raises(BaselineDataError, match="SHA-256 mismatch for test"):
        validate_split_manifest(manifest_path, paths, details)
