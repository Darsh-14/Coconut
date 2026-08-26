# Recourse — Explainable Chargeback Defense Copilot

Recourse takes a payment dispute, checks each piece of available evidence against the
specific claim the bank is making, and recommends **CONTEST** or **ACCEPT** with a confidence
score and a full audit trail — or says **NEEDS_HUMAN_REVIEW** when the evidence genuinely
doesn't resolve the claim, instead of guessing. A human approves before anything is treated
as final. Built for Razorpay's AI Buildathon, Track 2 (AI Risk Manager).

> **Build status: Phase 0 of 8 complete** (repo scaffold, config validation, health check,
> frontend shell). Sections 2, 7, and 9 of this README are filled in during Phase 8, once
> there are real evaluation numbers to report. Nothing here is a placeholder for a number
> that doesn't exist yet.

---

## Safety constraints

These are enforced in code, not just documented:

| Constraint | Where it's enforced |
|---|---|
| Test-mode Razorpay keys only — the process refuses to boot on a live key | [backend/app/config.py](backend/app/config.py), guarded by [tests/test_config.py](backend/tests/test_config.py) |
| Never auto-submits to Razorpay or a bank; a human must approve | Phase 5 (`/approve` endpoint) |
| Disputes are synthetic; only the backing `payment_id` is a real test-mode payment | Phase 1–2 |
| Defense-only — no clawbacks, no customer contact, no payment mutation | System-wide |

---

## Setup

**Prerequisites:** Python 3.11+ and Node 18+.

```bash
git clone <repo-url>
cd recourse
```

### 1. Credentials

```bash
cp .env.example .env
```

Fill in `.env`:

- `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` — from the
  [Razorpay Dashboard](https://dashboard.razorpay.com/) → switch the mode toggle to **Test
  Mode** → Account & Settings → API Keys → Generate Test Key. The key id **must** begin with
  `rzp_test_`; Recourse refuses to start otherwise.
- `ANTHROPIC_API_KEY` — from the [Anthropic Console](https://console.anthropic.com/) → API
  Keys. Only needed to regenerate synthetic data and to draft representment packets; the API
  serves without it.

### 2. Backend

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 3. Frontend

```bash
cd frontend
npm install
```

---

## Running it

Two terminals.

**Backend** (from `backend/`):

```bash
uvicorn app.main:app --reload
```

→ http://127.0.0.1:8000 · health check at `/health` · interactive docs at `/docs`

**Frontend** (from `frontend/`):

```bash
npm run dev
```

→ http://localhost:5173

The Vite dev server proxies `/api/*` to the backend, so no base-URL configuration is needed.

---

## Running the tests

```bash
cd backend
pytest -q
```

---

## Project layout

```
backend/
  app/
    main.py          FastAPI entrypoint, /health
    config.py        env loading + test-mode enforcement
    models/          Pydantic schemas
    services/        razorpay client, verification engine, aggregator, packet generator
    db/              SQLAlchemy models + session
    api/             route definitions
  data/              synthetic dispute generation + generated dataset
  eval/              held-out set + evaluation harness
  tests/
frontend/
  src/pages/         DisputeQueue, CaseDetail, MetricsDashboard
  src/components/    EvidenceClaimMap, AuditTrail, ConfidenceBadge
  src/api/           typed API client
docs/
```

---

## Limitations

Stated plainly, and expanded in Phase 8:

- **Dispute records are synthetic.** Razorpay's test mode has no mechanism to fabricate a
  chargeback on demand, so there is no real disputable transaction to test against. The
  `payment_id` each dispute references *is* a real test-mode payment; the dispute wrapped
  around it is generated.
- **Nothing is ever auto-submitted.** On approval the system builds the exact payload it
  *would* send to Razorpay, stores it in the audit log, and labels it "would submit to
  Razorpay". It does not make the call.
- **The NLI model is used zero-shot**, not fine-tuned on dispute data.
