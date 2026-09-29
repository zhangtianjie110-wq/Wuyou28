"""Read-only, parameterized backtesting engine for stored predictions.

This module deliberately does not depend on collection controllers and never
writes to :class:`~app.database.Database`.  It converts raw prediction rows
into analysis features, evaluates an extensible set of AND conditions, and
reports results for VIP.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .constants import COMBINATIONS, COMBINATION_FIELDS, SOURCE_TYPES
from .stats import combination_matches, issue_sort_key, normalize_result


ConditionEvaluator = Callable[[dict[str, Any]], bool | tuple[bool, str]]
_CONDITION_REGISTRY: dict[str, ConditionEvaluator] = {}


@dataclass(frozen=True)
class ConditionResult:
    """The result of one registered condition evaluation."""

    passed: bool
    reason: str = ""


def register_condition(name: str, evaluator: ConditionEvaluator) -> None:
    """Register a reusable condition for future strategy extensions.

    An evaluator receives one converted row and may return either a boolean or
    ``(boolean, reason)``.  Built-in names are replaced intentionally so an
    application can refine a condition without changing the engine.
    """

    key = str(name).strip()
    if not key or not callable(evaluator):
        raise ValueError("条件名称不能为空，且 evaluator 必须可调用")
    _CONDITION_REGISTRY[key] = evaluator


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _source_total(source_type: str) -> int:
    # Do not reject legacy rows here; validity is reported by the caller.
    return 100 if source_type == "VIP" else 56


def _ordered_groups(counts: Mapping[str, int], descending: bool = False) -> list[str]:
    indexed = {combo: index for index, combo in enumerate(COMBINATIONS)}
    return sorted(
        COMBINATIONS,
        key=lambda combo: (
            -int(counts[combo]) if descending else int(counts[combo]),
            indexed[combo],
        ),
    )


def convert_prediction(record: Mapping[str, Any]) -> dict[str, Any]:
    """Convert one prediction row to immutable-in-practice analysis data.

    The input mapping is copied.  No derived value is written back to the
    database row, which keeps the stored record untouched.
    """

    values = dict(record)
    source_type = str(values.get("source_type") or "")
    counts = {
        combo: _as_int(values.get(field))
        for combo, field in COMBINATION_FIELDS.items()
    }
    ascending = _ordered_groups(counts)
    descending = _ordered_groups(counts, descending=True)
    numbers = [counts[combo] for combo in COMBINATIONS]
    minimum = min(numbers)
    second_minimum = counts[ascending[1]]
    maximum = max(numbers)
    actual_raw = values.get("actual_combo") or values.get("actual_result")
    actual_combo = normalize_result(actual_raw)
    lowest_two = ascending[:2]
    converted = {
        "id": values.get("id"),
        "issue_no": str(values.get("issue_no") or ""),
        "source_type": source_type,
        "counts": counts,
        "big_single": counts["大单"],
        "big_double": counts["大双"],
        "small_single": counts["小单"],
        "small_double": counts["小双"],
        "minimum": minimum,
        "second_minimum": second_minimum,
        "maximum": maximum,
        "max_min_diff": maximum - minimum,
        "lowest_two": tuple(lowest_two),
        "lowest_two_text": "、".join(lowest_two),
        "tied_min": numbers.count(minimum) > 1,
        "ascending_rank": tuple(ascending),
        "descending_rank": tuple(descending),
        "rank": {combo: index + 1 for index, combo in enumerate(ascending)},
        "actual_result": str(values.get("actual_result") or ""),
        "actual_combo": actual_combo,
        "valid_outcome": actual_combo in COMBINATIONS,
        "source_total": _source_total(source_type),
        "raw": values,
    }
    return converted


def convert_predictions(
    records: Iterable[Mapping[str, Any]],
    source_type: str | None = None,
) -> list[dict[str, Any]]:
    """Convert and chronologically order rows, optionally for one source."""

    converted = [convert_prediction(row) for row in records]
    if source_type is not None:
        converted = [row for row in converted if row["source_type"] == source_type]
    return sorted(converted, key=lambda row: (issue_sort_key(row["issue_no"]), _as_int(row["id"])))


def _bounded(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    return _as_int(value)


def _in_range(value: int, params: Mapping[str, Any], low_key: str, high_key: str) -> bool:
    lower = _bounded(params.get(low_key), None)
    upper = _bounded(params.get(high_key), None)
    return (lower is None or value >= lower) and (upper is None or value <= upper)


def _selection(row: Mapping[str, Any], params: Mapping[str, Any]) -> tuple[str, ...]:
    selected = params.get("selected_groups", params.get("specified_groups"))
    if selected is None and params.get("specified_pair") is not None:
        selected = params.get("specified_pair")
    if selected is not None:
        if isinstance(selected, str):
            selected = [item for item in re.split(r"[、,，/|\s]+", selected) if item]
        result = tuple(str(item) for item in selected if str(item) in COMBINATIONS)
        if result:
            return tuple(dict.fromkeys(result))
    groups = _as_int(params.get("min_groups", 1), 1)
    groups = max(1, min(groups, 2))
    return tuple(row["ascending_rank"][:groups])


def _parse_relation(relation: Any) -> tuple[str, str, str] | None:
    if isinstance(relation, (list, tuple)) and len(relation) == 3:
        left, operator, right = relation
        return str(left), str(operator), str(right)
    if isinstance(relation, str):
        match = re.match(r"^\s*(大单|大双|小单|小双)\s*(<=|>=|==|=|<|>)\s*(大单|大双|小单|小双)\s*$", relation)
        if match:
            return match.group(1), match.group(2), match.group(3)
    return None


def _rank_relations_pass(row: Mapping[str, Any], relations: Any) -> bool:
    if not relations:
        return True
    rank = row["rank"]
    if isinstance(relations, Mapping):
        if "relations" in relations:
            relations = relations["relations"]
        elif "ascending" in relations:
            expected = [str(combo) for combo in relations["ascending"]]
            return tuple(row["ascending_rank"])[: len(expected)] == tuple(expected)
        elif all(str(key) in COMBINATIONS for key in relations):
            return all(rank[str(key)] == _as_int(value) for key, value in relations.items())
    if isinstance(relations, str):
        relations = [relations]
    for item in relations if isinstance(relations, Sequence) else []:
        parsed = _parse_relation(item)
        if not parsed:
            return False
        left, operator, right = parsed
        left_rank, right_rank = rank[left], rank[right]
        if operator in ("=", "==") and left_rank != right_rank:
            return False
        if operator == "<" and not left_rank < right_rank:
            return False
        if operator == ">" and not left_rank > right_rank:
            return False
        if operator == "<=" and not left_rank <= right_rank:
            return False
        if operator == ">=" and not left_rank >= right_rank:
            return False
    return True


def _builtin_conditions(row: dict[str, Any], params: Mapping[str, Any]) -> ConditionResult:
    if not _in_range(row["minimum"], params, "min_value_min", "min_value_max"):
        return ConditionResult(False, "最小值不在范围内")
    if not _in_range(row["second_minimum"] - row["minimum"], params, "lowest_two_diff_min", "lowest_two_diff_max"):
        return ConditionResult(False, "第一、第二最小值差值不在范围内")
    if not _in_range(row["max_min_diff"], params, "max_min_diff_min", "max_min_diff_max"):
        return ConditionResult(False, "最大最小差值不在范围内")
    if not bool(params.get("allow_tie", True)) and row["tied_min"]:
        return ConditionResult(False, "最小值存在并列")
    requested = params.get("selected_groups", params.get("specified_groups"))
    if requested is not None or params.get("specified_pair") is not None:
        chosen = _selection(row, params)
        if len(chosen) != 2:
            return ConditionResult(False, "指定双组合必须正好包含两组")
    if not _rank_relations_pass(row, params.get("rank_relations")):
        return ConditionResult(False, "四组排名关系不满足")
    return ConditionResult(True)


def _evaluate_conditions(row: dict[str, Any], params: Mapping[str, Any], extra_conditions: Iterable[ConditionEvaluator]) -> ConditionResult:
    builtin = _builtin_conditions(row, params)
    if not builtin.passed:
        return builtin
    for name, evaluator in _CONDITION_REGISTRY.items():
        if name not in params:
            continue
        result = evaluator(row)
        result = result if isinstance(result, tuple) else (bool(result), "")
        if not result[0]:
            return ConditionResult(False, result[1] or f"条件 {name} 不满足")
    for evaluator in extra_conditions:
        result = evaluator(row)
        result = result if isinstance(result, tuple) else (bool(result), "")
        if not result[0]:
            return ConditionResult(False, result[1] or "自定义条件不满足")
    return ConditionResult(True)


def _window_metrics(outcomes: list[dict[str, Any]], window: int) -> dict[str, Any]:
    recent = outcomes[-window:]
    hits = sum(1 for item in recent if item["hit"])
    samples = len(recent)
    return {
        "window": window,
        "samples": samples,
        "hits": hits,
        "misses": samples - hits,
        "hit_rate": round(hits / samples * 100, 2) if samples else None,
        "insufficient_sample": samples == 0,
    }


def _streak_metrics(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    max_hit = max_miss = current = 0
    current_state = "none"
    current_length = 0
    for item in outcomes:
        state = "hit" if item["hit"] else "miss"
        current = current + 1 if state == current_state else 1
        current_state, current_length = state, current
        if state == "hit":
            max_hit = max(max_hit, current)
        else:
            max_miss = max(max_miss, current)
    return {
        "max_consecutive_hits": max_hit,
        "max_consecutive_misses": max_miss,
        "current_state": current_state,
        "current_streak": current_length,
    }


def run_condition_backtest(
    records: Iterable[Mapping[str, Any]],
    conditions: Mapping[str, Any] | None = None,
    *,
    source_type: str | None = None,
    min_sample_size: int = 30,
    extra_conditions: Iterable[ConditionEvaluator] = (),
) -> dict[str, Any]:
    """Run one parameterized strategy against one source's records."""

    params = dict(conditions or {})
    rows = convert_predictions(records, source_type)
    outcomes: list[dict[str, Any]] = []
    matched_periods = 0
    excluded = 0
    details: list[dict[str, Any]] = []
    for row in rows:
        result = _evaluate_conditions(row, params, extra_conditions)
        selected = _selection(row, params)
        if not result.passed:
            continue
        matched_periods += 1
        if not row["valid_outcome"]:
            excluded += 1
            details.append({"issue_no": row["issue_no"], "selected": selected, "hit": None, "reason": "开奖缺失或无效"})
            continue
        hit = any(combination_matches(combo, row["actual_combo"]) for combo in selected)
        outcome = {"issue_no": row["issue_no"], "selected": selected, "actual_combo": row["actual_combo"], "hit": hit}
        outcomes.append(outcome)
        details.append({**outcome, "reason": ""})
    valid_samples = len(outcomes)
    hits = sum(1 for item in outcomes if item["hit"])
    misses = valid_samples - hits
    threshold = max(1, _as_int(min_sample_size, 30))
    metrics = {
        "source_type": source_type or "全部",
        "total_periods": len(rows),
        "matched_periods": matched_periods,
        "valid_samples": valid_samples,
        "excluded_missing_outcome": excluded,
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / valid_samples * 100, 2) if valid_samples else None,
        "insufficient_sample": valid_samples < threshold,
        "minimum_sample_size": threshold,
        "recent": {str(window): _window_metrics(outcomes, window) for window in (30, 50, 100, 200)},
        **_streak_metrics(outcomes),
        "average_condition_interval": round(len(rows) / matched_periods, 2) if matched_periods else None,
        "conditions": params,
        "details": details,
        "warning": f"有效样本不足（{valid_samples}/{threshold}）" if valid_samples < threshold else "",
    }
    return metrics


def run_auto_backtest(
    records: Iterable[Mapping[str, Any]],
    conditions: Mapping[str, Any] | None = None,
    *,
    min_sample_size: int = 30,
    extra_conditions: Iterable[ConditionEvaluator] = (),
) -> dict[str, dict[str, Any]]:
    """Run results for the configured VIP source."""

    rows = list(records)
    return {
        source: run_condition_backtest(
            rows,
            conditions,
            source_type=source,
            min_sample_size=min_sample_size,
            extra_conditions=extra_conditions,
        )
        for source in SOURCE_TYPES
    }


def run_database_backtest(
    database: Any,
    conditions: Mapping[str, Any] | None = None,
    *,
    min_sample_size: int = 30,
    extra_conditions: Iterable[ConditionEvaluator] = (),
) -> dict[str, dict[str, Any]]:
    """Read valid rows through the existing database API and run analysis.

    ``valid_backtest_records`` is a read-only query.  This function intentionally
    has no database writes, migrations, or result persistence side effects.
    """

    return {
        source: run_condition_backtest(
            database.valid_backtest_records(source),
            conditions,
            source_type=source,
            min_sample_size=min_sample_size,
            extra_conditions=extra_conditions,
        )
        for source in SOURCE_TYPES
    }


def _record_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Sort by issue first, then available draw time and stable id."""

    return (
        issue_sort_key(str(record.get("issue_no") or "")),
        str(record.get("draw_time") or record.get("actual_time") or ""),
        str(record.get("created_at") or ""),
        _as_int(record.get("id")),
    )


def prepare_backtest_records(
    records: Iterable[Mapping[str, Any]],
    source_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return complete, outcome-bearing rows in deterministic time order.

    Rows marked invalid or partial are excluded.  Rows without a status field
    remain supported for callers that provide plain historical dictionaries.
    """

    prepared: list[dict[str, Any]] = []
    for record in records:
        row = dict(record)
        if source_type is not None and str(row.get("source_type") or "") != source_type:
            continue
        if bool(row.get("is_invalid")) or str(row.get("status") or "") in {
            "无效", "待检查", "待开奖", "部分失败", "不完整", "partial", "missing", "incomplete",
        }:
            continue
        if normalize_result(row.get("actual_combo") or row.get("actual_result")) is None:
            continue
        prepared.append(row)
    return sorted(prepared, key=_record_sort_key)


def split_train_validation(
    records: Iterable[Mapping[str, Any]],
    train_ratio: float = 0.7,
    *,
    source_type: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split complete rows chronologically without shuffling or leakage."""

    ordered = prepare_backtest_records(records, source_type)
    if not ordered:
        return [], []
    ratio = min(max(float(train_ratio), 0.1), 0.9)
    split_index = max(1, min(len(ordered) - 1, int(len(ordered) * ratio))) if len(ordered) > 1 else len(ordered)
    return ordered[:split_index], ordered[split_index:]


def run_train_validation_backtest(
    records: Iterable[Mapping[str, Any]],
    conditions: Mapping[str, Any] | None = None,
    *,
    train_ratio: float = 0.7,
    source_type: str | None = None,
    min_sample_size: int = 30,
    extra_conditions: Iterable[ConditionEvaluator] = (),
) -> dict[str, Any]:
    """Choose conditions on the training slice, then evaluate both slices."""

    train_rows, validation_rows = split_train_validation(
        records, train_ratio, source_type=source_type
    )
    train = run_condition_backtest(
        train_rows, conditions, source_type=source_type, min_sample_size=min_sample_size,
        extra_conditions=extra_conditions,
    )
    validation = run_condition_backtest(
        validation_rows, conditions, source_type=source_type, min_sample_size=min_sample_size,
        extra_conditions=extra_conditions,
    )
    overall = run_condition_backtest(
        train_rows + validation_rows, conditions, source_type=source_type,
        min_sample_size=min_sample_size, extra_conditions=extra_conditions,
    )
    train_rate = train["hit_rate"]
    validation_rate = validation["hit_rate"]
    difference = (
        round(validation_rate - train_rate, 2)
        if train_rate is not None and validation_rate is not None else None
    )
    train_details = [dict(item, dataset="训练集") for item in train["details"]]
    validation_details = [dict(item, dataset="验证集") for item in validation["details"]]
    hits = train["hits"] + validation["hits"]
    misses = train["misses"] + validation["misses"]
    return {
        "conditions": dict(conditions or {}),
        "source_type": source_type or "全部",
        "train": train,
        "validation": validation,
        "overall": overall,
        "train_samples": train["total_periods"],
        "train_triggered": train["matched_periods"],
        "train_valid_samples": train["valid_samples"],
        "train_hit_rate": train_rate,
        "validation_samples": validation["total_periods"],
        "validation_triggered": validation["matched_periods"],
        "validation_valid_samples": validation["valid_samples"],
        "validation_hit_rate": validation_rate,
        "hit_rate_difference": difference,
        "matched": train["matched_periods"] + validation["matched_periods"],
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / (hits + misses) * 100, 2) if hits + misses else 0.0,
        "details": train_details + validation_details,
        "selection_basis": "training_only",
    }


def _candidate_ranges(total: int) -> tuple[tuple[int, int], ...]:
    return (
        (0, total),
        (0, min(total, 10)),
        (10, min(total, 20)),
        (20, min(total, 35)),
    )


def generate_condition_candidates(
    source_type: str = "VIP",
    *,
    max_candidates: int = 64,
) -> list[dict[str, Any]]:
    """Build a bounded, deterministic condition set for training-only scans."""

    total = _source_total(source_type)
    ranges = _candidate_ranges(total)
    diff_ranges = ((0, 1), (0, 3), (2, 5), (0, total))
    spread_ranges = ((0, total), (10, min(total, 30)), (20, total))
    rank_relations: tuple[Any, ...] = (
        None,
        ["大单<大双"],
        ["大双<小单"],
    )
    pairs = tuple((left, right) for index, left in enumerate(COMBINATIONS) for right in COMBINATIONS[index + 1:])
    candidates: list[dict[str, Any]] = []
    # Each family contributes a small fixed set.  The hard cap is applied
    # before any result ranking so scans cannot become an implicit optimizer.
    for min_groups in (1, 2):
        for allow_tie in (True, False):
            for value_range in ranges[:2]:
                for diff_range in diff_ranges[:2]:
                    candidate = {
                        "min_groups": min_groups,
                        "min_value_min": value_range[0],
                        "min_value_max": value_range[1],
                        "lowest_two_diff_min": diff_range[0],
                        "lowest_two_diff_max": diff_range[1],
                        "max_min_diff_min": 0,
                        "max_min_diff_max": total,
                        "allow_tie": allow_tie,
                    }
                    candidates.append(candidate)
                    if len(candidates) >= max_candidates:
                        return candidates
    for pair in pairs:
        for value_range in ranges[:1]:
            candidate = {
                "min_value_min": value_range[0],
                "min_value_max": value_range[1],
                "lowest_two_diff_min": 0,
                "lowest_two_diff_max": total,
                "max_min_diff_min": 0,
                "max_min_diff_max": total,
                "allow_tie": False,
                "selected_groups": list(pair),
            }
            candidates.append(candidate)
            if len(candidates) >= max_candidates:
                return candidates
    for spread in spread_ranges:
        for relation in rank_relations:
            candidates.append({
                "min_groups": 1,
                "min_value_min": 0,
                "min_value_max": total,
                "lowest_two_diff_min": 0,
                "lowest_two_diff_max": total,
                "max_min_diff_min": spread[0],
                "max_min_diff_max": spread[1],
                "allow_tie": True,
                "rank_relations": relation,
            })
            if len(candidates) >= max_candidates:
                return candidates
    return candidates[:max(1, int(max_candidates))]


def scan_conditions(
    records: Iterable[Mapping[str, Any]],
    *,
    source_type: str = "VIP",
    train_ratio: float = 0.7,
    max_candidates: int = 64,
    min_sample_size: int = 30,
    extra_conditions: Iterable[ConditionEvaluator] = (),
) -> dict[str, Any]:
    """Scan a bounded set; validation is evaluated only after train selection."""

    rows = list(records)
    train_rows, validation_rows = split_train_validation(rows, train_ratio, source_type=source_type)
    candidates = generate_condition_candidates(source_type, max_candidates=max_candidates)
    results: list[dict[str, Any]] = []
    for index, conditions in enumerate(candidates, start=1):
        train = run_condition_backtest(
            train_rows, conditions, source_type=source_type,
            min_sample_size=min_sample_size, extra_conditions=extra_conditions,
        )
        validation = run_condition_backtest(
            validation_rows, conditions, source_type=source_type,
            min_sample_size=min_sample_size, extra_conditions=extra_conditions,
        )
        train["details"] = [dict(item, dataset="训练集") for item in train["details"]]
        validation["details"] = [dict(item, dataset="验证集") for item in validation["details"]]
        overall = run_condition_backtest(
            train_rows + validation_rows, conditions, source_type=source_type,
            min_sample_size=min_sample_size, extra_conditions=extra_conditions,
        )
        train_rate, validation_rate = train["hit_rate"], validation["hit_rate"]
        results.append({
            "candidate_index": index,
            "conditions": conditions,
            "train": train,
            "validation": validation,
            "overall": overall,
            "train_triggered": train["matched_periods"],
            "validation_triggered": validation["matched_periods"],
            "train_valid_samples": train["valid_samples"],
            "validation_valid_samples": validation["valid_samples"],
            "train_hit_rate": train_rate,
            "validation_hit_rate": validation_rate,
            "hit_rate_difference": (
                round(validation_rate - train_rate, 2)
                if train_rate is not None and validation_rate is not None else None
            ),
            "sample_warning": train["warning"] or validation["warning"],
            "selection_basis": "training_only",
        })
    return {
        "source_type": source_type,
        "train_ratio": min(max(float(train_ratio), 0.1), 0.9),
        "tested_conditions": len(results),
        "max_candidates": max_candidates,
        "results": results,
        "training_issue_range": (train_rows[0]["issue_no"], train_rows[-1]["issue_no"]) if train_rows else None,
        "validation_issue_range": (validation_rows[0]["issue_no"], validation_rows[-1]["issue_no"]) if validation_rows else None,
        "selection_basis": "training_only",
    }


def _aggregate_outcomes(details: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate validation detail rows without reordering windows."""

    rows = [dict(item) for item in details if item.get("hit") is not None]
    hits = sum(1 for item in rows if item.get("hit"))
    misses = len(rows) - hits
    return {
        "valid_samples": len(rows),
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / len(rows) * 100, 2) if rows else None,
        "details": rows,
    }


def run_walk_forward(
    records: Iterable[Mapping[str, Any]],
    conditions: Mapping[str, Any] | None = None,
    *,
    train_window: int = 200,
    validation_window: int = 50,
    step: int = 50,
    source_type: str | None = None,
    min_sample_size: int = 30,
    extra_conditions: Iterable[ConditionEvaluator] = (),
) -> dict[str, Any]:
    """Run fixed train/validation windows moving strictly forward in time."""

    ordered = prepare_backtest_records(records, source_type)
    train_size = max(1, int(train_window))
    validation_size = max(1, int(validation_window))
    step_size = max(1, int(step))
    windows: list[dict[str, Any]] = []
    start = 0
    while start + train_size + validation_size <= len(ordered):
        train_rows = ordered[start:start + train_size]
        validation_rows = ordered[start + train_size:start + train_size + validation_size]
        train = run_condition_backtest(train_rows, conditions, source_type=source_type, min_sample_size=min_sample_size, extra_conditions=extra_conditions)
        validation = run_condition_backtest(validation_rows, conditions, source_type=source_type, min_sample_size=min_sample_size, extra_conditions=extra_conditions)
        train["details"] = [dict(item, dataset="训练集") for item in train["details"]]
        validation["details"] = [dict(item, dataset="验证集") for item in validation["details"]]
        windows.append({
            "window_index": len(windows) + 1,
            "train_issue_range": (train_rows[0]["issue_no"], train_rows[-1]["issue_no"]),
            "validation_issue_range": (validation_rows[0]["issue_no"], validation_rows[-1]["issue_no"]),
            "train": train,
            "validation": validation,
            "conditions": dict(conditions or {}),
        })
        start += step_size
    combined = _aggregate_outcomes(
        detail for window in windows for detail in window["validation"]["details"]
    )
    return {
        "source_type": source_type or "全部",
        "train_window": train_size,
        "validation_window": validation_size,
        "step": step_size,
        "conditions": dict(conditions or {}),
        "windows": windows,
        "combined_validation": combined,
        "selection_basis": "fixed_conditions_no_future_data",
    }


__all__ = [
    "ConditionResult",
    "convert_prediction",
    "convert_predictions",
    "register_condition",
    "run_auto_backtest",
    "run_condition_backtest",
    "run_database_backtest",
    "prepare_backtest_records",
    "split_train_validation",
    "run_train_validation_backtest",
    "generate_condition_candidates",
    "scan_conditions",
    "run_walk_forward",
]
