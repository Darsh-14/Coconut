# Pitch outline

Notes for the 5-minute video. The judging parameters are **Problem Taste, Build Quality,
AI Judgment, Failure Recovery** — this maps each to concrete evidence in the repo rather
than to claims.

---

## Problem taste

The non-obvious framing, and the one to lead with:

> The expensive mistake is not failing to contest a chargeback. It is contesting one you
> were going to lose — you pay the representment fee *and* lose the transaction.

That reframes the objective. A system optimised for recall would maximise contests; this one
optimises **precision on the cases it decides** and abstains elsewhere. `false_positive_cost_estimate_inr`
is a headline metric for exactly that reason.

The second framing point: *"do we have delivery proof"* and *"do we have **good** delivery
proof"* look nearly identical to a language model. That gap is the entire engineering
problem, and naming it early shows you understood the domain before writing code.

## AI judgment

Three deliberate choices, each with a reason:

1. **The decision is not made by an LLM.** A local NLI cross-encoder: deterministic,
   free at evaluation scale, reproducible by anyone cloning the repo, no rate limits. An
   LLM only rewrites prose *after* the verdict exists and cannot alter a recommendation,
   verdict or confidence.
2. **The policy remains inspectable.** Deterministic rules and the NLI verdicts propose a
   decision; a synthetic-trained safety gate may only demote CONTEST to human review.
3. **The system abstains.** The model decides 16 of 79 cases on their evidence; 63 go to a
   human, and this regenerated held-out run has no NPCI auto-resolved cases.
   Model coverage and deterministic resolution are reported separately rather than blurred.

If asked why not Gemini/Claude for the verdict: cost and determinism at eval scale, plus
the fact that the decision needs to be auditable and reproducible — not a stylistic
preference.

## Build quality

- 300+ tests. The valuable ones are not coverage padding: boundary tests on strict
  inequalities, an SDK stub that raises on any network access, a leakage check between the
  data splits, injected timeouts on the drafting path.
- Every safety constraint is enforced in code and guarded by a test — see the table at the
  end of ARCHITECTURE.md. Constraints that live only in a README are decoration.
- The full UI loop was driven in a real headless browser with zero console errors.

## Failure recovery — the strongest section

Lead with the one that changes the story, not the smallest one.

**1. The core engine was broken, and measurement caught it.**

> Precision **0.481** — worse than a coin flip, and *inverted*: it fired CONTEST on losing
> cases more often than winning ones. Cause: entailment cannot perceive evidentiary
> strength, because strong and weak proof both contradict the claim. Fix: a second
> substantiation signal. → **0.625**, false-positive cost ₹42,000 → ₹9,000.

**2. A live provider outage hung a request for 296 seconds.**

> Gemini returned 503. The fallback produced correct output — but only after the SDK
> retried internally for nearly five minutes. A fallback that isn't fast isn't graceful.
> Bounded it: **296s → 41.6s → 3.2s**.

**3. Hard-coded model ids would have been dead on arrival.**

> `gemini-2.5-flash` and `gemini-2.0-flash` — the ids most people would write from memory —
> return **404** on this API version. Found by probing the live key rather than trusting
> recall. The code now discovers models at runtime.

**4. Reverting my own change after measuring it.**

> Tightened `SUPPORT_FLOOR` to make the UI more honest; it cost 40% of recall, because the
> aggregation rule needs *all* verdicts to be `support` and the change downgraded legitimate
> contextual evidence. Measured, reverted, documented.

**5. Rejecting a better-looking number.**

> One configuration scored **0.800** precision. Rejected: 5 auto-decisions across 182
> records scales to ~2 held-out, and precision from 2 samples is noise. Worth saying out
> loud — it demonstrates knowing when a metric is lying.

Also available if time permits: `razorpay` 1.4.2 unimportable on Python 3.12+ (would have
broken every fresh clone); the international-card rejection; test suite silently starting to
call a paid API once a key existed.

## What did you discard, and why

The question a panel always asks. The answer, verbatim:

> "I checked, found my own idea was already commercial, and moved to something genuinely
> unbuilt."

The discarded idea was the Evidence Gap Advisor — telling a merchant which missing evidence
would flip a borderline case. Justt already markets ROI-based fight-or-accept decisioning,
so it was not the differentiator it looked like. What replaced it is in the beat below.

## The headline beat — the risk-budget prototype

> "Most chargeback tools report a win rate. That tells you what happened, not what will
> happen. So instead of me picking a confidence threshold and hoping — watch this.
>
> [drag to a workable budget] I tell the system the maximum contest-error rate I'll
> tolerate on disputes it contests automatically. It calibrates its own threshold on a
> development sample, and tells me what that costs in coverage. [drag to 5%] At 5% the
> sample cannot support it, and the system says so rather than pretending.
>
> This is a Hoeffding-corrected operating-point search inspired by conformal risk control.
> The current implementation is deliberately labelled a prototype, not a deployment
> guarantee."

**Then the part that must not be cut for time:**

> "And I'll be straight about what it showed me. The tightest budget this data supports is
> about 71% — which is not a useful operating point. The confidence score
> underneath it has no dynamic range, so there's nothing for a threshold to bite on. That's
> the same AUC-0.57 ceiling I found three different ways. Calibration didn't fix the model.
> It made the model's limits impossible to hide — and it still beat my hand-picked
> thresholds on the held-out set, 0.69 precision against 0.63.
>
> Also: calibration reuses synthetic development data and the threshold grid does not yet
> control family-wise error. The held-out result is an empirical check. Formal
> Learn-then-Test is future work, after a genuinely independent calibration split exists."

That last paragraph is the pitch. In a track whose bar is honest measurement, being the one
candidate who names their own ceiling out loud is worth more than a better number.

## The UPI beat

Show a UPI dispute where the payer has already burned their cap. Then:

> "Every chargeback-AI product I looked at — Justt, Chargeflow, Riskified, Kount — is built
> around Visa and Mastercard mechanics, because that's where their market is. UPI doesn't
> work that way. NPCI caps disputes at 10 per customer and 5 per payer-payee per 30 days,
> and URCS auto-rejects the overflow under CD1 and CD2 without a human ever looking at it.
> So on these rails a real share of outcomes is deterministic — which means it's predictable
> exactly, not statistically. This tells the merchant not to spend representment effort on a
> dispute the system will reject on its own. It's a rules engine, not a model, which is why
> it's fully explainable and why the rules live in one config block with the date I verified
> them against NPCI's circulars."

Follow-up worth having ready: *why no `AUTO_ACCEPT`?* Because that branch depends on the
beneficiary bank's TCC or return in the next settlement cycle, which this system cannot
see. Declining to fill in an enum branch you cannot observe is the same instinct as
abstaining on thin evidence.

## What to avoid claiming

- Don't call six correct contests proof of perfect performance. Report 1.000 observed
  precision at 20.3% coverage and the 0.610 Wilson lower bound together.
- Don't imply the disputes are real. Lead with that limitation — it reads as rigour.
- Don't claim return-risk scoring or abuse-ring detection are built. Say the core
  generalises, and that this repo does one loop end to end.

## Closing line

> "It decides 16 of 79 cases on their evidence and sends 63 to a person. Six of six contest
> calls match the synthetic labels, but six is small support, so the 61% Wilson lower bound
> stays beside the 100% point estimate. That honest abstention is the feature."
