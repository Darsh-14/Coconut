# Demo script

Five minutes, live. Assumes backend on :8000 and frontend on :5173, both already running.
The backend lifespan seeds an empty database automatically.

Rehearse the two slow steps once beforehand so the model is warm: the first `/decide` loads
the NLI model (~15s cold), and `/evaluate` takes about 90 seconds on this machine.

---

## 0:00 — The problem (30s)

> "A merchant gets a chargeback. Contesting costs about ₹1,500 in fees and staff time, so
> below a certain ticket size they just concede — and when they do contest, they often
> contest cases they were always going to lose, and pay twice.
>
> The expensive mistake isn't failing to contest. It's contesting badly. So the question
> isn't 'do we have delivery proof' — it's 'do we have *good enough* delivery proof'."

## 0:30 — The front page, then the queue (45s)

Open http://localhost:5173. That is the landing page — scroll once, so the held-out numbers
and the *what it deliberately doesn't do* block land, then **Open the dashboard** and sign
in. The fields are pre-filled; it is one click.

> "Everything I'm about to claim is already on that page, limitations included. And the
> sign-in is a front door, not an account system — it says so on itself. Single-merchant
> demo; authentication was out of scope on purpose."

- 182 disputes, ₹10L in dispute, response countdowns, urgent ones in red.
- Press **Assess 15**. Rows fill in live: the split bar shows most land in *Unclear*.
- Point at the sidebar guardrails: test mode, synthetic disputes, never auto-submits.
- Point at a `real payment` tag: *"the dispute is synthetic, but the payment underneath it
  is a real test-mode Razorpay payment. I'll come back to why that distinction matters."*

## 1:15 — A case, and the actual insight (90s)

Click a CONTEST case (`disp_synthetic_0168` is a good one).

- Bank's claim at the top.
- Each evidence item has a verdict badge **and a yellow highlight inside the text**.

> "That highlight is the sentence that actually drove the verdict — OTP captured, ID number
> matching the KYC record. That's what makes this defensible rather than a black box.
>
> And notice the confidences differ: 50% and 90%. Overall confidence is **50%**, the
> minimum, not the average — because a chain of evidence is only as strong as its weakest
> link, and that's the item the bank will attack first."

**The thing worth saying out loud:**

> "The first version of this scored **0.481 precision** — worse than a coin flip, and
> inverted: it recommended contesting losing cases *more often* than winning ones. The
> reason is that a great delivery proof and a useless one *both* contradict 'never
> arrived'. Entailment can't see evidentiary strength.
>
> So it now asks two questions per item: does this engage the claim, and does it
> *substantiate* a specific enough position to act on. That took precision to 0.625 and cut
> false-positive cost by 79%."

## 2:20 — The UPI beat (45s)

Filter the queue to **No action** and open one. Point at the budget strip.

> "Every chargeback-AI product I looked at is built around Visa and Mastercard mechanics.
> UPI doesn't work that way. NPCI caps disputes at 10 per customer and 5 per payer-payee
> per 30 days, and URCS auto-rejects the overflow under CD1 and CD2 without a human ever
> looking. So on these rails a real share of outcomes is deterministic — predictable
> exactly, not statistically.
>
> This payer has burned their cap. The merchant should spend nothing here. It's a rules
> engine, not a model — which is why the rules sit in one config block with the date I
> verified them against NPCI's circulars, and why that date is on screen."

If asked why there's no AUTO_ACCEPT: that branch depends on the beneficiary bank's TCC or
return in the *next* settlement cycle, which this system can't see. Same instinct as
abstaining on thin evidence.

## 2:45 — Approve, and the honest bit (45s)

Scroll to the drafted representment, edit a word, click **Approve & prepare packet**.

- Audit entry appears. Expand **"Would submit to Razorpay — not sent"**.

> "This is the exact payload we'd send. We build it, log it, and stop. The dispute is
> synthetic — it doesn't exist on Razorpay's side — so submitting would be theatre. It's
> blocked in two independent places, and there's a test that fails loudly if either
> regresses."

## 3:30 — Metrics (60s)

**Performance** → **Run evaluation**. The page already shows the last recorded run, so
the live one is a verification rather than a reveal. While it runs:

> "This is the held-out 30%, untouched during development. Real inference, not a cached
> number — that's why it takes a minute."

When it lands: 69.2 / 75.0 / 72.0, model coverage 29.1%, ₹6,000.

> "Model coverage of 29.1% means it decides 23 of 79 cases on their evidence. Five more
> resolve under deterministic NPCI caps; 51, or 64.6%, go to a person. That abstention is
> the product, not a shortfall — it says 'I don't know' instead of guessing.
>
> The number I actually care about isn't the precision. It's that at the thresholds I
> hand-tuned, the working set scored 0.625 and coverage 0.214 and the held-out set scored
> 0.625 and 0.215 — it generalised instead of fitting noise. Calibration then beat that
> operating point, 0.625 to 0.692, without ever seeing the held-out data."

## 4:30 — Close (30s)

> "Three things I'd point at. The decision is a local NLI model, not an LLM — deterministic,
> free, reproducible; an LLM only rewrites prose after the fact and can't change a verdict.
> Everything that failed is documented with numbers, including a Gemini outage that hung a
> request for 296 seconds until I bounded it. And the core is a claim-verification loop —
> assertion, evidence, does it substantiate — which is the same shape as return-risk scoring
> or abuse-ring detection."

---

## If something breaks

| Symptom | Do this |
|---|---|
| Landed on a marketing page | That's the landing page — **Open the dashboard**, top right |
| Bounced to a sign-in screen | Expected. Pre-filled; click **Continue to dashboard** |
| Queue empty | `cd backend && python -m app.db.seed` |
| "Cannot reach the backend" | Backend isn't running, or something else holds :8000 |
| First `/decide` hangs | Model downloading. Warm it up before demoing |
| Drafted packet looks templated | Gemini was unavailable; the fallback fired — **say so, it's the point** |
| Everything overdue in red | `python -m app.db.seed --reset` rebases the dates |
