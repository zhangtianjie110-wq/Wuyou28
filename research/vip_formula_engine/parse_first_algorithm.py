"""Persist the syntax AST for the first current saved algorithm."""

import json
from pathlib import Path

from extract_algorithms import read_current_algorithms
from formula_parser import parse_formula


ROOT = Path(__file__).resolve().parent


def main() -> None:
    algorithms = read_current_algorithms()
    first = algorithms[0]
    result = {
        "algorithm_id": first["id"],
        "name": first["name"],
        "formulaText": first["formulaText"],
        "createdAt": first["createdAt"],
        "parsed_formula": parse_formula(first["formulaText"]),
    }
    (ROOT / "data" / "first_algorithm.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
