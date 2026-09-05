"""Build exactly 1,000 synthetic stress cases without changing the original splits."""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models.schemas import Dispute
from eval.stress_common import (
    SUITE, MANIFEST, LIMITATIONS, digest, frozen_configuration, validate_records,
)
from eval.stress_scenarios import SCENARIOS, LABELS, RATIONALES

SEED = 20260905


def generate():
    rng = random.Random(SEED)
    families = [(reason, index) for reason in SCENARIOS for index in range(5)]
    schedule = (families * 34)[:1000]
    rng.shuffle(schedule)
    records, mapping = [], {}
    for index, (reason, variant) in enumerate(schedule):
        ref = f"X{rng.getrandbits(56):014X}"
        amount = rng.randint(299, 45000) * 100
        happened = datetime(2026, 5, 1, tzinfo=timezone.utc) + timedelta(days=rng.randrange(100))
        values = {"ref": ref, "amount": f"{amount / 100:.2f}", "date": happened.date().isoformat()}
        source = SCENARIOS[reason]
        evidence = [{"type": kind, "content": text.format(**values), "source_ref": f"record_{ref}_{n}"}
                    for n, (kind, text) in enumerate(source["bundles"][variant])]
        rng.shuffle(evidence)
        raised = happened + timedelta(days=10)
        record = Dispute(
            dispute_id=f"disp_synthetic_stress_{ref}", payment_id=f"pay_PENDING_stress_{ref}",
            phase="chargeback", reason_code=reason, claim_text=source["claim"].format(**values),
            amount=amount, raised_at=raised, respond_by=raised + timedelta(days=14),
            evidence_bundle=evidence, ground_truth_label=LABELS[variant],
            rail=(("card", "rupay")[index % 2] if reason == "unrecognized_transaction"
                  else ("card", "upi", "rupay")[index % 3]), payer_ref=f"payer_stress_{ref}",
        )
        records.append(record)
        mapping[record.dispute_id] = f"{reason}_{variant + 1}"
    validate_records(records)
    return records, mapping


def main():
    if SUITE.exists() or MANIFEST.exists():
        raise ValueError("Stress suite already exists. Use evaluate_stress.py --validate-only; do not overwrite a frozen test.")
    frozen = frozen_configuration()  # Freeze before authoring/reading new labels.
    records, mapping = generate()
    raw = [r.model_dump(mode="json") for r in records]
    manifest = {
        "schema_version": 1, "evaluation": "synthetic stress suite", "seed": SEED,
        "n_cases": len(raw), "scenario_families": len(set(mapping.values())),
        "dataset_sha256": digest(raw), "frozen_configuration": frozen,
        "label_source": "Authored fictional facts and assumed contest outcomes; no model-labelled or bank-adjudicated cases.",
        "label_rationales": {f"{reason}_{i + 1}": RATIONALES[i] for reason in SCENARIOS for i in range(5)},
        "case_families": mapping, "family_counts": dict(Counter(mapping.values())),
        "label_counts": dict(Counter(r.ground_truth_label for r in records)),
        "reason_counts": dict(Counter(r.reason_code for r in records)),
        "rail_counts": dict(Counter(r.rail for r in records)),
        "limitations": LIMITATIONS,
    }
    SUITE.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Created {len(records)} synthetic stress cases across {manifest['scenario_families']} families.")
    print(json.dumps({k: manifest[k] for k in ("label_counts", "rail_counts", "dataset_sha256")}, indent=2))
    print("No inference, training or headline metric update was performed.")


if __name__ == "__main__":
    main()
