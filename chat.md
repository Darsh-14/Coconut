# Coconut Conversation Context

## Project

Coconut is an explainable chargeback defense copilot for Razorpay's AI Buildathon 2026, Track 2: AI Risk Manager.

The system:

- Checks dispute evidence against the bank's claim.
- Uses a local NLI cross-encoder for evidence verification.
- Produces `CONTEST`, `ACCEPT`, `NEEDS_HUMAN_REVIEW`, or UPI `NO_ACTION_NEEDED` decisions.
- Abstains when evidence is insufficient instead of guessing.
- Generates representment prose only after the decision is made.
- Requires human approval before preparing a representment payload.
- Logs what would be submitted to Razorpay but never auto-submits synthetic disputes.
- Uses Razorpay test-mode credentials only.

## Buildathon Assessment

Research of Razorpay's 2026 Buildathon materials identified these practical priorities:

1. Reliable end-to-end demo.
2. Strong technical reasoning.
3. Measured outcomes.
4. Novelty tied to a real merchant problem.
5. Authentication is low priority for this single-merchant demo.

The published signals emphasize problem taste, build quality, AI judgment, and failure recovery. Track 2 specifically expects a working risk detector/verifier/auto-responder with measured precision and recall, honest false-positive cost, and defense-only behavior.

Current assessment:

- Technical reasoning: strong.
- Measured outcomes: implemented and honestly documented, but limited by synthetic data and weak confidence separation.
- Novelty: strong combination of evidence-level verification, abstention, risk-budget calibration, UPI rules forecasting, human approval, and audit trails.
- Authentication: intentionally out of scope. The sign-in page is a demo front door, not real authentication.
- End-to-end reliability: substantially implemented, but Docker and fresh-environment execution still require verification.

## UI Changes Completed

The following UI work was completed without changing routes, model behavior, API contracts, or application logic:

- Trimmed redundant copy across the landing page, dashboard, login, queue, overview, and metrics pages.
- Removed the `CHARGEBACK DEFENCE` sidebar subtitle.
- Shortened the demo-mode login explanation.
- Simplified landing-page feature descriptions, FAQ copy, and metrics explanations.
- Updated displayed metrics and comparison labels to use shared recorded values where applicable.
- Replaced the original shield/check logo with a transparent elemental coconut SVG.
- Removed the square logo background.
- Enlarged the coconut within the existing logo footprint.
- Removed the smiley face and colored playful details.
- Refined the logo into a mature monochrome black-and-white elemental mark.

Frontend validation passed repeatedly with:

```powershell
Set-Location 'D:\Risky Rich\frontend'
npm run build
```

## Commit

The UI and logo changes were committed in:

```text
3d737b2 chore: refine demo UI copy and coconut logo
```

The commit contains the frontend files associated with the copy cleanup and logo work. Other repository changes were intentionally left uncommitted because they predated or were unrelated to that scoped work.

## Docker Implementation Review

Docker uses a multi-stage build:

- Node 22 builds the React/Vite frontend.
- Python 3.13 runs FastAPI and serves the built frontend.
- `app.server:site` serves the frontend and mounts the API under `/api`.
- The model is cached in a named volume rather than baked into the image.
- SQLite data is stored in a named volume.
- The runtime uses a non-root `coconut` user.
- `/api/health` is liveness-oriented.
- `/api/ready` checks model loading, calibration, and database availability.
- The Docker healthcheck correctly targets `/api/ready`.

Files reviewed:

- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
- `backend/app/server.py`
- `backend/app/main.py`
- `backend/app/config.py`
- `.env.example`
- `backend/tests/test_server.py`

Strengths:

- Good separation between build and runtime stages.
- Single-origin deployment removes the two-terminal setup for judges.
- Sensitive files and local databases are excluded from the build context.
- Test-mode Razorpay keys are enforced at startup.
- Model and database persistence are explicit.
- The mounted API lifespan is delegated correctly, so startup validation, seeding, calibration, and warmup run in the composed server.
- SPA fallback and path traversal protection are tested.

Open Docker risks:

1. Docker was not installed in the current environment, so `docker compose up --build` was not executed.
2. Compose mounts `/data` for SQLite, but the Dockerfile explicitly creates and owns `/models` only. The `/data` named volume permissions need to be verified. A likely hardening change is to create and chown `/data` together with `/models`.
3. First startup requires downloading roughly 750 MB of model data and may take several minutes.
4. A valid `.env` with `rzp_test_` credentials is required before Compose starts.
5. The container's unauthenticated write endpoints are suitable only for a controlled demo, not a public deployment.
6. Container memory, restart behavior, model warmup, and database persistence have not been tested in Docker.

A Linux CPython 3.13 Torch 2.13.0 CPU wheel was successfully resolved, so the Python/Torch combination has an available Linux wheel. Actual image build and import/runtime compatibility still need Docker validation.

## Test/Validation Notes

- Frontend production builds passed.
- Root-level pytest was blocked during collection by permission-denied directories:
  - `pytest-backend-final-review`
  - `pytest-backend-final-review-2`
- The application test suite should be run separately with:

```powershell
Set-Location 'D:\Risky Rich'
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

- Docker commands could not run because `docker` was not available on the current PATH.

## Recommended Next Steps

1. Run `docker compose up --build` on a machine with Docker.
2. Verify `/api/ready` becomes healthy after model warmup.
3. Verify SQLite can create and update `/data/coconut.db` as the non-root user.
4. Run the full backend suite from `backend/tests`.
5. Run the frontend UI smoke scripts in the actual demo environment.
6. Pre-warm the model volume before presenting.
7. Keep full authentication out of scope unless the app is being publicly deployed.
8. For public hosting, add minimal server-side protection for mutation routes rather than building a full account system.
