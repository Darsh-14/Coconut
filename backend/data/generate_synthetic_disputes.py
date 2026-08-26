"""Generate the synthetic dispute dataset and write the 70/30 train/held-out split.

CLAUDE.md Section 9 specifies that Claude generates these records. There are two supported
transports for that, and both feed the *same* validation, normalisation and splitting
pipeline so the output is identical in shape:

  --source api       Calls the Anthropic API in batches, using Section 9's exact prompt.
                     Requires ANTHROPIC_API_KEY.

  --source curated   Loads Claude-authored batches from data/curated_batches/*.json.
                     These were written by Claude directly in an authoring session rather
                     than over the API. Same author, same spec, no API key required --
                     and since Section 5 commits synthetic_disputes.json as output, a
                     person cloning this repo never needs to regenerate it at all.

Usage:
    python data/generate_synthetic_disputes.py --source curated
    python data/generate_synthetic_disputes.py --source api --n 260

Section 9 requires that no field hints at the evidence-quality bucket beyond
ground_truth_label itself, so no bucket marker is ever persisted; the proportions are
controlled at authoring time and verified here by label distribution.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

# Make `app` importable when this script is run from backend/ or from data/.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.schemas import KNOWN_REASON_CODES, Dispute  # noqa: E402

DATA_DIR = BACKEND_ROOT / "data"
CURATED_DIR = DATA_DIR / "curated_batches"
WORKING_SET_PATH = DATA_DIR / "synthetic_disputes.json"
HELD_OUT_PATH = BACKEND_ROOT / "eval" / "held_out_set.json"

# Fixed seed: the split must be reproducible for anyone who reruns this.
SPLIT_SEED = 20260826
TRAIN_FRACTION = 0.70

# Placeholder until Phase 2 backfills real test-mode Razorpay payment ids.
# Deliberately un-mistakable for a real id (real ones look like `pay_XXXXXXXXXXXXXXXX`).
PENDING_PAYMENT_PREFIX = "pay_PENDING_"

# Response windows are phase-dependent in the real card networks; these are realistic.
RESPOND_WINDOW_DAYS: dict[str, int] = {
    "retrieval": 12,
    "fraud": 18,
    "chargeback": 21,
    "pre_arbitration": 14,
    "arbitration": 10,
}

ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"


# --- Section 9's prompt (verbatim structure) --------------------------------------------

SYSTEM_PROMPT = (
    "You generate synthetic e-commerce chargeback dispute records for an ML training and "
    "evaluation dataset. Output ONLY a valid JSON array, no prose, no markdown code fences."
)

RECORD_SCHEMA_EXAMPLE = """{
  "phase": "chargeback",
  "reason_code": "goods_not_received",
  "claim_text": "Cardholder asserts the merchandise was never delivered to the billing address on file.",
  "amount": 249900,
  "currency": "INR",
  "evidence_bundle": [
    {"type": "delivery_proof", "content": "...", "source_ref": "..."},
    {"type": "communication_log", "content": "...", "source_ref": null}
  ],
  "ground_truth_label": "contest_win"
}"""


def build_user_prompt(n: int) -> str:
    return f"""Generate {n} synthetic dispute records. Each record must match this schema exactly:
{RECORD_SCHEMA_EXAMPLE}

Field constraints:
- "type" of each evidence item is one of: delivery_proof, communication_log, device_signal, order_history, other
- "phase" is one of: fraud, retrieval, chargeback, pre_arbitration, arbitration
- "ground_truth_label" is one of: contest_win, contest_loss, should_accept
- "amount" is an integer in paise
- each record has 1-4 evidence items

Vary the records along these axes:
- phase: mostly "chargeback", some "fraud" and "retrieval"
- reason_code: rotate through {", ".join(KNOWN_REASON_CODES)}
- evidence quality, in roughly these proportions:
  - ~40% of records: evidence that clearly and specifically supports the merchant
    (ground_truth_label = "contest_win")
  - ~35% of records: evidence that is weak, missing key details, or actually contradicts the
    merchant's position (ground_truth_label = "contest_loss" or "should_accept")
  - ~25% of records: evidence that is present and plausible-sounding but genuinely does not
    resolve the claim either way -- this bucket must NOT be an easier version of the other two,
    it must be authentically ambiguous, because this is the bucket that should end up
    correctly routed to human review later
- amount: realistic range, Rs 299 to Rs 45,000, expressed in paise
- claim_text: written like a bank's dispute reason summary, not a customer's own words

Do not include any field that hints at the bucket beyond ground_truth_label itself -- the
verification engine will only ever see claim_text and evidence_bundle."""


# --- sources -----------------------------------------------------------------------------


def load_curated() -> list[dict[str, Any]]:
    """Load Claude-authored batch files from data/curated_batches/."""
    if not CURATED_DIR.is_dir():
        raise SystemExit(f"No curated batches found at {CURATED_DIR}")

    batch_files = sorted(CURATED_DIR.glob("batch_*.json"))
    if not batch_files:
        raise SystemExit(f"No batch_*.json files in {CURATED_DIR}")

    records: list[dict[str, Any]] = []
    for path in batch_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path.name} is not valid JSON: {exc}") from exc
        if not isinstance(payload, list):
            raise SystemExit(f"{path.name} must contain a JSON array")
        print(f"  loaded {len(payload):>3} records from {path.name}")
        records.extend(payload)
    return records


def generate_via_api(n_total: int, batch_size: int) -> list[dict[str, Any]]:
    """Call the Anthropic API in batches, per Section 9."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("The `anthropic` package is required for --source api") from exc

    from app.config import get_settings

    settings = get_settings()
    if not settings.anthropic_configured:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Either set it, or use --source curated, "
            "which needs no API key."
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    records: list[dict[str, Any]] = []
    remaining = n_total

    while remaining > 0:
        n = min(batch_size, remaining)
        print(f"  requesting {n} records from {ANTHROPIC_MODEL} ...")
        message = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_prompt(n)}],
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        batch = _parse_json_array(text)
        print(f"    -> parsed {len(batch)} records")
        records.extend(batch)
        remaining -= len(batch) if batch else n

    return records


def _parse_json_array(text: str) -> list[dict[str, Any]]:
    """Parse a JSON array, tolerating stray code fences the model may emit anyway."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1:
        print("    !! no JSON array found in response; skipping batch", file=sys.stderr)
        return []
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        print(f"    !! batch failed to parse ({exc}); skipping", file=sys.stderr)
        return []
    return parsed if isinstance(parsed, list) else []


# --- normalisation + validation ----------------------------------------------------------


def normalise(raw: Iterable[dict[str, Any]], reference: datetime) -> list[Dispute]:
    """Assign mechanical fields, validate against the Section 6 schema, drop bad records.

    Authored/generated records carry only the decision-relevant fields (phase, reason_code,
    claim_text, amount, evidence_bundle, ground_truth_label). Identifiers and timestamps are
    assigned here so they are deterministic and so the queue always shows live countdowns.
    """
    rng = random.Random(SPLIT_SEED)
    validated: list[Dispute] = []
    seen_claims: set[str] = set()
    rejected = 0

    for raw_record in raw:
        if not isinstance(raw_record, dict):
            rejected += 1
            continue

        record = dict(raw_record)  # never mutate the caller's dict

        # Drop exact duplicate claims -- the API path occasionally repeats across batches.
        claim_key = (record.get("claim_text") or "").strip().lower()
        if not claim_key or claim_key in seen_claims:
            rejected += 1
            continue
        seen_claims.add(claim_key)

        index = len(validated) + 1
        record["dispute_id"] = f"disp_synthetic_{index:04d}"
        record.setdefault("currency", "INR")
        # Phase 2 backfills a subset of these with real test-mode payment ids.
        record["payment_id"] = f"{PENDING_PAYMENT_PREFIX}{index:04d}"

        # Spread raised_at over the recent past so the queue has a realistic mix of
        # urgency, including some inside Section 12's red-alert 48h window.
        phase = record.get("phase", "chargeback")
        window_days = RESPOND_WINDOW_DAYS.get(phase, 21)
        age_days = rng.uniform(0.5, window_days - 0.5)
        raised_at = reference - timedelta(days=age_days)
        record["raised_at"] = raised_at.isoformat()
        record["respond_by"] = (raised_at + timedelta(days=window_days)).isoformat()

        try:
            validated.append(Dispute.model_validate(record))
        except Exception as exc:  # pydantic ValidationError and friends
            rejected += 1
            print(f"    !! rejected record {index}: {exc}", file=sys.stderr)

    if rejected:
        print(f"  rejected {rejected} invalid/duplicate record(s)")
    return validated


def stratified_split(
    records: list[Dispute], train_fraction: float = TRAIN_FRACTION
) -> tuple[list[Dispute], list[Dispute]]:
    """Split 70/30, stratified by ground_truth_label.

    Stratifying rather than splitting purely at random: an unstratified 30% sample of ~260
    records can skew the held-out label balance by several points, which would move the
    reported precision/recall for reasons that have nothing to do with model quality.
    """
    rng = random.Random(SPLIT_SEED)
    by_label: dict[str, list[Dispute]] = defaultdict(list)
    for record in records:
        by_label[record.ground_truth_label or "unlabelled"].append(record)

    train: list[Dispute] = []
    held_out: list[Dispute] = []
    for label in sorted(by_label):
        bucket = by_label[label][:]
        rng.shuffle(bucket)
        cut = round(len(bucket) * train_fraction)
        train.extend(bucket[:cut])
        held_out.extend(bucket[cut:])

    rng.shuffle(train)
    rng.shuffle(held_out)
    return train, held_out


# --- reporting ---------------------------------------------------------------------------


def describe(name: str, records: list[Dispute]) -> None:
    if not records:
        print(f"\n{name}: EMPTY")
        return
    total = len(records)
    labels = Counter(r.ground_truth_label or "unlabelled" for r in records)
    phases = Counter(r.phase for r in records)
    reasons = Counter(r.reason_code for r in records)

    print(f"\n{name}: {total} records")
    print("  ground_truth_label:")
    for label, count in labels.most_common():
        print(f"    {label:<16} {count:>4}  ({count / total:>6.1%})")
    print("  phase:            " + ", ".join(f"{k}={v}" for k, v in phases.most_common()))
    print("  reason_code:      " + ", ".join(f"{k}={v}" for k, v in reasons.most_common()))
    amounts = [r.amount for r in records]
    print(f"  amount (INR):     min={min(amounts) / 100:,.0f}  max={max(amounts) / 100:,.0f}")
    ev_counts = [len(r.evidence_bundle) for r in records]
    print(f"  evidence/record:  min={min(ev_counts)}  max={max(ev_counts)}  "
          f"mean={sum(ev_counts) / total:.1f}")


def write_json(path: Path, records: list[Dispute]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [json.loads(r.model_dump_json()) for r in records]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  wrote {len(records):>4} records -> {path.relative_to(BACKEND_ROOT)}")


# --- entrypoint --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--source",
        choices=("curated", "api"),
        default="curated",
        help="Where records come from (default: curated, needs no API key).",
    )
    parser.add_argument("--n", type=int, default=260, help="Target record count for --source api.")
    parser.add_argument("--batch-size", type=int, default=30, help="Records per API call (25-40).")
    args = parser.parse_args()

    print(f"Recourse synthetic dispute generation (source={args.source})")

    if args.source == "api":
        raw = generate_via_api(args.n, args.batch_size)
    else:
        raw = load_curated()

    print(f"\nnormalising + validating {len(raw)} raw records ...")
    reference = datetime.now(timezone.utc)
    records = normalise(raw, reference)

    if not records:
        print("No valid records produced.", file=sys.stderr)
        return 1

    describe("FULL SET", records)

    train, held_out = stratified_split(records)
    describe("WORKING SET (synthetic_disputes.json)", train)
    describe("HELD-OUT SET (eval/held_out_set.json)", held_out)

    print("\nwriting ...")
    write_json(WORKING_SET_PATH, train)
    write_json(HELD_OUT_PATH, held_out)

    print(
        "\nDone. The held-out set must not be inspected or tuned against until /evaluate "
        "is run (CLAUDE.md Section 9)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
