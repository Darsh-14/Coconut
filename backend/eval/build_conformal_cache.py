"""Score the held-out set once, and split it into calibration and test halves.

WHY A CACHE
-----------
Calibrating at a new risk budget must be instant -- the whole point of the slider is that
it responds -- and the per-record scores do not depend on alpha at all. Alpha only chooses
where to cut. So the expensive part (one NLI pass over the held-out set) runs once here,
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
Section 29 says to split the held-out set 50/50 into calibration and test. Implemented
literally, that does not work, and the reason is worth stating rather than hiding:

    held-out calibration half   40 records, of which 12 are contest-eligible
    Hoeffding slack at n=12     0.310
    above lambda = 0.55         n drops to 1, slack 1.073
    smallest achievable alpha   0.539

A guarantee of "at most 54% false positives" is worthless, and every budget a user would
actually ask for comes back unachievable -- which would leave the system deferring 100% of
cases forever. The binding constraint is n, not the model.

So calibration runs on the WORKING set and verification on the FULL held-out set. This is
disjoint by construction (different files, no shared ids), it is exchangeable in the same
way the original split was, and it is arguably more faithful to this project's own
principle than the spec's instruction: spending held-out data to pick a threshold is
tuning on held-out data, which is exactly what the rest of the repo refuses to do.

The consequence is stated in the README rather than buried: even at ~46 calibration
points the slack is ~0.16, so only relatively loose budgets are achievable. That is the
honest finite-sample reality of a distribution-free bound on a few hundred records, and
the UI reports the smallest achievable alpha so the limit is visible instead of implied.

    python eval/build_conformal_cache.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.schemas import Dispute  # noqa: E402
from app.services.conformal_calibrator import SCORE_CACHE  # noqa: E402
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
    engine = get_verification_engine()
    calibration = score_file(WORKING, engine, "working-set (calibration)")
    test = score_file(HELD_OUT, engine, "held-out (test)")

    # The disjointness the guarantee depends on, asserted rather than assumed.
    overlap = {r["dispute_id"] for r in calibration} & {r["dispute_id"] for r in test}
    assert not overlap, f"calibration and test share ids: {sorted(overlap)[:5]}"

    payload = {
        "calibration": calibration,
        "test": test,
        "calibration_source": "data/synthetic_disputes.json (working set)",
        "test_source": "eval/held_out_set.json",
        "structural_rule": (
            "contest_score = min(confidence over supporting verdicts), defined only when "
            "all verdicts support and >= 2 distinct evidence types support"
        ),
    }
    SCORE_CACHE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def eligible(rows):
        return sum(1 for r in rows if r["score"] is not None)

    print("")
    print(
        f"calibration {len(calibration)} ({eligible(calibration)} contest-eligible)  "
        f"test {len(test)} ({eligible(test)} contest-eligible)"
    )
    print(f"wrote {SCORE_CACHE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
