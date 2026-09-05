"""Stress-suite integrity, honest abstention metrics, and resume guards."""
import copy
import json

import pytest

from eval.generate_stress_set import generate
from eval.stress_common import SUITE, MANIFEST, digest, load_suite, metrics, validate_records
from eval.evaluate_stress import build_report, validate_checkpoint


def test_1000_reproducible_cases_without_original_split_overlap():
    records, families = generate()
    repeat, again = generate()
    assert records == repeat and families == again
    assert len(records) == 1000
    assert len(set(families.values())) == 30
    assert {r.ground_truth_label for r in records} == {"contest_win", "contest_loss", "should_accept"}
    assert len({r.reason_code for r in records}) == 6
    assert len({r.payer_ref for r in records}) == 1000
    assert all(r.phase == "chargeback" for r in records)
    assert all(r.rail != "upi" for r in records if r.reason_code == "unrecognized_transaction")
    validate_records(records)
    with pytest.raises(ValueError, match="unique"):
        validate_records([records[0], *records[:-1]])
    duplicate = records[0].model_copy(update={"dispute_id": records[-1].dispute_id})
    with pytest.raises(ValueError, match="Duplicate claim"):
        validate_records([*records[:-1], duplicate])


def test_saved_suite_matches_generator_and_frozen_configuration():
    records, manifest = load_suite()
    expected, families = generate()
    assert records == expected
    assert manifest["case_families"] == families
    assert digest(json.loads(SUITE.read_text(encoding="utf-8"))) == manifest["dataset_sha256"]


def test_suite_rejects_dataset_or_configuration_tampering(monkeypatch, tmp_path):
    import eval.stress_common as common
    raw = json.loads(SUITE.read_text(encoding="utf-8"))
    raw[0]["amount"] += 100
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(common, "SUITE", changed)
    with pytest.raises(ValueError, match="Dataset differs"):
        common.load_suite()
    monkeypatch.setattr(common, "SUITE", SUITE)
    monkeypatch.setattr(common, "frozen_configuration", lambda: {"changed": True})
    with pytest.raises(ValueError, match="changed since freeze"):
        common.load_suite()


def test_abstention_is_not_credited_as_accuracy_or_population_recall():
    rows = [{"label": label, "recommendation": decision} for label, decision in [
        ("contest_win", "CONTEST"), ("contest_loss", "CONTEST"),
        ("contest_win", "ACCEPT"), ("should_accept", "ACCEPT"),
        ("contest_win", "NEEDS_HUMAN_REVIEW"), ("contest_loss", "NO_ACTION_NEEDED"),
    ]]
    result = metrics(rows)
    assert result["precision"] == .5
    assert result["selective_recall"] == .5
    assert result["population_auto_win_capture"] == pytest.approx(1 / 3)
    assert result["coverage"] == pytest.approx(4 / 6)
    assert result["false_positive_cost_estimate_inr"] == 1500
    assert result["contest_support"] == 2
    assert result["confusion"]["flagged_human"] == 1
    assert metrics([])["precision"] is None
    assert metrics(rows[4:])["precision_wilson_95_descriptive_only"] is None


def test_resume_rejects_different_run_and_wrong_row_order():
    records, families = generate()
    row = {"dispute_id": records[0].dispute_id, "label": records[0].ground_truth_label,
           "recommendation": "NEEDS_HUMAN_REVIEW", "reason_code": records[0].reason_code,
           "rail": records[0].rail, "family": families[records[0].dispute_id]}
    checkpoint = {"identity": "frozen-run", "rows": [row]}
    assert validate_checkpoint(checkpoint, "frozen-run", records, families) == [row]
    with pytest.raises(ValueError, match="different dataset"):
        validate_checkpoint(checkpoint, "other-run", records, families)
    wrong = copy.deepcopy(checkpoint)
    wrong["rows"][0]["dispute_id"] = records[1].dispute_id
    with pytest.raises(ValueError, match="in order"):
        validate_checkpoint(wrong, "frozen-run", records, families)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    report = build_report([row], manifest, 1500, 1)
    assert report["complete_1000"] is False
    assert report["scenario_families_evaluated"] == 1
