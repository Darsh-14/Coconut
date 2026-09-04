"""Create leakage-safe chronological splits from normalized real dispute records.

This is an offline research utility.  It never contacts Razorpay and never reads secrets.
Input must first be normalized and pseudonymized by ``import_real_disputes.py``.

The splitter keeps every ``leakage_group_ref`` in exactly one split, orders groups by
decision time, and only permits boundaries that do not move backward in time. It writes four
JSONL files plus a manifest containing counts and SHA-256 fingerprints.  The fingerprint
of ``test.jsonl`` is the lock: training and threshold selection must never consume it.

Usage (from ``backend/``)::

    python data/split_real_disputes.py \
        --input data/private/normalized.jsonl \
        --output-dir data/private/splits
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.real_data import RealDisputeRecord  # noqa: E402

SPLIT_NAMES = ("train", "validation", "calibration", "test")
DEFAULT_RATIOS = (0.60, 0.15, 0.10, 0.15)
ALGORITHM_VERSION = "strict-group-chronological-v1"


class SplitError(ValueError):
    """Raised when safe splits cannot be produced from the supplied corpus."""


@dataclass(frozen=True)
class _Group:
    key: str
    records: tuple[RealDisputeRecord, ...]
    first_decision_at: datetime
    last_decision_at: datetime


def _json_records(path: Path) -> list[dict[str, Any]]:
    """Read a JSON array or JSONL file without accepting any other top-level shape."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SplitError(f"cannot read {path}: {exc}") from exc

    if not text.strip():
        raise SplitError(f"{path} is empty")

    if path.suffix.lower() == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SplitError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(row, dict):
                raise SplitError(f"{path}:{line_number}: each JSONL row must be an object")
            rows.append(row)
        return rows

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SplitError(f"{path}: invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise SplitError(f"{path}: expected a JSON array of objects (or use a .jsonl file)")
    return payload


def load_normalized(path: Path) -> list[RealDisputeRecord]:
    """Load and revalidate importer output, rejecting duplicate dispute references."""
    if not path.is_file():
        raise SplitError(f"input does not exist or is not a file: {path}")

    records: list[RealDisputeRecord] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(_json_records(path), 1):
        try:
            record = RealDisputeRecord.model_validate(raw)
        except ValidationError as exc:
            # Pydantic's default exception rendering includes ``input_value``. If someone
            # accidentally points this tool at a raw export, echoing that error could put
            # PII into a terminal log. Keep only field locations and validation messages.
            details = "; ".join(
                f"{'.'.join(str(part) for part in error.get('loc', ())) or 'record'}: "
                f"{error['msg']}"
                for error in exc.errors(include_url=False, include_input=False)
            )
            raise SplitError(
                f"record {index} is not valid normalized data ({details})"
            ) from None
        identity = (record.merchant_ref, record.dispute_ref)
        if identity in seen:
            raise SplitError(
                f"duplicate normalized dispute at record {index}: "
                f"merchant_ref={record.merchant_ref!r}, dispute_ref={record.dispute_ref!r}"
            )
        seen.add(identity)
        records.append(record)

    if not records:
        raise SplitError("the normalized corpus contains no records")
    return records


def parse_ratios(value: str | Sequence[float]) -> tuple[float, float, float, float]:
    """Parse and validate four non-zero ratios that sum to one."""
    if isinstance(value, str):
        try:
            ratios = tuple(float(part.strip()) for part in value.split(","))
        except ValueError as exc:
            raise SplitError("--ratios must contain four comma-separated numbers") from exc
    else:
        ratios = tuple(float(part) for part in value)

    if len(ratios) != len(SPLIT_NAMES):
        raise SplitError("exactly four ratios are required: train,validation,calibration,test")
    if any(ratio <= 0 or ratio >= 1 for ratio in ratios):
        raise SplitError("every split ratio must be greater than 0 and less than 1")
    if abs(sum(ratios) - 1.0) > 1e-9:
        raise SplitError(f"split ratios must sum to 1.0; received {sum(ratios):.12g}")
    return ratios  # type: ignore[return-value]


def _make_groups(records: Iterable[RealDisputeRecord]) -> list[_Group]:
    buckets: dict[str, list[RealDisputeRecord]] = defaultdict(list)
    for record in records:
        buckets[record.leakage_group_ref].append(record)

    groups: list[_Group] = []
    for key, members in buckets.items():
        ordered = tuple(sorted(members, key=lambda row: (row.decision_at, row.dispute_ref)))
        groups.append(
            _Group(
                key=key,
                records=ordered,
                first_decision_at=ordered[0].decision_at,
                last_decision_at=ordered[-1].decision_at,
            )
        )
    return sorted(groups, key=lambda group: (group.first_decision_at, group.key))


def _valid_boundary_positions(groups: Sequence[_Group]) -> list[int]:
    """Return cuts where every timestamp on the left is <= every timestamp on the right."""
    if len(groups) < 2:
        return []

    prefix_latest: list[datetime] = []
    latest = groups[0].last_decision_at
    for group in groups:
        latest = max(latest, group.last_decision_at)
        prefix_latest.append(latest)

    suffix_earliest: list[datetime] = [groups[-1].first_decision_at] * len(groups)
    earliest = groups[-1].first_decision_at
    for index in range(len(groups) - 1, -1, -1):
        earliest = min(earliest, groups[index].first_decision_at)
        suffix_earliest[index] = earliest

    return [
        cut
        for cut in range(1, len(groups))
        if prefix_latest[cut - 1] <= suffix_earliest[cut]
    ]


def _choose_cuts(
    groups: Sequence[_Group], ratios: Sequence[float]
) -> tuple[int, int, int]:
    """Select three valid temporal cuts nearest the requested cumulative record ratios."""
    valid = _valid_boundary_positions(groups)
    boundary_count = len(SPLIT_NAMES) - 1
    if len(valid) < boundary_count:
        raise SplitError(
            "cannot create four strictly chronological, group-disjoint splits: only "
            f"{len(valid)} non-decreasing temporal boundaries exist across "
            f"{len(groups)} leakage groups. Check overly broad/spanning leakage_group_ref "
            "values or collect more chronological groups; safety is not weakened automatically."
        )

    cumulative_records: list[int] = [0]
    for group in groups:
        cumulative_records.append(cumulative_records[-1] + len(group.records))
    total = cumulative_records[-1]
    targets: list[float] = []
    running = 0.0
    for ratio in ratios[:-1]:
        running += ratio
        targets.append(total * running)

    # Dynamic programming: dp[j][i] is the least cumulative target error after choosing
    # boundary j at valid[i].  A prefix minimum makes this O(3*n), not O(n^3).
    previous: list[float] = [abs(cumulative_records[cut] - targets[0]) for cut in valid]
    parents: list[list[int | None]] = [[None] * len(valid)]

    for target_index in range(1, boundary_count):
        current = [float("inf")] * len(valid)
        parent = [None] * len(valid)
        best_cost = float("inf")
        best_index: int | None = None
        for index, cut in enumerate(valid):
            # Update with positions strictly before this one.
            preceding = index - 1
            if preceding >= 0 and previous[preceding] < best_cost:
                best_cost = previous[preceding]
                best_index = preceding
            if best_index is not None:
                current[index] = best_cost + abs(cumulative_records[cut] - targets[target_index])
                parent[index] = best_index
        previous = current
        parents.append(parent)

    final_index = min(range(len(valid)), key=lambda index: (previous[index], valid[index]))
    if previous[final_index] == float("inf"):
        raise SplitError("not enough ordered temporal boundaries to create four non-empty splits")

    chosen_indices = [final_index]
    for target_index in range(boundary_count - 1, 0, -1):
        parent_index = parents[target_index][chosen_indices[-1]]
        if parent_index is None:  # defensive; the finite-state check above should prevent it
            raise SplitError("internal boundary-selection failure")
        chosen_indices.append(parent_index)
    chosen_indices.reverse()
    return tuple(valid[index] for index in chosen_indices)  # type: ignore[return-value]


def split_records(
    records: Sequence[RealDisputeRecord],
    ratios: Sequence[float] = DEFAULT_RATIOS,
) -> dict[str, list[RealDisputeRecord]]:
    """Return non-empty group-disjoint splits with strict temporal boundaries."""
    checked_ratios = parse_ratios(ratios)
    groups = _make_groups(records)
    if len(groups) < len(SPLIT_NAMES):
        raise SplitError(
            f"at least {len(SPLIT_NAMES)} leakage groups are required; found {len(groups)}"
        )

    cuts = (0, *_choose_cuts(groups, checked_ratios), len(groups))
    result: dict[str, list[RealDisputeRecord]] = {}
    for index, name in enumerate(SPLIT_NAMES):
        selected_groups = groups[cuts[index] : cuts[index + 1]]
        selected = [record for group in selected_groups for record in group.records]
        result[name] = sorted(selected, key=lambda row: (row.decision_at, row.dispute_ref))

    _assert_safe(result)
    return result


def _assert_safe(splits: dict[str, list[RealDisputeRecord]]) -> None:
    """Fail closed if grouping or chronological invariants were violated."""
    owner: dict[str, str] = {}
    for name in SPLIT_NAMES:
        records = splits.get(name, [])
        if not records:
            raise SplitError(f"split {name!r} is empty")
        for record in records:
            previous = owner.setdefault(record.leakage_group_ref, name)
            if previous != name:
                raise SplitError(
                    f"leakage group {record.leakage_group_ref!r} appears in {previous} and {name}"
                )

    for left_name, right_name in zip(SPLIT_NAMES, SPLIT_NAMES[1:]):
        latest_left = max(row.decision_at for row in splits[left_name])
        earliest_right = min(row.decision_at for row in splits[right_name])
        if latest_left > earliest_right:
            raise SplitError(
                f"chronology reversal between {left_name} and {right_name}: "
                f"{latest_left.isoformat()} > {earliest_right.isoformat()}"
            )


def _canonical_jsonl(records: Sequence[RealDisputeRecord]) -> bytes:
    lines = [
        json.dumps(
            record.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for record in records
    ]
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _distribution(records: Sequence[RealDisputeRecord], field: str) -> dict[str, int]:
    def display(value: Any) -> str:
        return str(getattr(value, "value", value))

    counts = Counter(display(getattr(row, field)) for row in records)
    return dict(sorted(counts.items()))


def build_manifest(
    splits: dict[str, list[RealDisputeRecord]],
    ratios: Sequence[float],
    input_path: Path,
    input_sha256: str,
    payloads: dict[str, bytes],
) -> dict[str, Any]:
    """Build a PII-free, machine-checkable provenance manifest."""
    details: dict[str, Any] = {}
    for name in SPLIT_NAMES:
        records = splits[name]
        details[name] = {
            "file": f"{name}.jsonl",
            "sha256": _sha256(payloads[name]),
            "record_count": len(records),
            "leakage_group_count": len({row.leakage_group_ref for row in records}),
            "merchant_count": len({row.merchant_ref for row in records}),
            "decision_at_min": min(row.decision_at for row in records).isoformat(),
            "decision_at_max": max(row.decision_at for row in records).isoformat(),
            "merchant_action": _distribution(records, "merchant_action"),
            "final_outcome": _distribution(records, "final_outcome"),
        }

    return {
        "schema_version": "1.0",
        "algorithm": ALGORITHM_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # Even a basename can contain a merchant/customer name, so provenance retains only
        # the content fingerprint and non-identifying format.
        "input_format": input_path.suffix.lower().lstrip("."),
        "input_sha256": input_sha256,
        "requested_ratios": dict(zip(SPLIT_NAMES, ratios)),
        "total_records": sum(len(rows) for rows in splits.values()),
        "splits": details,
        "locked_test": {
            "file": "test.jsonl",
            "sha256": details["test"]["sha256"],
            "rule": "never use for feature, model, hyperparameter, or threshold selection",
        },
    }


def _atomic_write(path: Path, data: bytes) -> None:
    """Replace one file atomically without ever exposing a partially written payload."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_splits(
    splits: dict[str, list[RealDisputeRecord]],
    output_dir: Path,
    ratios: Sequence[float],
    input_path: Path,
    force: bool = False,
) -> dict[str, Any]:
    """Write all split files and the manifest, refusing accidental overwrite by default."""
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = [output_dir / f"{name}.jsonl" for name in SPLIT_NAMES]
    targets.append(output_dir / "manifest.json")
    if input_path.resolve() in {path.resolve() for path in targets}:
        raise SplitError("the normalized input file cannot also be one of the output artifacts")
    existing = [path.name for path in targets if path.exists()]
    if existing and not force:
        raise SplitError(
            f"refusing to overwrite existing split artifacts: {', '.join(existing)}; "
            "pass --force only when intentionally creating a new dataset version"
        )

    payloads = {name: _canonical_jsonl(splits[name]) for name in SPLIT_NAMES}
    input_sha256 = _sha256(input_path.read_bytes())
    manifest = build_manifest(splits, ratios, input_path, input_sha256, payloads)
    manifest_bytes = (
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")

    # Manifest is written last: its presence means every file it fingerprints is complete.
    for name in SPLIT_NAMES:
        _atomic_write(output_dir / f"{name}.jsonl", payloads[name])
    _atomic_write(output_dir / "manifest.json", manifest_bytes)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True, help="Normalized JSON/JSONL input.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Private output directory.")
    parser.add_argument(
        "--ratios",
        default=",".join(str(value) for value in DEFAULT_RATIOS),
        help="train,validation,calibration,test ratios (default: 0.60,0.15,0.10,0.15).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an intentional prior split version. The new manifest gets new hashes.",
    )
    args = parser.parse_args()

    try:
        ratios = parse_ratios(args.ratios)
        records = load_normalized(args.input)
        splits = split_records(records, ratios)
        manifest = write_splits(splits, args.output_dir, ratios, args.input, args.force)
    except SplitError as exc:
        parser.error(str(exc))

    print(f"Wrote {manifest['total_records']} normalized records to {args.output_dir}")
    for name in SPLIT_NAMES:
        details = manifest["splits"][name]
        print(
            f"  {name:<11} {details['record_count']:>6} records  "
            f"{details['leakage_group_count']:>6} groups  sha256={details['sha256'][:12]}..."
        )
    print(f"Locked test fingerprint: {manifest['locked_test']['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
