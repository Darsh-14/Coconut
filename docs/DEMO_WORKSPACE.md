# Isolated demo workspace

Build the frontend once, then start a separate local server:

```powershell
Set-Location 'D:\Risky Rich\frontend'
npm run build
Set-Location '..\backend'
..\.venv\Scripts\python.exe -m uvicorn app.demo:app --host 127.0.0.1 --port 8011
```

Open http://127.0.0.1:8011 and choose **Try demo**. No Razorpay credentials are needed.
The regular server can continue running on port 8000. Use a single demo worker; every
fresh process creates a new temporary SQLite database and overrides payment credentials.

The small Demo strip links to contest, accept, human review, and UPI-limit examples.
Open each case and click **Assess** to run the real evidence engine. Initial model loading
may take several minutes. These are prepared inputs, not precomputed decisions; changed
evidence or risk budgets can produce different recommendations. Reset restores the inputs,
dates, and default risk budget and clears demo edits, decisions, and approvals.

The demo uses the same UI, inference, evidence verification, and approval audit as the
regular app. Drafts use the deterministic template. Submission remains simulated; payment
creation and webhooks are disabled. The showcase cases are selected from the working set;
the full held-out evaluation is separate and its results are synthetic, not merchant outcomes.

The normal app's database, credentials, and calibration state are not shared with the
demo process. This adds no production authentication or live bank submission capability.

To verify the full demo flow while that server is running:

```powershell
Set-Location 'D:\Risky Rich\frontend'
node scripts/demo-ui.mjs
```

This resets the demo, assesses all four cases with real inference, edits and approves a
contest, resets again, and checks the layout at phone and desktop widths.
