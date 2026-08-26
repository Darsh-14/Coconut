"""Seed the database from the committed working set.

Only data/synthetic_disputes.json is loaded. eval/held_out_set.json is deliberately never
seeded: /evaluate reads it directly, and keeping it out of the queue is a structural
guarantee that held-out records cannot leak into development or the demo (Section 9).

Usage:
    python -m app.db.seed            # seed if empty
    python -m app.db.seed --reset    # drop decisions/audit and re-seed disputes
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import delete, func, select

from app.config import BACKEND_ROOT
from app.db.database import init_db, session_scope
from app.db.models import AuditLogRow, DecisionRow, DisputeRow
from app.models.schemas import Dispute

logger = logging.getLogger("recourse.seed")

WORKING_SET = BACKEND_ROOT / "data" / "synthetic_disputes.json"


def load_working_set(path: Path = WORKING_SET) -> list[Dispute]:
    if not path.is_file():
        raise SystemExit(
            f"{path} not found. Run: python data/generate_synthetic_disputes.py --source curated"
        )
    return [Dispute.model_validate(r) for r in json.loads(path.read_text(encoding="utf-8"))]


def seed(reset: bool = False) -> int:
    init_db()
    disputes = load_working_set()

    with session_scope() as session:
        if reset:
            session.execute(delete(AuditLogRow))
            session.execute(delete(DecisionRow))
            session.execute(delete(DisputeRow))
            session.flush()
            print("  cleared existing disputes, decisions and audit entries")

        existing = set(session.scalars(select(DisputeRow.dispute_id)).all())
        added = 0
        for dispute in disputes:
            if dispute.dispute_id in existing:
                continue
            session.add(DisputeRow.from_schema(dispute))
            added += 1

        session.flush()
        total = session.scalar(select(func.count()).select_from(DisputeRow))

    print(f"  seeded {added} new dispute(s); {total} total in the queue")
    return total or 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--reset", action="store_true", help="Wipe decisions and audit entries, then re-seed."
    )
    args = parser.parse_args()

    print("Seeding Recourse database from the working set")
    seed(reset=args.reset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
