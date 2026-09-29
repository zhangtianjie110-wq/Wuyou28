from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import sys
from typing import Any

from ..constants import APP_NAME, DEFAULT_DB_PATH


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntegrationPaths:
    draw_db: Path
    draw_raw_inputs: Path
    vip100_production: Path
    vip100_hash_status: Path
    strategy_db: Path
    strategy_runtime_status: Path
    vip100_replay_db: Path | None = None

    @classmethod
    def from_environment(cls) -> "IntegrationPaths":
        local_appdata = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        default_root = (
            Path.home()
            / "Documents"
            / "Codex"
            / "2026-09-25"
            / "vip"
            / "research"
            / "vip_formula_engine"
        )
        root = Path(os.environ.get("VIP100_FORMULA_ENGINE_ROOT", default_root))
        engine_root = Path(os.environ.get("VIP100_ENGINE_ROOT", root / "VIP100LocalEngine"))
        strategy_root = Path(
            os.environ.get("STRATEGY_RESEARCH_ROOT", root / "StrategyResearchEngine")
        )
        canonical_strategy_db = (
            local_appdata / APP_NAME / "data" / "strategy_research.sqlite3"
        )
        legacy_strategy_db = strategy_root / "data" / "strategy_research.sqlite3"
        strategy_db_override = os.environ.get("STRATEGY_RESEARCH_DB")
        if strategy_db_override:
            strategy_db = Path(strategy_db_override)
        elif not getattr(sys, "frozen", False) and legacy_strategy_db.is_file():
            strategy_db = legacy_strategy_db
        else:
            strategy_db = canonical_strategy_db
        paths = cls(
            draw_db=Path(
                os.environ.get(
                    # Keep the read-only gateway on the same canonical path
                    # as Database(); the environment variable is explicit
                    # diagnostic/deployment override only.
                    "WUY28_DRAW_DB",
                    DEFAULT_DB_PATH,
                )
            ),
            draw_raw_inputs=Path(
                os.environ.get(
                    "VIP100_YU28_RAW_INPUTS", engine_root / "data" / "raw_inputs"
                )
            ),
            vip100_production=Path(
                os.environ.get(
                    "VIP100_PRODUCTION_DATA", root / "data" / "vip100_production_v2"
                )
            ),
            vip100_hash_status=Path(
                os.environ.get(
                    "VIP100_HASH_STATUS",
                    root / "data" / "vip100_v2_control" / "hash_status.json",
                )
            ),
            strategy_db=strategy_db,
            strategy_runtime_status=Path(
                os.environ.get(
                    "STRATEGY_RUNTIME_STATUS",
                    strategy_root / "data" / "runtime" / "status.json",
                )
            ),
            vip100_replay_db=Path(
                os.environ.get(
                    "VIP100_REPLAY_DB",
                    root / "data" / "vip100_reconstructed_v1.sqlite3",
                )
            ),
        )
        logger.info(
            "integration paths resolved: draw_db=%s exists=%s draw_raw_inputs=%s "
            "vip100_production=%s strategy_db=%s local_appdata=%s draw_db_override=%s",
            paths.draw_db,
            paths.draw_db.is_file(),
            paths.draw_raw_inputs,
            paths.vip100_production,
            paths.strategy_db,
            local_appdata,
            bool(os.environ.get("WUY28_DRAW_DB")),
        )
        return paths


@dataclass(frozen=True)
class DrawRecord:
    issue: str
    draw_time: str
    number: str
    combination: str
    countdown: str = ""
    source: str = "YU28"


@dataclass(frozen=True)
class Vip100Prediction:
    position: int
    algorithm_id: str
    algorithm_name: str
    formula: str
    prediction: int
    combination: str
    hit: bool | None


@dataclass(frozen=True)
class Vip100Batch:
    issue: str
    generated_at: str
    engine_version: str
    algorithm_hash: str
    history_hash: str
    input_hash: str
    source: str
    actual_result: str | None
    predictions: tuple[Vip100Prediction, ...]
    input_start_issue: str | None = None
    input_end_issue: str | None = None
    replay_version: str | None = None

    @property
    def prediction_count(self) -> int:
        return len(self.predictions)


@dataclass(frozen=True)
class StrategySummary:
    strategy_id: str
    strategy_hash: str
    status: str
    source_status: str
    predictor: str
    conditions: dict[str, Any]
    train_samples: int
    validation_samples: int
    test_samples: int
    trigger_count: int
    hit_count: int
    miss_count: int
    accuracy: float | None
    validation_accuracy: float | None
    test_accuracy: float | None
    walk_forward_accuracy: float | None
    max_consecutive_misses: int
    recent_20_accuracy: float | None
    recent_50_accuracy: float | None
    recent_100_accuracy: float | None
    forward_samples: int
    forward_accuracy: float | None
    created_at: str | None = None
    train_triggers: int = 0
    validation_triggers: int = 0
    test_triggers: int = 0
    train_accuracy: float | None = None
    max_consecutive_hits: int = 0
    current_streak_type: str = "NONE"
    current_streak_count: int = 0
    average_trigger_interval: float | None = None
    sample_warning: str | None = None
    strategy_name: str = ""
    strategy_version: str = ""
    rule_hash: str = ""
    target_issue: str | None = None
    triggered: bool = False
    current_prediction: tuple[str, ...] | None = None
    prediction_status: str = "WAITING_DATA"
    prediction_generated_at: str | None = None
    prediction_source: str | None = None


@dataclass(frozen=True)
class StrategyDetail:
    summary: StrategySummary
    historical_triggers: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    forward_records: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    walk_forward_windows: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    prediction_history: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    statistics: dict[str, Any] = field(default_factory=dict)
    latest_trigger: dict[str, Any] | None = None
    history_records: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    history_scope: str = "ALL"
    history_limit: int = 100
