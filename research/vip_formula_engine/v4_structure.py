"""Read-only structural distance analysis for all current saved formulas."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from extract_algorithms import read_current_algorithms
from formula_parser import parse_formula


ROOT = Path(__file__).resolve().parent


def _numbers(parsed: dict[str, Any]) -> list[int]:
    return [int(value) for value in parsed["numbers"]]


def _diffs(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, int]]:
    result = []
    left_groups = left["groups"]
    right_groups = right["groups"]
    for group_index, (left_group, right_group) in enumerate(zip(left_groups, right_groups), start=1):
        for term_index, (left_term, right_term) in enumerate(zip(left_group["terms"], right_group["terms"]), start=1):
            if left_term.get("value") != right_term.get("value"):
                result.append({"group": group_index, "position": term_index, "left": left_term["value"], "right": right_term["value"]})
    return result


def _pair(left_item: dict, right_item: dict, left_ast: dict, right_ast: dict) -> dict[str, Any]:
    left_numbers = _numbers(left_ast)
    right_numbers = _numbers(right_ast)
    same_length = len(left_numbers) == len(right_numbers)
    hamming = sum(a != b for a, b in zip(left_numbers, right_numbers)) if same_length else None
    same_group_lengths = left_ast["term_counts"] == right_ast["term_counts"]
    multiset_delta = sum((Counter(left_numbers) - Counter(right_numbers)).values()) + sum((Counter(right_numbers) - Counter(left_numbers)).values())
    same_multiset = Counter(left_numbers) == Counter(right_numbers)
    group_difference_count = sum(a != b for a, b in zip(left_ast["groups"], right_ast["groups"]))
    return {
        "left": {"id": left_item["id"], "formulaText": left_item["formulaText"]},
        "right": {"id": right_item["id"], "formulaText": right_item["formulaText"]},
        "total_length_left": len(left_numbers),
        "total_length_right": len(right_numbers),
        "same_total_length": same_length,
        "same_group_lengths": same_group_lengths,
        "hamming_distance": hamming,
        "multiset_delta": multiset_delta,
        "same_number_multiset": same_multiset,
        "group_difference_count": group_difference_count,
        "numeric_differences": _diffs(left_ast, right_ast),
    }


def analyze() -> dict[str, Any]:
    algorithms = read_current_algorithms()
    parsed = [parse_formula(item["formulaText"]) for item in algorithms]
    pairs = []
    for index, left in enumerate(algorithms):
        for right_index in range(index + 1, len(algorithms)):
            pairs.append(_pair(left, algorithms[right_index], parsed[index], parsed[right_index]))
    pairs.sort(
        key=lambda item: (
            0 if item["same_group_lengths"] else 1,
            item["hamming_distance"] if item["hamming_distance"] is not None else 999,
            item["multiset_delta"],
            abs(item["total_length_left"] - item["total_length_right"]),
            item["left"]["id"],
            item["right"]["id"],
        )
    )
    one_number = [item for item in pairs if item["same_group_lengths"] and item["hamming_distance"] == 1]
    one_position = [item for item in pairs if item["same_total_length"] and item["same_number_multiset"] and item["hamming_distance"] > 0]
    one_segment = [item for item in pairs if item["same_total_length"] and item["group_difference_count"] == 1]
    return {
        "algorithm_count": len(algorithms),
        "pair_count": len(pairs),
        "one_number_difference_pair_count": len(one_number),
        "one_position_difference_pair_count": len(one_position),
        "one_segment_difference_pair_count": len(one_segment),
        "closest_20": pairs[:20],
        "closest_10": pairs[:10],
        "output_comparisons": [],
        "output_comparison_reason": "only the separately displayed current algorithm has a reliable algorithm_id mapping",
    }


def main() -> None:
    result = analyze()
    (ROOT / "data" / "v4_structure_analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: result[key] for key in ("algorithm_count", "pair_count", "one_number_difference_pair_count", "one_position_difference_pair_count", "one_segment_difference_pair_count")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
