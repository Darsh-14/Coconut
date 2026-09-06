"""The background queue turns recommendations into an automatic workflow."""

from __future__ import annotations

from threading import Event
from time import monotonic, sleep


def test_scheduler_drains_a_scan_once_without_duplicate_cases(monkeypatch):
    from app.api import routes
    from app.services import automation

    monkeypatch.delenv("COCONUT_SKIP_WARMUP", raising=False)
    monkeypatch.setenv("COCONUT_AUTO_ASSESS", "1")
    monkeypatch.setattr(automation, "_candidate_ids", lambda: ["disp_a", "disp_a", "disp_b"])

    assessed: list[str] = []
    finished = Event()

    def assess(dispute_id: str) -> bool:
        assessed.append(dispute_id)
        if dispute_id == "disp_b":
            finished.set()
        return True

    monkeypatch.setattr(routes, "assess_if_needed", assess)

    with automation._state_lock:
        automation._queued_ids.clear()
        automation._scan_requested = False
        automation._worker_running = False
        automation._completed = 0
        automation._failed = 0
        automation._last_error = None

    assert automation.schedule_automatic_assessment() is True
    assert finished.wait(timeout=2)

    deadline = monotonic() + 2
    while automation.status()["running"] and monotonic() < deadline:
        sleep(0.01)

    assert assessed == ["disp_a", "disp_b"]
    assert automation.status() == {
        "enabled": True,
        "running": False,
        "queued": 0,
        "completed": 2,
        "failed": 0,
        "last_error": None,
        "external_submission": "human_approval_required",
    }


def test_scheduler_can_be_disabled(monkeypatch):
    from app.services import automation

    monkeypatch.setenv("COCONUT_AUTO_ASSESS", "0")
    assert automation.schedule_automatic_assessment(["disp_a"]) is False
