"""FastAPI application entrypoint for Recourse.

Run from the ``backend/`` directory:

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    yield
    logger.info("Recourse shutting down")


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


@app.get("/health", tags=["ops"])
def health() -> dict:
    """Liveness + configuration check.

    Returns 200 only when the process booted with a valid test-mode configuration, which
    is the only way it can boot at all.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "razorpay_mode": "test",
        "razorpay_key_id_prefix": settings.razorpay_key_id[:14],
        "anthropic_configured": settings.anthropic_configured,
        "auto_submit_to_razorpay": False,
    }


__all__ = ["app", "ConfigError"]
