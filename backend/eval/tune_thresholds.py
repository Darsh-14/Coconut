"""Threshold tuning for the verification engine, on the working set only.

WHAT THIS MAY AND MAY NOT TOUCH
-------------------------------
Tunable here: the engine's own internal constants -- DAMNING_THRESHOLD,
ENGAGEMENT_THRESHOLD, ENGAGEMENT_WEIGHT, SUPPORT_FLOOR. These are design choices made in
this repo, not specified anywhere.

NOT tunable: the Section 10 aggregation rule (contradict > 0.7, average support > 0.65,
>= 2 distinct evidence types, min() for overall confidence). CLAUDE.md states that rule
literally and calls it "exact rule, not a black box". Moving those numbers to flatter a
metric would be tuning away the spec, so the sweep holds them fixed.

WHY IT CACHES
-------------
Scoring the working set costs one full pass of NLI inference (~3 minutes). The thresholds
are applied *after* scoring, so a sweep of thousands of configurations needs exactly one
pass: cache (engagement, damning, substantiation) per evidence item, then replay the
decision logic in pure Python. Without this, a 2,000-point sweep would take four days.

HONESTY NOTE
------------
Selection happens on the working set. The held-out set is scored once, afterwards, with
the single chosen configuration -- never used to choose between configurations.

    python eval/tune_thresholds.py --build-cache      # one inference pass
    python eval/tune_thresholds.py                    # sweep the cache
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.schemas import Dispute  # noqa: E402

WORKING_SET = BACKEND_ROOT / "data" / "synthetic_disputes.json"
CACHE_PATH = BACKEND_ROOT / "eval" / ".signal_cache.json"

# Section 10, held fixed. See the module docstring.
CONTRADICT_GATE = 0.7
SUPPORT_AVERAGE_GATE = 0.65
MIN_DISTINCT_TYPES = 2


def build_cache() -> None:
    """One inference pass over the working set, caching the raw two-signal outputs."""
    from app.services.verification_engine import get_verification_engine

    records = [Dispute(**r) for r in json.loads(WORKING_SET.read_text(encoding="utf-8"))]
    engine = get_verification_engine()

    cached = []
    for i, record in enumerate(records, 1):
        if record.ground_truth_label is None:
            continue
        assessments = engine.assess_bundle(
            record.claim_text, record.evidence_bundle, record.reason_code
        )
        cached.append(
            {
                "dispute_id": record.dispute_id,
                "label": record.ground_truth_label,
                "items": [
                    {
                        "engagement": a.engagement,
                        "damning": a.damning,
                        "substantiation": a.substantiation,
                        "type": record.evidence_bundle[a.evidence_index].type,
                    }
                    for a in assessments
                ],
            }
        )
        if i % 20 == 0:
            print(f"  ...{i}/{len(records)}", flush=True)

    CACHE_PATH.write_text(json.dumps(cached), encoding="utf-8")
    print(f"cached {len(cached)} records -> {CACHE_PATH.name}")


def recommend(record: dict, damning_t: float, engage_t: float, weight: float, floor: float) -> str:
    """Replay _decide() then the Section 10 rule from cached signals."""
    verdicts = []
    for item in record["items"]:
        if item["damning"] > damning_t:
            verdicts.append(("contradict", item["damning"], item["type"]))
        elif item["engagement"] > engage_t:
            blended = weight * item["engagement"] + (1 - weight) * item["substantiation"]
            if blended >= floor:
                verdicts.append(("support", blended, item["type"]))
            else:
                verdicts.append(("neutral", 1.0 - blended, item["type"]))
        else:
            neutrality = 1.0 - max(item["engagement"], item["damning"])
            verdicts.append(("neutral", neutrality, item["type"]))

    if not verdicts:
        return "NEEDS_HUMAN_REVIEW"

    contradicting = [v for v in verdicts if v[0] == "contradict" and v[1] > CONTRADICT_GATE]
    if contradicting:
        return "ACCEPT"

    supporting = [v for v in verdicts if v[0] == "support"]
    if len(supporting) == len(verdicts):
        average = sum(v[1] for v in supporting) / len(supporting)
        distinct = {v[2] for v in supporting}
        if average > SUPPORT_AVERAGE_GATE and len(distinct) >= MIN_DISTINCT_TYPES:
            return "CONTEST"
    return "NEEDS_HUMAN_REVIEW"


def score(records: list[dict], *, damning_t: float, engage_t: float, weight: float, floor: float) -> dict:
    tp = fp = fn = tn = flagged = 0
    for record in records:
        rec = recommend(record, damning_t, engage_t, weight, floor)
        positive = record["label"] == "contest_win"
        if rec == "CONTEST":
            tp += positive
            fp += not positive
        elif rec == "ACCEPT":
            fn += positive
            tn += not positive
        else:
            flagged += 1

    n = len(records)
    decided = n - flagged
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "coverage": decided / n if n else 0.0,
        "accuracy": (tp + tn) / decided if decided else 0.0,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn, "flagged": flagged,
        "decided": decided,
        "fp_cost": fp * 1500,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-cache", action="store_true")
    parser.add_argument(
        "--min-decided",
        type=int,
        default=25,
        help="Reject configurations that auto-decide fewer than this many working-set "
        "records. Precision measured over a handful of samples is noise, not a result.",
    )
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args()

    if args.build_cache:
        build_cache()
        return 0

    if not CACHE_PATH.exists():
        print("no cache; run with --build-cache first", file=sys.stderr)
        return 1

    records = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    print(f"sweeping over {len(records)} cached working-set records\n")

    grid = list(
        itertools.product(
            [0.30, 0.40, 0.50, 0.60, 0.70],          # damning
            [0.30, 0.40, 0.50, 0.60, 0.70],          # engagement
            [0.20, 0.30, 0.40, 0.50, 0.60, 0.70],    # weight
            [0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70],  # floor
        )
    )

    results = []
    for damning_t, engage_t, weight, floor in grid:
        m = score(records, damning_t=damning_t, engage_t=engage_t, weight=weight, floor=floor)
        if m["decided"] < args.min_decided:
            continue
        m.update(damning=damning_t, engagement=engage_t, weight=weight, floor=floor)
        results.append(m)

    print(f"{len(results)} of {len(grid)} configurations cleared the "
          f"min-decided={args.min_decided} floor\n")
    if not results:
        return 1

    # F1 balances the two errors the product cares about; ties break toward coverage.
    results.sort(key=lambda m: (m["f1"], m["coverage"]), reverse=True)

    header = f"{'F1':>6} {'prec':>6} {'rec':>6} {'acc':>6} {'cov':>6} {'dec':>4} " \
             f"{'FPcost':>7}  dam  eng  wgt  flr"
    print(header)
    print("-" * len(header))
    for m in results[: args.top]:
        print(
            f"{m['f1']:6.3f} {m['precision']:6.3f} {m['recall']:6.3f} {m['accuracy']:6.3f} "
            f"{m['coverage']:6.3f} {m['decided']:4d} {m['fp_cost']:7.0f}  "
            f"{m['damning']:.2f} {m['engagement']:.2f} {m['weight']:.2f} {m['floor']:.2f}"
        )

    current = score(records, damning_t=0.50, engage_t=0.50, weight=0.50, floor=0.45)
    print(
        f"\ncurrent shipped config (0.50/0.50/0.50/0.45):\n"
        f"{current['f1']:6.3f} {current['precision']:6.3f} {current['recall']:6.3f} "
        f"{current['accuracy']:6.3f} {current['coverage']:6.3f} {current['decided']:4d} "
        f"{current['fp_cost']:7.0f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
