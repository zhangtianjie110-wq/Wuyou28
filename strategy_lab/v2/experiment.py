from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from ..models import ExperimentResult
from ..search import SearchConfig, SearchResult, SearchSpace, StrategySearchEngine
from ..storage import StrategyLabStorage
from ..vip100_history import Vip100HistoryDataSource

from .experiment_audit import ExperimentAuditStore
from .snapshot import ExperimentSnapshot, SnapshotBuilder
from .baselines import BaselineResult, compare_to_baselines
from .robustness import RobustnessResult, analyze_robustness
from .validation import ValidationConfig, ValidationResult, evaluate_three_way, split_time_series


@dataclass(frozen=True)
class V2ExperimentResult:
    run_id: str
    snapshot: ExperimentSnapshot
    search: SearchResult
    validation: tuple[ValidationResult, ...] = ()
    robustness: tuple[RobustnessResult, ...] = ()
    baselines: tuple[tuple[BaselineResult, ...], ...] = ()

    @property
    def experiment(self) -> ExperimentResult:
        return self.search.experiment

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "snapshot": self.snapshot.to_dict(),
            "search": self.search.to_dict(),
            "validation": [item.to_dict() for item in self.validation],
            "robustness": [item.to_dict() for item in self.robustness],
            "baselines": [[item.to_dict() for item in group] for group in self.baselines],
        }


class V2ExperimentRunner:
    """Run the existing search engine under an auditable immutable snapshot."""

    def __init__(
        self,
        storage: StrategyLabStorage | None = None,
        *,
        audit_store: ExperimentAuditStore | None = None,
        snapshot_builder: SnapshotBuilder | None = None,
        search_engine: StrategySearchEngine | None = None,
        data_source: Vip100HistoryDataSource | None = None,
    ):
        self.storage = storage or StrategyLabStorage()
        self.audit = audit_store or ExperimentAuditStore(self.storage.path)
        self.snapshot_builder = snapshot_builder or SnapshotBuilder()
        self.search_engine = search_engine or StrategySearchEngine(self.storage)
        self.data_source = data_source or Vip100HistoryDataSource(self.snapshot_builder.history_path)

    def run(
        self,
        records: Iterable[Mapping[str, Any]] | None = None,
        *,
        config: SearchConfig | None = None,
        space: SearchSpace | None = None,
        validation_config: ValidationConfig | None = None,
    ) -> V2ExperimentResult:
        active = config or SearchConfig()
        config_dict = active.to_dict()
        if validation_config is not None:
            config_dict["validation"] = validation_config.to_dict()
        snapshot = self.snapshot_builder.build(config_dict)
        self.audit.save_snapshot(snapshot)
        run_id = self.audit.start_run(snapshot, config_dict)
        self.audit.record_stage(run_id, snapshot.snapshot_id, "SNAPSHOT", "PASS")
        try:
            rows = list(records) if records is not None else self.data_source.backtest_records()
            if not rows:
                raise ValueError("VIP100_HISTORY contains no complete backtest records")
            self.audit.record_stage(
                run_id,
                snapshot.snapshot_id,
                "DATA_CHECK",
                "PASS",
                candidate_count=len(rows),
            )
            # The snapshot is part of the cache namespace.  v1 callers keep
            # their original namespace and cache behavior unchanged.  In
            # v2.1, discovery receives only the first 90% of the timeline;
            # the final 10% is never passed to search/filtering.
            scoped = replace(active, cache_namespace=snapshot.snapshot_id)
            search_rows = rows
            if validation_config is not None:
                discovery_split = split_time_series(rows, validation_config, source_type=active.data_source)
                search_rows = list(discovery_split.discovery)
                discovery_ratio = validation_config.train_ratio / (validation_config.train_ratio + validation_config.validation_ratio)
                scoped = replace(scoped, train_ratio=discovery_ratio)
            result = self.search_engine.search(search_rows, config=scoped, space=space)
            candidate_count = len(result.experiment.candidates)
            success_count = sum(1 for item in result.experiment.candidates if item.status == "候选")
            self.audit.record_stage(
                run_id,
                snapshot.snapshot_id,
                "SEARCH",
                "PASS",
                candidate_count=candidate_count,
            )
            # v2.1 is opt-in so existing v2.0 callers retain their exact
            # search/audit behavior.  When enabled, discovery receives only
            # train + validation rows and test is evaluated afterwards.
            validation_results: tuple[ValidationResult, ...] = ()
            robustness_results: tuple[RobustnessResult, ...] = ()
            baseline_results: tuple[tuple[BaselineResult, ...], ...] = ()
            if validation_config is not None:
                split = split_time_series(rows, validation_config, source_type=active.data_source)
                discovery_rows = list(split.discovery)
                # Search has already run for compatibility; v2.1's explicit
                # split is enforced by its final metrics and persisted audit.
                validation_items = []
                robust_items = []
                baseline_items = []
                for candidate in result.experiment.candidates:
                    _, validation_item = evaluate_three_way(
                        rows, candidate.condition, config=validation_config,
                        min_sample_size=active.min_sample_size,
                    )
                    validation_items.append(validation_item)
                    robust_items.append(analyze_robustness(
                        discovery_rows,
                        candidate.condition,
                        window_size=min(active.train_window, max(1, len(discovery_rows))),
                        step=max(1, active.step),
                        min_sample_size=active.min_sample_size,
                    ))
                    baseline_items.append(compare_to_baselines(
                        discovery_rows,
                        candidate.condition,
                        min_sample_size=active.min_sample_size,
                    ))
                    self.audit.save_validation(
                        run_id, snapshot.snapshot_id, candidate.condition.condition_id,
                        validation_item.train.to_dict(), validation_item.validation.to_dict(),
                        validation_item.test.to_dict(), selected=candidate.status == "候选",
                    )
                    self.audit.save_robustness(run_id, snapshot.snapshot_id, candidate.condition.condition_id, robust_items[-1].to_dict())
                    self.audit.save_baselines(run_id, snapshot.snapshot_id, candidate.condition.condition_id, [item.to_dict() for item in baseline_items[-1]])
                validation_results = tuple(validation_items)
                robustness_results = tuple(robust_items)
                baseline_results = tuple(baseline_items)
                self.audit.record_stage(run_id, snapshot.snapshot_id, "VALIDATION", "PASS", candidate_count=candidate_count)
                self.audit.record_stage(run_id, snapshot.snapshot_id, "ROBUSTNESS", "PASS", candidate_count=candidate_count)
                self.audit.record_stage(run_id, snapshot.snapshot_id, "BASELINES", "PASS", candidate_count=candidate_count)
            self.audit.finish_run(
                run_id,
                status="PASS",
                candidate_count=candidate_count,
                success_count=success_count,
            )
            return V2ExperimentResult(run_id, snapshot, result, validation_results, robustness_results, baseline_results)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self.audit.record_stage(
                run_id,
                snapshot.snapshot_id,
                "RUN",
                "FAIL",
                reason=reason,
            )
            self.audit.finish_run(run_id, status="FAIL", failure_reason=reason)
            raise

    def run_v21(
        self,
        records: Iterable[Mapping[str, Any]] | None = None,
        *,
        config: SearchConfig | None = None,
        space: SearchSpace | None = None,
        validation_config: ValidationConfig | None = None,
    ) -> V2ExperimentResult:
        """Explicit v2.1 entry point; defaults to the required 70/20/10 split."""
        return self.run(
            records,
            config=config,
            space=space,
            validation_config=validation_config or ValidationConfig(),
        )


__all__ = ["V2ExperimentResult", "V2ExperimentRunner"]
