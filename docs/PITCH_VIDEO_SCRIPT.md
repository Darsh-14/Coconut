# Coconut — five-minute pitch video

Target length: about 4 minutes 40 seconds, leaving room for pauses and page loading.

## 0:00–0:35 — Problem

Hi, I’m Darsh, and this is Coconut, an explainable chargeback defence copilot built for
Razorpay’s AI Risk Manager track.

When a dispute arrives, a merchant has to decide whether the evidence is strong enough to
contest it. A false contest costs time, fees and margin, while conceding a valid case loses
revenue. The difficult part is not producing a confident answer. It is knowing when the
evidence does not justify one.

## 0:35–1:05 — Product

Coconut reads the bank’s claim, checks every evidence item, and recommends one of four
outcomes: contest, accept, send to human review, or take no action when an NPCI rule is
expected to resolve the case.

This is the isolated demo workspace. Its sample cases and database are separate from the
regular application, but every assessment uses the same decision engine. I can reset it at
any time, so the walkthrough is reproducible.

## 1:05–2:15 — Live workflow

[Open the Contest case and click Assess.]

Here the model does not return a single unexplained score. Coconut checks whether each
piece of evidence addresses the accusation and whether it is specific enough to prove the
merchant’s position. It highlights the sentence that drove each verdict, so an operator
can inspect the reasoning instead of trusting a label.

[Open Evidence, then Representment.]

The response draft is created only after the decision. A human can edit it, approve or
reject it, and every action is written to the audit trail. Coconut records the payload that
would be sent, but this prototype never automatically submits a synthetic dispute.

[Briefly open Human review and Accept.]

Weak or conflicting evidence is deferred. Evidence that supports the customer’s claim is
accepted. The system is designed to abstain rather than manufacture certainty.

[Open the UPI-limit case.]

Coconut also models India-specific UPI operations. It tracks the payer-payee dispute count
over 30 days and forecasts when NPCI’s URCS cap should auto-reject a dispute, avoiding an
unnecessary merchant response.

## 2:15–3:10 — AI judgment and architecture

[Show an architecture diagram or the README diagram.]

The evidence layer uses a pinned local NLI cross-encoder. It produces evidence-level
support, contradiction and neutral signals. A deterministic aggregator applies the
business rules. A separate synthetic-trained logistic safety gate can only demote a
proposed contest to human review; it cannot create a contest by itself.

The operating threshold comes from a risk budget rather than a hand-picked confidence
number. This lets the merchant state the maximum contest-error rate they can tolerate and
see the resulting coverage. The system also detects stale evidence and locks decision-bound
actions until the case is assessed again.

Razorpay test-mode credentials are enforced at startup. Coconut can create and verify a
test backing payment, validates webhook signatures from the raw request body, and keeps
all submission behaviour behind human approval.

## 3:10–3:55 — Measurement

[Open Performance.]

On the current 79-case synthetic held-out set, Coconut made six contest recommendations
and all six were correct, for an observed precision of 100 percent. Model coverage was
20.3 percent, and the Wilson 95 percent precision interval was 61 to 100 percent.

That is a small synthetic result, not a production claim. I show the support, coverage,
confusion matrix and false-positive cost because high precision obtained by deferring most
cases must be reported honestly. The full evaluation can be rerun from this page.

## 3:55–4:35 — Failure recovery

The hardest failures changed the architecture. The original evidence score was often
confident even for weak proof, so I separated relevance from substantiation and added the
contest safety gate. Model startup could delay the first assessment, so the application
warms the model in the background and exposes separate health and readiness checks.

I also found stale decisions could survive evidence edits, approvals could race with
changes, and demo state could leak between walkthroughs. Coconut now fingerprints evidence,
rechecks mutable state before writes, uses decision-bound approvals, and runs the demo in
a separate resettable process and temporary database.

## 4:35–4:50 — Close

Coconut combines evidence-level AI verification, explicit abstention, measurable risk
budgets, India-specific UPI rules and a human-controlled audit trail. It helps a merchant
fight the chargebacks worth fighting, while making uncertainty and failure visible.

