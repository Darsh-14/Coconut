# Coconut precision and accuracy improvement plan

## Executive summary

Coconut's current contest precision is **100% (6 correct CONTEST decisions out of 6)** on
79 synthetic held-out disputes. The Wilson 95% confidence interval is approximately
**61.0%-100%**, so the point estimate is not a stable estimate of production performance.
The current model decides 16/79 cases on their evidence and sends 63 to human review; no
case in this regenerated held-out run crossed the deterministic NPCI caps. Its population
automatic-win capture is 6/32, or **18.8%**.

The bottleneck is not the final threshold. Coconut's zero-shot NLI signals have only about
0.57 ranking AUC, and eligible scores cluster around 0.50. A threshold can exchange coverage
for precision, but it cannot create information that the score does not contain. Raising the
threshold produced apparently perfect precision on one or two held-out cases, which is not a
statistically valid improvement.

The recommended route is therefore:

1. Collect authorised, pseudonymised, matured merchant dispute outcomes.
2. Build reliable case and evidence-level labels without counterfactual contamination.
3. Establish a structured baseline using the pipeline already added to the repository.
4. Fine-tune the evidence verifier on chargeback-specific support and sufficiency labels.
5. Train a case-level calibrated model over evidence scores and structured signals.
6. Select abstention thresholds on an independent calibration split.
7. Evaluate exactly once on a locked chronological test set and then in shadow mode.

No step below guarantees a higher metric. It creates the conditions under which a measured,
reproducible improvement can be earned rather than manufactured.

---

## 1. Define the outcome before changing the model

### Primary estimand

The first supervised model should estimate:

```text
P(final_outcome = won | merchant_action = contested, evidence available at decision_at)
```

Only disputes that were actually contested and later resolved `won` or `lost` have an
observed binary outcome for this task.

Do not train the win model on:

- accepted disputes;
- expired disputes;
- withdrawn disputes;
- unresolved or pending disputes;
- processor `lost` statuses where the merchant action is unknown;
- partial or administratively closed cases without a separately defined label policy.

Razorpay can record an accepted dispute as `lost`. That does not show that contesting the
same dispute would have lost. Treating accepted cases as negative contest outcomes creates a
counterfactual-label error and teaches the model to reproduce historical merchant policy.

### Product decision

The model output is not itself the final action. Coconut should continue to produce three
model-side states:

```text
high P(win)       -> recommend CONTEST
low P(win)        -> recommend ACCEPT
uncertain middle  -> NEEDS_HUMAN_REVIEW
```

NPCI/URCS deterministic outcomes remain a separate rules layer and must not be included as
model wins.

---

## 2. Predeclare success criteria

Do not choose the release criterion after seeing the test result. A defensible initial gate
is:

| Requirement | Initial gate |
|---|---:|
| Locked-test CONTEST precision point estimate | at least 85% |
| Wilson 95% lower confidence bound for CONTEST precision | at least 80% |
| Locked-test predicted-CONTEST support | at least 300 |
| Model decision coverage | at least 15% |
| Selective accuracy | better than the current engine at matched coverage |
| Population automatic-win capture | better than the current engine |
| False-CONTEST cost | lower than the current engine at matched case mix |
| Important subgroup regression | none beyond a predeclared tolerance |

These are proposed engineering gates, not claims that Coconut currently satisfies them.

Three hundred predicted contests matters because precision from 6/6 is extremely uncertain.
For example, an observed 90% precision over 300 predictions has a Wilson 95% interval of
roughly 86%-93%, which is much more informative than the current interval.

Always report the denominator next to precision. `90% (9/10)` and `90% (270/300)` are not
equivalent evidence.

---

## 3. Acquire the correct data

### Required sources

For each authorised merchant, join:

1. Processor dispute history
   - dispute ID;
   - payment ID;
   - reason code;
   - phase;
   - amount and currency;
   - created/respond-by timestamps;
   - status history;
   - final resolution.
2. Merchant action history
   - contested, accepted, expired, withdrawn, or no action;
   - action timestamp;
   - evidence actually submitted;
   - representment cost.
3. Order and billing data
   - order creation and fulfilment;
   - capture count;
   - duplicate/reversal state;
   - refund destination and status;
   - subscription/cancellation timing.
4. Logistics data
   - delivery timestamps;
   - destination match;
   - signature/OTP availability;
   - proof-of-delivery availability;
   - carrier exceptions.
5. Customer communication evidence
   - messages available before `decision_at`;
   - cancellation/refund requests;
   - receipt or usage acknowledgements;
   - delivery complaints.
6. Authentication and account signals
   - 3DS/OTP state;
   - device/account continuity;
   - prior undisputed activity;
   - address or recipient match indicators.

### Data that does not solve this problem

Generic credit-card fraud datasets label transactions as fraudulent or genuine. They do not
contain the issuer claim, evidence bundle, merchant action, representment submission, or bank
outcome. They may support a separate fraud-risk feature later, but must not be mixed into the
chargeback-win evaluation and presented as an accuracy improvement.

### Suggested data scale

| Stage | Suggested volume | Purpose |
|---|---:|---|
| Contract pilot | 100-300 rows | Validate mappings, redaction and timelines |
| Learning-curve pilot | 500-1,000 matured contests | Determine whether the task is learnable |
| First useful training corpus | 5,000-20,000 matured contests | Train across reasons, rails and merchants |
| Locked test | enough to produce at least 300 predicted contests | Support the precision claim |

These are planning ranges. The learning curve and class/reason distribution should determine
the final requirement.

---

## 4. Use the privacy-safe ingestion pipeline

The repository now contains:

```text
backend/app/models/real_data.py
backend/app/models/real_annotations.py
backend/app/models/real_features.py
backend/data/import_real_disputes.py
backend/data/export_annotation_batch.py
backend/data/audit_annotation_agreement.py
backend/data/import_adjudications.py
backend/data/split_real_disputes.py
backend/eval/real_metrics.py
backend/eval/train_real_baseline.py
backend/training/build_evidence_pairs.py
```

Run the following commands from the `backend` directory.

Generate a private HMAC key in the current PowerShell session:

```powershell
$env:COCONUT_DATA_HMAC_KEY = (& ..\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))").Trim()
```

Import a merchant-authorised staging export:

```powershell
python data/import_real_disputes.py `
  --input D:\secure-data\merchant-disputes.jsonl `
  --output data\private\normalized.jsonl
```

Create leakage-safe splits:

```powershell
python data/split_real_disputes.py `
  --input data\private\normalized.jsonl `
  --output-dir data\private\splits
```

Run the structured/text baseline:

```powershell
python eval/train_real_baseline.py `
  --splits-dir data\private\splits `
  --output eval\artifacts\real\baseline-v1.json `
  --target-precision 0.85 `
  --min-calibration-support 100 `
  --min-test-support 300
```

The importer must remain offline. Do not put merchant API keys, raw exports, normalized rows,
split files or trained artifacts into Git.

---

## 5. Fix label quality before model quality

### Case-level labels

Retain the raw observations:

```text
merchant_action: contested | accepted | expired | withdrawn | no_action
final_outcome:   won | lost | partial | closed | pending
```

Derive `contest_win` or `contest_loss` only when:

```text
merchant_action == contested
and final_outcome in {won, lost}
and resolved_at is present
```

### Evidence-level labels

The NLI verifier requires labels for what each evidence item proves, not merely whether the
whole case won. Annotate each claim/evidence pair as:

- `support`: directly and sufficiently supports the merchant position;
- `contradict`: supports the issuer claim or undermines the merchant position;
- `neutral`: relevant context but does not resolve the claim;
- `insufficient`: topically aligned but missing a required proof element.

Do not infer an evidence label from the final bank outcome. A strong evidence item can appear
inside a lost case for procedural reasons, and a weak item can appear in a bundle that won due
to another document.

### Annotation protocol

1. Write a reason-code-specific rubric.
2. Blind reviewers to final outcome during evidence annotation.
3. Double-label at least 10%-20% of records.
4. Measure inter-annotator agreement.
5. Adjudicate disagreements through a domain expert.
6. Store annotation provenance and rubric version.
7. Keep a never-trained gold annotation set.

---

## 6. Eliminate temporal and entity leakage

Every feature must represent information available at `decision_at`.

Explicitly exclude:

- final dispute status;
- resolution timestamp;
- recovered amount;
- post-decision evidence;
- later customer messages;
- whether evidence was eventually submitted;
- merchant action as a predictive input;
- filenames or storage paths that encode the outcome;
- fields derived from a later webhook state.

Group all related records before splitting. A leakage group should cover connected records
sharing a dispute, payment, order, resubmission, pre-arbitration chain, copied evidence bundle,
or other source-defined root. Compute connected components upstream when several identifiers
form a chain.

Use four time-ordered datasets:

```text
older                                      newer
TRAIN -> VALIDATION -> CALIBRATION -> LOCKED TEST
```

- Train model weights on train only.
- Select architecture and hyperparameters using validation only.
- Select CONTEST/ACCEPT thresholds using calibration only.
- Open the locked test once after code, features and thresholds are frozen.

Run a separate complete-merchant holdout evaluation. A global chronological split and a
strict unseen-merchant split may be impossible to combine when merchants span the same dates,
so report them as two different tests rather than pretending one test establishes both.

---

## 7. Build a model ladder, not one expensive experiment

Every stage must beat the prior stage on the same validation protocol before advancing.

### Experiment A: current Coconut engine

Freeze and replay the current zero-shot NLI engine as the reference.

Record:

- precision/coverage curve;
- PR-AUC;
- selective accuracy;
- population win capture;
- cost per false contest;
- results by reason, phase and rail.

### Experiment B: hashed logistic baseline

Use the baseline already implemented in `train_real_baseline.py`.

It combines:

- claim/evidence tokens;
- evidence type and count;
- reason code;
- phase;
- payment rail;
- currency;
- log-scaled amount.

This is the minimum supervised benchmark. A complex neural model should not ship if it cannot
reliably beat this baseline.

### Experiment C: structured gradient-boosted baseline

After the deterministic baseline is established, add a gradient-boosted tree model over
carefully defined pre-decision fields:

- proof-of-delivery present;
- address/recipient match;
- signature or OTP present;
- refund to original payment method;
- refund completed before claim;
- duplicate settled captures;
- reversal present;
- cancellation before renewal;
- usage after renewal;
- evidence completeness score;
- number and diversity of independent evidence sources;
- phase, reason and rail.

Compare LightGBM/XGBoost/CatBoost only if their dependency and artifact costs are acceptable.
Use probability calibration afterward; tree probabilities are not automatically calibrated.

### Experiment D: chargeback-specific evidence verifier

Fine-tune the existing DeBERTa cross-encoder on annotated evidence pairs.

Recommended input format:

```text
[reason code + normalized bank claim] [SEP] [one evidence sentence]
```

Recommended output classes:

```text
support | contradict | neutral | insufficient
```

`insufficient` is crucial. The current false contests are often evidence that sounds relevant
but omits the decisive proof element.

Training requirements:

- class-balanced or cost-sensitive sampling;
- hard negatives from topically relevant but inadequate evidence;
- reason-code stratification;
- merchant/group isolation;
- maximum sequence length measured from real documents;
- early stopping on validation PR-AUC or precision at required coverage;
- deterministic seeds and recorded package/model versions.

Do not fine-tune directly from case win/loss labels assigned to every evidence sentence. That
would give individual evidence items noisy labels they did not earn.

### Experiment E: hierarchical case-level model

For each evidence item, produce:

- support probability;
- contradiction probability;
- insufficiency probability;
- evidence type;
- completeness indicators;
- strongest-sentence score;
- source independence indicator.

Aggregate these with structured features in a small case-level model. Compare:

1. Regularized logistic regression.
2. Gradient-boosted trees.
3. A small attention/set-pooling network only if simpler models plateau.

The model should learn combinations such as:

- delivery status plus matching recipient plus OTP;
- refund confirmation plus original-payment-method match;
- cancellation timing plus renewal and usage timestamps;
- duplicate captures plus absence/presence of reversal.

Do not include merchant ID as a feature. It can memorize a merchant's historical win rate and
inflate random-split results without learning transferable evidence quality.

### Experiment F: reason- and phase-specific processing

The current single-probe approach handles retrieval requests poorly because a retrieval is
often phrased as a request rather than an accusation.

Implement normalized claim templates by reason and phase:

```text
retrieval/goods_not_received:
  Required proposition: merchant can prove fulfilment and recipient/destination match.

chargeback/credit_not_processed:
  Required proposition: refund completed to the original payment method before cutoff.

chargeback/subscription_cancelled:
  Required proposition: cancellation occurred after renewal cutoff or service was used.
```

Start with shared model weights and reason/phase features. Use separate expert models only when
each reason has enough samples to support independent training and evaluation.

---

## 8. Target the four known false-CONTEST patterns

The present held-out errors reveal missing features rather than a threshold problem.

### Delivery ambiguity

Failure pattern: delivery photograph or scan exists, but destination/recipient is ambiguous.

Add explicit fields:

```text
pod_present
delivery_address_match
recipient_match
signature_present
otp_present
gps_precision/met_requirement
multi_unit_address_ambiguity
```

### Wrong refund destination

Failure pattern: store-wallet credit is treated as equivalent to a refund to the original
payment method.

Add:

```text
refund_initiated
refund_completed
refund_destination_original_method
refund_completed_before_claim
refund_amount_matches
```

### Undelivered renewal notice

Failure pattern: a renewal notice exists but hard-bounced.

Add:

```text
renewal_notice_generated
renewal_notice_delivered
renewal_notice_bounced
cancellation_timestamp
renewal_timestamp
post_renewal_usage
```

### Missing proof-of-delivery document

Failure pattern: carrier status says delivered while the actual POD is absent.

Add:

```text
carrier_status_delivered
pod_document_available
pod_document_submitted
pod_contains_recipient_or_address
```

These fields must be extracted from data available before the recommendation. Missing values
must remain missing; never translate absence into a favourable default.

---

## 9. Optimize for the correct objective

Raw accuracy is not the primary business objective because classes and costs are asymmetric.
A false CONTEST incurs representment cost and may damage the merchant's position, while a false
ACCEPT misses recoverable revenue.

Track:

```text
expected_value =
    P(win | case) * recoverable_amount
    - representment_cost
    - expected operational/network penalty
```

But do not replace evidence sufficiency with amount. A high-value weak case should not become
factually contestable merely because its expected rupee upside is large. Use value after the
model estimates evidentiary win probability and before the human prioritizes the queue.

Maintain two comparisons:

1. Model-quality comparison at matched coverage.
2. Business-value comparison under the same cost assumptions.

---

## 10. Calibrate and abstain correctly

After model selection, fit probability calibration using only validation/calibration data.
Compare:

- Platt/logistic scaling;
- isotonic regression when calibration volume is adequate;
- temperature scaling for neural logits.

Select two thresholds:

```text
P(win) >= contest_threshold -> CONTEST
P(win) <= accept_threshold  -> ACCEPT
otherwise                   -> HUMAN REVIEW
```

Threshold selection must require:

- target precision;
- minimum predicted support;
- minimum coverage;
- confidence interval reporting;
- no access to locked-test labels.

Never advertise 100% precision from one or two predictions. If no calibration threshold meets
the requirements, the correct output is an unsupported operating point and human deferral.

---

## 11. Evaluation report specification

Every experiment report should include:

### Overall metrics

- predicted-CONTEST precision with Wilson interval;
- predicted-CONTEST support;
- population automatic-win capture;
- selective recall, explicitly named;
- model, CONTEST and ACCEPT coverage;
- selective accuracy;
- PR-AUC/average precision;
- Brier score;
- expected calibration error and calibration plot;
- raw confusion/deferred counts;
- false-CONTEST cost;
- recovered value estimate.

### Slices

- reason code;
- phase;
- payment rail;
- amount band;
- month/time window;
- evidence completeness;
- merchant cohort without exposing merchant identity;
- seen-merchant chronological test;
- completely unseen-merchant test.

Suppress or clearly mark slice metrics with inadequate support. A noisy slice should not be
used to claim a regression or improvement.

### Required comparisons

```text
current zero-shot engine
vs hashed logistic baseline
vs structured baseline
vs fine-tuned evidence model
vs combined case-level model
```

Report matched-coverage comparisons so a model cannot appear more precise merely by deciding
almost nothing.

---

## 12. Ablation plan

Run these controlled removals on validation data:

| Ablation | Question answered |
|---|---|
| Remove claim/evidence text | Are structured signals carrying the model? |
| Remove structured evidence indicators | Does fine-tuned text add real value? |
| Remove reason/phase | Is the model learning reason-specific requirements? |
| Remove evidence completeness | Are false contests driven by missing documents? |
| Remove authentication/device signals | How much do fraud cases depend on them? |
| Remove amount | Is monetary value distorting probability? |
| Replace fine-tuned encoder with zero-shot encoder | Did domain training improve signal? |
| Remove hard-negative training | Does it fix plausible-but-insufficient evidence? |

Advance a component only if it contributes repeatable validation improvement and does not
introduce unacceptable subgroup regressions.

---

## 13. Shadow deployment

Do not replace the current runtime immediately after a good offline result.

### Stage 1: offline replay

- Run on historical cases using only cutoff-time evidence.
- Confirm manifest and code fingerprints.
- Freeze the model and thresholds.
- Evaluate the locked test once.

### Stage 2: shadow mode

- Generate recommendations without showing or acting on them.
- Preserve evidence snapshots and predictions.
- Reconcile with final processor outcomes later.
- Monitor score, reason-code and evidence drift.

### Stage 3: recommendation-only pilot

- Show recommendation and explanation to reviewers.
- Require mandatory human approval.
- Record overrides and reasons.
- Do not auto-submit.

### Stage 4: small high-confidence canary

- Start with at most 5% of eligible cases.
- Restrict to supported reasons and rails.
- Keep human approval.
- Roll back on precision, calibration, latency or drift breach.

The present Coconut safety boundary remains unchanged: no automatic live dispute submission.

---

## 14. Concrete repository implementation sequence

### Phase A: data and baseline - already implemented

- `backend/app/models/real_data.py`
  - strict normalized data contract;
  - separate action and outcome;
  - optional evidence annotations;
  - obvious sensitive-text guards.
- `backend/data/import_real_disputes.py`
  - JSON/JSONL/CSV ingestion;
  - HMAC pseudonymization;
  - redaction and forbidden-key checks;
  - deterministic deduplication;
  - atomic output.
- `backend/data/split_real_disputes.py`
  - grouped chronological four-way split;
  - manifest and locked-test hash.
- `backend/eval/real_metrics.py`
  - intervals, calibration and selective metrics.
- `backend/eval/train_real_baseline.py`
  - deterministic hashed logistic baseline;
  - calibration-only threshold selection;
  - locked-test claim gate.

### Phase B: annotation tooling (implemented; requires human labels)

Implemented:

```text
backend/data/export_annotation_batch.py
backend/data/import_adjudications.py
backend/data/audit_annotation_agreement.py
```

Implemented safeguards:

- outcome-blind evidence tasks;
- reviewer pseudonym contracts;
- exact rubric-version checks;
- duplicate-review rejection;
- two-reviewer consensus and explicit expert-adjudication rules;
- unresolved disagreement counts and anonymized agreement reports.

Reviewer-file retention and immutability must be enforced by the authorised data owner; the
repository does not claim to provide a regulated annotation-log storage system.

### Phase C: structured feature extraction (contract and baseline integration implemented)

Implemented:

```text
backend/app/models/real_features.py
backend/data/import_real_disputes.py
backend/eval/train_real_baseline.py
backend/tests/test_real_data_import.py
backend/tests/test_real_baseline.py
```

The importer now accepts an explicit tri-state signal contract, rejects signals observed after
the prediction cutoff, and the baseline uses only whitelisted signal values. Tests verify that
unknown is distinct from false and that outcome, resolution, action, and identifiers do not
alter the feature vector.

### Phase D: evidence-model fine-tuning

Add:

```text
backend/training/build_evidence_pairs.py
backend/training/train_evidence_cross_encoder.py
backend/training/evaluate_evidence_model.py
backend/tests/test_training_data_leakage.py
```

The evidence-pair builder is implemented. Actual cross-encoder fine-tuning and comparison
remain blocked on an authorised, human-labelled corpus; creating synthetic evidence labels
from case outcomes would invalidate the experiment.

Artifacts must record:

- base model revision;
- tokenizer revision;
- dataset/split hashes;
- seed;
- hyperparameters;
- label mapping;
- code revision;
- validation metrics.

### Phase E: case model and calibration

Add:

```text
backend/training/build_case_features.py
backend/training/train_case_model.py
backend/training/calibrate_case_model.py
backend/eval/compare_real_models.py
```

The comparison script should generate one machine-readable JSON report and one Markdown model
card from the same values.

### Phase F: shadow runtime adapter

Add a separate, feature-flagged service:

```text
backend/app/services/real_model_shadow.py
```

Rules:

- default disabled;
- never changes the current recommendation;
- never submits anything;
- logs only pseudonymous case/model/version/outcome fields;
- no raw evidence text in operational logs;
- timeout/failure cannot break the normal Coconut request.

---

## 15. Deadline-aware execution order

### Before the immediate demo deadline

Do:

1. Keep the current application behavior stable.
2. Demonstrate the real-data contract, importer and locked-test pipeline using the explicitly
   fictional fixture.
3. Explain that the fixture validates engineering, not model performance.
4. Present the current 100% as 6/6 with its 61.0%-100% confidence interval.
5. Show why human review and NPCI rules are separate from model precision.
6. State that real-data training is implemented as an offline path but awaits an authorised
   corpus.

Do not:

- change the shipped threshold using held-out labels;
- describe the fictional fixture as real merchant data;
- claim the hashed baseline improved production performance;
- train overnight on generic fraud data and rename the result chargeback accuracy;
- destabilize the working demo by swapping the runtime model before verification.

### First research sprint after obtaining data

1. Import 100-300 records and repair source mappings.
2. Audit redaction and `decision_at` leakage manually.
3. Produce label/action/outcome distributions.
4. Run the current engine and hashed baseline.
5. Build a learning curve at 10%, 25%, 50%, 75% and 100% of training data.
6. Annotate the highest-value error clusters.
7. Fine-tune the evidence verifier.
8. Add structured completeness signals.
9. Freeze thresholds and run the locked test.
10. Start a later-time shadow window only if the release gate passes.

---

## 16. Experiment log template

Use this for every model run:

```markdown
# Experiment ID

- Date:
- Owner:
- Hypothesis:
- Code revision:
- Dataset manifest SHA-256:
- Train/validation/calibration/test hashes:
- Base model and revision:
- Feature schema version:
- Hyperparameters:
- Predeclared primary metric:
- Minimum support and coverage:

## Validation result

- Precision and interval:
- Predicted-CONTEST support:
- Coverage:
- Population automatic-win capture:
- PR-AUC:
- Brier/ECE:
- Cost estimate:
- Subgroup regressions:

## Decision

- Reject / continue / freeze for locked test
- Reason:
- Test set opened: no/yes
```

Never overwrite an experiment. New data, labels, features, thresholds or code require a new
experiment ID and artifact.

---

## 17. Final recommendation

The fastest credible route to higher precision is not a larger generic language model and not
a more aggressive threshold. It is a chargeback-specific evidence-sufficiency signal trained
on real, cutoff-correct, human-annotated merchant evidence, combined with structured proof
completeness and calibrated case outcomes.

Prioritize work in this order:

1. Correct observed labels.
2. Leakage-safe real data.
3. Structured baseline.
4. Evidence-level hard negatives.
5. Fine-tuned verifier.
6. Case-level calibrated model.
7. Independent locked test.
8. Shadow deployment with human approval.

Until an authorised corpus is available, Coconut should retain its current model, abstention
behavior and transparent synthetic metrics. The new offline pipeline provides the foundation;
the data and controlled experiments are what can produce a real boost.
