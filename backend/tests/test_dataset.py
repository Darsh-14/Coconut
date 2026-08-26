"""Dataset integrity guards for the generated corpus (CLAUDE.md Sections 6 and 9).

The dataset is a committed artefact, so these assertions protect it from silent corruption
by a regeneration or a hand edit. The most important one is test_no_leakage_between_splits:
if a record appeared in both the working set and the held-out set, every metric produced by
/evaluate would be quietly inflated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.schemas import KNOWN_REASON_CODES, Dispute

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKING_SET = BACKEND_ROOT / "data" / "synthetic_disputes.json"
HELD_OUT_SET = BACKEND_ROOT / "eval" / "held_out_set.json"

MIN_AMOUNT_PAISE = 29_900  # Rs 299
MAX_AMOUNT_PAISE = 4_500_000  # Rs 45,000


def _load(path: Path) -> list[Dispute]:
    records = json.loads(path.read_text(encoding="utf-8"))
    return [Dispute.model_validate(r) for r in records]


@pytest.fixture(scope="module")
def working_set() -> list[Dispute]:
    return _load(WORKING_SET)


@pytest.fixture(scope="module")
def held_out_set() -> list[Dispute]:
    return _load(HELD_OUT_SET)


def test_both_splits_exist():
    assert WORKING_SET.is_file(), f"missing {WORKING_SET}"
    assert HELD_OUT_SET.is_file(), f"missing {HELD_OUT_SET}"


def test_every_record_is_schema_valid(working_set, held_out_set):
    """_load() would have raised on any invalid record; this pins the count expectation."""
    assert len(working_set) > 0
    assert len(held_out_set) > 0


def test_total_size_within_spec_range(working_set, held_out_set):
    total = len(working_set) + len(held_out_set)
    assert 200 <= total <= 300, f"spec requires 200-300 records, found {total}"


def test_split_is_approximately_seventy_thirty(working_set, held_out_set):
    total = len(working_set) + len(held_out_set)
    train_fraction = len(working_set) / total
    assert 0.67 <= train_fraction <= 0.73, f"train fraction {train_fraction:.3f} is not ~0.70"


def test_no_leakage_between_splits(working_set, held_out_set):
    """A record in both splits would silently inflate every evaluation metric."""
    train_ids = {d.dispute_id for d in working_set}
    held_ids = {d.dispute_id for d in held_out_set}
    assert not (train_ids & held_ids), f"dispute_id overlap: {sorted(train_ids & held_ids)}"

    train_claims = {d.claim_text.strip().lower() for d in working_set}
    held_claims = {d.claim_text.strip().lower() for d in held_out_set}
    overlap = train_claims & held_claims
    assert not overlap, f"{len(overlap)} claim_text value(s) appear in both splits"


def test_dispute_ids_are_unique(working_set, held_out_set):
    all_ids = [d.dispute_id for d in working_set + held_out_set]
    assert len(all_ids) == len(set(all_ids)), "duplicate dispute_id found"


def test_every_record_has_a_ground_truth_label(working_set, held_out_set):
    for record in working_set + held_out_set:
        assert record.ground_truth_label is not None, f"{record.dispute_id} has no label"


def test_label_distribution_matches_spec_proportions(working_set, held_out_set):
    """Section 9: ~40% contest_win, ~60% across contest_loss + should_accept."""
    records = working_set + held_out_set
    total = len(records)
    wins = sum(1 for r in records if r.ground_truth_label == "contest_win")
    win_fraction = wins / total
    assert 0.33 <= win_fraction <= 0.47, f"contest_win share {win_fraction:.1%} is off target"


def test_held_out_distribution_tracks_the_working_set(working_set, held_out_set):
    """Stratified split: the two halves should not differ wildly in label balance."""
    def win_share(records: list[Dispute]) -> float:
        return sum(1 for r in records if r.ground_truth_label == "contest_win") / len(records)

    assert abs(win_share(working_set) - win_share(held_out_set)) < 0.10


def test_amounts_are_within_the_specified_range(working_set, held_out_set):
    for record in working_set + held_out_set:
        assert MIN_AMOUNT_PAISE <= record.amount <= MAX_AMOUNT_PAISE, (
            f"{record.dispute_id} amount {record.amount} paise is outside Rs 299 - Rs 45,000"
        )


def test_reason_codes_are_from_the_known_vocabulary(working_set, held_out_set):
    for record in working_set + held_out_set:
        assert record.reason_code in KNOWN_REASON_CODES, (
            f"{record.dispute_id} has unexpected reason_code {record.reason_code!r}"
        )


def test_every_record_has_at_least_one_evidence_item(working_set, held_out_set):
    for record in working_set + held_out_set:
        assert len(record.evidence_bundle) >= 1, f"{record.dispute_id} has no evidence"


def test_respond_by_is_after_raised_at(working_set, held_out_set):
    """Model validation enforces this, but the queue countdown depends on it holding."""
    for record in working_set + held_out_set:
        assert record.respond_by > record.raised_at


def test_no_record_leaks_its_evidence_quality_bucket(working_set, held_out_set):
    """Section 9 forbids any field hinting at the bucket beyond ground_truth_label."""
    raw = json.loads(WORKING_SET.read_text(encoding="utf-8"))
    raw += json.loads(HELD_OUT_SET.read_text(encoding="utf-8"))
    allowed = set(Dispute.model_fields.keys())
    for record in raw:
        extra = set(record.keys()) - allowed
        assert not extra, f"unexpected field(s) {extra} would leak bucket information"
