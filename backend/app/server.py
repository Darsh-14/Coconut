"""Single-origin server: the API under /api, the built frontend everywhere else.

WHY THIS IS A SEPARATE APP RATHER THAN MORE ROUTES ON app.main
--------------------------------------------------------------
The obvious approach -- add a static mount to the existing application -- does not work,
and the reason is worth writing down because it fails quietly rather than loudly.

The API owns `/disputes` and `/disputes/{id}`. The frontend routes on those same paths.
Whichever is registered first wins, so a merged app either serves JSON to someone who typed
a case URL into their browser, or shadows the API. Sniffing the Accept header to tell them
apart is the usual trick and it is guesswork.

So the two are composed instead of merged. The API application is mounted whole under
`/api`, which is exactly the prefix the frontend already calls in development (Vite proxies
`/api/*` and strips it), so the same build works in both places with no base-URL variable.
Everything not under `/api` is the single-page app.

Nothing about app.main changes: `uvicorn app.main:app` still serves the API at the root, so
the tests, the README's curl examples, and the dev workflow are untouched.

    Development:  uvicorn app.main:app --reload   +  npm run dev
    Container:    uvicorn app.server:site         (one process, one port, one origin)
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.main import APP_VERSION, app as api_app

logger = logging.getLogger("recourse.server")

# backend/app/server.py -> backend/app -> backend -> repo root -> frontend/dist
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

site = FastAPI(
    title="Recourse",
    version=APP_VERSION,
    docs_url=None,  # the API's own /api/docs is the one to use
    redoc_url=None,
    openapi_url=None,
)

# Mounted whole, so every API route -- present and future -- is reachable under /api
# without being restated here.
site.mount("/api", api_app)


if FRONTEND_DIST.is_dir():
    # Hashed build assets: safe to cache hard, and served before the catch-all.
    site.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    INDEX = FRONTEND_DIST / "index.html"

    @site.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        """Serve a real file when one exists, otherwise the app shell.

        The fallback is what makes a client-side route survive a refresh or a pasted link:
        /disputes/disp_synthetic_0004 is not a file on disk, and without this it would 404
        rather than opening the case.
        """
        candidate = (FRONTEND_DIST / full_path).resolve()
        # Resolve and re-check containment: a path like ../../.env would otherwise escape
        # the build directory and serve whatever it found.
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(FRONTEND_DIST.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(INDEX)

    logger.info("serving the built frontend from %s", FRONTEND_DIST)
else:

    @site.get("/{full_path:path}", include_in_schema=False)
    def no_build(full_path: str) -> JSONResponse:
        """Say what is missing rather than 404-ing a blank page."""
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "No frontend build found. Run `npm run build` in frontend/, or use "
                    "the development setup: `uvicorn app.main:app --reload` plus "
                    "`npm run dev`."
                ),
                "expected_at": str(FRONTEND_DIST),
                "api": "/api",
            },
        )

    logger.warning("no frontend build at %s; serving the API only", FRONTEND_DIST)


__all__ = ["FRONTEND_DIST", "site"]
