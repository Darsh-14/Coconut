"""Small, network-free JSON/JSONL helpers shared by annotation commands."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence


class AnnotationDataError(ValueError):
    """Safe-to-display annotation pipeline failure."""


def load_json_objects(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise AnnotationDataError("input does not exist or is not a regular file")
    try:
        if path.suffix.lower() == ".jsonl":
            objects: list[Any] = []
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8-sig").splitlines(), start=1
            ):
                if not line.strip():
                    continue
                try:
                    objects.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise AnnotationDataError(
                        f"invalid JSON on line {line_number}, column {exc.colno}"
                    ) from None
        elif path.suffix.lower() == ".json":
            objects = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(objects, list):
                raise AnnotationDataError(".json input must contain one top-level array")
        else:
            raise AnnotationDataError("input extension must be .json or .jsonl")
    except AnnotationDataError:
        raise
    except json.JSONDecodeError as exc:
        raise AnnotationDataError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}"
        ) from None
    except (OSError, UnicodeError) as exc:
        raise AnnotationDataError(f"could not read input: {type(exc).__name__}") from None
    if not objects:
        raise AnnotationDataError("input contains no records")
    if not all(isinstance(value, dict) for value in objects):
        raise AnnotationDataError("every input record must be a JSON object")
    return objects


def atomic_write_objects(path: Path, values: Sequence[dict[str, Any]], *, force: bool) -> None:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        text = "".join(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for value in values
        )
    elif suffix == ".json":
        text = json.dumps(values, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    else:
        raise AnnotationDataError("output extension must be .json or .jsonl")
    atomic_write_bytes(path, text.encode("utf-8"), force=force)


def atomic_write_bytes(path: Path, payload: bytes, *, force: bool) -> None:
    if path.exists() and not force:
        raise AnnotationDataError("output already exists; pass --force to replace it")
    if path.exists() and not path.is_file():
        raise AnnotationDataError("output exists and is not a regular file")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() and not force:
            raise AnnotationDataError("output was created concurrently; refusing to replace it")
        os.replace(temporary, path)
        temporary = None
    except AnnotationDataError:
        raise
    except OSError as exc:
        raise AnnotationDataError(f"could not write output atomically: {type(exc).__name__}") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


__all__ = [
    "AnnotationDataError",
    "atomic_write_bytes",
    "atomic_write_objects",
    "load_json_objects",
]
