"""Audit historical versus v3 algorithm-list hashes without mutation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from extract_algorithms import LEVELDB_LOG, _arrays_from_log, read_current_algorithms


ROOT = Path(__file__).resolve().parent
HISTORICAL = "18c1390bdbf3d5db6e48939fc5c124f217ab04e2195db2cc60b3bff4e0e838bd"
V3 = "8ab6c0e4b07809b636bf4f7b5d3561d65ac0c3ce7469b6cad6167328558fa460"


def _hash_json(value, *, sort_keys: bool, ensure_ascii: bool, separators):
    payload = json.dumps(
        value,
        ensure_ascii=ensure_ascii,
        sort_keys=sort_keys,
        separators=separators,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest(), len(payload)


def audit() -> dict:
    rows = read_current_algorithms()
    ordered = sorted(rows, key=lambda item: item["id"])
    raw_arrays = _arrays_from_log(LEVELDB_LOG.read_bytes())
    raw_current = raw_arrays[-1]
    compact = (",", ":")
    default = None
    v3_hash, v3_bytes = _hash_json(ordered, sort_keys=False, ensure_ascii=False, separators=compact)
    historical_hash, historical_bytes = _hash_json(ordered, sort_keys=True, ensure_ascii=False, separators=compact)
    report = {
        "source": str(LEVELDB_LOG),
        "count": len(rows),
        "unique_ids": len({item["id"] for item in rows}),
        "unique_formulaText": len({item["formulaText"] for item in rows}),
        "field_order_in_current_objects": list(rows[0].keys()) if rows else [],
        "field_order_with_sort_keys": sorted(rows[0].keys()) if rows else [],
        "historical_hash": HISTORICAL,
        "v3_hash": V3,
        "historical_hash_reproduced": historical_hash,
        "v3_hash_reproduced": v3_hash,
        "historical_matches": historical_hash == HISTORICAL,
        "v3_matches": v3_hash == V3,
        "variant_hashes": {
            "preserve_keys_ascii_false_compact": {"sha256": v3_hash, "bytes": v3_bytes},
            "sort_keys_ascii_false_compact": {"sha256": historical_hash, "bytes": historical_bytes},
            "preserve_keys_ascii_true_compact": {"sha256": _hash_json(ordered, sort_keys=False, ensure_ascii=True, separators=compact)[0]},
            "sort_keys_ascii_true_compact": {"sha256": _hash_json(ordered, sort_keys=True, ensure_ascii=True, separators=compact)[0]},
            "preserve_keys_ascii_false_default_separators": {"sha256": _hash_json(ordered, sort_keys=False, ensure_ascii=False, separators=default)[0]},
            "sort_keys_ascii_false_default_separators": {"sha256": _hash_json(ordered, sort_keys=True, ensure_ascii=False, separators=default)[0]},
            "raw_leveldb_array_sort_keys_compact": {"sha256": _hash_json(sorted(raw_current, key=lambda item: item["id"]), sort_keys=True, ensure_ascii=False, separators=compact)[0]},
        },
        "unicode_effect": "none: current name and formula values are ASCII",
        "root_cause": "JSON object key ordering differs; data content, count, IDs, formulas, and ID sort order are the same",
        "recommended_canonical_rule": "sort by id, then json.dumps(sort_keys=True, ensure_ascii=False, separators=(',', ':')), then SHA-256 UTF-8",
        "leveldb_write": False,
    }
    return report


def main() -> None:
    report = audit()
    (ROOT / "data" / "v3_hash_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: report[key] for key in ("count", "unique_ids", "unique_formulaText", "historical_hash_reproduced", "v3_hash_reproduced", "root_cause")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
