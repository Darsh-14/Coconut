"""Compute privacy-safe reviewer agreement diagnostics for evidence labels."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any, Sequence

from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.real_annotations import ReviewerAnnotation  # noqa: E402
from data.annotation_io import (  # noqa: E402
    AnnotationDataError,
    atomic_write_bytes,
    load_json_objects,
)

LABELS = ("support", "contradict", "neutral", "insufficient")


def _cohen_kappa(left: Sequence[str], right: Sequence[str]) -> float | None:
    if len(left) != len(right) or not left:
        return None
    n = len(left)
    observed = sum(a == b for a, b in zip(left, right)) / n
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected = sum(left_counts[label] * right_counts[label] for label in LABELS) / (n * n)
    if expected >= 1.0:
        return 1.0 if observed >= 1.0 else None
    return (observed - expected) / (1.0 - expected)


def agreement_report(annotations: Sequence[ReviewerAnnotation]) -> dict[str, Any]:
    reviewer_rows = [value for value in annotations if value.role == "reviewer"]
    if not reviewer_rows:
        raise AnnotationDataError("no reviewer labels were provided")

    by_reviewer: dict[str, dict[str, str]] = {}
    by_task: dict[str, list[str]] = {}
    for value in reviewer_rows:
        reviewer_tasks = by_reviewer.setdefault(value.reviewer_ref, {})
        if value.task_id in reviewer_tasks:
            raise AnnotationDataError("a reviewer submitted more than one label for the same task")
        reviewer_tasks[value.task_id] = value.label
        by_task.setdefault(value.task_id, []).append(value.label)

    aliases = {
        reviewer_ref: f"reviewer_{index:03d}"
        for index, reviewer_ref in enumerate(sorted(by_reviewer), start=1)
    }
    pairs: list[dict[str, Any]] = []
    for left_ref, right_ref in combinations(sorted(by_reviewer), 2):
        shared = sorted(set(by_reviewer[left_ref]) & set(by_reviewer[right_ref]))
        if not shared:
            continue
        left = [by_reviewer[left_ref][task_id] for task_id in shared]
        right = [by_reviewer[right_ref][task_id] for task_id in shared]
        confusion = {
            left_label: {
                right_label: sum(
                    a == left_label and b == right_label for a, b in zip(left, right)
                )
                for right_label in LABELS
            }
            for left_label in LABELS
        }
        pairs.append(
            {
                "reviewer_a": aliases[left_ref],
                "reviewer_b": aliases[right_ref],
                "shared_tasks": len(shared),
                "observed_agreement": sum(a == b for a, b in zip(left, right)) / len(shared),
                "cohen_kappa": _cohen_kappa(left, right),
                "confusion_matrix_rows_a_columns_b": confusion,
            }
        )

    multi_reviewed = [labels for labels in by_task.values() if len(labels) >= 2]
    disagreements = sum(len(set(labels)) > 1 for labels in multi_reviewed)
    label_counts = Counter(value.label for value in reviewer_rows)
    return {
        "schema_version": "1.0",
        "reviewers": len(by_reviewer),
        "tasks": len(by_task),
        "reviewer_labels": len(reviewer_rows),
        "tasks_with_two_or_more_reviews": len(multi_reviewed),
        "tasks_with_disagreement": disagreements,
        "disagreement_rate_on_multi_reviewed": (
            disagreements / len(multi_reviewed) if multi_reviewed else None
        ),
        "label_distribution": {label: label_counts[label] for label in LABELS},
        "pairwise": pairs,
        "contains_task_or_reviewer_identifiers": False,
    }


def audit_file(input_path: Path, output_path: Path, *, force: bool = False) -> dict[str, Any]:
    try:
        annotations = [
            ReviewerAnnotation.model_validate(row) for row in load_json_objects(input_path)
        ]
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.errors()[0].get("loc", ()))
        raise AnnotationDataError(f"annotation input violates its contract at {location}") from None
    report = agreement_report(annotations)
    payload = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(output_path, payload, force=force)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = audit_file(args.input, args.output, force=args.force)
    except AnnotationDataError as exc:
        print(f"Agreement audit failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"Audited {report['reviewer_labels']} labels across {report['tasks']} tasks; "
        f"{report['tasks_with_disagreement']} multi-reviewed tasks disagree."
    )
    print(f"Wrote: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
