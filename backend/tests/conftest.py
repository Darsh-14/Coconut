"""Shared test fixtures.

The important one is `disable_llm_drafting`: it is autouse, so no test ever reaches a
live LLM provider. Without it the suite would start calling Gemini as soon as a developer
put a key in .env -- making tests slow, non-deterministic, dependent on a third party's
uptime, and quietly billable. Tests that exercise the LLM path stub it explicitly instead.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def skip_model_warmup():
    """Stop every TestClient(app) from spawning a background model load.

    The warm-up thread is right for a server and wrong for a test suite: dozens of them
    race each other, they load ~750MB for tests that stub the engine anyway, and one that
    outlives its test tries to register an atexit hook during interpreter shutdown. Tests
    that need real inference get it through the engine itself.
    """
    os.environ["RECOURSE_SKIP_WARMUP"] = "1"
    yield
    os.environ.pop("RECOURSE_SKIP_WARMUP", None)


@pytest.fixture(autouse=True)
def disable_llm_drafting(monkeypatch, request):
    """Force the deterministic template path for every test by default.

    Opt out with @pytest.mark.uses_llm on a test that stubs the provider itself.
    """
    if request.node.get_closest_marker("uses_llm"):
        return
    monkeypatch.setattr(
        "app.services.packet_llm.draft_with_llm",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
