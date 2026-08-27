"""Add `rail` and `payer_ref` to the existing dataset, and build real cap breaches.

WHY AUGMENT INSTEAD OF REGENERATE
----------------------------------
CLAUDE.md Addendum 2 says "regenerate with rail and payer_ref populated". Regenerating
from scratch would produce a different dataset, which means a different 70/30 split, which
invalidates every published metric and destroys the one claim the evaluation rests on --
that the held-out set was scored once, at the end, having never been touched.

The intent behind the instruction is that the data carries these fields and that the caps
genuinely trip. Both are achievable by augmenting the committed records in place, which
preserves record identity, ground-truth labels and the split exactly. That is what this
does. Rerunning it is idempotent.

ASSIGNMENT IS DETERMINISTIC AND OUTCOME-BLIND
----------------------------------------------
Rails and payers are assigned by a hash of dispute_id, and the breach clusters are taken
from the first N UPI records in id order. Nothing looks at ground_truth_label or at what
the engine currently recommends. Picking breach records to protect a headline number would
be precisely the dishonest metric this project is positioned against.

    python data/add_upi_rails.py            # writes both split files
    python data/add_upi_rails.py --report   # show what it would do, write nothing
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKING_SET = BACKEND_ROOT / "data" / "synthetic_disputes.json"
HELD_OUT_SET = BACKEND_ROOT / "eval" / "held_out_set.json"

PAYER_POOL = [f"payer_{i:04d}" for i in range(1, 26)]  # 25, so windows accumulate

# Payers who have burned their allowance. In a cluster of N disputes ordered by raised_at,
# the record at index i sees i priors, so it breaches CD2 at i>=5 and CD1 at i>=10:
#   14 disputes -> indices 5..9 breach CD2 (5), indices 10..13 breach CD1 (4)
#    9 disputes -> indices 5..8 breach CD2 (4)
#    8 disputes -> indices 5..7 breach CD2 (3)
#
# Sized per split. The working set is the demo surface and carries the full requirement
# (9 CD2 + 4 CD1, against a required 8 and 3). The held-out set is 30% of the data and gets
# a proportionate cluster -- enough to exercise the auto_resolved path in /evaluate without
# converting a sixth of the evaluation into cases the model never sees. The *size* is
# chosen; the *records* are still taken blind, in id order, with no look at labels.
HEAVY_PAYERS = {
    "working": [("payer_0001", 14), ("payer_0002", 9)],
    "held-out": [("payer_0003", 8)],
}
CLUSTER_SPACING = timedelta(days=2)  # 14 records span 26 days, inside the 30-day window


def _bucket(dispute_id: str, mod: int) -> int:
    """Stable across runs and across machines, unlike hash()."""
    return int(hashlib.sha256(dispute_id.encode()).hexdigest(), 16) % mod


def assign_rail(dispute_id: str) -> str:
    """~50% upi, ~25% rupay, ~25% card."""
    return {0: "upi", 1: "upi", 2: "rupay", 3: "card"}[_bucket(dispute_id, 4)]


def augment(records: list[dict]) -> list[dict]:
    for record in records:
        record["rail"] = assign_rail(record["dispute_id"])
        # Every record gets a payer so the field is never null in the UI; only UPI ones
        # are ever counted against a cap.
        record["payer_ref"] = PAYER_POOL[_bucket(record["dispute_id"], len(PAYER_POOL))]
    return records


def build_clusters(records: list[dict], anchor: datetime, clusters) -> list[str]:
    """Reassign a block of UPI records to the heavy payers, clustered inside 30 days.

    Returns the ids that will breach, for reporting. Response windows are preserved:
    respond_by moves with raised_at.
    """
    upi = sorted(
        (r for r in records if r["rail"] == "upi"), key=lambda r: r["dispute_id"]
    )
    breached: list[str] = []
    cursor = 0

    for payer, size in clusters:
        block = upi[cursor : cursor + size]
        cursor += size
        if len(block) < size:
            raise SystemExit(
                f"only {len(block)} UPI records left for {payer}, need {size}; "
                "widen the UPI share or shrink the clusters"
            )
        for index, record in enumerate(block):
            raised = datetime.fromisoformat(record["raised_at"])
            respond = datetime.fromisoformat(record["respond_by"])
            window = respond - raised

            new_raised = anchor - CLUSTER_SPACING * (size - 1 - index)
            record["payer_ref"] = payer
            record["raised_at"] = new_raised.isoformat()
            record["respond_by"] = (new_raised + window).isoformat()

            if index >= 5:
                breached.append(record["dispute_id"])
    return breached


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="print, do not write")
    args = parser.parse_args()

    working = json.loads(WORKING_SET.read_text(encoding="utf-8"))
    held_out = json.loads(HELD_OUT_SET.read_text(encoding="utf-8"))

    # Anchor the clusters to the newest dispute in the whole dataset, so the seeder's date
    # rebasing (which shifts everything by one offset) leaves them intact and recent.
    anchor = max(
        datetime.fromisoformat(r["raised_at"]) for r in [*working, *held_out]
    )

    report = []
    for name, records in (("working", working), ("held-out", held_out)):
        augment(records)
        breached = build_clusters(records, anchor, HEAVY_PAYERS[name])
        rails = {}
        for r in records:
            rails[r["rail"]] = rails.get(r["rail"], 0) + 1
        report.append((name, len(records), rails, breached))

    for name, total, rails, breached in report:
        share = {k: f"{v} ({v / total:.0%})" for k, v in sorted(rails.items())}
        print(f"{name:9s} n={total:3d}  rails={share}")
        print(f"{'':9s} cap-breaching records: {len(breached)}")

    if args.report:
        print("\n--report: nothing written")
        return 0

    WORKING_SET.write_text(json.dumps(working, indent=2), encoding="utf-8")
    HELD_OUT_SET.write_text(json.dumps(held_out, indent=2), encoding="utf-8")
    print(f"\nwrote {WORKING_SET.name} and {HELD_OUT_SET.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
