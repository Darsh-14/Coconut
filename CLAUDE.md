# CLAUDE.md — Recourse: Explainable Chargeback Defense Copilot

## 1. What you're building and for whom

Recourse is a submission for Razorpay's AI Buildathon, Track 2 (AI Risk Manager), evaluated
by a technical panel that is judging: does it actually work end to end, are the metrics real
and reproducible, and is the repo clean enough that a stranger can clone it and have it
running in under five minutes. A narrow, fully-working loop beats a broad, half-working one.
Do not add scope beyond what's specified here.

The product: a Razorpay merchant gets a payment dispute (chargeback). Recourse ingests the
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

- **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 (sync engine is fine —
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
- **LLM usage (Claude, via the `anthropic` Python SDK):** only for (a) generating the
  synthetic dispute dataset offline, and (b) drafting the natural-language representment
  packet after the decision is already made by the NLI model. Use a fast/cheap current model
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
      "notes": {"purpose": "recourse-synthetic-dispute-backing"}
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
DATABASE_URL=sqlite:///./recourse.db
ASSUMED_REPRESENTMENT_COST_INR=1500
```

---

## 5. Repository structure

```
recourse/
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

**`POST /disputes/{dispute_id}/approve`** → body `{"approved": bool, "edited_packet":
str | null}`. Returns the updated `AuditLogEntry`. Applies the real-vs-synthetic handling
from Section 7.

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