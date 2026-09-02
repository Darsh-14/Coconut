"""FastAPI application entrypoint for Recourse.

Run from the ``backend/`` directory:

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import ConfigError, get_settings

logger = logging.getLogger("recourse")

APP_VERSION = "0.1.0"

# The Vite dev server. No auth in this system (CLAUDE.md Section 16), so CORS is the only
# gate between the browser and the API, and it stays pinned to localhost dev origins.
DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate the environment before serving a single request.

    get_settings() raises ConfigError if RAZORPAY_KEY_ID is absent or is not a test-mode
    key. We let that propagate: a misconfigured process must not start.
    """
    settings = get_settings()
    logger.info(
        "Recourse starting up | razorpay_key_id=%s... | test_mode=enforced | anthropic_configured=%s",
        settings.razorpay_key_id[:14],
        settings.anthropic_configured,
    )

    from app.db.database import init_db

    init_db()

    # A fresh clone or container starts with an empty file; an empty queue reads as a
    # broken app rather than a new one. No-ops once anything is in the database.
    from app.db.seed import seed_if_empty

    try:
        seed_if_empty()
    except Exception as exc:  # noqa: BLE001 -- an unseeded app still runs
        logger.warning("could not seed the database at startup: %s", exc)

    # Calibrate from the cached scores so the app boots with a working threshold. Without
    # this the aggregator has no calibrated lambda and defers every case, which looks like
    # a broken product rather than a cautious one.
    from app.services.conformal_calibrator import bootstrap_from_cache

    bootstrap_from_cache()

    # Load the model off the request path. The first /decide used to pay the whole ~15s
    # load mid-interaction, which the UI had to apologise for. A daemon thread so a slow
    # or unreachable model hub delays nothing and blocks no shutdown; /health reports
    # whether it has finished.
    if os.getenv("RECOURSE_SKIP_WARMUP") != "1":
        threading.Thread(target=_warm_up_model, name="model-warmup", daemon=True).start()

    yield
    logger.info("Recourse shutting down")


def _warm_up_model() -> None:
    from app.services.verification_engine import warm_up

    warm_up()


app = FastAPI(
    title="Recourse",
    description=(
        "Explainable chargeback defense copilot. Test-mode only; never auto-submits to "
        "Razorpay or a bank."
    ),
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


from app.api.routes import router as api_router  # noqa: E402
from app.api.webhooks import router as webhook_router  # noqa: E402

app.include_router(api_router)
app.include_router(webhook_router)


@app.get("/health", tags=["ops"])
def health() -> dict:
    """Liveness + configuration check.

    Returns 200 only when the process booted with a valid test-mode configuration, which
    is the only way it can boot at all.
    """
    settings = get_settings()
    from app.services.conformal_calibrator import active_state
    from app.services.verification_engine import model_is_loaded

    calibration = active_state()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "razorpay_mode": "test",
        "razorpay_key_id_prefix": settings.razorpay_key_id[:14],
        "anthropic_configured": settings.anthropic_configured,
        "auto_submit_to_razorpay": False,
        "database": _database_health(),
        "model_loaded": model_is_loaded(),
        "calibrated": bool(calibration.get("calibrated")),
        "calibrated_threshold": calibration.get("threshold"),
        "risk_budget_alpha": calibration.get("alpha"),
    }


def _database_health() -> str:
    """Cheapest possible proof the database is actually reachable, not just configured."""
    try:
        from sqlalchemy import text

        from app.db.database import engine

        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001
        logger.error("database health check failed: %s", exc)
        return "unreachable"


@app.get("/ready", tags=["ops"])
def ready() -> JSONResponse:
    """Readiness, as distinct from liveness.

    /health answers "is this process up". This answers "can it actually decide a case
    right now" -- which is a different question while the model is still loading, the
    score cache is invalid, or the database is unavailable. A load balancer or deploy
    script should gate on this endpoint.
    """
    from app.services.conformal_calibrator import active_state
    from app.services.verification_engine import model_is_loaded

    loaded = model_is_loaded()
    calibrated = bool(active_state().get("calibrated"))
    database = _database_health()
    is_ready = loaded and calibrated and database == "ok"
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={
            "ready": is_ready,
            "model_loaded": loaded,
            "calibrated": calibrated,
            "database": database,
        },
    )


__all__ = ["app", "ConfigError"]
