"""Interactively create a reviewer reference without persisting the raw identity."""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.real_annotations import pseudonymize_reviewer  # noqa: E402
from data.import_real_disputes import HMAC_ENV_VAR, MIN_HMAC_KEY_BYTES  # noqa: E402


def main() -> int:
    raw_key = os.environ.get(HMAC_ENV_VAR)
    if raw_key is None or len(raw_key.encode("utf-8")) < MIN_HMAC_KEY_BYTES:
        print(
            f"{HMAC_ENV_VAR} must be set to at least {MIN_HMAC_KEY_BYTES} UTF-8 bytes.",
            file=sys.stderr,
        )
        return 2
    identity = getpass.getpass("Reviewer identity (used in memory only): ")
    try:
        reviewer_ref = pseudonymize_reviewer(raw_key.encode("utf-8"), identity)
    except ValueError as exc:
        print(f"Could not create reviewer ref: {exc}", file=sys.stderr)
        return 2
    print(reviewer_ref)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
