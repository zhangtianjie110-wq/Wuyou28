"""Summarize syntax observed across the current saved algorithm array."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from formula_parser import parse_formula


ROOT = Path(__file__).resolve().parent


def main() -> None:
    algorithms = json.loads((ROOT / "data" / "algorithms.json").read_text(encoding="utf-8"))
    parsed = [parse_formula(item["formulaText"]) for item in algorithms]
    syntax_chars = "=[]+#|"
    summary = {
        "formula_count": len(parsed),
        "parsed_successfully": len(parsed),
        "operator_presence": {
            operator: sum(operator in item["raw"] for item in parsed)
            for operator in syntax_chars
        },
        "operator_counts": {
            operator: dict(
                Counter(
                    (item["raw"].count(operator) if operator in "=[]" else item["operator_counts"].get(operator, 0))
                    for item in parsed
                )
            )
            for operator in syntax_chars
        },
        "group_count_distribution": dict(Counter(item["group_count"] for item in parsed)),
        "term_count_distribution": dict(
            Counter(",".join(map(str, item["term_counts"])) for item in parsed)
        ),
        "number_min": min(item["number_range"]["min"] for item in parsed),
        "number_max": max(item["number_range"]["max"] for item in parsed),
        "duplicate_group_formulas": sum(item["duplicate_group_count"] > 0 for item in parsed),
        "duplicate_number_formulas": sum(item["duplicate_number_count"] > 0 for item in parsed),
    }
    (ROOT / "data" / "syntax_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
