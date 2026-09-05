"""Integrity and metrics helpers for the separately versioned synthetic stress suite."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from app.models.schemas import Dispute
from app.services.conformal_calibrator import (
    DEFAULT_ALPHA, DEFAULT_DELTA, SCORE_CACHE, calibrate_threshold,
    calibration_pairs, expected_cache_metadata, load_scores,
)
from app.services.synthetic_win_gate import ARTIFACT_PATH, load_synthetic_win_model
from eval.real_metrics import wilson_interval

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "eval/stress_1000.json"
MANIFEST = ROOT / "eval/stress_1000.manifest.json"
PROTECTED_DATA = (
    ROOT / "data/synthetic_disputes.json", ROOT / "data/training_supplement.json",
    ROOT / "eval/held_out_set.json", ARTIFACT_PATH, SCORE_CACHE,
)
LIMITATIONS = [
    "Synthetic stress evaluation with authored outcome assumptions, not observed merchant outcomes.",
    "1,000 parameterised cases share 30 scenario families; they are not 1,000 independent observations.",
    "Case-level Wilson intervals assume independence and are descriptive only for this correlated suite.",
    "Templates were authored with knowledge of the application; this is not an independently adjudicated blind test.",
    "Class, rail and reason proportions are designed test coverage, not estimated production prevalence.",
    "All payer references are unique: this suite tests evidence decisions below UPI caps, not cap-history sequences.",
    "Report precision with contest support, coverage, selective recall and population win capture.",
]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def file_digest(path):
    # Stable across Git's Windows/Linux newline conversions.
    return hashlib.sha256(path.read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()


def frozen_configuration():
    cache = load_scores()
    model = load_synthetic_win_model()
    if cache is None or model is None:
        raise ValueError("The shipped calibration cache and gate must both be compatible before evaluation.")
    threshold = calibrate_threshold(calibration_pairs(cache), DEFAULT_ALPHA, DEFAULT_DELTA)
    if threshold is None:
        raise ValueError("The default risk budget has no supported threshold.")
    sources = sorted((ROOT / "app").rglob("*.py")) + [
        ROOT / "eval/build_conformal_cache.py", ROOT / "eval/real_metrics.py",
        ROOT / "eval/stress_common.py", ROOT / "eval/evaluate_stress.py",
        ROOT / "eval/generate_stress_set.py", ROOT / "eval/stress_scenarios.py",
    ]
    return {
        "alpha": DEFAULT_ALPHA, "delta": DEFAULT_DELTA, "nli_threshold": threshold,
        "gate_threshold": model.threshold, "gate_model_version": model.model_version,
        "inference_identity": expected_cache_metadata(),
        "files": {str(p.relative_to(ROOT)).replace("\\", "/"): file_digest(p)
                  for p in [*PROTECTED_DATA, *sources] if p.is_file()},
    }


def input_signature(record):
    return digest({"claim": record.claim_text.strip().lower(),
                   "evidence": sorted((e.type, e.content.strip().lower()) for e in record.evidence_bundle)})


def validate_records(records):
    if len(records) != 1000:
        raise ValueError("The stress suite must contain exactly 1,000 records.")
    ids = [r.dispute_id for r in records]
    if len(set(ids)) != len(ids) or any(not x.startswith("disp_synthetic_stress_") for x in ids):
        raise ValueError("Stress IDs must be unique and must retain the synthetic gate prefix.")
    if any(r.ground_truth_label is None for r in records):
        raise ValueError("Every stress case needs an authored expected outcome.")
    signatures = {input_signature(r) for r in records}
    if len(signatures) != len(records):
        raise ValueError("Duplicate claim/evidence inputs found.")
    for path in PROTECTED_DATA[:3]:
        if not path.exists():
            continue
        previous = [Dispute.model_validate(v) for v in json.loads(path.read_text(encoding="utf-8"))]
        if set(ids) & {r.dispute_id for r in previous} or signatures & {input_signature(r) for r in previous}:
            raise ValueError(f"Exact overlap with {path.name}; aborting.")


def load_suite():
    raw = json.loads(SUITE.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if digest(raw) != manifest["dataset_sha256"]:
        raise ValueError("Dataset differs from its frozen manifest.")
    records = [Dispute.model_validate(v) for v in raw]
    validate_records(records)
    if manifest["frozen_configuration"] != frozen_configuration():
        raise ValueError("Model, thresholds, source code, training data or inference packages changed since freeze.")
    if set(manifest["case_families"]) != {r.dispute_id for r in records}:
        raise ValueError("Family mapping does not match the dataset.")
    return records, manifest


def metrics(rows, cost=1500.0):
    counts = Counter()
    for row in rows:
        positive = row["label"] == "contest_win"
        decision = row["recommendation"]
        if decision == "CONTEST":
            counts["tp" if positive else "fp"] += 1
        elif decision == "ACCEPT":
            counts["fn" if positive else "tn"] += 1
        elif decision == "NO_ACTION_NEEDED":
            counts["auto_resolved"] += 1
        else:
            counts["flagged_human"] += 1
    tp, fp, fn, tn = (counts[k] for k in ("tp", "fp", "fn", "tn"))
    support, decided = tp + fp, tp + fp + fn + tn
    precision = tp / support if support else None
    recall = tp / (tp + fn) if tp + fn else None
    positives = sum(r["label"] == "contest_win" for r in rows)
    return {
        "n_evaluated": len(rows), "contest_support": support,
        "precision": precision,
        "precision_wilson_95_descriptive_only": wilson_interval(tp, support).to_dict() if support else None,
        "selective_recall": recall,
        "selective_f1": (2 * precision * recall / (precision + recall) if precision + recall else 0.0)
                        if precision is not None and recall is not None else None,
        "population_auto_win_capture": tp / positives if positives else None,
        "coverage": decided / len(rows) if rows else 0.0,
        "selective_accuracy": (tp + tn) / decided if decided else None,
        "false_positive_cost_estimate_inr": fp * cost,
        "assumed_cost_per_false_contest_inr": cost,
        "confusion": {k: counts[k] for k in ("tp", "fp", "fn", "tn", "flagged_human", "auto_resolved")},
    }
