from __future__ import annotations

from dataclasses import dataclass


MAX_HISTORY_WINDOW = 500_000
UI_WINDOWS = (30, 50, 100, 200, 500, 1_000, 5_000, 10_000, 50_000)
DETAIL_WINDOWS = (*UI_WINDOWS, None)


@dataclass(frozen=True)
class HotColdThresholds:
    extreme_percentile: float = 5.0
    warm_percentile: float = 20.0
    extreme_relative_deviation: float = 0.25
    warm_relative_deviation: float = 0.10


HOT_COLD_THRESHOLDS = HotColdThresholds()

