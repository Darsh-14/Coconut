"""Supplement isolation checks; these tests never train or load the NLI model."""
import json
from pathlib import Path

import pytest
from app.models.schemas import Dispute
from data.build_training_supplement import build_records
from training.train_synthetic_win_gate import load_supplement, TrainingError, WORKING_SET


def test_supplement_is_valid_distinct_and_keeps_counterfactual_pairs_in_training(tmp_path):
    values = build_records()
    assert len(values) == 24
    assert len({v['dispute_id'] for v in values}) == 24
    assert len({v['claim_text'] for v in values}) == 12
    assert sum(v['ground_truth_label'] == 'contest_win' for v in values) == 12
    path = tmp_path / 'supplement.json'
    path.write_text(json.dumps(values), encoding='utf-8')
    working = [Dispute.model_validate(v) for v in json.loads(WORKING_SET.read_text(encoding='utf-8'))]
    assert len(load_supplement(path, working)) == 24


def test_supplement_rejects_copied_working_record_under_new_id(tmp_path):
    working = [Dispute.model_validate(v) for v in json.loads(WORKING_SET.read_text(encoding='utf-8'))]
    value = working[0].model_dump(mode='json')
    value['dispute_id'] = 'disp_synthetic_new_id'
    path = tmp_path / 'copy.json'
    path.write_text(json.dumps([value]), encoding='utf-8')
    with pytest.raises(TrainingError, match='overlaps'):
        load_supplement(path, working)


def test_supplement_rejects_held_out_record(tmp_path):
    path = tmp_path / 'copy.json'
    held = Path(__file__).resolve().parents[1] / 'eval/held_out_set.json'
    value = json.loads(held.read_text(encoding='utf-8'))[0]
    path.write_text(json.dumps([value]), encoding='utf-8')
    with pytest.raises(TrainingError, match='overlaps'):
        load_supplement(path, [])
