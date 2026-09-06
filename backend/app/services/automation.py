"""Background orchestration for automatic dispute assessment.

The NLI pipeline already returns a decision.  This module closes the workflow gap by
running that pipeline whenever a dispute enters the queue and by draining unassessed
records after model warm-up.  It deliberately stops at the internal recommendation:
Razorpay submission and human approval remain separate actions.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterable

from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import DisputeRow

logger = logging.getLogger("coconut.automation")

_state_lock = threading.Lock()
_queued_ids: set[str] = set()
_scan_requested = False
_worker_running = False
_completed = 0
_failed = 0
_last_error: str | None = None


def enabled() -> bool:
    """Allow operators and tests to disable background inference explicitly."""
    return (
        os.getenv("COCONUT_AUTO_ASSESS", "1") != "0"
        and os.getenv("COCONUT_SKIP_WARMUP") != "1"
    )


def schedule_automatic_assessment(dispute_ids: Iterable[str] | None = None) -> bool:
    """Queue specific disputes, or scan the database for every unassessed dispute.

    Calls coalesce into one daemon worker.  Repeated events cannot create duplicate
    decisions because the route-level worker re-checks the latest decision while holding
    the same per-dispute lock used by manual assessment.
    """
    if not enabled():
        return False

    global _scan_requested, _worker_running
    with _state_lock:
        if dispute_ids is None:
            _scan_requested = True
        else:
            _queued_ids.update(dispute_ids)

        if _worker_running:
            return True
        _worker_running = True

    threading.Thread(
        target=_run_worker,
        name="automatic-dispute-assessment",
        daemon=True,
    ).start()
    return True


def status() -> dict[str, object]:
    with _state_lock:
        return {
            "enabled": enabled(),
            "running": _worker_running,
            "queued": len(_queued_ids),
            "completed": _completed,
            "failed": _failed,
            "last_error": _last_error,
            "external_submission": "human_approval_required",
        }


def _candidate_ids() -> list[str]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(DisputeRow.dispute_id).order_by(
                    DisputeRow.respond_by, DisputeRow.dispute_id
                )
            ).all()
        )


def _take_work() -> tuple[bool, list[str]]:
    global _scan_requested
    with _state_lock:
        scan = _scan_requested
        _scan_requested = False
        ids = list(_queued_ids)
        _queued_ids.clear()
    return scan, ids


def _run_worker() -> None:
    global _worker_running, _completed, _failed, _last_error

    # Import lazily so app.api.routes can import this module from mutation endpoints
    # without a module-import cycle.
    from app.api.routes import assess_if_needed

    while True:
        scan, ids = _take_work()
        if scan:
            try:
                ids.extend(_candidate_ids())
            except Exception as exc:  # noqa: BLE001 -- report and keep queued work alive
                logger.exception("could not scan the dispute queue for automatic assessment")
                with _state_lock:
                    _failed += 1
                    _last_error = str(exc)

        for dispute_id in dict.fromkeys(ids):
            try:
                if assess_if_needed(dispute_id):
                    with _state_lock:
                        _completed += 1
            except Exception as exc:  # noqa: BLE001 -- one bad case must not stop the queue
                logger.exception("automatic assessment failed for %s", dispute_id)
                with _state_lock:
                    _failed += 1
                    _last_error = f"{dispute_id}: {exc}"

        with _state_lock:
            if _scan_requested or _queued_ids:
                continue
            _worker_running = False
            return


__all__ = ["enabled", "schedule_automatic_assessment", "status"]
