from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterator


def read_json_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


@contextmanager
def readonly_sqlite(path: Path) -> Iterator[sqlite3.Connection]:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    try:
        yield connection
    finally:
        connection.close()


def parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)


def age_seconds(value: object) -> float | None:
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())


def freshness(value: object, stale_after_seconds: int) -> dict:
    age = age_seconds(value)
    if age is None:
        return {"status": "OFFLINE", "timestamp": value, "age_seconds": None}
    return {
        "status": "FRESH" if age <= stale_after_seconds else "STALE",
        "timestamp": value,
        "age_seconds": round(age, 3),
    }
