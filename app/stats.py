from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .constants import (
    COMBINATIONS,
    COMBINATION_FIELDS,
    OPPOSITE_COMBINATIONS,
    SOURCE_TOTALS,
)


@dataclass(frozen=True)
class ValidationResult:
    status: str
    reason: str
    values: dict[str, Any]


def normalize_result(value: Any) -> str | None:
    """把“四组合”文字或 0-27 的开奖结果转换为四组合。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    compact = re.sub(r"\s+", "", text)
    aliases = {
        "大单": "大单",
        "大雙": "大双",
        "大双": "大双",
        "小单": "小单",
        "小單": "小单",
        "小双": "小双",
        "小雙": "小双",
    }
    if compact in aliases:
        return aliases[compact]
    try:
        number = int(float(compact))
    except (TypeError, ValueError):
        return None
    if not 0 <= number <= 27:
        return None
    size = "小" if number <= 13 else "大"
    parity = "双" if number % 2 == 0 else "单"
    return size + parity


def combination_matches(selected: str, actual: str) -> bool:
    """A combination wins when either its size or parity matches the result."""
    return selected in OPPOSITE_COMBINATIONS and OPPOSITE_COMBINATIONS[selected] != actual


def parse_plan_items(text: str | None) -> list[str]:
    if not text or not str(text).strip():
        return []
    raw = re.split(r"[\s,，;；|/]+", str(text).strip())
    return [item for item in raw if item]


def normalize_plans(text: str | None) -> tuple[list[str], list[str]]:
    normalized: list[str] = []
    invalid: list[str] = []
    for item in parse_plan_items(text):
        combo = normalize_result(item)
        if combo is None:
            invalid.append(item)
        else:
            normalized.append(combo)
    return normalized, invalid


def combination_stats(values: dict[str, int]) -> dict[str, Any]:
    ordered = [(combo, int(values[COMBINATION_FIELDS[combo]])) for combo in COMBINATIONS]
    ascending = sorted(enumerate(ordered), key=lambda item: (item[1][1], item[0]))
    lowest = [ascending[0][1], ascending[1][1]]
    numbers = [value for _, value in ordered]
    minimum = min(numbers)
    return {
        "stat_min": minimum,
        "stat_max": max(numbers),
        "lowest_two": "、".join(combo for combo, _ in lowest),
        "lowest_two_diff": abs(lowest[1][1] - lowest[0][1]),
        "tied_min": numbers.count(minimum) > 1,
        "average": round(sum(numbers) / 4, 2),
    }


def selected_combinations(values: dict[str, int], method: str) -> list[str]:
    indexed = [(idx, combo, int(values[COMBINATION_FIELDS[combo]])) for idx, combo in enumerate(COMBINATIONS)]
    ascending = sorted(indexed, key=lambda item: (item[2], item[0]))
    descending = sorted(indexed, key=lambda item: (-item[2], item[0]))
    if method == "lowest_one":
        chosen = ascending[:1]
    elif method == "lowest_two":
        chosen = ascending[:2]
    elif method == "highest_one":
        chosen = descending[:1]
    elif method == "highest_two":
        chosen = descending[:2]
    elif method == "highest_lowest":
        chosen = [ascending[0], descending[0]]
    elif method == "middle_two":
        chosen = ascending[1:3]
    else:
        raise ValueError(f"未知测试方法：{method}")
    return list(dict.fromkeys(item[1] for item in chosen))


def issue_sort_key(issue: str) -> tuple:
    text = str(issue or "")
    pieces = re.split(r"(\d+)", text)
    return tuple(int(piece) if piece.isdigit() else piece.lower() for piece in pieces)


def validate_and_enrich(payload: dict[str, Any]) -> ValidationResult:
    values = dict(payload)
    reasons: list[str] = []
    issue = str(values.get("issue_no") or "").strip()
    values["issue_no"] = issue
    if not issue:
        reasons.append("缺少期号")

    source = str(values.get("source_type") or "").strip()
    if source != "VIP":
        reasons.append("预测类型无效")
    expected_total = SOURCE_TOTALS.get(source, 100)

    counts: dict[str, int] = {}
    for field in COMBINATION_FIELDS.values():
        try:
            counts[field] = int(values.get(field, 0))
        except (TypeError, ValueError):
            counts[field] = 0
            reasons.append(f"{field} 不是整数")
        if counts[field] < 0:
            reasons.append("四组合数量不能小于 0")
    values.update(counts)

    plan_text = str(values.get("plan_text") or "").strip()
    plans, invalid_plans = normalize_plans(plan_text)
    values["plan_text"] = plan_text
    values["plan_count"] = len(parse_plan_items(plan_text))
    if invalid_plans:
        reasons.append("计划中有无法识别的内容：" + "、".join(invalid_plans[:5]))
    if plan_text and len(plans) != expected_total:
        reasons.append(f"{source or '当前类型'}计划数量应为 {expected_total}，当前为 {len(plans)}")

    derived_counts = {field: 0 for field in COMBINATION_FIELDS.values()}
    for plan in plans:
        derived_counts[COMBINATION_FIELDS[plan]] += 1
    total = sum(counts.values())
    if plans and len(plans) == expected_total:
        if total == 0:
            counts = derived_counts
            values.update(counts)
            total = expected_total
        elif counts != derived_counts:
            reasons.append(f"四组合数量与 {expected_total} 个计划内容不一致")
    if total != expected_total:
        reasons.append(f"{source or '当前类型'}四组合合计应为 {expected_total}，当前为 {total}")

    actual_raw = str(values.get("actual_result") or "").strip()
    actual_combo = normalize_result(actual_raw)
    values["actual_result"] = actual_raw
    values["actual_combo"] = actual_combo
    if actual_raw and actual_combo is None:
        reasons.append("开奖结果格式无效，应为 0-27 或四组合")

    values.update(combination_stats(counts))
    if actual_combo:
        wrong_combo = OPPOSITE_COMBINATIONS[actual_combo]
        wrong = counts[COMBINATION_FIELDS[wrong_combo]]
        values["correct_count"] = expected_total - wrong
        values["wrong_count"] = wrong
    else:
        values["correct_count"] = None
        values["wrong_count"] = None

    if bool(values.get("is_invalid")):
        status = "无效"
        reasons.insert(0, "已人工标记无效")
    elif reasons:
        status = "待检查"
    elif not actual_combo:
        status = "待开奖"
    else:
        status = "正常"
    values["status"] = status
    values["invalid_reason"] = "；".join(dict.fromkeys(reasons))
    return ValidationResult(status=status, reason=values["invalid_reason"], values=values)


def max_streak(results: Iterable[bool], wanted: bool) -> int:
    best = current = 0
    for result in results:
        if result is wanted:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best
