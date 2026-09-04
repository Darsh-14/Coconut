# CLAUDE.md — Coconut: Explainable Chargeback Defense Copilot

## 1. What you're building and for whom

Coconut is a submission for Razorpay's AI Buildathon, Track 2 (AI Risk Manager), evaluated
by a technical panel that is judging: does it actually work end to end, are the metrics real
and reproducible, and is the repo clean enough that a stranger can clone it and have it
running in under five minutes. A narrow, fully-working loop beats a broad, half-working one.
Do not add scope beyond what's specified here.

The product: a Razorpay merchant gets a payment dispute (chargeback). Coconut ingests the
dispute, gathers the available evidence, checks each piece of evidence against the specific
claim the bank is making, recommends CONTEST or ACCEPT with a confidence score and a full
audit trail, drafts the representment text if contesting, and — when the evidence genuinely
doesn't support a confident call — says so instead of guessing. A human always approves
before anything is treated as final.

---

## 2. Hard constraints — never violate these, under any circumstance

1. **Test mode only.** Every Razorpay API call must use test-mode keys. At startup, read
   `RAZORPAY_KEY_ID` and hard-fail with a clear error if it does not start with `rzp_test_`.
2. **No automatic submission to Razorpay's live dispute/bank workflow.** The system drafts
   and recommends. A human must click approve. This is non-negotiable even in a demo script.
3. **Disputes in this system are synthetic, not real Razorpay dispute objects** — Razorpay's
   test mode does not support fabricating chargebacks on demand, so there is no way to create
   a real disputable transaction to test against. Keep this distinction sharp in the code and
   the README (see Section 7 for exactly what's real vs. synthesized).
4. **Strictly defense-only.** Nothing in this system takes offensive action of any kind
   (no automated refund clawbacks, no contacting customers, no altering payment records).

---

## 3. Tech stack — use exactly this, don't substitute

- **Backend:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.0 (sync engine is fine —
  don't add async complexity for this scale), SQLite as the database file.
- **ML — verification engine:** `sentence-transformers`, using the pretrained cross-encoder
  `cross-encoder/nli-deberta-v3-base` (confirmed real, on Hugging Face, trained on
  SNLI + MultiNLI, apache-2.0 license, ~184M params, based on `microsoft/deberta-v3-base`).
  Use it exactly like this:
  ```python
  from sentence_transformers import CrossEncoder
  model = CrossEncoder('cross-encoder/nli-deberta-v3-base')
  scores = model.predict([(evidence_text, claim_text)])
  # scores shape: (n, 3) -> [contradiction, entailment, neutral] per SBERT's documented order
  label_mapping = ['contradiction', 'entailment', 'neutral']
  ```
  Do not call a large LLM API for this decision. It must be deterministic, local, and free to
  run thousands of times during evaluation without rate limits or per-call cost.
- **LLM usage** — only for (a) generating the
  synthetic dispute dataset offline, and (b) drafting the natural-language representment
  packet after the decision is already made by the NLI model.

  > **AMENDMENT (approved during phase 6):** drafting is now provider-pluggable —
  > Gemini, Anthropic, or a deterministic template — selected via `LLM_PROVIDER`.
  > Gemini is preferred by default because its free tier lets anyone cloning this repo
  > exercise the LLM path without buying credits; the Anthropic path below remains fully
  > implemented. Scope is unchanged: an LLM only ever rewrites prose for a decision the
  > NLI engine has already made. See ARCHITECTURE.md → Representment drafting. Use a fast/cheap current model
  (e.g. `claude-haiku-4-5-20251001`) for bulk synthetic generation, and you may use a stronger
  current model (e.g. `claude-sonnet-5`) for packet drafting quality if you want — check
  `docs.claude.com` for the current canonical model id strings before hard-coding one, since
  these change over time.
- **Razorpay integration:** the official `razorpay` PyPI package.
  ```python
  import razorpay
  client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
  order = client.order.create({
      "amount": amount_in_paise,   # e.g. 19900 = ₹199.00
      "currency": "INR",
      "receipt": receipt_id,
      "notes": {"purpose": "coconut-synthetic-dispute-backing"}
  })
  payment = client.payment.fetch(payment_id)
  ```
  For the Disputes-side methods (fetch/accept/contest), do not guess the exact call
  signature — introspect the installed package directly (`python -c "import razorpay,
  inspect; print(inspect.getsource(razorpay.Client))"` or check
  `site-packages/razorpay/resources/dispute.py`) and use whatever it actually exposes. Wrap
  every dispute-related call in a function that logs the request payload and, if the
  `dispute_id` is synthetic (see Section 7), **does not actually make the network call** —
  log what would have been sent instead.
- **Frontend:** React + TypeScript + Vite, Tailwind CSS. Scaffold with
  `npm create vite@latest frontend -- --template react-ts`, then add Tailwind.
- **Explainability:** for each evidence-claim pair, surface which sentence or phrase within
  the evidence most influenced the verdict. A simple, defensible approach: split evidence
  into sentences, score each sentence independently against the claim with the same
  cross-encoder, and surface the highest-scoring sentence for the winning label. Don't build
  a novel attribution method — a clear, explainable heuristic beats a fancy opaque one here.

---

## 4. Environment variables (`.env.example` — commit this file, never commit `.env`)

```
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
DATABASE_URL=sqlite:///./coconut.db
ASSUMED_REPRESENTMENT_COST_INR=1500
```

---

## 5. Repository structure

```
Coconut/
├── README.md
├── ARCHITECTURE.md
├── CLAUDE.md                        (this file)
├── .env.example
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py                 (loads + validates env vars, enforces test-mode prefix)
│   │   ├── models/
│   │   │   └── schemas.py            (all Pydantic models from Section 6)
│   │   ├── services/
│   │   │   ├── razorpay_client.py
│   │   │   ├── verification_engine.py
│   │   │   ├── decision_aggregator.py
│   │   │   ├── packet_generator.py
│   │   │   └── risk_scorer.py        (stretch goal — build only after everything else works)
│   │   ├── db/
│   │   │   ├── database.py
│   │   │   └── models.py             (SQLAlchemy ORM models)
│   │   └── api/
│   │       └── routes.py             (all endpoints from Section 8)
│   ├── data/
│   │   ├── generate_synthetic_disputes.py
│   │   └── synthetic_disputes.json   (generated output, committed)
│   ├── eval/
│   │   ├── run_evaluation.py
│   │   └── held_out_set.json         (30% split, never touched during development/tuning)
│   ├── tests/
│   │   ├── test_verification_engine.py
│   │   ├── test_decision_aggregator.py
│   │   └── test_api.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── DisputeQueue.tsx
│   │   │   ├── CaseDetail.tsx
│   │   │   └── MetricsDashboard.tsx
│   │   ├── components/
│   │   │   ├── EvidenceClaimMap.tsx
│   │   │   ├── AuditTrail.tsx
│   │   │   └── ConfidenceBadge.tsx
│   │   └── api/
│   │       └── client.ts
│   └── package.json
└── docs/
    ├── pitch_outline.md
    └── demo_script.md
```

---

## 6. Data contracts — exact schemas (put these in `backend/app/models/schemas.py`)

```python
from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime

class EvidenceItem(BaseModel):
    type: Literal["delivery_proof", "communication_log", "device_signal", "order_history", "other"]
    content: str
    source_ref: Optional[str] = None

class Dispute(BaseModel):
    dispute_id: str
    payment_id: str                 # links to a REAL test-mode Razorpay payment (Section 7)
    phase: Literal["fraud", "retrieval", "chargeback", "pre_arbitration", "arbitration"]
    reason_code: str
    claim_text: str
    amount: int                     # paise
    currency: str = "INR"
    raised_at: datetime
    respond_by: datetime
    evidence_bundle: list[EvidenceItem]
    ground_truth_label: Optional[Literal["contest_win", "contest_loss", "should_accept"]] = None

class ClaimVerdict(BaseModel):
    evidence_index: int
    label: Literal["support", "contradict", "neutral"]
    confidence: float               # 0.0-1.0
    highlighted_span: Optional[str] = None

class Decision(BaseModel):
    dispute_id: str
    recommendation: Literal["CONTEST", "ACCEPT", "NEEDS_HUMAN_REVIEW"]
    confidence: float
    claim_verdicts: list[ClaimVerdict]
    drafted_packet: Optional[str] = None
    decided_at: datetime
    model_version: str = "cross-encoder/nli-deberta-v3-base"

class AuditLogEntry(BaseModel):
    id: int
    dispute_id: str
    decision: Decision
    approved_by_human: bool = False
    approved_at: Optional[datetime] = None
    submitted_to_razorpay: bool = False
    would_be_razorpay_payload: Optional[dict] = None   # logged, not sent — see Section 7

class EvalMetrics(BaseModel):
    precision: float
    recall: float
    f1: float
    confusion_matrix: dict          # {"tp": int, "fp": int, "fn": int, "tn": int, "flagged_human": int}
    false_positive_cost_estimate_inr: float
    coverage: float                 # fraction NOT flagged to human
    n_evaluated: int
```

---

## 7. The real-vs-synthetic boundary — read this twice, it prevents a broken demo

- **Real:** the underlying `payment_id` each dispute references should come from an actual
  test-mode order/payment created via the `razorpay` SDK (Section 3). This is what makes the
  demo "real Razorpay integration" and not just a mock.
- **Synthetic:** the dispute itself — `dispute_id`, `phase`, `reason_code`, `claim_text`,
  `evidence_bundle`, `ground_truth_label` — is generated (Section 9), because Razorpay's test
  mode has no mechanism to fabricate a chargeback on demand.
- **Consequence for the `/approve` endpoint:** when a human approves a CONTEST decision, do
  **not** call `client.dispute.contest(...)` against the real API (it will error — the
  `dispute_id` doesn't exist on Razorpay's side). Instead, build the exact request payload
  you *would* send, store it in `would_be_razorpay_payload` on the audit log entry, set
  `submitted_to_razorpay = True`, and show it in the UI clearly labeled "would submit to
  Razorpay." State this openly in the README — it's an honest engineering call, not a gap to
  hide.

---

## 8. API contract — exact endpoints

**`GET /disputes`** → `200`
```json
[{"dispute_id": "disp_synthetic_0001", "phase": "chargeback", "reason_code": "goods_not_received",
  "amount": 249900, "currency": "INR", "respond_by": "2026-08-17T10:00:00Z", "status": "pending"}]
```
`status` is computed: `pending` (no decision yet) | `decided` (decision exists, not approved) |
`approved` | `submitted`.

**`GET /disputes/{dispute_id}`** → `200`, full `Dispute` + latest `Decision` (nullable) + list
of `AuditLogEntry`.

**`POST /disputes/{dispute_id}/decide`** → runs the verification engine + aggregator, persists
and returns a `Decision`. Body: none required.

**Phase-0 API correction:** `POST /disputes/{dispute_id}/approve` requires body
`{"decision_id": int, "approved": bool, "edited_packet": str | null}`. Draft saves and
packet exports also require the current `decision_id`, and
`POST /disputes/{dispute_id}/withdraw` requires the standing `approval_id` query parameter.
These optimistic tokens reject stale tabs rather than applying an action to a newer record.
The endpoint returns the new `AuditLogEntry` and applies Section 7's real-vs-synthetic
handling.

**`POST /evaluate`** → runs the full pipeline over `eval/held_out_set.json` (never used during
development), returns `EvalMetrics`.

---

## 9. Synthetic data generation — use this exact prompt template

In `generate_synthetic_disputes.py`, call the Anthropic API with a system + user message
structured like this (fill in `{n}` and the schema from Section 6):

```
SYSTEM: You generate synthetic e-commerce chargeback dispute records for an ML training and
evaluation dataset. Output ONLY a valid JSON array, no prose, no markdown code fences.

USER: Generate {n} synthetic dispute records. Each record must match this schema exactly:
[paste the Dispute + EvidenceItem schema from Section 6 as a JSON Schema or example].

Vary the records along these axes:
- phase: mostly "chargeback", some "fraud" and "retrieval"
- reason_code: rotate through goods_not_received, goods_not_as_described, duplicate_charge,
  unrecognized_transaction, subscription_cancelled, credit_not_processed
- evidence quality, in roughly these proportions:
  - ~40% of records: evidence that clearly and specifically supports the merchant
    (ground_truth_label = "contest_win")
  - ~35% of records: evidence that is weak, missing key details, or actually contradicts the
    merchant's position (ground_truth_label = "contest_loss" or "should_accept")
  - ~25% of records: evidence that is present and plausible-sounding but genuinely does not
    resolve the claim either way — this bucket must NOT be an easier version of the other two,
    it must be authentically ambiguous, because this is the bucket that should end up
    correctly routed to human review later
- amount: realistic range, ₹299 to ₹45,000, expressed in paise
- claim_text: written like a bank's dispute reason summary, not a customer's own words

Do not include any field that hints at the bucket beyond ground_truth_label itself — the
verification engine will only ever see claim_text and evidence_bundle.
```

Generate in batches of 25-40 per API call to keep outputs reliable, concatenate, then do a
70/30 split into a working set (`synthetic_disputes.json`) and a held-out eval set
(`eval/held_out_set.json`). The held-out set must not be looked at again until Section 10's
`/evaluate` is run.

---

## 10. Decision aggregation — exact rule, not a black box

Given the list of `ClaimVerdict` for a dispute:

```
if any verdict has label == "contradict" and confidence > 0.7:
    recommendation = ACCEPT
elif all verdicts have label == "support"
     and average(confidence) > 0.65
     and count(distinct evidence.type among supporting verdicts) >= 2:
    recommendation = CONTEST
else:
    recommendation = NEEDS_HUMAN_REVIEW

overall_confidence = min(confidence across the verdicts that drove the decision)
```

Use the **minimum**, not the average, for `overall_confidence` — a chain of evidence is only
as strong as its weakest link, and this is a genuinely defensible, explainable design choice
worth stating explicitly in the pitch video, not an arbitrary pick.

---

## 11. Evaluation — exact metric definitions (implement literally this way)

Treat `recommendation == CONTEST` as the positive class. For each held-out record with a
`ground_truth_label`:

- **TP:** model says CONTEST, ground truth is `contest_win`
- **FP:** model says CONTEST, ground truth is `contest_loss` or `should_accept`
- **FN:** model says ACCEPT, ground truth is `contest_win`
- **TN:** model says ACCEPT, ground truth is `contest_loss` or `should_accept`
- **NEEDS_HUMAN_REVIEW** records are excluded from precision/recall/F1 but counted in
  `coverage = (n_evaluated - n_flagged_human) / n_evaluated`

```
precision = TP / (TP + FP)   # guard divide-by-zero
recall = TP / (TP + FN)
f1 = 2 * precision * recall / (precision + recall)
false_positive_cost_estimate_inr = FP * ASSUMED_REPRESENTMENT_COST_INR
```

Report all of this, plus `n_evaluated`, in the `/evaluate` response and on the
`MetricsDashboard` page. Do not round away the confusion matrix — show the raw counts.

---

## 12. Frontend — exact pages, exact contents

- **DisputeQueue:** table with `dispute_id` (truncated), a colored `phase` badge, `reason_code`,
  `amount` (formatted ₹), a countdown to `respond_by` (highlight red under 48 hours), and
  `status`. Row click → CaseDetail.
- **CaseDetail:** `claim_text` at the top. Below it, each evidence item with its
  `ClaimVerdict` badge (support = green, contradict = red, neutral = gray), confidence, and
  `highlighted_span` shown inline in the evidence text. A recommendation banner
  (CONTEST/ACCEPT/NEEDS_HUMAN_REVIEW) with overall confidence. If CONTEST, an editable
  textarea with `drafted_packet` and an "Approve & Submit" button calling
  `POST /disputes/{id}/approve`.
- **MetricsDashboard:** big-number cards for precision/recall/F1/coverage, a confusion matrix
  table, the false-positive cost estimate, and a "Re-run evaluation" button calling
  `POST /evaluate`.

Keep styling clean and legible over decorative. The panel is judging substance, not visual
polish — don't spend more than a day total on the frontend's look.

---

## 13. Build phases — commit after each with message format `feat(phase-N): <summary>`

| Phase | Build | Acceptance test before moving on |
|---|---|---|
| 0 | Repo scaffold, venv, `.env.example`, health check route, Vite frontend scaffold | `uvicorn app.main:app` returns 200 on `/health`; `npm run dev` boots the frontend |
| 1 | `generate_synthetic_disputes.py` using Section 9's prompt | 200-300 schema-valid records generated; label distribution roughly matches the specified proportions; 70/30 split written to disk |
| 2 | `razorpay_client.py`: create real test-mode orders/payments backing a subset of the synthetic disputes | Can create a test order, fetch it back, and confirm a synthetic dispute's `payment_id` resolves to it |
| 3 | `verification_engine.py`: NLI cross-encoder per claim + explainability span | `test_verification_engine.py` passes on 3 hand-written obvious cases (clear support, clear contradiction, clearly insufficient) before running on the full set |
| 4 | `decision_aggregator.py` (Section 10) + SQLAlchemy models + `db/database.py` | `test_decision_aggregator.py` passes using hand-constructed `ClaimVerdict` lists, no model inference needed for this test |
| 5 | FastAPI routes (Section 8), audit log persistence, Section 7's real-vs-synthetic handling in `/approve` | All four endpoints callable via `curl`/httpie against seeded data; `/evaluate` returns real, non-placeholder numbers |
| 6 | `packet_generator.py` using Claude for CONTEST cases | Given a CONTEST decision, produces a coherent draft referencing the specific supporting evidence within a few seconds |
| 7 | Frontend: all three pages wired to the live backend | Full loop navigable in the browser: queue → case → decide → approve → see it reflected in the audit trail and metrics dashboard |
| 8 | README, ARCHITECTURE.md, final polish pass | Clean clone + documented setup steps only, no manual fixes, gets a stranger to a running app |

---

## 14. Testing requirements

- `test_verification_engine.py`: 3+ hand-written cases with asserted expected labels.
- `test_decision_aggregator.py`: pure logic tests against Section 10's rule, no model needed.
- `test_api.py`: integration test hitting `/disputes/{id}/decide` against one seeded dispute,
  asserting a well-formed `Decision` comes back.
- A smoke test that `/evaluate` runs end-to-end and returns metrics within sane bounds
  (0 ≤ precision, recall, f1, coverage ≤ 1).

---

## 15. README — exact section order

1. One paragraph: what this is
2. The problem, with the specific numbers (win rates, RTO rates, non-contest rates)
3. Architecture diagram (reuse the Mermaid diagram from the planning doc, or regenerate one
   matching Sections 6-10 here)
4. Setup: exact commands, from `git clone` through a running app, including where to get
   Razorpay test-mode keys and an Anthropic API key
5. Running it: backend command, frontend command, URL
6. Regenerating synthetic data: exact command
7. Running evaluation: exact command, plus a results table with the actual numbers from your
   last real run (not placeholders)
8. Limitations, stated plainly: dispute data is synthetic and why; the system never
   auto-submits to Razorpay or a bank; the NLI model is used zero-shot, not fine-tuned, unless
   you completed the fine-tuning stretch goal
9. What this generalizes to: one paragraph connecting the verification core to Track 2's
   other example directions (return-risk scoring, abuse-ring detection) — without claiming
   you built those

---

## 16. Explicitly out of scope — do not build these even if they seem quick

- Live-mode Razorpay calls, in any form
- Automatic submission to a bank/network without a human click
- A general checkout-time fraud dashboard or multi-channel abuse-ring detection
- Fine-tuning the NLI model (stretch goal only, and only after Phases 0-8 are done and solid)
- Any authentication/user-account system — this is a single-merchant demo, skip login entirely

---

## 17. Definition of done

A person clones the repo fresh, follows the README's setup section with no undocumented
steps, populates `.env` from `.env.example`, runs the documented start commands, and can: see
a populated dispute queue backed by real test-mode Razorpay payments, open a case and see a
genuine per-claim evidence verdict with confidence and highlighted spans, approve a CONTEST
decision and see it logged in the audit trail with the honestly-labeled
"would submit to Razorpay" payload, and load the metrics dashboard to see real
precision/recall/F1/false-positive-cost/coverage numbers computed from Section 11's formulas
— all without you touching the code again.

# CLAUDE.md — Addendum (append to the end of the existing file)

This adds to, not replaces, the original spec. Read the whole original file first if this is
a fresh session. Everything below assumes Sections 1-17 already exist.

---

## 18. Positioning against what Razorpay has already shipped

Razorpay's own Agent Studio already includes a Dispute Responder Agent, an Abandoned Cart
Conversion Agent, and a Subscription Recovery Agent, launched publicly with Anthropic using
the Claude Agent SDK. Do not let a panel discover this on their own and wonder why it wasn't
mentioned. Add a short subsection to the README (insert into Section 15's item 2, right after
stating the problem) titled "Where this sits next to Razorpay's own Agent Studio" that states
this plainly, then pivots straight into Section 19 below.

Also add to ARCHITECTURE.md, by name: this project's architecture — decision logic runs
before any LLM call, thin evidence degrades to human review instead of guessing, every
decision is logged for replay — was designed independently and only afterward found to match
the lessons in Razorpay's own engineering blog post, "Meet Bumblebee: Agentic AI Flagging
Risky Merchants in Under 90 Seconds" (razorpay tech blog, dev.to, Dec 2025). Cite it by name.
The convergence is the point — say so explicitly, don't bury it as a footnote.

One more honest, specific line for the README's "what this generalizes to" section: Bumblebee's
own published results report system reliability — task completion rate, 88% to 99%+ — not
decision accuracy against labeled outcomes. This project's `/evaluate` endpoint reports
precision, recall, and false-positive cost against a held-out set specifically because that's
a different, complementary measurement the public material doesn't show.

---

## 19. Frontend priority — grounded, not assumed

The actual job posting for this role lists five required full-stack competencies: backend
services, data pipelines, LLM orchestration, frontends (React), and deployment infrastructure.
Frontend is required baseline, not the differentiator — it sits alongside four other things,
none singled out. Nothing in Razorpay's own published engineering writing about this class of
system discusses UI; every measured claim is architectural or numerical. Build the frontend
exactly to Section 12's spec, cleanly, and stop there. Do not add animation, decorative
imagery, or visual flourish beyond what Section 12 already calls for. Time saved here goes
into Section 20.

---

## 20. New component — Evidence Gap Advisor

### Why this exists
Checked against the market leaders in this exact space — Justt, Chargeflow, Riskified's
Dispute Resolve, Shopify's own AI-powered dispute defense, Chargeback Specialist. Every one of
them optimizes the same step: build the strongest case from whatever evidence already exists.
None of them tell the merchant, before the response deadline, which specific missing evidence
would actually flip a borderline decision. That's the gap this fills.

### The idea, precisely
This is the decision_aggregator's own rule (Section 10) run in reverse, with no new model.
GWIE-style counterfactual attribution finds what to remove to see what mattered for a verdict.
This finds what to hypothetically add to see what would matter — same logic, opposite
direction. For a case sitting at NEEDS_HUMAN_REVIEW (or CONTEST below a confidence floor), the
system substitutes a canonical strong exemplar for each evidence type the case is missing or
weak on, reruns the unchanged decision rule against that hypothetical, and reports which
substitution would actually cross a decision boundary — not just "raise confidence a bit,"
but change NEEDS_HUMAN_REVIEW into CONTEST, or a weak CONTEST into a strong one.

### Exact spec

New file: `backend/app/services/evidence_gap_advisor.py`

```python
CANONICAL_STRONG_EVIDENCE = {
    "delivery_proof": "Signed courier proof of delivery with timestamp and photo, matching the exact registered shipping address.",
    "communication_log": "Support conversation in which the customer explicitly confirms receiving the item.",
    "device_signal": "Device and IP fingerprint matching at least three prior undisputed orders from this customer.",
    "order_history": "Consistent order and delivery history for this customer over the past 12 months with zero prior disputes."
}
```

New Pydantic model, add to `backend/app/models/schemas.py`:

```python
class EvidenceGapSuggestion(BaseModel):
    evidence_type: Literal["delivery_proof", "communication_log", "device_signal", "order_history"]
    would_change_recommendation_to: Literal["CONTEST", "NEEDS_HUMAN_REVIEW"]
    confidence_delta: float
    rationale: str
```

Function signature:

```python
def suggest_evidence_gaps(
    dispute: Dispute,
    current_verdicts: list[ClaimVerdict],
    current_decision: Decision
) -> list[EvidenceGapSuggestion]:
```

Logic, exactly:
1. For each key in `CANONICAL_STRONG_EVIDENCE` not already present in `dispute.evidence_bundle`,
   or present with a `ClaimVerdict.confidence < 0.6`: build a hypothetical `evidence_bundle`
   with the canonical exemplar substituted in for that type only, everything else unchanged.
2. Run that hypothetical bundle through the existing `verification_engine.py` and then
   `decision_aggregator.py` — reuse Section 3 and Section 10 exactly as written, no new logic,
   no new model call.
3. Compare the hypothetical `recommendation` and `overall_confidence` against the real,
   current ones.
4. Keep only suggestions where the hypothetical recommendation actually crosses a decision
   boundary (NEEDS_HUMAN_REVIEW → CONTEST, or a CONTEST below 70% confidence rising above it).
   Discard anything that only nudges confidence without changing the practical outcome — that's
   noise, not advice.
5. Sort by `confidence_delta` descending. Return at most 2.

New endpoint, add to `backend/app/api/routes.py`:

`GET /disputes/{dispute_id}/evidence-gaps` → `200`, `list[EvidenceGapSuggestion]`

Frontend addition to `CaseDetail.tsx`: when the recommendation is `NEEDS_HUMAN_REVIEW`, or
`CONTEST` with confidence under 70%, fetch this endpoint and show a card above the
recommendation banner: "Getting [evidence type] would likely move this to contest
(+[X]% confidence)" for each returned suggestion, ranked, using the same visual language
(role colors, confidence bar) as the existing evidence cards from Section 12.

### Build order — this is a bonus phase, not a substitute
Add this as **Phase 9**, after Phase 8 (README/polish) in Section 13's table. Only start it
once Phases 0-8 are genuinely done and the core loop is provably solid end to end. If you
reach the point where Phase 9 would eat into review-and-polish time, skip it and say so
honestly in the README under a "what's next" heading instead of shipping it half-working. A
finished 8-phase project beats a 9-phase project with a broken bonus feature — this is the
same "narrow scope, finished" principle the whole spec has followed from the start.

Acceptance test: given a hand-constructed NEEDS_HUMAN_REVIEW case missing `delivery_proof`,
`GET /disputes/{id}/evidence-gaps` returns a suggestion for `delivery_proof` with
`would_change_recommendation_to: "CONTEST"` and a positive `confidence_delta`.

### The one line for the pitch video
Insert as a new beat 4.5 in Section 9's script, between "Metrics" and "Architecture": show the
Evidence Gap Advisor live on one NEEDS_HUMAN_REVIEW case, then say — "we checked Justt,
Chargeflow, Riskified, and Shopify's own AI defense tooling. All of them build the strongest
case from whatever evidence exists. None of them tell you, before the deadline, which specific
evidence to go get because it would flip the decision. This does, and it cost no new model —
it's the same decision rule, run in reverse."

---

## 21. Optional, cheaper idea if Phase 9 is too much

If Evidence Gap Advisor doesn't fit the remaining time, a smaller alternative: a "replay this
decision" view on CaseDetail — a timeline scrubber through the audit log's evidence-fetch and
verdict steps in order. This directly mirrors a debugging practice Razorpay's own Bumblebee
post describes by name ("we replay the exact sequence of fetcher outputs, examine what the
Analyzer saw"). Lower build cost, smaller payoff than Section 20, but same authenticity angle.
Pick one, not both, if time is tight.

# CLAUDE.md — Addendum 2: UPI Dispute Rules Engine

Append after Addendum 1. This **replaces Section 20 (Evidence Gap Advisor)** as the headline
novel feature. See Section 26 for what to do with the old Section 20.

---

## 22. Why this feature, and why nobody has built it

Every commercial chargeback-AI product surveyed — Justt, Chargeflow, Riskified Dispute
Resolve, Kount, Signifyd, ChargeMate, Chargeback Specialist — is architected around card
network mechanics: Visa VAMP thresholds, Mastercard ECM, card reason-code taxonomies, and a
human adjudicator at the network deciding outcomes. Their published feature sets confirm this.

India's UPI rails work differently in a way that is mechanical, not cosmetic:

- **Dispute caps (NPCI, from Dec 2023):** a customer may raise at most 10 chargebacks in a
  rolling 30-day window, and at most 5 against the same payer-payee combination in that same
  window. Claims exceeding these are auto-rejected with reason code **CD1** (over the 10-per-
  customer cap) or **CD2** (over the 5-per-payer-payee cap).
- **Auto-disposition (NPCI, from 15 Feb 2025):** URCS automatically accepts or rejects
  chargebacks based on the TCC (Transaction Credit Confirmation) or RET (return request)
  raised by the beneficiary bank in the settlement cycle following chargeback initiation.
  Applies to bulk upload and UDIR, not front-end dispute paths.
- **RGNB override (NPCI, from 15 Jul 2025):** "Remitting Bank Raising Good Faith Negative
  Chargeback" lets a remitting bank re-raise a chargeback that URCS auto-declined under CD1 or
  CD2, without the previously-required NPCI whitelisting. Front-end interface only. NPCI has
  stated RGNB cannot be used to dodge penalties or compensation.
- **Separate card rails:** RuPay disputes clear through NPCI's RGCS with its own timelines,
  reason codes, and escalation rules — not Visa/Mastercard rules.

**The consequence, which is the whole idea:** on UPI rails a meaningful share of dispute
outcomes are decided by a deterministic rules engine, not human judgment. That makes them
*predictable in advance, exactly.* No global vendor models this, because their product
architecture assumes a human reviewer at a card network. This is a structural gap, not an
oversight.

### Mandatory verification step before building
These rules have changed three times in under two years (Dec 2023, Feb 2025, Jul 2025). Before
implementing, search for the current NPCI circulars and confirm the cap numbers, the CD1/CD2
code meanings, and RGNB's current status. If any number in Section 23 turns out to be stale,
use the current one and note the correction in the commit message and the README. Do **not**
hard-code these values inline — put them all in one config block (Section 23) with a comment
citing the circular date, so a reviewer can see exactly what the engine assumes and when it
was verified. Being visibly explicit about a rules-engine's provenance is itself a signal of
engineering maturity; state in the README that these are configurable because NPCI revises
them.

---

## 23. Config — `backend/app/services/npci_rules.py`

```python
from datetime import timedelta

# NPCI UPI dispute rules. VERIFY against current NPCI circulars before relying on these.
# Sources as of build date: caps introduced Dec 2023; URCS auto-disposition 15 Feb 2025;
# RGNB category 15 Jul 2025. Update the dates below when re-verified.
NPCI_RULES = {
    "verified_on": "PUT_THE_DATE_YOU_CHECKED_HERE",
    "cap_per_customer_30d": 10,          # exceeding -> auto-reject CD1
    "cap_per_payer_payee_30d": 5,        # exceeding -> auto-reject CD2
    "cap_window": timedelta(days=30),
    "auto_reject_codes": {
        "CD1": "Exceeded 10 chargebacks per customer in rolling 30-day window",
        "CD2": "Exceeded 5 chargebacks per payer-payee combination in rolling 30-day window",
    },
    "rgnb_available": True,              # remitting bank good-faith re-raise, front-end only
    "rgnb_note": "Cannot be used to avoid penalties or compensation (NPCI guidance).",
}
```

---

## 24. Component spec

### New schema additions (`backend/app/models/schemas.py`)

```python
class DisputeBudget(BaseModel):
    payer_ref: str
    customer_disputes_30d: int
    payer_payee_disputes_30d: int
    customer_cap_remaining: int
    payer_payee_cap_remaining: int
    window_resets_at: datetime

class URCSForecast(BaseModel):
    predicted_disposition: Literal["AUTO_REJECT", "AUTO_ACCEPT", "PROCEEDS_TO_MERCHANT", "UNKNOWN"]
    predicted_reason_code: Optional[str] = None      # "CD1" | "CD2" | None
    rgnb_re_raise_possible: bool
    budget: DisputeBudget
    explanation: str
    rules_verified_on: str
```

Extend `Dispute` with two optional fields (keep them optional so card-rail disputes still
validate):

```python
    rail: Literal["upi", "rupay", "card"] = "card"
    payer_ref: Optional[str] = None    # stable pseudonymous payer identifier
```

### New service: `backend/app/services/urcs_forecaster.py`

```python
def forecast_urcs_disposition(dispute: Dispute, dispute_history: list[Dispute]) -> URCSForecast:
```

Logic, exactly — this is a pure function over counters, no model, no LLM:

1. If `dispute.rail != "upi"`, return `predicted_disposition="UNKNOWN"` with an explanation
   that URCS rules don't govern this rail. Do not guess.
2. Count disputes in `dispute_history` where `raised_at` falls within
   `NPCI_RULES["cap_window"]` before `dispute.raised_at`:
   - `customer_disputes_30d`: all disputes with the same `payer_ref`, any merchant.
   - `payer_payee_disputes_30d`: same `payer_ref` **and** same merchant.
3. If `customer_disputes_30d >= cap_per_customer_30d` → `AUTO_REJECT`, reason `CD1`.
   Else if `payer_payee_disputes_30d >= cap_per_payer_payee_30d` → `AUTO_REJECT`, reason `CD2`.
   Else → `PROCEEDS_TO_MERCHANT`, reason `None`.
4. `rgnb_re_raise_possible = (predicted_disposition == "AUTO_REJECT" and NPCI_RULES["rgnb_available"])`.
5. Build `explanation` as one plain sentence naming the counter, the cap, and the code —
   e.g. "This payer has raised 5 of a permitted 5 disputes against this merchant in the last
   30 days; URCS is expected to auto-reject under CD2."
6. Set `rules_verified_on` from config so the provenance travels with every forecast.

**Deliberately do not** claim `AUTO_ACCEPT`. That branch depends on the beneficiary bank's
TCC/RET in the next settlement cycle, which this system has no visibility into. Returning
`PROCEEDS_TO_MERCHANT` and saying so in the explanation is the honest output. Write a code
comment stating this explicitly — a reviewer noticing you *declined* to over-claim is worth
more than a fuller-looking enum.

### Integration with the existing decision path

In `decision_aggregator.py`, run the forecast **before** the Section 10 rule and short-circuit:

```
forecast = forecast_urcs_disposition(dispute, history)
if forecast.predicted_disposition == "AUTO_REJECT":
    recommendation = NO_ACTION_NEEDED
    # URCS is expected to reject this on the merchant's behalf.
    # Spending representment effort here is waste.
else:
    ...existing Section 10 logic unchanged...
```

Add `NO_ACTION_NEEDED` to the `Decision.recommendation` Literal. Persist the full
`URCSForecast` on the audit log entry alongside the decision.

This ordering mirrors the deterministic-rules-before-LLM pattern from Razorpay's own Bumblebee
post (Addendum 1, Section 18) — say so in ARCHITECTURE.md, since it's now literally true twice
over in this codebase.

### Endpoint

`GET /disputes/{dispute_id}/urcs-forecast` → `200`, `URCSForecast`.

### Synthetic data change (updates Section 9)

Regenerate with `rail` and `payer_ref` populated. Requirements:
- ~50% of records `rail="upi"`, rest split between `rupay` and `card`.
- Reuse a small pool of `payer_ref` values (say 25) so 30-day windows actually accumulate.
- Deliberately construct at least 8 records that breach `CD2` and at least 3 that breach `CD1`,
  with `raised_at` timestamps clustered inside a 30-day window so the counters genuinely trip.
- Those records still need a `ground_truth_label` for the Section 11 metrics — label them by
  what the *merchant-side* outcome would have been, and exclude `NO_ACTION_NEEDED` decisions
  from precision/recall the same way `NEEDS_HUMAN_REVIEW` is excluded, counting them in a new
  `auto_resolved` field on `EvalMetrics`. Do not let cap-breach cases silently inflate your
  precision — that would be exactly the kind of dishonest metric this whole project is
  positioned against, and a panel would catch it.

### Frontend (extends Section 12)

- **DisputeQueue:** add a small rail badge (upi / rupay / card). For forecast
  `AUTO_REJECT`, show the row muted with a "URCS will likely auto-reject (CD2)" tag — visually
  de-prioritized, because the merchant genuinely doesn't need to act.
- **CaseDetail:** above the recommendation banner, when `rail="upi"`, a compact budget strip:
  two counters ("payer: 3 of 10 this window" / "with you: 5 of 5") using the existing
  role colors, the predicted disposition, the reason code, and the RGNB availability line.
  Include the `rules_verified_on` date in small muted text — visible provenance.

### Tests

- `test_urcs_forecaster.py`: cap-not-reached → `PROCEEDS_TO_MERCHANT`; exactly-at-CD2-cap →
  `AUTO_REJECT`/`CD2`; over-CD1-cap → `AUTO_REJECT`/`CD1`; a dispute 31 days old correctly
  falls outside the window and does not count; `rail="card"` → `UNKNOWN`.
- Assert the CD1 check precedes CD2 when both would trip.

---

## 25. Build placement

This becomes **Phase 9**, replacing the old Phase 9. Same rule as before: only start after
Phases 0-8 are genuinely done. The forecaster itself is small (a pure function plus counters),
but the synthetic-data regeneration and the metrics change in Section 24 are real work — budget
most of a day, not an hour.

**Acceptance test:** a synthetic UPI dispute whose payer already has 5 disputes against the
same merchant inside 30 days returns `AUTO_REJECT` / `CD2` / `rgnb_re_raise_possible=True`, the
decision comes back `NO_ACTION_NEEDED`, and `/evaluate` counts it under `auto_resolved` rather
than in precision or recall.

---

## 26. What happens to the old Evidence Gap Advisor

Demote it. Addendum 1's Section 20 stays in the repo docs as a "planned next" item in the
README, not a built feature. Reason to state honestly if asked: on re-examination, ROI-based
fight-or-accept decisioning is already commercially available (Justt markets it directly), so
it isn't the differentiator it first appeared to be. Being able to say *"I checked, found my
own idea was already commercial, and moved to something genuinely unbuilt"* is a strong answer
to a panel's inevitable "what did you discard and why" question. Put that sentence in
`docs/pitch_outline.md` verbatim.

---

## 27. The pitch beat (replaces Addendum 1's beat 4.5)

Show a UPI dispute where the payer has already burned their cap. Then:

"Every chargeback-AI product I looked at — Justt, Chargeflow, Riskified, Kount — is built
around Visa and Mastercard mechanics, because that's where their market is. UPI doesn't work
that way. NPCI caps disputes at 10 per customer and 5 per payer-payee per 30 days, and URCS
auto-rejects the overflow under CD1 and CD2 without a human ever looking at it. So on these
rails a real share of outcomes is deterministic — which means it's predictable exactly, not
statistically. This tells the merchant not to spend representment effort on a dispute the
system will reject on its own. It's a rules engine, not a model, which is why it's fully
explainable and why the rules live in one config block with the date I verified them against
NPCI's circulars."

# CLAUDE.md — Addendum 3: Conformal Risk Control (the Risk Budget Dial)

> **PHASE-0 SUPERSESSION NOTICE — IMPLEMENTED STATE:** The addendum below is retained as
> design history, not as a valid guarantee or current implementation contract. Phase 0 ships
> a development-time operating-point search on reused synthetic working data and an empirical
> check on a disjoint held-out file; it does not establish finite-sample or deployment risk
> control. It also intentionally changes the legacy Section 10 CONTEST gate from average
> support confidence to weakest-link (`min`) confidence, so its reported comparison is not a
> threshold-only ablation. The selected-case error `FP / (TP + FP)` is called the
> **contest-error rate** (false-discovery rate) in user-facing copy. Historical code and JSON
> identifiers containing `fp_rate`, plus the `/verify-guarantee` route, remain compatibility
> names only. Where this addendum conflicts with the Phase-0 README or architecture, those
> implemented-state documents take precedence.

Append after Addendum 2. This is now the **headline feature**. It does not sit alongside
Section 10 — it **replaces Section 10's hard-coded thresholds and legacy average-support
gate**. Read Section 33 before
deciding what to keep from Addenda 1 and 2.

---

## 28. The problem this fixes

Section 10 of the original spec hard-codes `0.7` (contradict threshold), `0.65` (average
support confidence), and `0.6` (weak-evidence cutoff in Addendum 1). None of these numbers is
justified by anything. A panel will ask where they came from, and "I picked them" is a bad
answer in a track whose stated bar is measured precision and recall on a held-out set.

The risk-budget search removes a picked runtime threshold. Instead, you choose a **risk
budget** — a maximum tolerated contest-error (false-discovery) rate among auto-contested
cases — and the system selects a threshold and reports the coverage it can achieve at that
budget. The Phase-0 procedure does not meet the independence and multiplicity-control
conditions needed for a formal finite-sample guarantee.

This reframes the core prototype from "our model got 87% precision" to "you name the
contest-error rate you can live with, and the system shows the operating point and its
empirical held-out result — here's what that costs you in coverage."

### Grounding (cite these in ARCHITECTURE.md)
- Conformal prediction gives finite-sample, distribution-free validity under exchangeability;
  split conformal is the practical variant (Vovk et al. 2005; Papadopoulos et al. 2002;
  Angelopoulos & Bates tutorial).
- Conformal risk control extends conformal from coverage sets to controlling a general
  user-specified expected loss (Bates et al. 2021; Angelopoulos et al. 2024).
- Selective classification / abstention with deferral to human experts originates with Chow's
  rejection rule and the Learning-to-Defer line (El-Yaniv & Wiener 2010; Geifman & El-Yaniv
  2017).
- Active 2026 applications include drug discovery, medical foundation models, GUI agents, and
  financial ranking — **not payment disputes**. State this gap plainly; it is the novelty
  claim, and it is checkable.

Do not overstate. The measured ratio is the contest-error/false-discovery rate among
*auto-contested* disputes. Phase 0 reports an empirical check, not a guarantee.

---

## 29. Method — implement exactly this, do not improvise

Use **Learn-then-Test style bounded risk control with a Hoeffding correction.** It is correct,
simple, ~40 lines, and fully explainable on camera.

Setup:
- Split the held-out set (Section 9) into a **calibration** split and a **test** split, 50/50.
  The calibration split is used only to pick the threshold. The test split is used only to
  verify the guarantee held. Never mix them.
- Let `s(x) ∈ [0,1]` be the confidence the decision aggregator already produces for a CONTEST
  recommendation (Section 10's `overall_confidence`, the min over driving verdicts — keep that
  definition, it stays).
- For a candidate threshold `λ`, define the empirical risk on calibration data:

```
R̂(λ) = (# calibration disputes where s(x) ≥ λ AND ground_truth is NOT contest_win)
        / max(1, # calibration disputes where s(x) ≥ λ)
```

i.e. the contest-error (false-discovery) rate among cases the system would auto-contest at
threshold `λ`. The historical helper and response fields retain `fp_rate` in their names for
compatibility, but the denominator is `TP + FP`, not `FP + TN`.

- Given a user-specified risk budget `α` (max tolerated contest-error rate) and failure probability `δ`
  (default `0.1`), select:

```
λ̂ = min { λ ∈ Λ : R̂(λ) + sqrt( log(1/δ) / (2 * n_λ) ) ≤ α }
```

where `Λ` is a grid `[0.50, 0.51, ..., 0.99]` and `n_λ` is the number of calibration points at
or above `λ`. Take the **smallest** qualifying `λ` — that maximizes coverage subject to the
budget. If no `λ` in the grid qualifies, return `None` and have the system report honestly that
the requested budget is not achievable with the available calibration data. **Do not silently
fall back to a default threshold** — an unachievable budget is a real finding and hiding it
would defeat the entire point of the feature.

The guarantee statement to put in the README, worded precisely:

> With probability at least 1 − δ over the draw of the calibration set, the false-discovery rate
> among disputes the system auto-contests is at most α, assuming calibration and deployment
> data are exchangeable.

### Honest limitations — put these in the README, do not bury them
1. Calibration data here is **synthetic** (Section 9). The guarantee therefore holds relative
   to the synthetic distribution. If real dispute data differs, the guarantee does not
   automatically transfer. Say this explicitly.
2. Exchangeability is an assumption. Real dispute streams drift (seasonal fraud patterns, new
   attack modes), which breaks it. Note that handling drift would require adaptive/online
   conformal methods, and that this is out of scope.
3. The bound is on contest-error/false-discovery rate only, not on recall or on total money
   recovered.

Stating all three is not a weakness in the pitch — it is the single clearest demonstration that
you understand what you built. Say them on camera.

---

## 30. Implementation

### New file: `backend/app/services/conformal_calibrator.py`

```python
import math
from typing import Optional

GRID = [round(0.50 + 0.01 * i, 2) for i in range(50)]  # 0.50 .. 0.99

def empirical_fp_rate(scores_and_labels, lam):
    selected = [(s, y) for (s, y) in scores_and_labels if s >= lam]
    if not selected:
        return None, 0
    fps = sum(1 for (_, y) in selected if y != "contest_win")
    return fps / len(selected), len(selected)

def calibrate_threshold(scores_and_labels, alpha: float, delta: float = 0.1) -> Optional[float]:
    """Smallest lambda whose Hoeffding-corrected contest-error rate is <= alpha.

    `empirical_fp_rate` is the retained legacy helper name; its denominator is TP + FP.
    Returns None if the budget is unachievable on this calibration set."""
    for lam in GRID:
        r_hat, n_lam = empirical_fp_rate(scores_and_labels, lam)
        if r_hat is None or n_lam == 0:
            continue
        slack = math.sqrt(math.log(1.0 / delta) / (2.0 * n_lam))
        if r_hat + slack <= alpha:
            return lam
    return None
```

### New schema additions (`backend/app/models/schemas.py`)

```python
class CalibrationResult(BaseModel):
    alpha: float                      # requested max contest-error rate
    delta: float                      # failure probability; nominal confidence is 1 - delta
    calibrated_threshold: Optional[float]
    achievable: bool
    calibration_set_size: int
    n_above_threshold: int
    empirical_fp_rate_on_calibration: Optional[float]
    hoeffding_slack: Optional[float]
    guarantee_statement: str

class GuaranteeVerification(BaseModel):
    """Computed on the TEST split, never the calibration split."""
    alpha: float
    observed_fp_rate_on_test: float
    guarantee_held: bool
    coverage: float                   # fraction auto-decided (not deferred to human)
    n_test: int
```

Extend `Decision` with `calibrated_threshold_used: Optional[float]` and persist it on the audit
log — a decision is only reproducible if you know which threshold produced it.

### Change to `decision_aggregator.py` (supersedes Section 10)

```
forecast = forecast_urcs_disposition(...)        # Addendum 2, unchanged, still runs first
if forecast.predicted_disposition == "AUTO_REJECT":
    return NO_ACTION_NEEDED

lam = get_active_calibrated_threshold()          # from conformal_calibrator, cached
if lam is None:
    return NEEDS_HUMAN_REVIEW                    # budget unachievable -> defer everything

if any verdict is "contradict" with confidence >= lam:
    return ACCEPT
elif all verdicts are "support"
     and overall_confidence >= lam
     and count(distinct evidence types supporting) >= 2:
    return CONTEST
else:
    return NEEDS_HUMAN_REVIEW
```

Phase 0 deliberately promotes `min(confidence)` from Section 10's reported
`overall_confidence` to the unanimous-support gate itself; the legacy gate used
`average(confidence)`. Together with the single selected threshold, this is an intentional
operating-rule change. The ≥2-distinct-evidence-types rule remains a structural constraint.

### Endpoints

- `POST /calibrate` — body `{"alpha": float, "delta": float}` → `CalibrationResult`. Runs on
  the calibration split, caches the active threshold.
- `GET /verify-guarantee` → `GuaranteeVerification`. The historical route name is retained
  for compatibility; it runs the active threshold against the **test** split and reports
  whether the configured budget held empirically.
- Extend Section 11's `EvalMetrics` with `alpha`, `calibrated_threshold`, `guarantee_held`.

---

## 31. Frontend — the demo moment (extends Section 12)

On **MetricsDashboard**, above everything else:

- A slider labeled "Maximum contest-error rate I'll accept", range 1%–20%, step 1%,
  default 5%.
- On release, call `POST /calibrate`, then `GET /verify-guarantee`.
- Render three big numbers side by side: **calibrated threshold**, **coverage at this budget**,
  **observed contest-error rate on the test split** — with a pass/fail marker on whether the budget
  held.
- Below, one plain-English line, regenerated on each change:
  "At a 3% contest-error budget, the system auto-decides 61% of disputes and defers the rest.
  On the held-out test split, the observed contest-error rate was 2.1%."
- If `achievable` is `false`, show that clearly instead of a threshold:
  "A 1% budget isn't achievable with the current calibration set — the system would need to
  defer every case." Do not hide this state; make sure at least one slider position in the demo
  actually triggers it, and point it out on camera.

Use the existing role colors and the `--text-secondary` / metric-card patterns from Section 12.
No new visual language. Do not animate the numbers.

---

## 32. Tests

`test_conformal_calibrator.py`:
- Synthetic calibration set where all high-confidence cases are `contest_win` → a low `alpha`
  is achievable and returns a low threshold.
- Calibration set where high-confidence cases are half wrong → `alpha=0.01` returns `None`.
- Monotonicity sanity check: threshold returned for `alpha=0.02` is ≥ threshold for `alpha=0.10`.
- Slack shrinks as `n_lam` grows (assert on two hand-built sets of different sizes).
- An integration test asserting `/verify-guarantee` uses the test split and never touches
  calibration data — verify by asserting the calibration ids and test ids are disjoint.

---

## 33. What to keep from Addenda 1 and 2

Do not build all three. Priority order, hard:

1. **This addendum (conformal risk control).** Headline. Build it. It replaces Section 10, so
   it is not optional scope — it's a core change.
2. **Addendum 2 (UPI rules engine).** Keep as Phase 10 if — and only if — Phases 0–8 plus this
   addendum are done and solid. It composes cleanly (it short-circuits before the conformal
   path, as shown in Section 30) and it's the strongest *domain* differentiator to this
   addendum's *methodological* one. Together they are a genuinely unusual pairing: rigorous
   statistics plus India-native rails.
3. **Addendum 1 Section 20 (Evidence Gap Advisor).** Cut. README "planned next" only, per
   Addendum 1 Section 26.

If time runs short, ship 1 alone, fully finished, and list 2 and 3 as next steps. A calibrated
guarantee that provably holds beats three half-built features, and that judgment call is itself
what this whole spec has argued for from Section 1.

---

## 34. Pitch beat (replaces Addendum 2 Section 27 as the headline moment)

Put this at beat 4, replacing the plain metrics readout:

"Most chargeback tools report a win rate. That tells you what happened, not what will happen.
So instead of me picking a confidence threshold and hoping — watch this. [drag slider to 3%]
I'm telling the system: I'll tolerate at most a 3% contest-error rate on disputes it contests
automatically. It calibrates its own threshold on a held-out calibration split, and tells me
that costs 61% coverage — the rest defers to a human. [drag to 1%] At 1%, it can't do it, and
it says so rather than pretending. This is conformal risk control. It's used in drug discovery
and medical AI; as far as I can find, nobody has applied it to payment disputes. And the
guarantee is conditional — my calibration data is synthetic, and it assumes exchangeability, so
real-world drift would break it. That's the honest version."

The last sentence is not a hedge to be trimmed for time. Leave it in. In a track whose bar is
honest measurement, being the one candidate who names their own assumptions out loud is the
differentiator.

# CLAUDE.md — Addendum 4: Frontend Engineering & MCP Tooling Directives

Append after Addendum 3. This section defines operational rules for Claude Code in VS Code
when generating or modifying frontend code across `frontend/src/`.

---

## 35. Frontend Engineering & MCP Tooling Directives

### 35.1 UI/UX & Component Architecture
- **Framework & Tooling**: Vite + React + TypeScript, Tailwind CSS, Lucide React (`lucide-react`) icons.
- **Component Foundations**: Accessible, lightweight headless primitives (Radix UI / shadcn patterns).
- **Design Philosophy**: High-signal, executive dashboard aesthetic.
  - Dark-mode first by default: neutral card surfaces (`bg-neutral-900/70` or `bg-slate-900/60`), subtle borders (`border-white/10` or `border-neutral-800`), clean backdrop blur (`backdrop-blur-md`).
  - Clear typography hierarchy: prominent metric readouts, clean tabular numbers (`font-mono` for amounts/paise/IDs), and explicit role colors (Support = Emerald/Green, Contradict = Rose/Red, Neutral/Needs Human = Amber/Yellow/Slate).
- **Required UI States**: For every page and data-driven card (`DisputeQueue`, `CaseDetail`, `MetricsDashboard`):
  1. **Active**: Populated with realistic data adhering strictly to Section 6 schemas.
  2. **Loading**: Skeleton shimmers (`animate-pulse`), never blocking spinners.
  3. **Empty**: Informative icon + descriptive empty text.
  4. **Error**: Inline badge/banner with a non-destructive retry button.

---

### 35.2 MCP Connector Integration Rules

When Model Context Protocol (MCP) servers are active in Claude Code / VS Code, follow these protocols before modifying or authoring frontend code:

1. **Figma MCP (`figma-mcp`)**:
   - Extract exact hex tokens, border radii, card padding, and font scales directly from design nodes.
   - Map Figma auto-layout properties directly to Tailwind flex/grid utility classes (`flex`, `gap-x`, `items-center`).
   - If a matching primitive already exists in `src/components/`, reuse it instead of creating duplicate styles.

2. **Context7 Documentation MCP (`context7` / `@upstash/context7-mcp`)**:
   - Query current API documentation before using newer Tailwind CSS utility classes, Vite configurations, or Radix UI primitive props.
   - Prevent deprecated hook usage or stale TypeScript types.

3. **Playwright MCP (`playwright` / `@playwright/mcp`)**:
   - For end-to-end user workflows (`DisputeQueue` row click → `CaseDetail` review → `Approve & Submit` → `MetricsDashboard` slider interaction), run headless verification.
   - Verify keyboard navigability (`Tab`, `Enter`, `Escape`) across editable packet textareas and modal dialogs.
   - Test responsive layout boundaries at desktop (`1280px+`) and standard laptop (`1024px`) viewports.

4. **GitHub & Local Filesystem MCP (`filesystem` / `github`)**:
   - Confirm file paths and TypeScript aliases (e.g. `@/components`, `@/api/client`) before adding imports.
   - Use utility functions like `cn()` (`clsx` + `tailwind-merge`) consistently for dynamic class styling.

5. **Backend Schema Synchronization**:
   - Ensure frontend TypeScript types in `src/api/` match backend Pydantic models in `backend/app/models/schemas.py` 1:1.
   - Update `client.ts` endpoints to reflect the exact signatures defined in Section 8, Section 24, and Section 30.
