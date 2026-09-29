"""Read the current saved VIP algorithm array from the LevelDB log.

Only the literal ``jnd28:vip-saved-algorithms`` key is inspected.  This script
does not enumerate or process auth, token, cookie, or other WebView keys.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


LEVELDB_LOG = Path(
    r"C:\Users\Administrator\AppData\Local\com.le28.yuce\EBWebView\Default\Local Storage\leveldb\000010.log"
)
KEY = b"jnd28:vip-saved-algorithms"
OUTPUT = Path(__file__).resolve().parent / "data"


def _arrays_from_log(raw: bytes) -> list[list[dict[str, Any]]]:
    arrays: list[list[dict[str, Any]]] = []
    offset = 0
    while True:
        pos = raw.find(KEY, offset)
        if pos < 0:
            break
        start = raw.find(b"[{\"id\"", pos + len(KEY))
        if start >= 0:
            end = _json_array_end(raw, start)
            if end is not None:
                try:
                    value = json.loads(raw[start:end].decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    value = None
                if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                    arrays.append(value)
        offset = pos + len(KEY)
    return arrays


def _json_array_end(raw: bytes, start: int) -> int | None:
    """Find the end of one JSON array before LevelDB's binary tail."""

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(raw)):
        byte = raw[index]
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # quote
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte == 0x5B:  # [
            depth += 1
        elif byte == 0x5D:  # ]
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def read_current_algorithms() -> list[dict[str, Any]]:
    arrays = _arrays_from_log(LEVELDB_LOG.read_bytes())
    if not arrays:
        raise RuntimeError("saved algorithm array was not found")
    # The last write in the current log is the current browser state.
    current = arrays[-1]
    result = []
    for item in current:
        result.append(
            {
                "id": item["id"],
                "name": item.get("name", ""),
                "formulaText": item["formulaText"],
                "createdAt": item.get("createdAt"),
            }
        )
    return result


def main() -> None:
    algorithms = read_current_algorithms()
    raw_json = json.dumps(algorithms, ensure_ascii=False, separators=(",", ":"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "algorithms.json").write_text(raw_json + "\n", encoding="utf-8")
    summary = {
        "count": len(algorithms),
        "unique_ids": len({item["id"] for item in algorithms}),
        "unique_formulaText": len({item["formulaText"] for item in algorithms}),
        "name_counts": {name: sum(item["name"] == name for item in algorithms) for name in sorted({item["name"] for item in algorithms})},
        "sha256_current_order": hashlib.sha256(raw_json.encode("utf-8")).hexdigest(),
        "sha256_id_order": hashlib.sha256(json.dumps(sorted(algorithms, key=lambda item: item["id"]), ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "source": str(LEVELDB_LOG),
        "key": KEY.decode("ascii"),
    }
    (OUTPUT / "algorithm_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
