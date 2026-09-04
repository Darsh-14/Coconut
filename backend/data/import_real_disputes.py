"""Import already-exported historical disputes into a privacy-safe offline dataset.

No network client is imported or called here.  Raw identifiers are replaced with keyed HMAC
pseudonyms, obvious PII is removed from free text, and terminal outcome is kept separate from
the merchant's observed action.  The HMAC key is accepted *only* through the
``COCONUT_DATA_HMAC_KEY`` environment variable so it cannot leak via shell history.

Run from ``backend/``::

    python data/import_real_disputes.py --input private/export.jsonl \
        --output private/normalized.jsonl

CSV input stores its evidence list as JSON in an ``evidence_json`` column.  ``.json`` input
must contain an array; ``.jsonl`` contains one object per nonblank line.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.real_data import (  # noqa: E402
    AnnotationProvenance,
    EvidenceAdjudication,
    FinalOutcome,
    MerchantAction,
    RFC3339_PATTERN,
    RealDisputePhase,
    RealDisputeRecord,
    RealEvidenceType,
    RealPaymentRail,
    SourceKind,
    sensitive_text_kind,
)
from app.models.real_features import RealStructuredSignals  # noqa: E402

HMAC_ENV_VAR = "COCONUT_DATA_HMAC_KEY"
MIN_HMAC_KEY_BYTES = 32


class ImportPipelineError(ValueError):
    """A safe-to-display import failure (messages never contain source field values)."""


class UnsafeInputError(ImportPipelineError):
    """The input contains a credential/payment field that must not enter this pipeline."""


@dataclass(frozen=True)
class ImportResult:
    input_count: int
    output_count: int
    duplicate_count: int
    output_sha256: str
    output_path: Path


class _RawEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: RealEvidenceType
    content: str = Field(min_length=1, max_length=50_000)
    source_id: str | None = Field(default=None, min_length=1, max_length=1_024)
    adjudicated_label: EvidenceAdjudication | None = None
    annotation_provenance: AnnotationProvenance | None = None
    annotation_version: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )


class _RawRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_kind: SourceKind
    merchant_id: str = Field(min_length=1, max_length=1_024)
    dispute_id: str = Field(min_length=1, max_length=1_024)
    leakage_group_id: str | None = Field(default=None, min_length=1, max_length=1_024)
    payment_id: str | None = Field(default=None, min_length=1, max_length=1_024)
    order_id: str | None = Field(default=None, min_length=1, max_length=1_024)
    customer_id: str | None = Field(default=None, min_length=1, max_length=1_024)

    created_at: datetime
    decision_at: datetime
    respond_by: datetime | None = None
    resolved_at: datetime | None = None
    phase: RealDisputePhase
    reason_code: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    rail: RealPaymentRail
    amount: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    claim_text: str = Field(min_length=1, max_length=20_000)
    evidence: tuple[_RawEvidence, ...]
    structured_signals: RealStructuredSignals | None = None
    merchant_action: MerchantAction
    final_outcome: FinalOutcome
    evidence_submitted: bool
    recovered_amount: int | None = Field(default=None, ge=0)
    representment_cost: int | None = Field(default=None, ge=0)

    @field_validator("created_at", "decision_at", "respond_by", "resolved_at", mode="before")
    @classmethod
    def timestamps_must_be_rfc3339_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str) or not RFC3339_PATTERN.fullmatch(value):
            raise ValueError("timestamps must be RFC3339 strings with an explicit timezone")
        return value

    @field_validator("evidence_submitted", mode="before")
    @classmethod
    def parse_unambiguous_boolean(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        # CSV cannot carry a native boolean.  Only these two exact spellings are mapped;
        # values such as 0/1, yes/no, or an empty cell fail closed.
        if value == "true":
            return True
        if value == "false":
            return False
        raise ValueError("evidence_submitted must be true or false")

    @field_validator("amount", "recovered_amount", "representment_cost", mode="before")
    @classmethod
    def integer_minor_units_only(cls, value: Any) -> Any:
        # CSV has strings; JSON floats and booleans are rejected rather than silently rounded.
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("monetary values must be integers in minor currency units")
        if isinstance(value, str):
            if not re.fullmatch(r"[+-]?\d+", value.strip()):
                raise ValueError("monetary values must be integers in minor currency units")
            return int(value)
        if not isinstance(value, int):
            raise ValueError("monetary values must be integers in minor currency units")
        return value

    @field_validator("structured_signals", mode="before")
    @classmethod
    def structured_signal_timestamp_must_be_rfc3339(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("structured_signals must be an object")
        if not isinstance(value.get("observed_at"), str):
            raise ValueError("structured_signals.observed_at must be an RFC 3339 string")
        return value


# Key names are normalized to lowercase snake_case before comparison.  Raw primary IDs are
# allowed by the explicit schema above because they are HMACed; direct payment credentials,
# authentication material, and bank/card account data are rejected at every nesting level.
_FORBIDDEN_KEYS = frozenset(
    {
        "access_token",
        "account_number",
        "api_key",
        "api_secret",
        "authorization",
        "bank_account",
        "bank_account_number",
        "card_expiry",
        "card_number",
        "cookie",
        "cvc",
        "cvv",
        "cvv2",
        "expiry",
        "expiry_date",
        "full_card_number",
        "key_secret",
        "magnetic_stripe",
        "pan",
        "passphrase",
        "passwd",
        "password",
        "pin",
        "private_key",
        "refresh_token",
        "secret",
        "security_code",
        "set_cookie",
        "token",
        "track1",
        "track2",
    }
)
_SECRET_VALUE = re.compile(
    r"(?i)(?:rzp_(?:live|test)_[a-z0-9]+|sk_(?:live|test)_[a-z0-9]+|"
    r"sk-ant-[a-z0-9_-]+|bearer\s+[a-z0-9._~+/=-]{12,}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)

_EMAIL = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+")
_UPI = re.compile(r"(?i)(?<![\w.-])[a-z0-9][a-z0-9._-]{1,255}@[a-z]{2,64}(?![\w.-])")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s.-]?)?[6-9]\d{4}[\s.-]?\d{5}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_IP = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_PROCESSOR_REF = re.compile(
    r"(?i)\b(?:pay|disp|dp|order|ord|rfnd|refund|cust|inv|setl|trf)_[a-z0-9]{6,}\b"
)


def _normalise_key_name(value: str) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", value)
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _reject_unsafe_values(value: Any, path: str = "record") -> None:
    """Recursively reject dangerous keys/credentials without echoing their values."""

    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise UnsafeInputError(f"{path}: object keys must be strings")
            normalized = _normalise_key_name(key)
            if (
                normalized in _FORBIDDEN_KEYS
                or normalized.endswith("_token")
                or normalized.endswith("_password")
                or normalized.endswith("_secret")
            ):
                raise UnsafeInputError(
                    f"{path}.{key}: forbidden credential/payment-security field"
                )
            _reject_unsafe_values(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_unsafe_values(child, f"{path}[{index}]")
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise UnsafeInputError(f"{path}: credential-like value detected")


def _safe_validation_message(locator: str, exc: ValidationError) -> ImportPipelineError:
    messages: list[str] = []
    for error in exc.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in error.get("loc", ())) or "record"
        messages.append(f"{location}: {error['msg']}")
    return ImportPipelineError(f"{locator}: invalid record ({'; '.join(messages)})")


def _load_json(path: Path) -> list[tuple[str, dict[str, Any]]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError) as exc:
        raise ImportPipelineError(f"could not read input file: {type(exc).__name__}") from None
    except json.JSONDecodeError as exc:
        raise ImportPipelineError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}"
        ) from None
    if not isinstance(value, list):
        raise ImportPipelineError(".json input must contain one top-level array")
    result: list[tuple[str, dict[str, Any]]] = []
    for index, row in enumerate(value, start=1):
        if not isinstance(row, dict):
            raise ImportPipelineError(f"record {index}: expected a JSON object")
        result.append((f"record {index}", row))
    return result


def _load_jsonl(path: Path) -> list[tuple[str, dict[str, Any]]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ImportPipelineError(f"could not read input file: {type(exc).__name__}") from None
    result: list[tuple[str, dict[str, Any]]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ImportPipelineError(
                f"line {line_number}: invalid JSON at column {exc.colno}"
            ) from None
        if not isinstance(row, dict):
            raise ImportPipelineError(f"line {line_number}: expected a JSON object")
        result.append((f"line {line_number}", row))
    return result


def _load_csv(path: Path) -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ImportPipelineError("CSV input has no header row")
            if "evidence_json" not in reader.fieldnames:
                raise ImportPipelineError("CSV input requires an evidence_json column")
            for line_number, csv_row in enumerate(reader, start=2):
                if None in csv_row:
                    raise ImportPipelineError(
                        f"line {line_number}: row has more cells than the header"
                    )
                row: dict[str, Any] = {
                    key: (None if value is None or not value.strip() else value.strip())
                    for key, value in csv_row.items()
                }
                encoded_evidence = row.pop("evidence_json", None)
                if encoded_evidence is None:
                    row["evidence"] = []
                else:
                    try:
                        evidence = json.loads(encoded_evidence)
                    except json.JSONDecodeError as exc:
                        raise ImportPipelineError(
                            f"line {line_number}: evidence_json is invalid JSON at column {exc.colno}"
                        ) from None
                    if not isinstance(evidence, list):
                        raise ImportPipelineError(
                            f"line {line_number}: evidence_json must contain an array"
                        )
                    row["evidence"] = evidence
                encoded_signals = row.pop("structured_signals_json", None)
                if encoded_signals is not None:
                    try:
                        signals = json.loads(encoded_signals)
                    except json.JSONDecodeError as exc:
                        raise ImportPipelineError(
                            f"line {line_number}: structured_signals_json is invalid JSON "
                            f"at column {exc.colno}"
                        ) from None
                    if not isinstance(signals, dict):
                        raise ImportPipelineError(
                            f"line {line_number}: structured_signals_json must contain an object"
                        )
                    row["structured_signals"] = signals
                result.append((f"line {line_number}", row))
    except ImportPipelineError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ImportPipelineError(f"could not read CSV input: {type(exc).__name__}") from None
    return result


def load_raw_records(path: Path) -> list[tuple[str, dict[str, Any]]]:
    if not path.is_file():
        raise ImportPipelineError("input path does not exist or is not a regular file")
    suffix = path.suffix.lower()
    if suffix == ".json":
        rows = _load_json(path)
    elif suffix == ".jsonl":
        rows = _load_jsonl(path)
    elif suffix == ".csv":
        rows = _load_csv(path)
    else:
        raise ImportPipelineError("input extension must be .json, .jsonl, or .csv")
    if not rows:
        raise ImportPipelineError("input contains no records")
    return rows


def _load_hmac_key() -> bytes:
    raw = os.environ.get(HMAC_ENV_VAR)
    if raw is None:
        raise ImportPipelineError(
            f"{HMAC_ENV_VAR} is required; set it in the process environment, never a CLI argument"
        )
    key = raw.encode("utf-8")
    if len(key) < MIN_HMAC_KEY_BYTES:
        raise ImportPipelineError(
            f"{HMAC_ENV_VAR} must contain at least {MIN_HMAC_KEY_BYTES} UTF-8 bytes"
        )
    return key


def _canonical_identifier(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _pseudonym(key: bytes, namespace: str, value: str, *, scope: str = "") -> str:
    payload = json.dumps(
        ["coconut-real-data-v1", namespace, _canonical_identifier(scope), _canonical_identifier(value)],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hmac.new(key, payload, hashlib.sha256).hexdigest()[:24]
    return f"coc_v1_{digest}"


def redact_text(value: str, raw_identifiers: Iterable[str] = ()) -> str:
    """Redact obvious identifiers/PII; callers must still conduct a human privacy review."""

    redacted = value
    # Exact source IDs are tokens in many support transcripts.  Boundary matching avoids a
    # short ID changing an unrelated word, while still removing punctuation-heavy IDs.
    for raw_id in sorted(set(raw_identifiers), key=len, reverse=True):
        raw_id = raw_id.strip()
        if not raw_id:
            continue
        redacted = re.sub(
            rf"(?<!\w){re.escape(raw_id)}(?!\w)",
            "[REDACTED_REFERENCE]",
            redacted,
        )
    redacted = _EMAIL.sub("[REDACTED_EMAIL]", redacted)
    redacted = _UPI.sub("[REDACTED_UPI]", redacted)
    redacted = _PHONE.sub("[REDACTED_PHONE]", redacted)
    redacted = _CARD.sub("[REDACTED_CARD]", redacted)
    redacted = _IP.sub("[REDACTED_IP]", redacted)
    redacted = _PROCESSOR_REF.sub("[REDACTED_REFERENCE]", redacted)
    return redacted


def _normalise_record(raw_value: dict[str, Any], locator: str, key: bytes) -> RealDisputeRecord:
    _reject_unsafe_values(raw_value, locator)
    try:
        raw = _RawRecord.model_validate(raw_value)
    except ValidationError as exc:
        raise _safe_validation_message(locator, exc) from None

    merchant_scope = raw.merchant_id
    group_kind: str
    group_value: str
    if raw.leakage_group_id:
        group_kind, group_value = "explicit", raw.leakage_group_id
    elif raw.order_id:
        group_kind, group_value = "order", raw.order_id
    elif raw.payment_id:
        group_kind, group_value = "payment", raw.payment_id
    elif raw.customer_id:
        group_kind, group_value = "customer", raw.customer_id
    else:
        group_kind, group_value = "dispute", raw.dispute_id

    all_raw_ids = {
        value
        for value in (
            raw.merchant_id,
            raw.dispute_id,
            raw.leakage_group_id,
            raw.payment_id,
            raw.order_id,
            raw.customer_id,
            *(item.source_id for item in raw.evidence),
        )
        if value
    }
    evidence = tuple(
        {
            "type": item.type,
            "content_redacted": redact_text(item.content, all_raw_ids),
            "source_ref": (
                _pseudonym(
                    key,
                    "evidence_source",
                    item.source_id,
                    scope=f"{merchant_scope}\x00{raw.dispute_id}",
                )
                if item.source_id
                else None
            ),
            "adjudicated_label": item.adjudicated_label,
            "annotation_provenance": item.annotation_provenance,
            "annotation_version": item.annotation_version,
        }
        for item in raw.evidence
    )

    def rfc3339(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat().replace("+00:00", "Z")

    normalized = {
        "source_kind": raw.source_kind,
        "merchant_ref": _pseudonym(key, "merchant", raw.merchant_id),
        "dispute_ref": _pseudonym(key, "dispute", raw.dispute_id, scope=merchant_scope),
        "leakage_group_ref": _pseudonym(
            key, f"leakage_group:{group_kind}", group_value, scope=merchant_scope
        ),
        "payment_ref": (
            _pseudonym(key, "payment", raw.payment_id, scope=merchant_scope)
            if raw.payment_id
            else None
        ),
        "order_ref": (
            _pseudonym(key, "order", raw.order_id, scope=merchant_scope)
            if raw.order_id
            else None
        ),
        "customer_ref": (
            _pseudonym(key, "customer", raw.customer_id, scope=merchant_scope)
            if raw.customer_id
            else None
        ),
        "created_at": rfc3339(raw.created_at),
        "decision_at": rfc3339(raw.decision_at),
        "respond_by": rfc3339(raw.respond_by),
        "resolved_at": rfc3339(raw.resolved_at),
        "phase": raw.phase,
        "reason_code": raw.reason_code,
        "rail": raw.rail,
        "amount": raw.amount,
        "currency": raw.currency.upper(),
        "claim_text_redacted": redact_text(raw.claim_text, all_raw_ids),
        "evidence": evidence,
        "structured_signals": (
            raw.structured_signals.model_dump(mode="json")
            if raw.structured_signals is not None
            else None
        ),
        "merchant_action": raw.merchant_action,
        "final_outcome": raw.final_outcome,
        "evidence_submitted": raw.evidence_submitted,
        "recovered_amount": raw.recovered_amount,
        "representment_cost": raw.representment_cost,
    }
    try:
        return RealDisputeRecord.model_validate(normalized)
    except ValidationError as exc:
        raise _safe_validation_message(locator, exc) from None


def normalize_records(
    rows: Iterable[tuple[str, dict[str, Any]]], key: bytes
) -> tuple[list[RealDisputeRecord], int]:
    """Normalize, deduplicate exact repeats, and reject conflicting duplicate IDs."""

    by_identity: dict[tuple[str, str], tuple[RealDisputeRecord, str]] = {}
    duplicate_count = 0
    for locator, raw in rows:
        record = _normalise_record(raw, locator, key)
        identity = (record.merchant_ref, record.dispute_ref)
        previous = by_identity.get(identity)
        if previous is None:
            by_identity[identity] = (record, locator)
        elif previous[0] == record:
            duplicate_count += 1
        else:
            raise ImportPipelineError(
                f"{locator}: conflicts with duplicate dispute identity first seen at {previous[1]}"
            )
    records = [pair[0] for pair in by_identity.values()]
    records.sort(key=lambda item: (item.decision_at, item.merchant_ref, item.dispute_ref))
    return records, duplicate_count


def _serialize(records: Sequence[RealDisputeRecord], suffix: str) -> bytes:
    objects = [record.model_dump(mode="json") for record in records]
    if suffix == ".jsonl":
        text = "".join(
            json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for obj in objects
        )
    elif suffix == ".json":
        text = json.dumps(objects, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    else:
        raise ImportPipelineError("output extension must be .json or .jsonl")
    return text.encode("utf-8")


def _atomic_write(path: Path, payload: bytes, *, force: bool) -> None:
    if path.exists() and not force:
        raise ImportPipelineError("output already exists; pass --force to replace it")
    if path.exists() and not path.is_file():
        raise ImportPipelineError("output path exists and is not a regular file")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temp_path.chmod(0o600)
        except OSError:
            pass
        # Check again after the temp write to narrow the no-force race window.
        if path.exists() and not force:
            raise ImportPipelineError("output was created concurrently; refusing to replace it")
        os.replace(temp_path, path)
        temp_path = None
    except ImportPipelineError:
        raise
    except OSError as exc:
        raise ImportPipelineError(f"could not write output atomically: {type(exc).__name__}") from None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def import_file(input_path: Path, output_path: Path, *, force: bool = False) -> ImportResult:
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    if input_path == output_path:
        raise ImportPipelineError("input and output paths must be different")
    key = _load_hmac_key()
    rows = load_raw_records(input_path)
    records, duplicate_count = normalize_records(rows, key)
    payload = _serialize(records, output_path.suffix.lower())
    _atomic_write(output_path, payload, force=force)
    return ImportResult(
        input_count=len(rows),
        output_count=len(records),
        duplicate_count=duplicate_count,
        output_sha256=hashlib.sha256(payload).hexdigest(),
        output_path=output_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize a local historical dispute export without any network access."
    )
    parser.add_argument("--input", required=True, type=Path, help="Source .json, .jsonl, or .csv")
    parser.add_argument("--output", required=True, type=Path, help="Derived .json or .jsonl")
    parser.add_argument(
        "--force", action="store_true", help="Atomically replace an existing output file"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = import_file(args.input, args.output, force=args.force)
    except ImportPipelineError as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"Imported {result.output_count}/{result.input_count} records "
        f"({result.duplicate_count} exact duplicates removed)."
    )
    print(f"Output SHA-256: {result.output_sha256}")
    print(f"Wrote: {result.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
