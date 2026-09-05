"""Merge independently reviewed evidence labels into a normalized offline dataset."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.real_annotations import ReviewerAnnotation, annotation_task_id  # noqa: E402
from app.models.real_data import (  # noqa: E402
    AnnotationProvenance,
    EvidenceAdjudication,
    RealDisputeRecord,
)
from data.annotation_io import (  # noqa: E402
    AnnotationDataError,
    atomic_write_objects,
    load_json_objects,
)


@dataclass(frozen=True)
class AdjudicationResult:
    records: tuple[RealDisputeRecord, ...]
    labelled_tasks: int
    unresolved_tasks: int
    provenance_counts: dict[str, int]


def _validate_records(path: Path) -> list[RealDisputeRecord]:
    try:
        return [RealDisputeRecord.model_validate(row) for row in load_json_objects(path)]
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.errors()[0].get("loc", ()))
        raise AnnotationDataError(f"normalized input violates the privacy contract at {location}") from None


def _validate_annotations(path: Path) -> list[ReviewerAnnotation]:
    try:
        return [ReviewerAnnotation.model_validate(row) for row in load_json_objects(path)]
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.errors()[0].get("loc", ()))
        raise AnnotationDataError(f"annotation input violates its contract at {location}") from None


def _resolve_task(
    values: Sequence[ReviewerAnnotation], *, allow_single: bool
) -> tuple[EvidenceAdjudication, AnnotationProvenance] | None:
    reviewers = [value for value in values if value.role == "reviewer"]
    adjudicators = [value for value in values if value.role == "adjudicator"]
    if not reviewers:
        raise AnnotationDataError("an adjudicator label cannot exist without a reviewer label")
    if len(adjudicators) > 1:
        raise AnnotationDataError("a task must not have more than one adjudicator label")

    reviewer_labels = {value.label for value in reviewers}
    if adjudicators:
        return adjudicators[0].label, "expert_adjudication"
    if len(reviewers) >= 2 and len(reviewer_labels) == 1:
        return reviewers[0].label, "double_human_consensus"
    if len(reviewers) == 1 and allow_single:
        return reviewers[0].label, "single_human"
    return None


def merge_adjudications(
    records: Sequence[RealDisputeRecord],
    annotations: Sequence[ReviewerAnnotation],
    *,
    rubric_version: str,
    allow_single: bool = False,
    replace_existing: bool = False,
) -> AdjudicationResult:
    task_locations: dict[str, tuple[int, int]] = {}
    for record_index, record in enumerate(records):
        for evidence_index in range(len(record.evidence)):
            task_id = annotation_task_id(record, evidence_index)
            if task_id in task_locations:
                raise AnnotationDataError("duplicate annotation task ID in normalized input")
            task_locations[task_id] = (record_index, evidence_index)

    grouped: dict[str, list[ReviewerAnnotation]] = defaultdict(list)
    seen_reviewers: set[tuple[str, str]] = set()
    for annotation in annotations:
        if annotation.task_id not in task_locations:
            raise AnnotationDataError("annotation references an unknown task")
        if annotation.rubric_version != rubric_version:
            raise AnnotationDataError("annotation rubric version does not match the requested version")
        identity = (annotation.task_id, annotation.reviewer_ref)
        if identity in seen_reviewers:
            raise AnnotationDataError("a reviewer submitted more than one label for the same task")
        seen_reviewers.add(identity)
        grouped[annotation.task_id].append(annotation)

    updated = list(records)
    labelled = 0
    unresolved = 0
    provenance_counts: dict[str, int] = defaultdict(int)
    for task_id, values in grouped.items():
        resolution = _resolve_task(values, allow_single=allow_single)
        if resolution is None:
            unresolved += 1
            continue
        label, provenance = resolution
        record_index, evidence_index = task_locations[task_id]
        record = updated[record_index]
        existing = record.evidence[evidence_index]
        if existing.adjudicated_label is not None and not replace_existing:
            raise AnnotationDataError(
                "target evidence is already annotated; pass --replace-existing to replace it"
            )
        evidence = list(record.evidence)
        evidence[evidence_index] = type(existing).model_validate(
            {
                **existing.model_dump(mode="python"),
                "adjudicated_label": label,
                "annotation_provenance": provenance,
                "annotation_version": rubric_version,
            }
        )
        updated[record_index] = RealDisputeRecord.model_validate(
                {**record.model_dump(mode="json"), "evidence": [item.model_dump(mode="json") for item in evidence]}
        )
        labelled += 1
        provenance_counts[provenance] += 1

    return AdjudicationResult(
        records=tuple(updated),
        labelled_tasks=labelled,
        unresolved_tasks=unresolved,
        provenance_counts=dict(sorted(provenance_counts.items())),
    )


def import_adjudications(
    records_path: Path,
    annotations_path: Path,
    output_path: Path,
    *,
    rubric_version: str,
    allow_single: bool = False,
    replace_existing: bool = False,
    force: bool = False,
) -> AdjudicationResult:
    result = merge_adjudications(
        _validate_records(records_path),
        _validate_annotations(annotations_path),
        rubric_version=rubric_version,
        allow_single=allow_single,
        replace_existing=replace_existing,
    )
    atomic_write_objects(
        output_path,
        [record.model_dump(mode="json") for record in result.records],
        force=force,
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rubric-version", required=True)
    parser.add_argument("--allow-single", action="store_true")
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = import_adjudications(
            args.records,
            args.annotations,
            args.output,
            rubric_version=args.rubric_version,
            allow_single=args.allow_single,
            replace_existing=args.replace_existing,
            force=args.force,
        )
    except AnnotationDataError as exc:
        print(f"Adjudication import failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"Merged {result.labelled_tasks} labels; {result.unresolved_tasks} tasks remain unresolved."
    )
    print(f"Provenance: {result.provenance_counts}")
    print(f"Wrote: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
