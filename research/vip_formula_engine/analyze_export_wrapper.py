"""Check whether 11= and # occur in persisted saved-algorithm data."""

from __future__ import annotations

import json
from pathlib import Path

from extract_algorithms import LEVELDB_LOG, read_current_algorithms


ROOT = Path(__file__).resolve().parent


def main() -> None:
    algorithms = read_current_algorithms()
    formulas = [item["formulaText"] for item in algorithms]
    raw = LEVELDB_LOG.read_bytes()
    export_root = Path(__file__).resolve().parents[2] / "exports"
    known_export_files = [str(path) for path in export_root.rglob("*") if path.is_file()] if export_root.exists() else []
    result = {
        "persisted_key": "jnd28:vip-saved-algorithms",
        "algorithm_count": len(algorithms),
        "formula_contains_11_equal": any("11=" in formula for formula in formulas),
        "formula_contains_hash": any("#" in formula for formula in formulas),
        "raw_key_value_contains_11_equal_near_saved_array": b"11=" in raw,
        "raw_key_value_contains_hash_near_saved_array": b"#" in raw,
        "persisted_fields": sorted(algorithms[0].keys()) if algorithms else [],
        "all_name_fields_are_11": bool(algorithms) and all(item.get("name") == "11" for item in algorithms),
        "known_export_files": known_export_files,
        "conclusion": "unverified as an export wrapper; current persisted JSON provides no direct evidence for 11= or #",
        "do_not_infer": True,
    }
    (ROOT / "data" / "v2_export_wrapper_analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
