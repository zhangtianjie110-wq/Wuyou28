"""Read-only omission analysis for the official YU28 draw stream."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol


# Audited historical periods remain explicit DATA_GAP records when present in
# the selected window. They are never treated as ordinary draw observations.
KNOWN_DRAW_GAPS = frozenset(str(value) for value in range(3486466, 3486473))


class DrawSource(Protocol):
    def recent(self, limit: int = 20) -> Iterable[Any]: ...


@dataclass(frozen=True)
class DrawValue:
    issue: str
    value: int
    draw_time: str = ""


def _issue(value: Any) -> str:
    result = getattr(value, "issue", None)
    if result is None and isinstance(value, dict):
        result = value.get("issue", value.get("nbr"))
    result = str(result or "")
    if not result.isdigit():
        raise ValueError(f"invalid draw issue: {result!r}")
    return result


def _number(value: Any) -> int:
    raw = getattr(value, "number", None)
    if raw is None and isinstance(value, dict):
        raw = value.get("number", value.get("result"))
    if isinstance(raw, int):
        number = raw
    else:
        try:
            number = int(str(raw or "").rsplit("=", 1)[-1])
        except ValueError as exc:
            raise ValueError(f"invalid draw number: {raw!r}") from exc
    if not 0 <= number <= 27:
        raise ValueError(f"draw total outside 0..27: {number}")
    return number


def normalize_draws(rows: Iterable[Any]) -> tuple[DrawValue, ...]:
    by_issue: dict[str, DrawValue] = {}
    for row in rows:
        issue = _issue(row)
        draw_time = getattr(row, "draw_time", "")
        if isinstance(row, dict):
            draw_time = row.get("draw_time", row.get("time", ""))
        by_issue.setdefault(issue, DrawValue(issue, _number(row), str(draw_time or "")))
    return tuple(by_issue[key] for key in sorted(by_issue, key=int))


def _category(number: int) -> tuple[str, str, str]:
    size = "大" if number >= 14 else "小"
    parity = "双" if number % 2 == 0 else "单"
    return size, parity, size + parity


def _data_gaps(draws: tuple[DrawValue, ...]) -> tuple[str, ...]:
    if not draws:
        return ()
    observed = {draw.issue for draw in draws}
    start, end = int(draws[0].issue), int(draws[-1].issue)
    gaps = {str(issue) for issue in range(start, end + 1) if str(issue) not in observed}
    gaps.update(
        issue for issue in KNOWN_DRAW_GAPS
        if start <= int(issue) <= end and issue not in observed
    )
    return tuple(sorted(gaps, key=int))


def analyze_draws(rows: Iterable[Any], limit: int = 30) -> dict[str, Any]:
    """Return a read-only snapshot; missing issues are DATA_GAP metadata."""
    safe_limit = max(1, min(int(limit), 200))
    draws = normalize_draws(rows)
    if len(draws) > safe_limit:
        draws = draws[-safe_limit:]
    values = [draw.value for draw in draws]
    records: list[dict[str, Any]] = []
    for number in range(28):
        positions = [index for index, value in enumerate(values) if value == number]
        intervals = [b - a - 1 for a, b in zip(positions, positions[1:])]
        current = len(values) - positions[-1] - 1 if positions else len(values)
        all_gaps = [*intervals, current]
        size, parity, combination = _category(number)
        records.append({
            "number": number,
            "current_omission": current,
            "maximum_omission": max(all_gaps) if all_gaps else 0,
            "average_omission": round(sum(all_gaps) / len(all_gaps), 3) if all_gaps else 0.0,
            "last_issue": draws[positions[-1]].issue if positions else None,
            "occurrences": len(positions),
            "big_small": size,
            "odd_even": parity,
            "combination": combination,
        })
    gaps = _data_gaps(draws)
    return {
        "range": safe_limit,
        "draw_count": len(draws),
        "latest_issue": draws[-1].issue if draws else None,
        "data_gap_status": "DATA_GAP" if gaps else "COMPLETE",
        "data_gap_count": len(gaps),
        "data_gaps": list(gaps),
        "records": records,
    }


def snapshot_from_repository(repository: DrawSource, limit: int = 30) -> dict[str, Any]:
    return analyze_draws(repository.recent(limit), limit=limit)
