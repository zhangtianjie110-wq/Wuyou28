"""Validation helpers that do not mutate production data."""

from __future__ import annotations

from typing import Any, Iterable


def assert_strictly_prior(history: Iterable[dict[str, Any]], target_issue: int) -> None:
    """Ensure every input row is strictly earlier than the target issue."""

    invalid = [row.get("issue") for row in history if int(row["issue"]) >= target_issue]
    if invalid:
        raise AssertionError(f"future data supplied for {target_issue}: {invalid}")


def compare_outputs(rows: Iterable[dict[str, Any]]) -> dict[str, int | float]:
    rows = list(rows)
    equal = sum(1 for row in rows if row.get("matches") is True)
    unequal = sum(1 for row in rows if row.get("matches") is False)
    total = equal + unequal
    return {
        "compared": total,
        "一致": equal,
        "不一致": unequal,
        "一致率": (equal / total if total else None),
    }
