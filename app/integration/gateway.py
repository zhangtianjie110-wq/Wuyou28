from __future__ import annotations

from .data_center_repository import DataCenterRepository
from .draw_repository import DrawRepository
from .models import IntegrationPaths
from .strategy_repository import StrategyResearchRepository
from .strategy_large_sample_repository import StrategyLargeSampleRepository
from .strategy_dynamic_pair_repository import StrategyDynamicPairRepository
from .strategy_state_similarity_repository import StrategyStateSimilarityRepository
from .strategy_algorithm_quality_repository import StrategyAlgorithmQualityRepository
from .vip100_repository import Vip100Repository
from .vip100_reconstructed_repository import Vip100ReconstructedRepository
from ..history_analytics import HistoryAnalyticsEngine
from ..secure_store import load_yu28_api_key
from ..yu28 import YU28Client


class IntegrationGateway:
    """Read facade only; it owns no timers, workers, processes, or write handles."""

    def __init__(self, paths: IntegrationPaths | None = None):
        self.paths = paths or IntegrationPaths.from_environment()
        self.draws = DrawRepository(self.paths.draw_db, self.paths.draw_raw_inputs)
        self.vip100 = Vip100Repository(
            self.paths.vip100_production,
            self.paths.vip100_hash_status,
            self.paths.strategy_db,
        )
        replay_path = self.paths.vip100_replay_db or (
            self.paths.vip100_production.parent / "vip100_reconstructed_v1.sqlite3"
        )
        self.vip100_reconstructed = Vip100ReconstructedRepository(replay_path)
        self.strategies = StrategyResearchRepository(
            self.paths.strategy_db, self.paths.strategy_runtime_status
        )
        self.strategy_large_sample = StrategyLargeSampleRepository(
            self.paths.strategy_db
        )
        self.strategy_dynamic_pair = StrategyDynamicPairRepository(
            self.paths.strategy_db
        )
        self.strategy_state_similarity = StrategyStateSimilarityRepository(
            self.paths.strategy_db
        )
        self.strategy_algorithm_quality = StrategyAlgorithmQualityRepository(
            self.paths.strategy_db
        )
        self.data_center = DataCenterRepository(
            self.draws, self.vip100, self.strategies
        )
        self.history_analytics = HistoryAnalyticsEngine(self.draws)

    @staticmethod
    def _yu28() -> YU28Client:
        return YU28Client(load_yu28_api_key())

    def draw_by_issue(self, issue: str | int):
        return self._yu28().fetch_draw_by_issue(issue)

    def keno_20(self, limit: int = 1) -> dict:
        return self._yu28().fetch_keno(limit)

    def text_trend(self, limit: int = 20) -> dict:
        return self._yu28().fetch_text_trend(limit)

    def daily_stats(self) -> dict:
        return self._yu28().fetch_daily_stats()

    def omission(self) -> dict:
        return self._yu28().fetch_omission()

    def long_dragon(self) -> dict:
        return self._yu28().fetch_long_dragon()

    def history_omission(self, dimension: str, window: int | str | None = None) -> dict:
        return self.history_analytics.omission(dimension, window)

    def history_hot_cold(
        self, dimension: str, window: int | str | None = 30
    ) -> dict:
        return self.history_analytics.hot_cold(dimension, window)

    def history_object_detail(self, dimension: str, object_name: str) -> dict:
        return self.history_analytics.detail(dimension, object_name)

    def history_quality(self, window: int | str | None = None) -> dict:
        return self.history_analytics.quality(window)

    def strategy_current_status(self) -> dict:
        return self.strategies.current_status()

    def strategy_status(self) -> dict:
        return self.strategies.status()

    def strategy_list(self, limit: int = 2000):
        return self.strategies.list_strategies(limit)

    def strategy_detail(
        self,
        strategy_id: str,
        history_scope: str = "ALL",
        history_limit: int = 100,
    ):
        if self.strategy_dynamic_pair.contains(strategy_id):
            return self.strategy_dynamic_pair.get(
                strategy_id, history_scope, history_limit
            )
        if self.strategy_large_sample.contains(strategy_id):
            return self.strategy_large_sample.get(
                strategy_id, history_scope, history_limit
            )
        return self.strategies.get(strategy_id, history_scope, history_limit)

    def strategy_large_sample_status(self) -> dict:
        return self.strategy_large_sample.status()

    def strategy_large_sample_list(self, limit: int = 100):
        return self.strategy_large_sample.list_strategies(limit)

    def strategy_dynamic_pair_status(self) -> dict:
        return self.strategy_dynamic_pair.status()

    def strategy_dynamic_pair_list(self, limit: int = 100):
        return self.strategy_dynamic_pair.list_strategies(limit)

    def strategy_state_similarity_status(self) -> dict:
        return self.strategy_state_similarity.status()

    def strategy_state_similarity_list(self, limit: int = 20):
        return self.strategy_state_similarity.list_methods(limit)

    def strategy_state_similarity_current(self) -> dict:
        return self.strategy_state_similarity.current()

    def strategy_state_similarity_replay(
        self, method_id: str | None = None, limit: int = 100
    ) -> tuple[dict, ...]:
        return self.strategy_state_similarity.replay(method_id, limit)

    def strategy_state_similarity_segments(
        self, method_id: str | None = None
    ) -> tuple[dict, ...]:
        return self.strategy_state_similarity.segments(method_id)

    def strategy_algorithm_quality_status(self) -> dict:
        return self.strategy_algorithm_quality.status()

    def strategy_algorithm_quality_list(self, limit: int = 20):
        return self.strategy_algorithm_quality.list_methods(limit)

    def strategy_algorithm_quality_algorithms(self) -> tuple[dict, ...]:
        return self.strategy_algorithm_quality.algorithm_stats()

    def strategy_algorithm_quality_groups(self) -> tuple[dict, ...]:
        return self.strategy_algorithm_quality.groups()

    def strategy_algorithm_quality_current(self) -> dict:
        return self.strategy_algorithm_quality.current()

    def strategy_prediction_history(self, strategy_id: str) -> tuple[dict, ...]:
        return self.strategies.prediction_history(strategy_id)

    def vip100_issues(self, source_type: str, limit: int = 200) -> list[str]:
        source = str(source_type).upper()
        if source in {"FORWARD", "VIP100_LOCAL_V2"}:
            return self.vip100.list_issues(limit)
        if source == "RECONSTRUCTED":
            return self.vip100_reconstructed.list_issues(limit)
        raise ValueError(f"unsupported VIP100 source type: {source_type}")

    def vip100_batch(self, source_type: str, issue: str | int):
        source = str(source_type).upper()
        if source in {"FORWARD", "VIP100_LOCAL_V2"}:
            return self.vip100.get(issue)
        if source == "RECONSTRUCTED":
            return self.vip100_reconstructed.get(issue)
        raise ValueError(f"unsupported VIP100 source type: {source_type}")

    def health(self) -> dict:
        draw = self.draws.status()
        vip100 = self.vip100.status()
        strategy = self.strategies.status()
        freshness_states = [
            draw.get("freshness", {}).get("status", "OFFLINE"),
            vip100.get("freshness", {}).get("status", "OFFLINE"),
            strategy.get("freshness", {}).get("status", "OFFLINE"),
        ]
        if "ERROR" in freshness_states:
            aggregate = "ERROR"
        elif "OFFLINE" in freshness_states:
            aggregate = "OFFLINE"
        elif "STALE" in freshness_states:
            aggregate = "STALE"
        else:
            aggregate = "FRESH"
        return {
            "DRAW_SOURCE_STATUS": draw.get("status", "OFFLINE"),
            "DRAW_LATEST_ISSUE": draw.get("latest_issue"),
            "VIP100_STATUS": vip100.get("status", "OFFLINE"),
            "VIP100_LATEST_ISSUE": vip100.get("latest_issue"),
            "VIP100_PREDICTION_COUNT": vip100.get("prediction_count", 0),
            "VIP100_HASH_STATUS": vip100.get("hash_status", "OFFLINE"),
            "STRATEGY_ENGINE_STATUS": strategy.get("status", "OFFLINE"),
            "STRATEGY_DB_STATUS": strategy.get("database_status", "OFFLINE"),
            "DATA_FRESHNESS": aggregate,
            "DATA_FRESHNESS_DETAILS": {
                "draw": draw.get("freshness", {}),
                "vip100": vip100.get("freshness", {}),
                "strategy": strategy.get("freshness", {}),
            },
        }
