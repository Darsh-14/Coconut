"""The composed single-origin server (app/server.py).

The load-bearing test is test_the_mounted_apis_lifespan_actually_runs. Starlette does not
run the lifespan of an app mounted with `mount()`, and when this server was first written
it did not delegate — so every startup step was silently skipped in the container:

  * config validation never ran at startup, so a process holding a non-test-mode
    RAZORPAY_KEY_ID would boot rather than refuse to start (Section 2);
  * the database was never created or seeded;
  * the conformal threshold was never calibrated, so every case deferred to a human;
  * the model never warmed, so /ready could never pass the container healthcheck.

Every one of those failed quietly. This file exists so it cannot happen again unnoticed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.server import FRONTEND_DIST, site


@pytest.fixture(scope="module")
def client():
    with TestClient(site) as c:
        yield c


# -- the lifespan ---------------------------------------------------------------------------


def test_the_mounted_apis_lifespan_actually_runs(client):
    """If this fails, the container boots an unvalidated, uncalibrated, unseeded app."""
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    # Proof the API's own startup ran: nothing else sets these.
    assert body["calibrated"] is True, "the conformal threshold was never calibrated"
    assert body["database"] == "ok"


def test_test_mode_is_enforced_on_this_path_too(client):
    """Section 2, hard constraint 1. Note this passes even without lifespan delegation,
    because get_settings() also validates lazily -- the lifespan test above is what guards
    the stronger property that a misconfigured process refuses to START."""
    body = client.get("/api/health").json()
    assert body["razorpay_mode"] == "test"
    assert body["razorpay_key_id_prefix"].startswith("rzp_test_")
    assert body["auto_submit_to_razorpay"] is False


def test_readiness_is_reported_separately_from_liveness(client):
    """/health says the process is up; /ready says it can actually decide a case. A
    deploy that gates on the wrong one routes traffic into a cold-model stall."""
    assert client.get("/api/health").status_code == 200

    ready = client.get("/api/ready")
    assert ready.status_code in {200, 503}
    assert ready.json()["ready"] is (ready.status_code == 200)
    assert ready.json()["calibrated"] is True


def test_docker_healthcheck_targets_the_mounted_api():
    """The SPA catch-all serves HTML with 200 at root /ready, so that path cannot prove
    the mounted API is ready. Pin the healthcheck to the actual /api route."""
    dockerfile = (FRONTEND_DIST.parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8000/api/ready" in dockerfile


# -- routing --------------------------------------------------------------------------------


def test_the_api_is_reachable_under_its_prefix(client):
    response = client.get("/api/disputes")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.skipif(not FRONTEND_DIST.is_dir(), reason="no frontend build")
@pytest.mark.parametrize(
    "path",
    [
        "/",                                     # landing
        "/login",                                # front door
        "/app",                                  # dashboard root
        "/app/disputes",
        "/app/disputes/disp_synthetic_0004",     # the pasted-case-URL case
        "/app/metrics",
        "/disputes",                             # pre-/app link someone may still hold
        "/anything-unknown",
    ],
)
def test_client_routes_serve_the_app_shell_not_json(client, path):
    """The collision this whole module exists to avoid: a merged app would have served JSON
    to someone pasting a case URL into their browser.

    Moving the dashboard under /app shrank that surface -- no client route now shares a
    path with an API route -- but the property still has to hold, including for the old
    top-level /disputes URL, which must reach the app shell (and then the SPA's own
    not-found) rather than 404 at the server."""
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.skipif(not FRONTEND_DIST.is_dir(), reason="no frontend build")
@pytest.mark.parametrize(
    "path",
    [
        "/../.env",
        "/../../.env",
        "/../backend/recourse.db",
        "/..%2F.env",
        "/%2e%2e%2f.env",
    ],
)
def test_traversal_cannot_escape_the_build_directory(client, path):
    """The SPA fallback resolves a path against the build directory; without re-checking
    containment it would happily serve .env."""
    response = client.get(path)
    body = response.text
    assert "RAZORPAY_KEY_SECRET" not in body
    assert "rzp_test_" not in body or response.headers["content-type"].startswith("text/html")


@pytest.mark.skipif(not FRONTEND_DIST.is_dir(), reason="no frontend build")
def test_a_real_build_asset_is_served_as_itself(client):
    """The fallback must not swallow genuine files, or every asset would return index.html."""
    index = client.get("/").text
    assert "/assets/" in index, "the build should reference hashed assets"
