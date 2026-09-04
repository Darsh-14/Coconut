# Real-dispute research pipeline

This pipeline turns an authorised historical merchant export into a pseudonymised,
chronologically split research dataset and an offline baseline report. It is intentionally
separate from Coconut's API and demo database: it never fetches from Razorpay, never accepts
API credentials, and never submits a dispute.

The checked-in example at
[`backend/data/examples/real_disputes.sanitized.jsonl`](../backend/data/examples/real_disputes.sanitized.jsonl)
is strictly fictional **canonical normalized output**, so the splitter consumes it directly;
it is not raw input for the importer. It is useful only for validating the normalized contract
and downstream commands. It cannot support a performance claim.

## What this can and cannot establish

A real, representative, mature dataset can replace the current synthetic-only estimate with
an externally relevant measurement and can support supervised model development. It does not
guarantee that precision will improve. Do not report a target as achieved unless an untouched
test split has enough model-predicted `CONTEST` cases and the reported confidence interval
supports it.

This first baseline estimates `P(win | merchant actually contested)`. It does **not** learn
what would have happened had an accepted, expired, withdrawn, or untouched dispute been
contested. Those outcomes are unobserved counterfactuals.

Generic card-fraud datasets are not substitutes: a transaction-level `is_fraud` label has no
bank claim, pre-decision evidence bundle, merchant action, or representment outcome. Mixing
one into this evaluation would change the task while making the headline number look better.

## Privacy and security gate

Before importing anything:

1. Use only data the merchant is authorised to use for this purpose. Confirm the applicable
   consent, retention, deletion, access-control, and data-processing requirements with the
   data owner.
2. Keep the raw export encrypted outside the repository. The repository ignores the intended
   private data and generated-model locations, but `.gitignore` is not an access-control
   system.
3. Never include full PAN/card numbers, CVV, PIN, track data, passwords, API keys, webhook
   secrets, private keys, unredacted names, addresses, email addresses, phone numbers, UPI
   VPAs, IP addresses, or raw processor/customer/order identifiers.
4. Put `COCONUT_DATA_HMAC_KEY` in the environment or a secret manager, never in a command-line
   argument, source file, dataset, log, screenshot, or commit. Use one stable key for a dataset
   version so joins remain deterministic. Rotation deliberately produces different references.
5. Treat the pseudonymised output as sensitive. HMAC references and automatic text redaction
   reduce exposure; they do not prove that a dataset is anonymous. A human privacy review is
   still required before any output is shared.

The importer fails closed on forbidden raw field names, validates the schema, replaces common
sensitive text patterns with bracketed placeholders, and HMAC-pseudonymises identifiers. A
pattern scanner cannot recognise every form of sensitive data, so inspect source-specific
fields before and derived samples after every import.

## Source input contract

The offline importer accepts a JSON array, JSONL (one object per line), or CSV. Each source row
uses raw identifiers only at this boundary; they are not written to the normalized output.

| Field | Type | Required | Meaning |
|---|---:|:---:|---|
| `source_kind` | string | yes | `merchant_export`, `processor_export`, or `joined_export` |
| `merchant_id` | string | yes | Stable merchant/account identifier used only as HMAC input |
| `dispute_id` | string | yes | Stable source dispute identifier used only as HMAC input |
| `leakage_group_id` | string | no | Explicit root entity shared by related cases; otherwise the importer derives it from order, payment, customer, then dispute identity |
| `payment_id` | string | no | Source payment identifier, used only as HMAC input |
| `order_id` | string | no | Source order identifier, used only as HMAC input |
| `customer_id` | string | no | Source customer identifier, used only as HMAC input |
| `created_at` | RFC 3339 string | yes | Time the dispute was created, including a timezone |
| `decision_at` | RFC 3339 string | yes | Leakage-safe prediction cutoff; every feature and evidence item in the row must have been knowable then |
| `respond_by` | RFC 3339 string | no | Response deadline; must be later than `created_at` |
| `resolved_at` | RFC 3339 string | conditional | Required for a non-pending outcome; forbidden for `pending` |
| `phase` | string | yes | `fraud`, `retrieval`, `chargeback`, `pre_arbitration`, or `arbitration` |
| `reason_code` | string | yes | Source reason code, restricted to a compact non-PII identifier |
| `rail` | string | yes | `card`, `upi`, `rupay`, `wallet`, `netbanking`, or `other` |
| `amount` | integer | yes | Positive amount in currency minor units (for example, paise for INR) |
| `currency` | string | yes | Uppercase three-letter ISO currency code |
| `claim_text` | string | yes | Claim text presented at `decision_at`; importer writes only its redacted form |
| `evidence` | array | no for JSON/JSONL | Zero or more evidence objects described below; omitted means an empty bundle |
| `evidence_json` | JSON string column | yes for CSV | CSV representation of `evidence`; a blank cell means an empty bundle |
| `merchant_action` | string | yes | `contested`, `accepted`, `expired`, `withdrawn`, or `no_action` |
| `final_outcome` | string | yes | `won`, `lost`, `partial`, `closed`, or `pending` |
| `evidence_submitted` | boolean | yes | Whether evidence was actually submitted to the processor |
| `recovered_amount` | integer | no | Non-negative recovered amount in minor units, no greater than `amount`; forbidden while pending |
| `representment_cost` | integer | no | Non-negative observed representment cost in minor units |

Each evidence object has `type`, `content`, and an optional `source_id`. Allowed types are
`delivery_proof`, `communication_log`, `device_signal`, `order_history`, `refund_record`,
`billing_record`, `processor_record`, and `other`. `source_id` is HMAC-pseudonymised; `content`
is redacted into `content_redacted`.

A minimal fictional JSONL source row looks like this (one line in the actual file):

```json
{
  "source_kind": "joined_export",
  "merchant_id": "fictional_merchant_001",
  "dispute_id": "fictional_dispute_001",
  "payment_id": "fictional_payment_001",
  "order_id": "fictional_order_001",
  "created_at": "2025-01-01T09:00:00+05:30",
  "decision_at": "2025-01-02T09:00:00+05:30",
  "respond_by": "2025-01-08T09:00:00+05:30",
  "resolved_at": "2025-01-20T09:00:00+05:30",
  "phase": "chargeback",
  "reason_code": "goods_not_received",
  "rail": "card",
  "amount": 249900,
  "currency": "INR",
  "claim_text": "Customer says the parcel was not received.",
  "evidence": [
    {
      "type": "delivery_proof",
      "content": "Carrier record shows recipient confirmation at the verified destination."
    }
  ],
  "structured_signals": {
    "observed_at": "2025-01-02T08:55:00+05:30",
    "source_version": "warehouse-v1",
    "carrier_status_delivered": true,
    "pod_document_available": true,
    "recipient_match": null
  },
  "merchant_action": "contested",
  "final_outcome": "won",
  "evidence_submitted": true,
  "recovered_amount": 249900
}
```

Optional evidence annotations must be supplied as a complete trio, never piecemeal:
`adjudicated_label` (`support`, `contradict`, `neutral`, or `insufficient`),
`annotation_provenance` (`single_human`, `double_human_consensus`, or
`expert_adjudication`), and a versioned `annotation_version`. An outcome must never be copied
into an evidence annotation.

`structured_signals` is optional. Every signal is `true`, `false`, or `null` (unknown), and
`observed_at` must be on or before `decision_at`. The importer rejects late signals and
unknown fields. Source systems must map these values explicitly; Coconut does not infer them
from the final outcome or silently turn missing values into `false`.

All timestamps must include an offset (for example, `2026-01-15T10:30:00+05:30` or
`2026-01-15T05:00:00Z`). The importer canonicalizes them to UTC. Do not use file creation time,
resolution time, or the latest webhook time as `decision_at`.

## Canonical normalized record

Importer output is JSONL with one deterministic, validated record per line. It uses schema
version `1.0` and these renamed/derived fields:

- Raw identifier fields become `merchant_ref`, `dispute_ref`, `leakage_group_ref`, and
  optional `payment_ref`, `order_ref`, `customer_ref`. Evidence `source_id` becomes
  `source_ref`. Every value has the form `coc_v1_` followed by 24 lowercase hexadecimal
  characters.
- `claim_text` becomes `claim_text_redacted`; evidence `content` becomes
  `content_redacted`. Expected substitutions include `[REDACTED_EMAIL]`,
  `[REDACTED_PHONE]`, `[REDACTED_UPI]`, `[REDACTED_CARD]`, `[REDACTED_IP]`, and
  `[REDACTED_REFERENCE]`.
- `merchant_action` and `final_outcome` remain separate fields. They are never collapsed or
  inferred from each other.
- Amounts remain integers in minor units. The importer does not guess or convert units.

Duplicate `(merchant_ref, dispute_ref)` rows with identical content collapse deterministically.
Conflicting duplicates fail the import and must be reconciled at the source.

When identities form a chain (for example two disputes share a payment while another shares
that payment's order), compute a connected-component/root ID upstream and supply it as
`leakage_group_id`. A single fallback identifier cannot represent every many-to-many join.

## Razorpay mapping, without credentials

Create a staging export in an authorised system, then map it to the source contract above.
Do not add Razorpay API calls or credentials to this pipeline. Razorpay documents dispute
fields such as `id`, `payment_id`, `amount`, `currency`, `reason_code`, `respond_by`, `status`,
`phase`, `created_at`, and `evidence` in its
[Disputes API](https://razorpay.com/docs/api/disputes/fetch-all/?preferred-country=IN).
[Dispute webhooks](https://razorpay.com/docs/webhooks/disputes/?preferred-country=IN) can be
used by an authorised upstream system to retain status history.
Razorpay's [Accept Dispute API](https://razorpay.com/docs/api/disputes/accept/?preferred-country=IN)
documents that accepting moves a dispute to `lost`; that is why processor status alone is not
a valid label for what would have happened under contest.

Suggested staging mapping:

| Razorpay/upstream value | Source-contract field | Important rule |
|---|---|---|
| Merchant account identity or webhook `account_id` | `merchant_id` | Never carry the raw value beyond import |
| Dispute entity `id` | `dispute_id` | Do not paste a live ID into fixtures, issues, or logs |
| `payment_id` | `payment_id` | Use only for pseudonymisation and grouping |
| Expanded payment `order_id`, if authorised | `order_id` | Prefer this as the root group when repeat disputes can share an order |
| Dispute `created_at`, `respond_by` | corresponding timestamp | Convert Unix seconds to timezone-aware RFC 3339 in staging |
| `amount`, `currency`, `reason_code`, `phase` | same semantic field | Preserve amount minor units; map unknown rails to `other` |
| Non-null evidence fields | `evidence[]` | Export only evidence text known at `decision_at`; document references must not be downloaded into this repo |
| Final `status` | `final_outcome` | `won`/`lost` map directly; open or under-review rows remain `pending`; review `closed` semantics separately |
| Merchant action/audit log | `merchant_action` | Required independent observation; never infer `accepted` from `lost` |
| Actual internal review timestamp | `decision_at` | Must precede outcome information and include only then-known evidence |

Verify webhook signatures and deduplicate webhook event deliveries in the upstream integration,
following Razorpay's [webhook guidance](https://razorpay.com/docs/webhooks/). The offline
importer deliberately does neither because it accepts files, not network events.

## Run the pipeline

Run commands from `backend/` with the project virtual environment active.

### 1. Create a session-only pseudonymisation key

PowerShell:

```powershell
$coconutKeyBytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($coconutKeyBytes)
$env:COCONUT_DATA_HMAC_KEY = [Convert]::ToBase64String($coconutKeyBytes)
```

Bash/zsh:

```bash
export COCONUT_DATA_HMAC_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Store the generated value in an approved secret manager if later imports must join to the
same pseudonyms. Do not copy it into `.env` for this repository.

### 2. Import, redact, validate, and pseudonymise

```bash
python data/import_real_disputes.py \
  --input /secure/location/disputes.jsonl \
  --output data/private/normalized.jsonl
```

The command refuses to overwrite an existing output. Use `--force` only when intentionally
creating a replacement dataset version. Read every validation error; do not weaken a guard to
make a row pass.

### 3. Blind-label evidence before freezing splits

Export an outcome-blind batch. It contains the claim, evidence, reason, and phase, but no
merchant/dispute/source references, action, final outcome, recovery, or cost:

```bash
python data/export_annotation_batch.py \
  --input data/private/normalized.jsonl \
  --output data/private/annotation_tasks_v1.jsonl \
  --rubric-version evidence-v1
```

Each reviewer receives a stable `rev_v1_...` reference from the data owner. Generate it
interactively so the raw reviewer identity is neither stored nor placed in shell history:

```bash
python data/pseudonymize_reviewer.py
```

Reviewer output is JSON or JSONL using this contract:

```json
{
  "schema_version": "1.0",
  "task_id": "ann_v1_000000000000000000000000",
  "reviewer_ref": "rev_v1_000000000000000000000000",
  "role": "reviewer",
  "label": "support",
  "rubric_version": "evidence-v1",
  "confidence": 4,
  "reason_tags": ["direct_match"]
}
```

Combine reviewer files locally, audit agreement, then merge labels. Two matching reviewer
labels become `double_human_consensus`. Disagreement remains unresolved until one row with
`role=adjudicator` is supplied. A single label is rejected by default; `--allow-single`
exists only for an explicitly approved pilot policy.

```bash
python data/audit_annotation_agreement.py \
  --input data/private/reviews_v1.jsonl \
  --output data/private/agreement_v1.json

python data/import_adjudications.py \
  --records data/private/normalized.jsonl \
  --annotations data/private/reviews_v1.jsonl \
  --output data/private/adjudicated_v1.jsonl \
  --rubric-version evidence-v1
```

The agreement report contains counts, label distribution, pairwise confusion matrices,
observed agreement, and Cohen's kappa, but no task or reviewer references. Inspect low-agreement
reason codes and repair the rubric before training; do not hide disagreement through majority
vote or case outcomes.

### 4. Create immutable chronological/group splits

```bash
python data/split_real_disputes.py \
  --input data/private/adjudicated_v1.jsonl \
  --output-dir data/private/splits
```

Default record targets are 60% train, 15% validation, 10% calibration, and 15% test. The
splitter keeps every `leakage_group_ref` in one split and permits cuts only where a later
split does not begin before the prior split ends (equal timestamps are allowed). Ratios are
targets, not permission to break groups. If no safe four-way
split exists, collect or repair the data rather than randomising it.

The output directory contains `train.jsonl`, `validation.jsonl`, `calibration.jsonl`,
`test.jsonl`, and `manifest.json`. The manifest records counts, time ranges, label/action
breakdowns, and SHA-256 hashes. Freeze the test hash before model development; training,
feature choices, threshold selection, and error analysis must not inspect that file.

This four-way split measures later-time performance; it does not by itself prove performance
for an unseen merchant. For a multi-merchant study, run a separate evaluation that holds out
complete merchants, predeclare those merchant cohorts before training, and continue to exclude
`merchant_ref` from features. Do not force merchant isolation and global time isolation into a
single split when merchants span the same dates, because the two constraints may be impossible
to satisfy simultaneously.

### 5. Build evidence pairs and train/evaluate the offline baseline

Build fine-tuning inputs independently from each already-frozen split. This step copies only
human evidence labels and never creates sentence labels from case win/loss outcomes:

```bash
python training/build_evidence_pairs.py \
  --input data/private/splits/train.jsonl \
  --output training/private/evidence_train_v1.jsonl

python training/build_evidence_pairs.py \
  --input data/private/splits/validation.jsonl \
  --output training/private/evidence_validation_v1.jsonl
```

Do not build or inspect evidence pairs from the locked test split during development.

```bash
python eval/train_real_baseline.py \
  --splits-dir data/private/splits \
  --output eval/artifacts/real/real_baseline_v1.json \
  --target-precision 0.80 \
  --min-calibration-support 30 \
  --min-test-support 30
```

The baseline is deterministic L2-regularised logistic regression over signed hashed features.
Its whitelist uses only pre-decision phase, reason, rail, currency, amount, claim text,
evidence, and tri-state structured signals. Signal timestamps/source versions are audited but
are not features. Merchant/customer/order/payment identifiers, action, resolution, recovery,
and cost fields are excluded. Only actually contested rows with mature `won` or `lost`
outcomes are training/evaluation eligible.

Threshold selection uses calibration data, never test data. The artifact includes split/code
fingerprints, exclusions, threshold selection, validation/calibration/locked-test metrics,
confidence intervals, and a `precision_claim.status`. It contains a numeric hashed weight
vector, not raw text or a recoverable vocabulary. It is still a research artifact and remains
private by default.

For the tiny fictional fixture only, lower the support requirements and opt into the
explicitly labelled smoke behavior:

```bash
python data/split_real_disputes.py \
  --input data/examples/real_disputes.sanitized.jsonl \
  --output-dir data/private/example-splits

python eval/train_real_baseline.py \
  --splits-dir data/private/example-splits \
  --output eval/artifacts/real/example_smoke.json \
  --min-calibration-support 1 \
  --min-test-support 1 \
  --allow-insufficient-test-for-smoke
```

Passing the smoke override does not make the sample claimable. It only allows a pipeline check
to finish while the artifact retains an insufficient-support status.

## Label integrity

Keep these observations distinct:

- `merchant_action=contested` plus `final_outcome=won|lost` is an observed binary contest
  result and is eligible for the current baseline.
- `merchant_action=accepted` plus `final_outcome=lost` means the merchant conceded and the
  processor recorded a loss. It does not show that a contest would have lost.
- `partial`, `closed`, and `pending` need a separately specified task or adjudication policy;
  they are excluded from the binary target.
- `expired`, `withdrawn`, and `no_action` are valuable for operations/selection-bias analysis,
  but not as fabricated win/loss labels.
- Evidence annotations describe whether an evidence item supports a claim. They require their
  own human annotation protocol and cannot be derived from the case outcome.

Historical merchant behavior causes selection bias: easy-looking cases may be contested more
often. Report the action mix and eligible exclusions for every split and do not describe this
baseline as an optimal contest/accept policy until that bias is addressed prospectively.

## Metrics and honest reporting

`CONTEST` is the positive decision. At minimum report:

- precision among predicted contests, `TP / (TP + FP)`, with the Wilson confidence interval;
- selective `recall` over automated terminal decisions only, clearly labelled so it is not
  mistaken for population recall;
- `population_auto_win_capture`, which counts deferred eligible wins in its denominator and is
  the correct measure of how many available wins automation captures;
- decision/contest coverage and the raw predicted-contest count;
- selective accuracy only when clearly named and paired with coverage;
- confusion counts, PR-AUC, Brier score, calibration error, and action/outcome exclusions;
- slices by time, merchant cohort, rail, phase, reason code, and amount where sample sizes permit.

A point estimate such as 80% from a handful of predicted contests is not an 80% precision
demonstration. For the initial study, aim for at least 300 locked-test predicted contests and
predeclare the minimum support, target, confidence level, and release rule before opening the
test result. The trainer's default minimum of 30 is only a fail-fast floor, not a universal
sample-size recommendation.

## Release gates

Keep the baseline offline until all applicable gates pass:

1. Data owner approves use, retention, and access; raw and normalized data are absent from Git.
2. Import validation passes, redaction samples receive human review, duplicate conflicts are
   resolved, and the HMAC key is controlled.
3. Every feature is demonstrably knowable at `decision_at`; leakage groups are disjoint and
   split time ranges are chronological.
4. Training and threshold choices are frozen before the locked test is evaluated. The manifest
   test SHA-256 still matches.
5. Both classes and important merchant/rail/reason slices have adequate support. Report point
   estimates, intervals, denominators, exclusions, and the exact dataset/model versions.
6. The confidence-interval lower bound meets the predeclared precision target with the required
   support. If not, report the result as inconclusive or below target—do not retune on test.
7. Run in shadow mode on a later time window, compare model recommendations with human decisions,
   monitor drift and overrides, and establish rollback/retraining triggers.
8. A human remains the final approver. Coconut must not automatically accept, contest, or submit
   a live dispute.

If a gate fails, retain the current abstaining demo behavior and use the result to decide what
data or feature family to collect next. A failed honest gate is evidence, not a reason to lower
the standard after seeing the test set.
