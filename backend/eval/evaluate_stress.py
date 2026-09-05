"""Manually run the frozen model on the 1,000-case synthetic stress suite.

No API server, Docker, payment credentials, calibration writes or model training.
Progress is checkpointed after every 20 cases; --resume continues that same run.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.decision_aggregator import aggregate
from app.services.synthetic_win_gate import apply_synthetic_win_gate
from app.services.verification_engine import get_verification_engine
from eval.stress_common import ROOT, digest, load_suite, metrics


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_checkpoint(checkpoint, identity, records, families):
    if checkpoint.get("identity") != identity:
        raise ValueError("Checkpoint belongs to a different dataset/model/run configuration.")
    rows = checkpoint["rows"]
    if len(rows) > len(records):
        raise ValueError("Checkpoint contains too many rows.")
    for row, record in zip(rows, records):
        if (row["dispute_id"] != record.dispute_id or row["label"] != record.ground_truth_label
                or row["reason_code"] != record.reason_code or row["rail"] != record.rail
                or row["family"] != families[record.dispute_id]
                or row["recommendation"] not in {"CONTEST", "ACCEPT", "NEEDS_HUMAN_REVIEW", "NO_ACTION_NEEDED"}):
            raise ValueError("Checkpoint rows do not match this suite in order.")
    return rows


def build_report(rows, manifest, cost, limit):
    slices = {}
    for field in ("reason_code", "rail", "family"):
        groups = defaultdict(list)
        for row in rows:
            groups[row[field]].append(row)
        slices[field] = {key: metrics(group, cost) for key, group in sorted(groups.items())}
    return {
        "evaluation": "synthetic stress suite", "complete_1000": len(rows) == 1000 and limit is None,
        "dataset_sha256": manifest["dataset_sha256"],
        "frozen_configuration": manifest["frozen_configuration"],
        "metrics": metrics(rows, cost), "by_slice": slices,
        "scenario_families_evaluated": len(slices["family"]),
        "families_with_false_contests": [k for k, v in slices["family"].items() if v["confusion"]["fp"]],
        "limitations": manifest["limitations"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "eval/stress_runs/full")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int, help="Smoke test only; report will be marked incomplete.")
    parser.add_argument("--cost-inr", type=float, default=1500.0, help="Assumed cost per false contest, not an observed fee.")
    args = parser.parse_args()
    if args.limit is not None and not 1 <= args.limit <= 1000:
        parser.error("--limit must be 1..1000")
    if not math.isfinite(args.cost_inr) or args.cost_inr < 0:
        parser.error("--cost-inr must be finite and nonnegative")
    records, manifest = load_suite()
    print(f"Validated {len(records)} cases, {manifest['scenario_families']} families; frozen model and calibration match.", flush=True)
    if args.validate_only:
        return
    chosen = records[:args.limit] if args.limit else records
    identity = digest({"manifest": manifest, "limit": args.limit, "cost_inr": args.cost_inr})
    output = args.output_dir.resolve()
    if args.resume:
        checkpoint = json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))
        rows = validate_checkpoint(checkpoint, identity, chosen, manifest["case_families"])
    else:
        output.mkdir(parents=True, exist_ok=False)
        rows = []
        save(output / "checkpoint.json", {"identity": identity, "rows": rows})
    start = time.monotonic()
    initial_count = len(rows)
    # Labels and family names are never passed to inference or the aggregator.
    history = [record.model_copy(update={"ground_truth_label": None}) for record in records]
    threshold = manifest["frozen_configuration"]["nli_threshold"]
    engine = get_verification_engine()
    for index in range(initial_count, len(chosen)):
        record, blind_record = chosen[index], history[index]
        verdicts = engine.verify_bundle(blind_record.claim_text, blind_record.evidence_bundle, blind_record.reason_code)
        result = aggregate(verdicts, blind_record.evidence_bundle, blind_record, history, threshold=threshold)
        result, gate = apply_synthetic_win_gate(result, blind_record)
        rows.append({
            "dispute_id": record.dispute_id, "label": record.ground_truth_label,
            "recommendation": result.recommendation, "reason_code": record.reason_code,
            "rail": record.rail, "family": manifest["case_families"][record.dispute_id],
            "rationale": result.rationale, "gate": asdict(gate),
            "verdicts": [v.model_dump(mode="json") for v in verdicts],
        })
        if len(rows) % 20 == 0 or len(rows) == len(chosen):
            load_suite()  # Refuse to mix results if files change during a long run.
            save(output / "checkpoint.json", {"identity": identity, "rows": rows})
            print(f"{len(rows)}/{len(chosen)} complete; {time.monotonic() - start:.0f}s this session", flush=True)
    load_suite()
    report = build_report(rows, manifest, args.cost_inr, args.limit)
    save(output / "report.json", report)
    print(json.dumps({"complete_1000": report["complete_1000"], **report["metrics"]}, indent=2))
    print(f"Report: {output / 'report.json'}")
    print("Synthetic template variations are correlated; see family results and limitations in the report.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"Stress evaluation stopped: {exc}") from exc
