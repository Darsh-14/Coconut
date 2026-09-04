"""Blind evidence-annotation contracts for the offline real-data pipeline."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.real_data import (
    EvidenceAdjudication,
    RealDisputePhase,
    RealDisputeRecord,
    RealEvidenceType,
    sensitive_text_kind,
)

ANNOTATION_SCHEMA_VERSION = "1.0"
TASK_ID_PATTERN = r"^ann_v1_[0-9a-f]{24}$"
REVIEWER_REF_PATTERN = r"^rev_v1_[0-9a-f]{24}$"

AnnotationRole = Literal["reviewer", "adjudicator"]
AnnotationReasonTag = Literal[
    "direct_match",
    "direct_conflict",
    "missing_link",
    "ambiguous_actor",
    "ambiguous_time",
    "ambiguous_amount",
    "source_unreliable",
    "insufficient_detail",
    "not_applicable",
]


class _FrozenAnnotation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class AnnotationTask(_FrozenAnnotation):
    """One outcome-blind evidence/claim pair shown to reviewers."""

    schema_version: Literal["1.0"] = ANNOTATION_SCHEMA_VERSION
    task_id: str = Field(pattern=TASK_ID_PATTERN)
    rubric_version: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    phase: RealDisputePhase
    reason_code: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    claim_text_redacted: str = Field(min_length=1, max_length=20_000)
    evidence_type: RealEvidenceType
    evidence_content_redacted: str = Field(min_length=1, max_length=50_000)

    @field_validator("claim_text_redacted", "evidence_content_redacted")
    @classmethod
    def visible_text_must_remain_redacted(cls, value: str) -> str:
        sensitive_kind = sensitive_text_kind(value)
        if sensitive_kind:
            raise ValueError(f"annotation text contains an obvious {sensitive_kind}")
        return value


class ReviewerAnnotation(_FrozenAnnotation):
    """A reviewer decision without free text or raw reviewer identity."""

    schema_version: Literal["1.0"] = ANNOTATION_SCHEMA_VERSION
    task_id: str = Field(pattern=TASK_ID_PATTERN)
    reviewer_ref: str = Field(pattern=REVIEWER_REF_PATTERN)
    role: AnnotationRole = "reviewer"
    label: EvidenceAdjudication
    rubric_version: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    confidence: int = Field(ge=1, le=5)
    reason_tags: tuple[AnnotationReasonTag, ...] = ()

    @field_validator("reason_tags")
    @classmethod
    def reason_tags_must_be_unique(
        cls, value: tuple[AnnotationReasonTag, ...]
    ) -> tuple[AnnotationReasonTag, ...]:
        if len(value) != len(set(value)):
            raise ValueError("reason_tags must not contain duplicates")
        return value


def annotation_task_id(record: RealDisputeRecord, evidence_index: int) -> str:
    """Return a stable ID without exposing the dispute or evidence source reference."""

    evidence = record.evidence[evidence_index]
    payload = json.dumps(
        [
            "coconut-evidence-annotation-v1",
            record.dispute_ref,
            evidence_index,
            evidence.source_ref,
            evidence.type,
            evidence.content_redacted,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"ann_v1_{hashlib.sha256(payload).hexdigest()[:24]}"


def build_annotation_tasks(
    records: Sequence[RealDisputeRecord],
    *,
    rubric_version: str,
    include_annotated: bool = False,
) -> list[AnnotationTask]:
    """Build deterministically ordered tasks containing no action or outcome fields."""

    tasks: list[AnnotationTask] = []
    for record in records:
        for index, evidence in enumerate(record.evidence):
            if evidence.adjudicated_label is not None and not include_annotated:
                continue
            tasks.append(
                AnnotationTask(
                    task_id=annotation_task_id(record, index),
                    rubric_version=rubric_version,
                    phase=record.phase,
                    reason_code=record.reason_code,
                    claim_text_redacted=record.claim_text_redacted,
                    evidence_type=evidence.type,
                    evidence_content_redacted=evidence.content_redacted,
                )
            )
    return sorted(tasks, key=lambda task: task.task_id)


def pseudonymize_reviewer(key: bytes, reviewer_identity: str) -> str:
    """Create a stable local reviewer ref; the raw identity must never be persisted."""

    if len(key) < 32:
        raise ValueError("reviewer pseudonym key must contain at least 32 bytes")
    normalized = reviewer_identity.strip()
    if not normalized:
        raise ValueError("reviewer identity must not be blank")
    digest = hashlib.blake2b(
        normalized.encode("utf-8"), key=key[:64], digest_size=12, person=b"coco-review-v1"
    ).hexdigest()
    return f"rev_v1_{digest}"


__all__ = [
    "ANNOTATION_SCHEMA_VERSION",
    "AnnotationReasonTag",
    "AnnotationRole",
    "AnnotationTask",
    "REVIEWER_REF_PATTERN",
    "ReviewerAnnotation",
    "TASK_ID_PATTERN",
    "annotation_task_id",
    "build_annotation_tasks",
    "pseudonymize_reviewer",
]
