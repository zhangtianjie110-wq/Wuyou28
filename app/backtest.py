from __future__ import annotations

from typing import Any

from .constants import COMBINATION_FIELDS, SOURCE_TOTALS
from .stats import combination_matches, issue_sort_key, max_streak, selected_combinations


def _numbers(record: dict[str, Any]) -> list[int]:
    return [int(record[field]) for field in COMBINATION_FIELDS.values()]


def _has_lowest_tie(record: dict[str, Any]) -> bool:
    ordered = sorted(_numbers(record))
    return ordered[0] == ordered[1] or ordered[1] == ordered[2]


def _matches_conditions(
    record: dict[str, Any],
    previous: dict[str, Any] | None,
    params: dict[str, Any],
    previous_raw_loss_streak: int,
) -> tuple[bool, str]:
    minimum = int(record["stat_min"])
    total = SOURCE_TOTALS.get(str(record.get("source_type", "VIP")), 100)
    min_from = int(params.get("min_value_min", 0))
    min_to = int(params.get("min_value_max", total))
    if not min_from <= minimum <= min_to:
        return False, "最小值不在范围内"

    diff_max = int(params.get("lowest_two_diff_max", total))
    if int(record["lowest_two_diff"]) > diff_max:
        return False, "最低两项差值过大"

    if not bool(params.get("allow_tie", True)) and _has_lowest_tie(record):
        return False, "最低区域存在并列"

    prev_wrong_min = int(params.get("prev_wrong_min", 0))
    prev_wrong_max = int(params.get("prev_wrong_max", total))
    if previous is None or previous.get("wrong_count") is None:
        if prev_wrong_min > 0 or prev_wrong_max < total:
            return False, "没有可用的上一期错数"
    else:
        previous_wrong = int(previous["wrong_count"])
        if not prev_wrong_min <= previous_wrong <= prev_wrong_max:
            return False, "上一期错数不在范围内"

    required_losses = int(params.get("after_consecutive_losses", 0))
    if required_losses > 0 and previous_raw_loss_streak < required_losses:
        return False, "尚未达到连续错次数"
    return True, ""


def _metrics(rows: list[dict[str, Any]], total_periods: int) -> dict[str, Any]:
    outcomes = [bool(row["hit"]) for row in rows]
    hits = sum(outcomes)
    misses = len(outcomes) - hits
    return {
        "matched": len(rows),
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / len(rows) * 100, 2) if rows else 0.0,
        "max_hit_streak": max_streak(outcomes, True),
        "max_miss_streak": max_streak(outcomes, False),
        "average_interval": round(total_periods / len(rows), 2) if rows else 0.0,
    }


def run_backtest(
    records: list[dict[str, Any]],
    method: str,
    parameters: dict[str, Any],
    train_ratio: float = 0.7,
) -> dict[str, Any]:
    ordered = sorted(records, key=lambda row: (issue_sort_key(row["issue_no"]), row["id"]))
    if not ordered:
        empty = _metrics([], 0)
        return {
            **empty,
            "total_periods": 0,
            "train": empty.copy(),
            "validation": empty.copy(),
            "warning": "没有可参与回测的正常数据",
            "details": [],
            "train_ratio": train_ratio,
        }

    ratio = min(max(float(train_ratio), 0.1), 0.9)
    split_index = max(1, min(len(ordered) - 1, int(len(ordered) * ratio))) if len(ordered) > 1 else 1
    details: list[dict[str, Any]] = []
    raw_loss_streak = 0
    previous: dict[str, Any] | None = None

    for index, record in enumerate(ordered):
        selected = selected_combinations(record, method)
        raw_hit = any(
            combination_matches(combo, record["actual_combo"]) for combo in selected
        )
        eligible, skip_reason = _matches_conditions(
            record, previous, parameters, raw_loss_streak
        )
        if eligible:
            details.append(
                {
                    "issue_no": record["issue_no"],
                    "source_type": record["source_type"],
                    "dataset": "训练集" if index < split_index else "验证集",
                    "selected": "、".join(selected),
                    "actual_combo": record["actual_combo"],
                    "hit": raw_hit,
                    "min_value": record["stat_min"],
                    "lowest_two_diff": record["lowest_two_diff"],
                    "previous_wrong": previous.get("wrong_count") if previous else None,
                    "raw_loss_streak_before": raw_loss_streak,
                }
            )
        raw_loss_streak = 0 if raw_hit else raw_loss_streak + 1
        previous = record

    train_rows = [row for row in details if row["dataset"] == "训练集"]
    validation_rows = [row for row in details if row["dataset"] == "验证集"]
    overall = _metrics(details, len(ordered))
    train = _metrics(train_rows, split_index)
    validation = _metrics(validation_rows, max(0, len(ordered) - split_index))
    warning = ""
    if train["matched"] >= 3 and validation["matched"] >= 2:
        if train["hit_rate"] - validation["hit_rate"] >= 10:
            warning = "验证表现下降"
    return {
        **overall,
        "total_periods": len(ordered),
        "train": train,
        "validation": validation,
        "warning": warning,
        "details": details,
        "train_ratio": ratio,
    }


def run_rolling_backtest(
    records: list[dict[str, Any]],
    method: str,
    parameters: dict[str, Any],
    window_size: int = 30,
    train_ratio: float = 0.7,
) -> list[dict[str, Any]]:
    """Run the existing strategy repeatedly over a one-period rolling window."""
    ordered = sorted(records, key=lambda row: (issue_sort_key(row["issue_no"]), row["id"]))
    if not ordered:
        return []
    size = max(2, min(int(window_size), len(ordered)))
    windows: list[dict[str, Any]] = []
    for end in range(size, len(ordered) + 1):
        subset = ordered[end - size : end]
        result = run_backtest(subset, method, parameters, train_ratio)
        windows.append(
            {
                "start_issue": subset[0]["issue_no"],
                "end_issue": subset[-1]["issue_no"],
                "periods": len(subset),
                "matched": result["matched"],
                "hits": result["hits"],
                "misses": result["misses"],
                "hit_rate": result["hit_rate"],
                "validation_hit_rate": result["validation"]["hit_rate"],
                "warning": result.get("warning", ""),
            }
        )
    return windows
