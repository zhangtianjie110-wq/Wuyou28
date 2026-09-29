"""Small, explicit falsification experiments for numeric token meanings.

These are candidate tests only. A match does not establish semantics; every
candidate is recorded with support and counterexample counts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from formula_parser import parse_formula


ROOT = Path(__file__).resolve().parent


def _sum_from_number(text: str) -> int | None:
    match = re.search(r"=\s*(\d{1,2})", str(text))
    return int(match.group(1)) if match else None


def _candidate_value(sample: dict[str, Any], group_index: int, reverse: bool) -> int | None:
    history = sample["history_snapshot"]
    if not history:
        return None
    formula = parse_formula(sample["formulaText"])
    values: list[int] = []
    for group in formula["groups"]:
        group_values = []
        for term in group["terms"]:
            k = int(term["value"])
            index = -k if not reverse else k - 1
            if abs(index) > len(history):
                return None
            draw = history[index]
            value = _sum_from_number(draw["number"])
            if value is None:
                return None
            group_values.append(value)
        values.append(sum(group_values) % 28)
    return values[group_index]


def _evaluate_candidate(samples: list[dict[str, Any]], name: str, fn: Callable[[dict[str, Any]], int | None], detail: str) -> dict[str, Any]:
    tested = 0
    support = 0
    counterexamples = 0
    rows = []
    for sample in samples:
        expected_text = sample["le28_output"]["predicted_value"]
        try:
            expected = int(expected_text)
        except (TypeError, ValueError):
            expected = None
        actual = fn(sample)
        if expected is None or actual is None:
            continue
        tested += 1
        matches = actual == expected
        support += int(matches)
        counterexamples += int(not matches)
        rows.append({"issue": sample["issue"], "expected": expected, "candidate": actual, "matches": matches})
    return {
        "hypothesis": name,
        "detail": detail,
        "tested_samples": tested,
        "support_samples": support,
        "counterexamples": counterexamples,
        "agreement_rate": support / tested if tested else None,
        "rows": rows,
    }


def run() -> dict[str, Any]:
    payload = json.loads((ROOT / "data" / "v2_single_algorithm_observations.json").read_text(encoding="utf-8"))
    samples = []
    for item in payload["samples"]:
        samples.append({**item, "formulaText": payload["active_formula"]})
    hypotheses = []
    for reverse, orientation in ((False, "newest prior draw is lag 1"), (True, "oldest snapshot row is position 1")):
        for group_index in range(3):
            name = f"lag_sum_mod28_group_{group_index + 1}_{'oldest' if reverse else 'newest'}"
            hypotheses.append(
                _evaluate_candidate(
                    samples,
                    name,
                    lambda sample, group_index=group_index, reverse=reverse: _candidate_value(sample, group_index, reverse),
                    f"token [k] is treated as a draw-position lookup; '+' sums draw totals; group {group_index + 1} is the output; {orientation}; result modulo 28",
                )
            )
    hypotheses.extend(
        {
            "hypothesis": name,
            "detail": detail,
            "tested_samples": 0,
            "support_samples": 0,
            "counterexamples": 0,
            "agreement_rate": None,
            "status": "untested",
        }
        for name, detail in (
            ("base_algorithm_id", "[k] denotes another saved algorithm identifier"),
            ("data_column_id", "[k] denotes a data column identifier"),
            ("result_transform_id", "[k] denotes a deterministic result transform identifier"),
        )
    )
    return {
        "sample_count": len(samples),
        "hypotheses": hypotheses,
        "operator_observations": {
            "+": {"observed": True, "role": "syntax separator only", "control_experiments": 0},
            "|": {"observed": True, "role": "three-group separator only", "control_experiments": 0},
        },
    }


def main() -> None:
    result = run()
    (ROOT / "data" / "v2_mapping_experiments.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
