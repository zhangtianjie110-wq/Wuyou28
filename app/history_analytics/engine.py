from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Iterable, Protocol

from .config import DETAIL_WINDOWS, HOT_COLD_THRESHOLDS, MAX_HISTORY_WINDOW


DIMENSION_OBJECTS = {
    "NUMBER": tuple(str(value) for value in range(28)),
    "BIG_SMALL": ("大", "小"),
    "ODD_EVEN": ("单", "双"),
    "FOUR_COMBINATIONS": ("大单", "大双", "小单", "小双"),
}

DIMENSION_TEXT = {
    "NUMBER": "号码",
    "BIG_SMALL": "大小",
    "ODD_EVEN": "单双",
    "FOUR_COMBINATIONS": "四组合",
}

HOT_COLD_STATUS = ("极冷", "偏冷", "正常", "偏热", "极热")


class HistorySource(Protocol):
    def history(self, limit: int = MAX_HISTORY_WINDOW) -> Iterable[Any]: ...
    def since(self, issue: str | int, limit: int = MAX_HISTORY_WINDOW) -> Iterable[Any]: ...
    def latest(self) -> Any | None: ...


@dataclass(frozen=True)
class HistoryDraw:
    issue: int
    value: int
    draw_time: str

    @property
    def big_small(self) -> str:
        return "大" if self.value >= 14 else "小"

    @property
    def odd_even(self) -> str:
        return "双" if self.value % 2 == 0 else "单"

    @property
    def combination(self) -> str:
        return self.big_small + self.odd_even


def _raw_value(row: Any, name: str, *fallbacks: str) -> Any:
    value = getattr(row, name, None)
    if value is not None:
        return value
    if isinstance(row, dict):
        for key in (name, *fallbacks):
            if key in row:
                return row[key]
    return None


def _normalize_one(row: Any) -> HistoryDraw:
    issue_text = str(_raw_value(row, "issue", "nbr") or "").strip()
    if not issue_text.isdigit():
        raise ValueError("期号无效")
    raw_number = _raw_value(row, "number", "result", "value")
    if isinstance(raw_number, int):
        number = raw_number
    else:
        text = str(raw_number or "").strip()
        try:
            number = int(text.rsplit("=", 1)[-1])
        except ValueError as exc:
            raise ValueError("开奖号码无效") from exc
    if not 0 <= number <= 27:
        raise ValueError("开奖号码超出0至27")
    draw_time = str(_raw_value(row, "draw_time", "time") or "")
    return HistoryDraw(int(issue_text), number, draw_time)


def _dimension_value(draw: HistoryDraw, dimension: str) -> str:
    if dimension == "NUMBER":
        return str(draw.value)
    if dimension == "BIG_SMALL":
        return draw.big_small
    if dimension == "ODD_EVEN":
        return draw.odd_even
    if dimension == "FOUR_COMBINATIONS":
        return draw.combination
    raise ValueError(f"unsupported history dimension: {dimension}")


def _safe_dimension(value: str) -> str:
    dimension = str(value or "").upper()
    if dimension not in DIMENSION_OBJECTS:
        raise ValueError(f"unsupported history dimension: {value}")
    return dimension


def _safe_window(value: int | str | None) -> int | None:
    if value is None or str(value).upper() == "ALL":
        return None
    return max(1, min(int(value), MAX_HISTORY_WINDOW))


class HistoryAnalyticsEngine:
    """Reusable read-only analytics over official YU28 history."""

    omission_definition = "平均遗漏仅使用相邻两次出现之间已完成的遗漏周期；当前未结束周期不参与平均值。"
    percentile_definition = "历史分位为当前值在已完成历史周期或历史滚动窗口中的经验分布位置，不代表未来概率。"

    def __init__(self, source: HistorySource, max_history: int = MAX_HISTORY_WINDOW):
        self.source = source
        self.max_history = max(1, min(int(max_history), MAX_HISTORY_WINDOW))
        self._lock = RLock()
        self._draws: tuple[HistoryDraw, ...] = ()
        self._source_rows = 0
        self._duplicates = 0
        self._abnormal = 0
        self._full_loads = 0
        self._incremental_updates = 0
        self._analysis_cache: dict[tuple[Any, ...], dict[str, Any]] = {}

    @property
    def cache_state(self) -> dict[str, int]:
        return {
            "full_loads": self._full_loads,
            "incremental_updates": self._incremental_updates,
            "cached_draws": len(self._draws),
            "cached_analyses": len(self._analysis_cache),
        }

    def rebuild_cache(self) -> None:
        with self._lock:
            rows = list(self.source.history(self.max_history))
            self._replace_rows(rows)

    def _replace_rows(self, rows: Iterable[Any]) -> None:
        valid, duplicates, abnormal, total = self._prepare_rows(rows)
        self._draws = tuple(valid[-self.max_history :])
        self._source_rows = total
        self._duplicates = duplicates
        self._abnormal = abnormal
        self._analysis_cache.clear()
        self._full_loads += 1

    @staticmethod
    def _prepare_rows(
        rows: Iterable[Any],
    ) -> tuple[list[HistoryDraw], int, int, int]:
        by_issue: dict[int, HistoryDraw] = {}
        duplicates = abnormal = total = 0
        for row in rows:
            total += 1
            try:
                draw = _normalize_one(row)
            except (TypeError, ValueError):
                abnormal += 1
                continue
            if draw.issue in by_issue:
                duplicates += 1
                continue
            by_issue[draw.issue] = draw
        return [by_issue[key] for key in sorted(by_issue)], duplicates, abnormal, total

    def _ensure_current(self) -> None:
        with self._lock:
            if not self._draws:
                self.rebuild_cache()
                return
            latest = self.source.latest()
            if latest is None:
                return
            try:
                latest_draw = _normalize_one(latest)
            except (TypeError, ValueError):
                return
            cached_latest = self._draws[-1].issue
            if latest_draw.issue < cached_latest:
                self.rebuild_cache()
                return
            if latest_draw.issue == cached_latest:
                return
            new_rows = list(self.source.since(cached_latest, self.max_history))
            valid, duplicates, abnormal, total = self._prepare_rows(new_rows)
            valid = [row for row in valid if row.issue > cached_latest]
            if not valid and latest_draw.issue > cached_latest:
                self.rebuild_cache()
                return
            existing = {row.issue for row in self._draws}
            additions = [row for row in valid if row.issue not in existing]
            if additions:
                self._draws = tuple((*self._draws, *additions)[-self.max_history :])
                self._source_rows += total
                self._duplicates += duplicates
                self._abnormal += abnormal
                self._analysis_cache.clear()
                self._incremental_updates += len(additions)

    def _selected_draws(self, window: int | str | None) -> tuple[HistoryDraw, ...]:
        self._ensure_current()
        safe_window = _safe_window(window)
        return self._draws if safe_window is None else self._draws[-safe_window:]

    @staticmethod
    def _gap_count(draws: tuple[HistoryDraw, ...]) -> int:
        return sum(
            max(0, right.issue - left.issue - 1)
            for left, right in zip(draws, draws[1:])
        )

    def quality(self, window: int | str | None = None) -> dict[str, Any]:
        draws = self._selected_draws(window)
        missing = self._gap_count(draws)
        return {
            "valid_records": len(self._draws),
            "analysis_samples": len(draws),
            "start_issue": str(draws[0].issue) if draws else None,
            "latest_issue": str(draws[-1].issue) if draws else None,
            "missing_issues": missing,
            "duplicate_records": self._duplicates,
            "abnormal_records": self._abnormal,
            "last_updated_at": draws[-1].draw_time if draws else None,
            "status": "DATA_GAP" if missing else "COMPLETE",
            "max_history_window": self.max_history,
        }

    def omission(self, dimension: str, window: int | str | None = None) -> dict[str, Any]:
        dimension = _safe_dimension(dimension)
        safe_window = _safe_window(window)
        key = ("omission", dimension, safe_window)
        self._ensure_current()
        if key in self._analysis_cache:
            return self._analysis_cache[key]
        draws = self._draws if safe_window is None else self._draws[-safe_window:]
        values = [_dimension_value(draw, dimension) for draw in draws]
        records = []
        for object_name in DIMENSION_OBJECTS[dimension]:
            positions = [index for index, value in enumerate(values) if value == object_name]
            completed = [right - left - 1 for left, right in zip(positions, positions[1:])]
            current = len(values) - positions[-1] - 1 if positions else len(values)
            average = sum(completed) / len(completed) if completed else 0.0
            ratio = current / average if average > 0 else (0.0 if current == 0 else None)
            percentile = (
                sum(value <= current for value in completed) / len(completed) * 100
                if completed
                else None
            )
            records.append(
                {
                    "object": object_name,
                    "current_omission": current,
                    "average_omission": average,
                    "maximum_omission": max(completed) if completed else 0,
                    "over_average_ratio": ratio,
                    "historical_percentile": percentile,
                    "completed_cycles": len(completed),
                }
            )
        result = {
            "dimension": dimension,
            "dimension_text": DIMENSION_TEXT[dimension],
            "requested_window": safe_window,
            "actual_samples": len(draws),
            "records": tuple(records),
            "quality": self.quality(safe_window),
            "omission_definition": self.omission_definition,
            "percentile_definition": self.percentile_definition,
        }
        self._analysis_cache[key] = result
        return result

    @staticmethod
    def _rolling_percentile(
        values: list[str], object_name: str, sample_count: int, current_count: int
    ) -> float | None:
        if sample_count <= 0 or not values:
            return None
        if len(values) <= sample_count:
            return 100.0
        count = sum(value == object_name for value in values[:sample_count])
        lower_or_equal = int(count <= current_count)
        windows = 1
        for index in range(sample_count, len(values)):
            count += int(values[index] == object_name)
            count -= int(values[index - sample_count] == object_name)
            lower_or_equal += int(count <= current_count)
            windows += 1
        return lower_or_equal / windows * 100

    @staticmethod
    def _hot_cold_status(percentile: float | None, relative_deviation: float) -> str:
        if percentile is None:
            return "正常"
        thresholds = HOT_COLD_THRESHOLDS
        if (
            percentile <= thresholds.extreme_percentile
            and relative_deviation <= -thresholds.extreme_relative_deviation
        ):
            return "极冷"
        if (
            percentile <= thresholds.warm_percentile
            and relative_deviation <= -thresholds.warm_relative_deviation
        ):
            return "偏冷"
        if (
            percentile >= 100 - thresholds.extreme_percentile
            and relative_deviation >= thresholds.extreme_relative_deviation
        ):
            return "极热"
        if (
            percentile >= 100 - thresholds.warm_percentile
            and relative_deviation >= thresholds.warm_relative_deviation
        ):
            return "偏热"
        return "正常"

    def hot_cold(self, dimension: str, window: int | str | None = 30) -> dict[str, Any]:
        dimension = _safe_dimension(dimension)
        safe_window = _safe_window(window)
        key = ("hot_cold", dimension, safe_window)
        self._ensure_current()
        if key in self._analysis_cache:
            return self._analysis_cache[key]
        all_values = [_dimension_value(draw, dimension) for draw in self._draws]
        selected = all_values if safe_window is None else all_values[-safe_window:]
        actual_samples = len(selected)
        total_samples = len(all_values)
        records = []
        for object_name in DIMENSION_OBJECTS[dimension]:
            occurrences = sum(value == object_name for value in selected)
            total_occurrences = sum(value == object_name for value in all_values)
            rate = occurrences / actual_samples if actual_samples else 0.0
            baseline = total_occurrences / total_samples if total_samples else 0.0
            deviation = rate - baseline
            relative_deviation = deviation / baseline if baseline else 0.0
            percentile = self._rolling_percentile(
                all_values,
                object_name,
                actual_samples,
                occurrences,
            )
            records.append(
                {
                    "object": object_name,
                    "occurrences": occurrences,
                    "actual_samples": actual_samples,
                    "rate": rate,
                    "baseline_rate": baseline,
                    "deviation": deviation,
                    "relative_deviation": relative_deviation,
                    "historical_percentile": percentile,
                    "status": self._hot_cold_status(percentile, relative_deviation),
                }
            )
        result = {
            "dimension": dimension,
            "dimension_text": DIMENSION_TEXT[dimension],
            "requested_window": safe_window,
            "actual_samples": actual_samples,
            "records": tuple(records),
            "quality": self.quality(safe_window),
            "percentile_definition": self.percentile_definition,
        }
        self._analysis_cache[key] = result
        return result

    def detail(self, dimension: str, object_name: str) -> dict[str, Any]:
        dimension = _safe_dimension(dimension)
        if object_name not in DIMENSION_OBJECTS[dimension]:
            raise ValueError(f"unsupported object for {dimension}: {object_name}")
        omission_record = next(
            row
            for row in self.omission(dimension, None)["records"]
            if row["object"] == object_name
        )
        windows = []
        for window in DETAIL_WINDOWS:
            snapshot = self.hot_cold(dimension, window)
            record = next(row for row in snapshot["records"] if row["object"] == object_name)
            windows.append({"window": window, **record})
        return {
            "dimension": dimension,
            "dimension_text": DIMENSION_TEXT[dimension],
            "object": object_name,
            "omission": omission_record,
            "hot_cold": tuple(windows),
            "quality": self.quality(None),
            "omission_definition": self.omission_definition,
            "percentile_definition": self.percentile_definition,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

