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
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select

from app.config import BACKEND_ROOT
from app.db.database import init_db, session_scope
from app.db.models import AuditLogRow, DecisionRow, DisputeRow
from app.models.schemas import Dispute
from app.services.razorpay_client import is_placeholder_payment_id

logger = logging.getLogger("coconut.seed")

WORKING_SET = BACKEND_ROOT / "data" / "synthetic_disputes.json"


def load_working_set(path: Path = WORKING_SET) -> list[Dispute]:
    if not path.is_file():
        raise SystemExit(
            f"{path} not found. Run: python data/generate_synthetic_disputes.py --source curated"
        )
    return [Dispute.model_validate(r) for r in json.loads(path.read_text(encoding="utf-8"))]


def rebase_dates(disputes: list[Dispute], now: datetime | None = None) -> list[Dispute]:
    """Shift every timestamp forward so the queue is live relative to today.

    The committed dataset has absolute timestamps baked in at generation time. Without
    rebasing, a clone made weeks later shows a queue where every dispute is already
    overdue -- the response countdown, and Section 12's red-alert band, become useless.

    The whole set is shifted by a single offset, so the ORIGINAL spread of urgency is
    preserved exactly: the newest dispute lands at roughly now, and everything else keeps
    its relative position behind it.
    """
    if not disputes:
        return disputes
    now = now or datetime.now(timezone.utc)
    latest_raised = max(d.raised_at for d in disputes)
    shift = now - latest_raised
    return [
        d.model_copy(update={"raised_at": d.raised_at + shift, "respond_by": d.respond_by + shift})
        for d in disputes
    ]


def seed(reset: bool = False, rebase: bool = True) -> int:
    init_db()
    disputes = load_working_set()
    if rebase:
        disputes = rebase_dates(disputes)

    with session_scope() as session:
        if reset:
            session.execute(delete(AuditLogRow))
            session.execute(delete(DecisionRow))
            session.execute(delete(DisputeRow))
            session.flush()
            print("  cleared existing disputes, decisions and audit entries")

        existing = {row.dispute_id: row for row in session.scalars(select(DisputeRow)).all()}
        added = 0
        repointed = 0
        for dispute in disputes:
            row = existing.get(dispute.dispute_id)
            if row is None:
                session.add(DisputeRow.from_schema(dispute))
                added += 1
                continue
            # Re-running backfill_razorpay_backing.py replaces a pay_PENDING_ placeholder
            # with a real test-mode payment id. Without this the new id would sit in the
            # JSON and never reach the queue, and the UI would keep showing the placeholder.
            if rebase:
                row.raised_at = dispute.raised_at
                row.respond_by = dispute.respond_by
            # Never overwrite a real payment id with the JSON's placeholder. A merchant
            # can now attach a genuine test-mode payment through Checkout, which writes
            # pay_... onto the row while the committed dataset still says pay_PENDING_.
            # Repointing blindly would quietly undo that -- and re-seeding is exactly what
            # you do after a backfill, so it would have been undone at the worst moment.
            if row.payment_id != dispute.payment_id and not (
                is_placeholder_payment_id(dispute.payment_id)
                and not is_placeholder_payment_id(row.payment_id)
            ):
                logger.info(
                    "%s payment_id %s -> %s", row.dispute_id, row.payment_id, dispute.payment_id
                )
                row.payment_id = dispute.payment_id
                repointed += 1

        session.flush()
        total = session.scalar(select(func.count()).select_from(DisputeRow))

    print(f"  seeded {added} new dispute(s), repointed {repointed} payment_id(s); "
          f"{total} total in the queue")
    return total or 0


def seed_if_empty() -> int:
    """Populate an empty database on first start, and otherwise do nothing.

    Called at startup so a fresh clone or container shows a working queue instead of an
    empty page. Deliberately conditional on the table being empty rather than idempotent
    re-seeding: a full seed() also rebases timestamps and repoints payment ids from the
    committed JSON, which is right after a backfill and wrong on every ordinary restart.
    """
    init_db()
    with session_scope() as session:
        count = session.scalar(select(func.count()).select_from(DisputeRow)) or 0
    if count:
        return count
    logger.info("empty database; seeding the working set")
    return seed()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--reset", action="store_true", help="Wipe decisions and audit entries, then re-seed."
    )
    parser.add_argument(
        "--no-rebase",
        action="store_true",
        help=(
            "Keep the dataset's original absolute timestamps. By default they are shifted "
            "forward so the queue is live today; without that, an aged clone shows every "
            "dispute already overdue."
        ),
    )
    args = parser.parse_args()

    print("Seeding Coconut database from the working set")
    seed(reset=args.reset, rebase=not args.no_rebase)
    return 0


if __name__ == "__main__":
    sys.exit(main())
