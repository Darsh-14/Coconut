# Checks you can run

No tests are run automatically by these instructions. Run commands yourself, one group at
a time. Model loading can take several minutes. Keep the laptop plugged in and awake.

## Backend checks in a separate container

From the project folder:

```powershell
Set-Location 'D:\Risky Rich'
docker compose --profile test run --build --rm backend-tests
```

This excludes the slower model-loading tests and does not use your saved demo database or
Razorpay keys. To include the slower tests, run separately:

```powershell
docker compose --profile test run --rm backend-tests python -m pytest tests -q -p no:cacheprovider --basetemp=/tmp/coconut-full-tests
```

## Website checks in a disposable workspace

These checks edit a draft and record an approval. Use the separate workspace below, not
your presentation workspace. Its dummy keys cannot complete Razorpay Checkout.

```powershell
docker compose --profile smoke up --build -d --wait --wait-timeout 900 smoke
docker compose exec smoke python data/prepare_demo.py
Set-Location frontend
npm ci
npm run build
npm run lint
npx playwright install chromium
$env:BASE_URL = 'http://127.0.0.1:8011'
npm run verify:ui
Set-Location ..
docker compose --profile smoke stop smoke
```

To start again with a fresh disposable workspace, use
`docker compose --profile smoke up --force-recreate -d --wait --wait-timeout 900 smoke`.
This resets only the smoke container's cases. Do not use `down -v`; it deletes named volumes.

## Presentation checks

Start the regular app using the [presentation guide](DEMO_READINESS.md), then run:

```powershell
docker compose exec coconut python data/prepare_demo.py
```

Open **Demo readiness** and visit each case: contest, accept, human review, and UPI
auto-reject. Review the evidence and approval state. Complete test Checkout on the contest
case yourself, then run:

```powershell
docker compose exec coconut python data/prepare_demo.py --verify-backing
```

Only a successful remote payment check confirms the Razorpay backing. A placeholder ID or
test key alone does not. No payment is submitted to a bank by these checks.
