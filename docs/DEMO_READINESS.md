# Presentation runbook

## Container workflow

Docker must be installed and its engine running. Put your existing Razorpay **test-mode**
credentials in the root `.env`. Do not publish this unauthenticated demo to the internet.
Compose binds to loopback; the login screen does not authenticate API requests.

If `.env` does not exist, copy `.env.example` to `.env` and fill in
`RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` from your Razorpay test account. Keep the file
private. An Anthropic key and a data HMAC key are not needed for this demo.

From the repository root:

```powershell
docker compose build
docker compose run --rm coconut python eval/prewarm_model.py
docker compose up --build -d --wait --wait-timeout 900
docker compose ps
Invoke-RestMethod http://localhost:8000/api/ready
```

Open http://localhost:8000. The preparation command fills the persistent model cache and
executes one prediction. The server separately loads the weights into memory at startup.
Only present once `/api/ready` reports ready. A failed download must be resolved before
the presentation; the prewarm command returns a failure rather than swallowing the error.

Non-root runtime ownership covers `/data` and `/models`. Existing volumes created by an
older image may retain old ownership; inspect their permissions before changing anything.
Do not delete a data volume to repair permissions.

Verify the mounted volume is writable and database data survives a restart:

```powershell
docker compose exec coconut python -c "import os,sqlite3; assert os.access('/data',os.W_OK); c=sqlite3.connect('/data/coconut.db'); print(c.execute('select count(*) from disputes').fetchone()); c.close()"
docker compose restart coconut
docker compose up -d --wait --wait-timeout 180
docker compose exec coconut python -c "import sqlite3; c=sqlite3.connect('/data/coconut.db'); print(c.execute('select count(*) from disputes').fetchone()); c.close()"
```

Use `docker compose logs --tail 100 coconut` to investigate readiness failures. Inference
dependencies are pinned; a cache mismatch requires `python eval/build_conformal_cache.py`
in the same environment, followed by a server restart. This is inference, not training.

## Four-case presentation

```powershell
docker compose exec coconut python data/prepare_demo.py
```

The script adds labelled-as-demo database fixtures, never modifies evaluation datasets,
and checks the observed output of actual inference against each expected scenario:

1. `/app/disputes/disp_synthetic_demo_contest`: inspect evidence, attach a test payment,
   review the packet, approve, and show the audit log's **not sent** status.
2. `/app/disputes/disp_synthetic_demo_accept`: contradictory evidence; accept recommendation.
3. `/app/disputes/disp_synthetic_demo_needs_human_review`: deferred evidence review.
4. `/app/disputes/disp_synthetic_demo_upi_5`: payer-payee history reaches the configured cap.
   The suffix reflects the current five-dispute cap; follow the URL printed by the script
   if the rule changes. This is a rules demonstration, not bank adjudication.

Existing fixtures are preserved. A previously approved case cannot be reassessed until
you withdraw its approval in the UI. Never silently reset the audit log for a demo.

## Razorpay backing

Open the contest case, choose **Attach test payment**, complete the Razorpay test Checkout,
then return to Coconut and refresh its backing status. The exact button label may vary;
the payment panel sits in the case sidebar. A person must complete the hosted Checkout.

```powershell
docker compose exec coconut python data/prepare_demo.py --verify-backing
```

The check fetches an existing payment from Razorpay and verifies ID, amount, currency and
authorized/captured state. Missing/failed verification returns a nonzero status. Test keys
alone, a local `pay_` string, and order creation are not proof that a payment completed.
No script here creates charges or attempts to bypass Checkout challenges.

## Manual tests

```powershell
docker compose --profile test run --build --rm backend-tests
docker compose --profile smoke up --build -d --wait --wait-timeout 900 smoke
docker compose exec smoke python data/prepare_demo.py
cd frontend
npm ci
npm run build
npm run lint
npx playwright install chromium
$env:BASE_URL = 'http://127.0.0.1:8011'
npm run verify:ui
```

The backend test container has a fresh writable layer, test-only credentials, and no demo
volume. The bounded suite excludes tests that load real model weights; demo preparation
and the browser workflow separately exercise actual inference. Browser smoke records an
approval and edits a packet: run it on the disposable verification instance before the
presentation workspace. It saves screenshots and covers narrow layouts as well as desktop.
See [manual checks](MANUAL_CHECKS.md) for restart and full-suite commands. These are
instructions to run yourself, not a record of successful tests.

Without Docker, use the existing virtual environment and a separate SQLite file:

```powershell
cd 'D:\Risky Rich\backend'
$env:LLM_PROVIDER = 'none'
$env:DATABASE_URL = 'sqlite:///./demo-verification.db'
..\.venv\Scripts\python.exe data/prepare_demo.py
..\.venv\Scripts\python.exe -m uvicorn app.server:site --host 127.0.0.1 --port 8011
```

In a second terminal, run smoke with `BASE_URL=http://127.0.0.1:8011`. Build the frontend
before starting this single-origin server. This checks a fresh database, but reuses local
dependencies and therefore must not be described as a clean dependency installation.

## Optional extra training data — manual only

`data/training_supplement.json` contains 24 new authored synthetic cases across 12 paired
delivery/duplicate-charge scenarios. Combined with the original 261 records there are
285 available records: 182 working + 24 supplemental training + 79 unchanged test records.
Pairs have shared claims with materially different evidence. They are training-only in
every fold and excluded from calibration support counts. They are neither independent
test observations nor real merchant outcomes. No performance gain has been measured.

The generator source is `data/build_training_supplement.py`; its output is already included.
It refuses to overwrite an existing file. No API key is needed.

```powershell
cd 'D:\Risky Rich\backend'
..\.venv\Scripts\python.exe training/train_synthetic_win_gate.py --supplement data/training_supplement.json --output eval/synthetic_win_gate_candidate.json --target-precision 0.90 --min-support 8
..\.venv\Scripts\python.exe eval/evaluate_synthetic_gate.py --artifact eval/synthetic_win_gate_candidate.json
```

This trains the small gate, not the NLI cross-encoder. The original working-set cache remains
applicable because neither original split changes. If training fails its support/precision
check, keep the existing model. Evaluate a frozen candidate once; do not repeatedly tune on
test results. Similar-scenario leakage is still possible despite exact-duplicate checks,
and out-of-fold results remain development estimates.

Only after reviewing precision, support, recall and coverage, optionally promote manually:

```powershell
$backupName = 'eval/synthetic_win_gate.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json'
Copy-Item -LiteralPath eval/synthetic_win_gate.json -Destination $backupName -ErrorAction Stop
Copy-Item eval/synthetic_win_gate_candidate.json eval/synthetic_win_gate.json
```

Restart the local backend after promotion; for Docker, rebuild with `docker compose up --build -d`.
Rerun demo checks. Do not update recorded UI metrics
until a new evaluation has actually completed.

## Verification status

The owner reports Docker is installed. This agent session could not find its executable
on PATH or at the standard Docker Desktop location. That does not establish whether Docker
is available in another terminal. Container startup and the latest changes remain unverified.
No tests or training were run in the latest implementation pass, as requested.
The commands above are for manual verification, not evidence that a container run succeeded.

Navigation references: [Razorpay dashboard](https://razorpay.com/docs/payments/dashboard/)
and [product navigation](https://razorpay.com/docs/payments/dashboard/razorpay-home/?preferred-country=US).
Coconut groups existing workspaces and reports, provides search and filter shortcuts, and
keeps test-mode and authentication status visible. It does not add unsupported financial products.
