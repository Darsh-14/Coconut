"""Score the working and held-out datasets once for the risk-budget prototype.

WHY A CACHE
-----------
Calibrating at a new risk budget must be instant -- the whole point of the slider is that
it responds -- and the per-record scores do not depend on alpha at all. Alpha only chooses
where to cut. So the expensive part (one NLI pass over both datasets) runs once here,
and POST /calibrate replays the threshold search over the cached numbers in microseconds.

WHAT IS CACHED, AND WHY THAT IS ENOUGH
---------------------------------------
Enough to replay the entire decision at any threshold, without re-running the model:

    contest_score    min confidence over supporting verdicts, when the bundle is
                     structurally eligible for CONTEST (all verdicts support, >= 2
                     distinct evidence types). None otherwise -- such a case can never be
                     auto-contested at any lambda, so it never enters the risk estimate.
    max_contradict   highest confidence among contradicting verdicts, for the ACCEPT branch
    urcs_auto_reject Addendum 2's short-circuit, which runs before any of this
    label            ground truth

The structural rules (all-support, >= 2 distinct types, min-not-average) are design
choices, not arbitrary numbers, so they stay fixed and are baked into contest_score.
Only the numeric threshold is calibrated.

THE SPLIT -- AND A DELIBERATE DEVIATION FROM ADDENDUM 3 SECTION 29
------------------------------------------------------------------
Section 29 says to split the held-out set 50/50 into calibration and test. This repository
instead preserves the previously established 79-record held-out set as one evaluation set
and uses the 182-record working set for the threshold search. A literal half split would
also be extremely small:

    held-out calibration half   40 records, of which 12 are contest-eligible
    Hoeffding slack at n=12     0.310
    above lambda = 0.55         n drops to 1, slack 1.073

The larger working set still contains only 42 model-contest-eligible records after the URCS
short-circuit. At delta=0.1 its tightest Hoeffding-corrected statistic is about 0.71, so
ordinary low-risk budgets remain unsupported. Sample size and score quality are both
binding constraints.

Calibration therefore runs on the WORKING set and the empirical check on the FULL held-out
set. They have no shared ids, but the working set was also used to develop the score and
aggregation rule. The larger sample does not make it independent. This is a development-time,
Hoeffding-corrected operating-point search -- not a formal Learn-then-Test guarantee. A
formal release needs a calibration split held apart from score design and a family-wise
multiple-testing procedure for the threshold grid.

The UI reports the smallest empirically supportable alpha so this limitation is visible
instead of implied.

    python eval/build_conformal_cache.py
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.schemas import Dispute  # noqa: E402
from app.services.conformal_calibrator import (  # noqa: E402
    SCORE_CACHE,
    cache_rows_sha256,
    expected_cache_metadata,
)
from app.services.decision_aggregator import (  # noqa: E402
    MIN_DISTINCT_SUPPORTING_EVIDENCE_TYPES,
)
from app.services.urcs_forecaster import forecast_urcs_disposition  # noqa: E402
from app.services.verification_engine import get_verification_engine  # noqa: E402

HELD_OUT = BACKEND_ROOT / "eval" / "held_out_set.json"
WORKING = BACKEND_ROOT / "data" / "synthetic_disputes.json"


def score_record(record: Dispute, history: list[Dispute], engine) -> dict:
    verdicts = engine.verify_bundle(
        record.claim_text, record.evidence_bundle, record.reason_code
    )

    supporting = [v for v in verdicts if v.label == "support"]
    contradicting = [v for v in verdicts if v.label == "contradict"]

    # Structurally eligible for CONTEST: unanimous support across >= 2 evidence types.
    contest_score = None
    if verdicts and len(supporting) == len(verdicts):
        types = {
            record.evidence_bundle[v.evidence_index].type
            for v in supporting
            if v.evidence_index < len(record.evidence_bundle)
        }
        if len(types) >= MIN_DISTINCT_SUPPORTING_EVIDENCE_TYPES:
            # min, not average: a chain of evidence is only as strong as its weakest link.
            contest_score = min(v.confidence for v in supporting)

    forecast = forecast_urcs_disposition(record, history)

    return {
        "dispute_id": record.dispute_id,
        "label": record.ground_truth_label,
        "score": contest_score,
        "max_contradict": max((v.confidence for v in contradicting), default=None),
        "urcs_auto_reject": forecast.predicted_disposition == "AUTO_REJECT",
    }


def score_file(path, engine, label: str) -> list[dict]:
    records = [Dispute(**r) for r in json.loads(path.read_text(encoding="utf-8"))]
    records = [r for r in records if r.ground_truth_label is not None]
    print(f"scoring {len(records)} {label} records...")
    out = []
    for i, record in enumerate(records, 1):
        out.append(score_record(record, records, engine))
        if i % 25 == 0:
            print(f"  ...{i}/{len(records)}", flush=True)
    return out


def main() -> int:
    # Hash every input before loading the model. The run takes minutes; if source or code
    # changes during it, associating old imported behaviour with new on-disk hashes would
    # create an artifact that falsely validates.
    metadata = expected_cache_metadata()
    engine = get_verification_engine()
    calibration = score_file(WORKING, engine, "working-set (calibration)")
    test = score_file(HELD_OUT, engine, "held-out (test)")

    # The held-out empirical check must remain disjoint, asserted rather than assumed.
    overlap = {r["dispute_id"] for r in calibration} & {r["dispute_id"] for r in test}
    assert not overlap, f"calibration and test share ids: {sorted(overlap)[:5]}"

    if expected_cache_metadata() != metadata:
        raise RuntimeError(
            "Cache inputs or pipeline code changed while scoring; discard this run and retry."
        )

    payload = {
        **metadata,
        "calibration": calibration,
        "test": test,
        "rows_sha256": cache_rows_sha256(calibration, test),
        "generation_runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "calibration_source": "data/synthetic_disputes.json (working set)",
        "test_source": "eval/held_out_set.json",
        "structural_rule": (
            "contest_score = min(confidence over supporting verdicts), defined only when "
            "all verdicts support and >= 2 distinct evidence types support"
        ),
    }
    # Replace atomically only after both splits finish. An interrupted five-minute model
    # run must leave the last known-good cache intact rather than a truncated JSON file.
    temporary = SCORE_CACHE.with_suffix(SCORE_CACHE.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(SCORE_CACHE)

    def eligible(rows):
        return sum(
            1
            for r in rows
            if r["score"] is not None and not r.get("urcs_auto_reject", False)
        )

    print("")
    print(
        f"calibration {len(calibration)} ({eligible(calibration)} model-contest-eligible)  "
        f"test {len(test)} ({eligible(test)} model-contest-eligible)"
    )
    print(f"model {payload['model_version']}")
    print(f"wrote {SCORE_CACHE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
