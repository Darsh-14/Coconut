"""Export outcome-blind evidence/claim pairs for independent human review."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.real_annotations import build_annotation_tasks  # noqa: E402
from app.models.real_data import RealDisputeRecord  # noqa: E402
from data.annotation_io import (  # noqa: E402
    AnnotationDataError,
    atomic_write_objects,
    load_json_objects,
)


def export_batch(
    input_path: Path,
    output_path: Path,
    *,
    rubric_version: str,
    include_annotated: bool = False,
    force: bool = False,
) -> int:
    try:
        records = [RealDisputeRecord.model_validate(row) for row in load_json_objects(input_path)]
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.errors()[0].get("loc", ()))
        raise AnnotationDataError(f"normalized input violates the privacy contract at {location}") from None
    tasks = build_annotation_tasks(
        records, rubric_version=rubric_version, include_annotated=include_annotated
    )
    if not tasks:
        raise AnnotationDataError("no evidence items are eligible for annotation")
    atomic_write_objects(
        output_path,
        [task.model_dump(mode="json") for task in tasks],
        force=force,
    )
    return len(tasks)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rubric-version", required=True)
    parser.add_argument("--include-annotated", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        count = export_batch(
            args.input,
            args.output,
            rubric_version=args.rubric_version,
            include_annotated=args.include_annotated,
            force=args.force,
        )
    except AnnotationDataError as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 2
    print(f"Exported {count} outcome-blind evidence tasks to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
