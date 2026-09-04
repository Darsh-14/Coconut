"""Tests for outcome blinding, adjudication rules, and agreement measurement."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.real_annotations import (
    ReviewerAnnotation,
    annotation_task_id,
    build_annotation_tasks,
)
from app.models.real_data import RealDisputeRecord
from data.annotation_io import AnnotationDataError
from data.audit_annotation_agreement import agreement_report
from data.import_adjudications import merge_adjudications
from training.build_evidence_pairs import build_pairs


def _record() -> RealDisputeRecord:
    created = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return RealDisputeRecord.model_validate(
        {
            "schema_version": "1.0",
            "source_kind": "merchant_export",
            "merchant_ref": f"coc_v1_{1:024x}",
            "dispute_ref": f"coc_v1_{2:024x}",
            "leakage_group_ref": f"coc_v1_{3:024x}",
            "created_at": created.isoformat(),
            "decision_at": (created + timedelta(days=1)).isoformat(),
            "resolved_at": (created + timedelta(days=8)).isoformat(),
            "phase": "chargeback",
            "reason_code": "goods_not_received",
            "rail": "card",
            "amount": 249900,
            "currency": "INR",
            "claim_text_redacted": "The customer states that the goods did not arrive.",
            "evidence": [
                {
                    "type": "delivery_proof",
                    "content_redacted": "Carrier status says delivered on the promised date.",
                }
            ],
            "merchant_action": "contested",
            "final_outcome": "won",
            "evidence_submitted": True,
            "recovered_amount": 249900,
            "representment_cost": 10000,
        }
    )


def _annotation(task_id: str, reviewer: int, label: str, role: str = "reviewer"):
    return ReviewerAnnotation.model_validate(
        {
            "task_id": task_id,
            "reviewer_ref": f"rev_v1_{reviewer:024x}",
            "role": role,
            "label": label,
            "rubric_version": "evidence-v1",
            "confidence": 4,
        }
    )


def test_annotation_task_is_deterministic_and_outcome_blind():
    record = _record()
    first = build_annotation_tasks([record], rubric_version="evidence-v1")
    second = build_annotation_tasks([record], rubric_version="evidence-v1")

    assert first == second
    assert first[0].task_id == annotation_task_id(record, 0)
    rendered = first[0].model_dump_json()
    for forbidden in (
        "merchant_ref",
        "dispute_ref",
        "source_ref",
        "merchant_action",
        "final_outcome",
        "recovered_amount",
        "representment_cost",
        "won",
    ):
        assert forbidden not in rendered


def test_two_reviewer_consensus_is_provenanced():
    record = _record()
    task_id = annotation_task_id(record, 0)
    result = merge_adjudications(
        [record],
        [_annotation(task_id, 1, "support"), _annotation(task_id, 2, "support")],
        rubric_version="evidence-v1",
    )

    evidence = result.records[0].evidence[0]
    assert evidence.adjudicated_label == "support"
    assert evidence.annotation_provenance == "double_human_consensus"
    assert evidence.annotation_version == "evidence-v1"
    assert result.labelled_tasks == 1


def test_disagreement_requires_adjudicator_and_never_uses_case_outcome():
    record = _record()
    task_id = annotation_task_id(record, 0)
    conflicting = [
        _annotation(task_id, 1, "support"),
        _annotation(task_id, 2, "contradict"),
    ]
    unresolved = merge_adjudications(
        [record], conflicting, rubric_version="evidence-v1"
    )
    assert unresolved.unresolved_tasks == 1
    assert unresolved.records[0].evidence[0].adjudicated_label is None

    resolved = merge_adjudications(
        [record],
        [*conflicting, _annotation(task_id, 3, "insufficient", "adjudicator")],
        rubric_version="evidence-v1",
    )
    evidence = resolved.records[0].evidence[0]
    assert evidence.adjudicated_label == "insufficient"
    assert evidence.annotation_provenance == "expert_adjudication"


def test_single_review_and_duplicate_submissions_fail_closed_by_default():
    record = _record()
    task_id = annotation_task_id(record, 0)
    single = _annotation(task_id, 1, "support")
    result = merge_adjudications([record], [single], rubric_version="evidence-v1")
    assert result.labelled_tasks == 0
    assert result.unresolved_tasks == 1

    with pytest.raises(AnnotationDataError, match="more than one label"):
        merge_adjudications(
            [record], [single, single], rubric_version="evidence-v1"
        )


def test_agreement_report_has_kappa_but_no_reviewer_or_task_refs():
    task_a = "ann_v1_" + "1" * 24
    task_b = "ann_v1_" + "2" * 24
    annotations = [
        _annotation(task_a, 1, "support"),
        _annotation(task_a, 2, "support"),
        _annotation(task_b, 1, "contradict"),
        _annotation(task_b, 2, "neutral"),
    ]
    report = agreement_report(annotations)
    rendered = str(report)

    assert report["tasks_with_disagreement"] == 1
    assert report["pairwise"][0]["observed_agreement"] == 0.5
    assert report["pairwise"][0]["cohen_kappa"] == pytest.approx(1 / 3)
    assert "rev_v1_" not in rendered
    assert "ann_v1_" not in rendered


def test_evidence_pair_corpus_uses_human_label_not_case_outcome():
    record = _record()
    task_id = annotation_task_id(record, 0)
    adjudicated = merge_adjudications(
        [record],
        [
            _annotation(task_id, 1, "contradict"),
            _annotation(task_id, 2, "contradict"),
        ],
        rubric_version="evidence-v1",
    ).records[0]
    pair = build_pairs([adjudicated])[0]
    rendered = str(pair)

    assert pair["label"] == "contradict"
    assert "final_outcome" not in rendered
    assert "merchant_action" not in rendered
    assert "contest_win" not in rendered
