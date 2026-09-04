"""Build a chargeback evidence-classification corpus from human-adjudicated records.

This command never derives evidence labels from dispute outcomes.  Run it independently on
the already frozen train/validation splits; do not combine or reshuffle those splits here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.real_annotations import annotation_task_id  # noqa: E402
from app.models.real_data import RealDisputeRecord  # noqa: E402
from data.annotation_io import (  # noqa: E402
    AnnotationDataError,
    atomic_write_objects,
    load_json_objects,
)


def build_pairs(records: Sequence[RealDisputeRecord]) -> list[dict[str, Any]]:
    """Return only explicitly annotated evidence pairs, in stable order."""

    pairs: list[dict[str, Any]] = []
    for record in records:
        for index, evidence in enumerate(record.evidence):
            if evidence.adjudicated_label is None:
                continue
            pairs.append(
                {
                    "schema_version": "1.0",
                    "pair_id": annotation_task_id(record, index),
                    "phase": record.phase,
                    "reason_code": record.reason_code,
                    "claim_text_redacted": record.claim_text_redacted,
                    "evidence_type": evidence.type,
                    "evidence_content_redacted": evidence.content_redacted,
                    "label": evidence.adjudicated_label,
                    "annotation_provenance": evidence.annotation_provenance,
                    "annotation_version": evidence.annotation_version,
                }
            )
    return sorted(pairs, key=lambda pair: str(pair["pair_id"]))


def build_file(input_path: Path, output_path: Path, *, force: bool = False) -> int:
    try:
        records = [
            RealDisputeRecord.model_validate(row) for row in load_json_objects(input_path)
        ]
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.errors()[0].get("loc", ()))
        raise AnnotationDataError(f"normalized input violates the privacy contract at {location}") from None
    pairs = build_pairs(records)
    if not pairs:
        raise AnnotationDataError("no human-adjudicated evidence pairs were found")
    atomic_write_objects(output_path, pairs, force=force)
    return len(pairs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        count = build_file(args.input, args.output, force=args.force)
    except AnnotationDataError as exc:
        print(f"Evidence-pair build failed: {exc}", file=sys.stderr)
        return 2
    print(f"Built {count} human-labelled evidence pairs at {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
