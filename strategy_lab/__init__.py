"""Isolated strategy laboratory built on the application's backtest engine."""

from .conditions import StrategyConditionGenerator
from .engine import StrategyLabEngine
from .evaluator import StrategyEvaluator
from .filter import FilterConfig, FilterDecision, StrategyFilterEngine
from .models import CandidateResult, ExperimentResult, StrategyCondition
from .ranking import RankingEntry, RankingWeights, StrategyRanking
from .storage import StrategyLabStorage
from .freeze import FrozenStrategy, StrategyFreezeService
from .tracker import StrategyTracker, TrackingConfig, TrackingResult
from .compare import ComparisonResult, StrategyComparator, StrategyComparisonRow
from .search import SearchConfig, SearchResult, SearchSpace, StrategySearchEngine
from .auto_runner import AutoRunConfig, AutoRunResult, StrategyAutoRunner
from .vip100_history import Vip100HistoryDataSource

__version__ = "1.2.0"

__all__ = [
    "CandidateResult",
    "AutoRunConfig",
    "AutoRunResult",
    "ComparisonResult",
    "ExperimentResult",
    "FilterConfig",
    "FilterDecision",
    "FrozenStrategy",
    "RankingEntry",
    "RankingWeights",
    "SearchConfig",
    "SearchResult",
    "SearchSpace",
    "StrategyCondition",
    "StrategyAutoRunner",
    "StrategyConditionGenerator",
    "StrategyEvaluator",
    "StrategyFilterEngine",
    "StrategyFreezeService",
    "StrategyLabEngine",
    "StrategyLabStorage",
    "StrategySearchEngine",
    "StrategyComparator",
    "StrategyComparisonRow",
    "StrategyRanking",
    "StrategyTracker",
    "Vip100HistoryDataSource",
    "TrackingConfig",
    "TrackingResult",
    "__version__",
]
