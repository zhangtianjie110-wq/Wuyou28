"""Independent strategy research and forward-validation layer.

The laboratory reads prediction rows but persists its own analysis database.
It never updates ``predictions`` or changes a frozen strategy's conditions.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .auto_backtest import (
    convert_prediction,
    prepare_backtest_records,
    run_condition_backtest,
    run_walk_forward,
    split_train_validation,
)
from .constants import APP_VERSION, COMBINATIONS, DATA_DIR
from .stats import combination_matches, issue_sort_key


GENERATOR_VERSION = "strategy_lab_generator_v1"


def choose_lab_plan(valid_count: int) -> dict[str, Any]:
    """Choose a conservative validation plan from the available sample size."""

    count = max(0, int(valid_count))
    if count < 100:
        return {
            "label": "基础回测（样本不足，暂不启用 Walk-Forward）",
            "mode": "basic",
            "train_ratio": 0.7,
            "train_window": None,
            "validation_window": None,
            "step": None,
            "warning": "有效样本少于100期",
        }
    if count < 200:
        return {
            "label": "小窗口 Walk-Forward：训练60期 → 验证20期 → 步长20期",
            "mode": "small_window",
            "train_ratio": 0.7,
            "train_window": min(60, max(1, count - 20)),
            "validation_window": min(20, max(1, count // 5)),
            "step": min(20, max(1, count // 5)),
            "warning": "样本处于100至199期区间，使用小窗口",
        }
    train = min(200, max(1, count - 50))
    validation = min(50, max(1, count - train))
    return {
        "label": f"标准 Walk-Forward：训练{train}期 → 验证{validation}期 → 步长{validation}期",
        "mode": "standard_window" if count < 500 else "multi_window",
        "train_ratio": 0.7,
        "train_window": train,
        "validation_window": validation,
        "step": validation,
        "warning": "" if count >= 200 else "",
    }


def _condition_feature_passes(row: Mapping[str, Any], conditions: Mapping[str, Any]) -> bool:
    """Evaluate laboratory-only fields not present in the v1 engine."""

    def in_range(value: int, low: str, high: str) -> bool:
        return (conditions.get(low) is None or value >= int(conditions[low])) and (
            conditions.get(high) is None or value <= int(conditions[high])
        )

    tie_count = sum(value == row["minimum"] for value in row["counts"].values())
    if not in_range(row["second_minimum"], "second_min_value_min", "second_min_value_max"):
        return False
    if not in_range(tie_count, "tie_count_min", "tie_count_max"):
        return False
    if conditions.get("allow_tie") is False and tie_count > 1:
        return False
    return True


def _lab_extra_conditions(conditions: Mapping[str, Any]):
    groups = conditions.get("and_conditions") or []

    def evaluator(row: dict[str, Any]) -> bool:
        if not _condition_feature_passes(row, conditions):
            return False
        return all(_condition_feature_passes(row, group) for group in groups)

    return (evaluator,)


def canonical_conditions(conditions: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize conditions so duplicate and equivalent JSON is one candidate."""

    normalized = dict(conditions)
    if "selected_groups" in normalized:
        normalized["selected_groups"] = sorted(set(normalized["selected_groups"]))
    if "rank_relations" in normalized and normalized["rank_relations"]:
        normalized["rank_relations"] = sorted(normalized["rank_relations"])
    if "and_conditions" in normalized:
        normalized["and_conditions"] = sorted(
            (canonical_conditions(item) for item in normalized["and_conditions"]),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    return normalized


def condition_key(conditions: Mapping[str, Any]) -> str:
    """Compatibility alias for the canonical rule hash."""

    return rule_hash(conditions)


def rule_hash(conditions: Mapping[str, Any]) -> str:
    """Return the stable identity of the rule definition only.

    Dataset and freeze context deliberately do not participate in this hash;
    those inputs belong to :func:`strategy_version_id`.
    """

    # Keep the legacy condition-key serialization byte-for-byte compatible;
    # the new name separates the concept without changing existing IDs.
    content = json.dumps(canonical_conditions(conditions), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def strategy_version_id(
    rule_hash: str,
    dataset_hash: str = "",
    freeze_config: Mapping[str, Any] | None = None,
    code_version: str = APP_VERSION,
) -> str:
    """Build a deterministic version identity from a rule and freeze context."""

    payload = {
        "rule_hash": str(rule_hash),
        "dataset_hash": str(dataset_hash or ""),
        "freeze_config": freeze_config or {},
        "code_version": str(code_version),
    }
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def dataset_hash(records: Iterable[Mapping[str, Any]], source_type: str | None = None) -> str:
    """Hash the settled, valid dataset used by laboratory calculations.

    Only stable data fields are included. Database row ids, timestamps and
    other storage metadata are intentionally excluded so equivalent datasets
    produce the same digest.
    """

    prepared = prepare_backtest_records(records, source_type)
    payload = []
    for row in prepared:
        payload.append({
            "issue_no": str(row.get("issue_no") or ""),
            "source_type": str(row.get("source_type") or source_type or ""),
            "big_single": row.get("big_single"),
            "big_double": row.get("big_double"),
            "small_single": row.get("small_single"),
            "small_double": row.get("small_double"),
            "actual_result": row.get("actual_result"),
            "actual_combo": row.get("actual_combo"),
            "status": row.get("status") or "",
            "is_invalid": bool(row.get("is_invalid")),
        })
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def generate_lab_candidates(source_type: str, *, max_candidates: int = 128) -> list[dict[str, Any]]:
    """Generate bounded candidates across single, pair, rank and AND families."""

    total = 100 if source_type == "VIP" else 56
    value_ranges = ((0, total), (0, min(10, total)), (10, min(20, total)), (20, min(35, total)))
    second_ranges = ((0, total), (0, min(15, total)), (15, min(30, total)))
    diff_ranges = ((0, 1), (0, 3), (2, 5))
    spread_ranges = ((0, total), (10, min(30, total)), (20, total))
    ranks = (None, ["大单<大双"], ["大双<小单"])
    selections: list[dict[str, Any]] = [{"min_groups": 1}, {"min_groups": 2}]
    selections.extend(
        {"selected_groups": [left, right]}
        for index, left in enumerate(COMBINATIONS)
        for right in COMBINATIONS[index + 1:]
    )
    candidates: list[dict[str, Any]] = []

    def add(candidate: dict[str, Any]) -> bool:
        candidates.append(canonical_conditions(candidate))
        return len(candidates) >= max(1, int(max_candidates))

    for selection in selections:
        for value_range in value_ranges[:2]:
            for diff_range in diff_ranges[:2]:
                candidate = {
                    **selection,
                    "min_value_min": value_range[0], "min_value_max": value_range[1],
                    "second_min_value_min": 0, "second_min_value_max": total,
                    "lowest_two_diff_min": diff_range[0], "lowest_two_diff_max": diff_range[1],
                    "max_min_diff_min": 0, "max_min_diff_max": total,
                    "allow_tie": len(candidates) % 2 == 0,
                    "tie_count_min": 1, "tie_count_max": 4,
                }
                if add(candidate):
                    return candidates
    for second_range in second_ranges:
        for spread in spread_ranges:
            for rank in ranks:
                candidate = {
                    "min_groups": 1,
                    "min_value_min": 0, "min_value_max": total,
                    "second_min_value_min": second_range[0], "second_min_value_max": second_range[1],
                    "lowest_two_diff_min": 0, "lowest_two_diff_max": total,
                    "max_min_diff_min": spread[0], "max_min_diff_max": spread[1],
                    "allow_tie": True, "tie_count_min": 1, "tie_count_max": 4,
                    "rank_relations": rank,
                }
                if add(candidate):
                    return candidates
    for size in (2, 3):
        for value_range in value_ranges[:2]:
            groups = [
                {"min_value_min": value_range[0], "min_value_max": value_range[1]},
                {"max_min_diff_min": 0, "max_min_diff_max": total},
                {"lowest_two_diff_min": 0, "lowest_two_diff_max": 3},
            ][:size]
            if add({
                "min_groups": 1,
                "min_value_min": 0, "min_value_max": total,
                "second_min_value_min": 0, "second_min_value_max": total,
                "lowest_two_diff_min": 0, "lowest_two_diff_max": total,
                "max_min_diff_min": 0, "max_min_diff_max": total,
                "allow_tie": True, "tie_count_min": 1, "tie_count_max": 4,
                "and_conditions": groups,
            }):
                return candidates
    return candidates[:max(1, int(max_candidates))]


def generate_vip100_candidates(*, max_candidates: int = 128) -> list[dict[str, Any]]:
    """Generate the bounded candidate set used by the VIP100 MVP."""

    return generate_lab_candidates("VIP", max_candidates=max_candidates)


def _status_for_candidate(total: int, train: Mapping[str, Any], validation: Mapping[str, Any], minimum_trigger: int) -> tuple[str, str]:
    if total < 100 or train["matched_periods"] < minimum_trigger or train["valid_samples"] < minimum_trigger:
        return "样本不足", f"训练触发 {train['matched_periods']}，最低要求 {minimum_trigger}"
    if validation["valid_samples"] == 0:
        return "样本不足", "验证集没有有效触发样本"
    difference = abs(validation["hit_rate"] - train["hit_rate"]) if train["hit_rate"] is not None and validation["hit_rate"] is not None else 0
    if difference >= 15:
        return "训练/验证差异较大", f"训练/验证命中率差 {difference:.2f}%"
    return "进入样本外验证", "训练通过最低样本要求，验证集仅用于评估"


def run_strategy_lab_scan(
    records: Iterable[Mapping[str, Any]],
    *,
    source_type: str,
    max_candidates: int = 128,
    minimum_trigger: int = 5,
    train_ratio: float = 0.7,
) -> dict[str, Any]:
    """Run train filtering, then one-way validation and adaptive Walk-Forward."""

    raw = list(records)
    prepared = prepare_backtest_records(raw, source_type)
    data_digest = dataset_hash(prepared, source_type=source_type)
    plan = choose_lab_plan(len(prepared))
    train_rows, validation_rows = split_train_validation(prepared, train_ratio, source_type=source_type)
    generated = generate_lab_candidates(source_type, max_candidates=max_candidates)
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    training_passed = 0
    validation_tested = 0
    extra_cache: dict[str, tuple] = {}
    for index, conditions in enumerate(generated, start=1):
        key = condition_key(conditions)
        if key in seen:
            continue
        seen.add(key)
        extra_cache[key] = _lab_extra_conditions(conditions)
        train = run_condition_backtest(train_rows, conditions, source_type=source_type, min_sample_size=minimum_trigger, extra_conditions=extra_cache[key])
        validation = run_condition_backtest(validation_rows, conditions, source_type=source_type, min_sample_size=minimum_trigger, extra_conditions=extra_cache[key])
        status, status_reason = _status_for_candidate(len(prepared), train, validation, minimum_trigger)
        passed = train["matched_periods"] >= minimum_trigger and train["valid_samples"] >= minimum_trigger
        if passed:
            training_passed += 1
            validation_tested += 1
        walk_forward = None
        if passed and plan["train_window"] and plan["validation_window"]:
            walk_forward = run_walk_forward(
                prepared, conditions, train_window=plan["train_window"],
                validation_window=plan["validation_window"], step=plan["step"],
                source_type=source_type, min_sample_size=minimum_trigger,
                extra_conditions=extra_cache[key],
            )
        overall = run_condition_backtest(prepared, conditions, source_type=source_type, min_sample_size=minimum_trigger, extra_conditions=extra_cache[key])
        candidates.append({
            "candidate_index": index,
            "condition_key": key,
            "rule_hash": key,
            "conditions": conditions,
            "status": status,
            "status_reason": status_reason,
            "total_valid_data": len(prepared),
            "trigger_count": overall["matched_periods"],
            "trigger_ratio": round(overall["matched_periods"] / len(prepared) * 100, 2) if prepared else 0.0,
            "train": train,
            "validation": validation if passed else None,
            "overall": overall,
            "walk_forward": walk_forward,
            "validated": passed,
        })
    first_issue = prepared[0]["issue_no"] if prepared else None
    last_issue = prepared[-1]["issue_no"] if prepared else None
    now = datetime.now()
    run_id = f"LAB-{now.strftime('%Y%m%d%H%M%S%f')}-{data_digest[:12]}"
    manifest = {
        "run_id": run_id,
        "created_at": now.isoformat(timespec="seconds"),
        "dataset_hash": data_digest,
        "dataset_rows": len(prepared),
        "dataset_first_issue": first_issue,
        "dataset_last_issue": last_issue,
        "code_version": APP_VERSION,
        "generator_version": GENERATOR_VERSION,
        "random_seed": None,
        "train_start": train_rows[0]["issue_no"] if train_rows else None,
        "train_end": train_rows[-1]["issue_no"] if train_rows else None,
        "validation_start": validation_rows[0]["issue_no"] if validation_rows else None,
        "validation_end": validation_rows[-1]["issue_no"] if validation_rows else None,
        "holdout_start": None,
        "candidate_count": len(candidates),
        "status": "COMPLETED",
        "config": {
            "source_type": source_type,
            "max_candidates": max_candidates,
            "minimum_trigger": minimum_trigger,
            "train_ratio": train_ratio,
            "plan": plan,
        },
    }
    return {
        "run_id": run_id,
        "source_type": source_type,
        "dataset_hash": data_digest,
        "dataset_rows": len(prepared),
        "dataset_first_issue": first_issue,
        "dataset_last_issue": last_issue,
        "manifest": manifest,
        "plan": plan,
        "total_valid_data": len(prepared),
        "excluded_records": len(raw) - len(prepared),
        "generated_candidates": len(generated),
        "tested_candidates": len(candidates),
        "training_passed": training_passed,
        "validation_tested": validation_tested,
        "minimum_trigger": minimum_trigger,
        "train_ratio": train_ratio,
        "results": candidates,
        "selection_basis": "training_only",
    }


def _vip_candidate_sort_key(candidate: Mapping[str, Any]) -> tuple:
    """Sort candidates without changing their underlying backtest metrics."""

    validation = candidate.get("validation") or {}
    valid_samples = int(validation.get("valid_samples") or 0)
    hit_rate = validation.get("hit_rate")
    train = candidate.get("train") or {}
    train_rate = train.get("hit_rate")
    # Candidates without a training-qualified validation result remain visible,
    # but are placed after candidates that can be compared out of sample.
    return (
        -(float(candidate.get("composite_score") or 0.0)),
        1 if candidate.get("quality_status") == "WARNING_COVERAGE" else 0,
        0 if candidate.get("validated") and valid_samples else 1,
        -(float(hit_rate) if hit_rate is not None else -1.0),
        -valid_samples,
        -(float(train_rate) if train_rate is not None else -1.0),
        int(candidate.get("candidate_index") or 0),
    )


def _rolling_candidate_metrics(
    prepared: list[Mapping[str, Any]],
    conditions: Mapping[str, Any],
    *,
    extra_conditions: Iterable,
) -> dict[str, dict[str, Any]]:
    """Calculate recent performance over the last N input periods."""

    metrics: dict[str, dict[str, Any]] = {}
    for window in (30, 50, 100):
        rows = prepared[-window:]
        result = run_condition_backtest(
            rows,
            conditions,
            source_type="VIP",
            min_sample_size=1,
            extra_conditions=extra_conditions,
        )
        metrics[str(window)] = {
            "window": window,
            "trigger_count": result["matched_periods"],
            "hit_count": result["hits"],
            "miss_count": result["misses"],
            "hit_rate": result["hit_rate"],
            "max_consecutive_errors": result["max_consecutive_misses"],
            "details": result["details"],
        }
    return metrics


def _candidate_coverage_metrics(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Measure theoretical OR coverage for the combinations a candidate buys."""

    details = (candidate.get("overall") or {}).get("details", [])
    coverage_values: list[float] = []
    selected_sizes: list[int] = []
    for detail in details:
        selected = tuple(detail.get("selected") or ())
        if not selected:
            continue
        covered = sum(
            1 for actual in COMBINATIONS
            if any(combination_matches(combo, actual) for combo in selected)
        )
        coverage_values.append(covered / len(COMBINATIONS) * 100)
        selected_sizes.append(len(selected))
    coverage_rate = round(sum(coverage_values) / len(coverage_values), 2) if coverage_values else 0.0
    average_selected = round(sum(selected_sizes) / len(selected_sizes), 2) if selected_sizes else 0.0
    warning = coverage_rate >= 99.0 and average_selected >= 2.0
    if warning:
        risk = "HIGH"
        reason = "OR覆盖型策略：两个及以上组合的理论覆盖率达到100%"
    elif coverage_rate >= 90.0:
        risk = "MEDIUM"
        reason = "覆盖范围较宽"
    else:
        risk = "LOW"
        reason = "覆盖范围正常"
    return {
        "coverage_rate": coverage_rate,
        "average_selected_groups": average_selected,
        "coverage_warning": warning,
        "coverage_warning_reason": reason,
        "coverage_risk": risk,
    }


def _composite_score(candidate: Mapping[str, Any]) -> float:
    """Return a transparent MVP score for display ordering only."""

    validation = candidate.get("validation") or {}
    validation_rate = validation.get("hit_rate")
    recent = candidate.get("rolling") or {}
    recent_rates = [item["hit_rate"] for item in recent.values() if item.get("hit_rate") is not None]
    recent_rate = sum(recent_rates) / len(recent_rates) if recent_rates else 0.0
    sample_count = int(validation.get("valid_samples") or 0)
    sample_component = min(sample_count / 50.0, 1.0) * 20.0
    worst_miss_streak = max(
        (int(item.get("max_consecutive_errors") or 0) for item in recent.values()),
        default=0,
    )
    coverage_rate = float(candidate.get("coverage_rate") or 0.0)
    coverage_penalty = 30.0 if coverage_rate >= 99.0 else (12.0 if coverage_rate >= 90.0 else 0.0)
    score = (
        (float(validation_rate) if validation_rate is not None else 0.0) * 0.5
        + recent_rate * 0.3
        + sample_component
        - min(worst_miss_streak, 10) * 1.5
        - coverage_penalty
    )
    return round(max(0.0, score), 2)


def run_vip100_strategy_search(
    records: Iterable[Mapping[str, Any]],
    *,
    max_candidates: int = 128,
    minimum_trigger: int = 5,
    top_n: int = 10,
) -> dict[str, Any]:
    """Run the MVP search against VIP100 using a fixed chronological 70/30 split.

    The existing scan remains the source of truth for candidate evaluation. This
    wrapper only fixes the source and split for the MVP, then adds deterministic
    ranking and a bounded TOP view.
    """

    raw = list(records)
    prepared = prepare_backtest_records(raw, "VIP")
    result = run_strategy_lab_scan(
        raw,
        source_type="VIP",
        max_candidates=max_candidates,
        minimum_trigger=minimum_trigger,
        train_ratio=0.7,
    )
    for candidate in result["results"]:
        candidate["rolling"] = _rolling_candidate_metrics(
            prepared,
            candidate["conditions"],
            extra_conditions=_lab_extra_conditions(candidate["conditions"]),
        )
        candidate.update(_candidate_coverage_metrics(candidate))
        candidate["composite_score"] = _composite_score(candidate)
        validation_samples = int((candidate.get("validation") or {}).get("valid_samples") or 0)
        if candidate["coverage_warning"]:
            candidate["quality_status"] = "WARNING_COVERAGE"
        elif validation_samples < 30:
            candidate["quality_status"] = "SMALL_SAMPLE"
        elif not candidate.get("validated"):
            candidate["quality_status"] = "OBSERVE"
        else:
            candidate["quality_status"] = "NORMAL"
        candidate["legacy_status"] = candidate.get("status")
        candidate["status"] = candidate["quality_status"]
    ordered = sorted(result["results"], key=_vip_candidate_sort_key)
    limit = max(1, int(top_n))
    for rank, candidate in enumerate(ordered, start=1):
        candidate["rank"] = rank
    result["results"] = ordered
    result["top_n"] = min(limit, len(ordered))
    result["top_strategies"] = ordered[:limit]
    result["selection_basis"] = "validation_hit_rate_then_sample_size"
    result["train_ratio"] = 0.7
    result["validation_ratio"] = 0.3
    result["vip_only"] = True
    result["manifest"]["config"].update({
        "search_type": "VIP100_AUTOMATIC_STRATEGY_MVP",
        "top_n": limit,
    })
    return result


def evaluate_forward_profile(profile: Mapping[str, Any], records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate only rows after the frozen issue; conditions are immutable."""

    frozen = str(profile["frozen_at_issue"])
    source = str(profile["source_type"])
    conditions = profile["conditions"]
    rows = [
        row for row in prepare_backtest_records(records, source)
        if issue_sort_key(row["issue_no"]) > issue_sort_key(frozen)
    ]
    result = run_condition_backtest(rows, conditions, source_type=source, min_sample_size=1, extra_conditions=_lab_extra_conditions(conditions))
    result["stage"] = "forward_test"
    result["frozen_at_issue"] = frozen
    result["conditions_frozen"] = True
    historical_rate = profile.get("validation", {}).get("hit_rate")
    if result["valid_samples"] == 0:
        result["status"] = "样本不足"
    elif historical_rate is not None and result["hit_rate"] is not None and historical_rate - result["hit_rate"] >= 15:
        result["status"] = "后续表现衰减"
    else:
        result["status"] = "持续观察"
    result["details"] = [dict(item, dataset="forward_test") for item in result["details"]]
    return result


class StrategyLabStore:
    """Independent SQLite store for laboratory runs and frozen profiles."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or (DATA_DIR / "strategy_lab.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS strategy_lab_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    dataset_hash TEXT NOT NULL,
                    dataset_rows INTEGER NOT NULL,
                    dataset_first_issue TEXT,
                    dataset_last_issue TEXT,
                    code_version TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    generator_version TEXT NOT NULL,
                    random_seed TEXT,
                    train_start TEXT,
                    train_end TEXT,
                    validation_start TEXT,
                    validation_end TEXT,
                    holdout_start TEXT,
                    candidate_count INTEGER NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lab_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    manifest_run_id TEXT,
                    source_type TEXT NOT NULL,
                    generated_candidates INTEGER NOT NULL,
                    tested_candidates INTEGER NOT NULL,
                    training_passed INTEGER NOT NULL,
                    validation_tested INTEGER NOT NULL,
                    plan_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lab_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    source_type TEXT NOT NULL,
                    candidate_key TEXT NOT NULL,
                    conditions_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, candidate_key),
                    FOREIGN KEY(run_id) REFERENCES lab_runs(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS strategy_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT NOT NULL UNIQUE,
                    profile_name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    source_type TEXT NOT NULL,
                    conditions_json TEXT NOT NULL,
                    frozen_at_issue TEXT NOT NULL,
                    training_stats_json TEXT NOT NULL,
                    validation_stats_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS strategy_forward_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    frozen_at_issue TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(strategy_id, frozen_at_issue),
                    FOREIGN KEY(strategy_id) REFERENCES strategy_profiles(strategy_id) ON DELETE CASCADE
                );
                """
            )
            # These migrations are additive and preserve existing laboratory
            # data. The formal prediction database is never opened here.
            self._ensure_column(db, "lab_runs", "manifest_run_id", "TEXT")
            for column, definition in (
                ("rule_hash", "TEXT"),
                ("rule_json", "TEXT"),
                ("trigger_count", "INTEGER"),
                ("hit_count", "INTEGER"),
                ("hit_rate", "REAL"),
                ("wilson_lower", "REAL"),
                ("wilson_upper", "REAL"),
                ("baseline_rate", "REAL"),
                ("lift", "REAL"),
                ("raw_p_value", "REAL"),
                ("fdr_q_value", "REAL"),
                ("reject_reason", "TEXT"),
                ("status", "TEXT"),
            ):
                self._ensure_column(db, "lab_candidates", column, definition)
            for column, definition in (
                ("rule_hash", "TEXT"),
                ("strategy_version_id", "TEXT"),
                ("dataset_hash_at_freeze", "TEXT"),
                ("freeze_config_json", "TEXT"),
            ):
                self._ensure_column(db, "strategy_profiles", column, definition)

    def save_run(self, result: Mapping[str, Any]) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        manifest = dict(result.get("manifest") or {})
        if not manifest:
            # Keep the store usable for callers that construct legacy-shaped
            # results directly, while still creating a complete manifest.
            digest = str(result.get("dataset_hash") or dataset_hash([], result.get("source_type")))
            manifest = {
                "run_id": str(result.get("run_id") or f"LAB-{now.replace(':', '').replace('-', '')}-{digest[:12]}"),
                "created_at": now,
                "dataset_hash": digest,
                "dataset_rows": int(result.get("dataset_rows") or result.get("total_valid_data") or 0),
                "dataset_first_issue": result.get("dataset_first_issue"),
                "dataset_last_issue": result.get("dataset_last_issue"),
                "code_version": APP_VERSION,
                "generator_version": GENERATOR_VERSION,
                "random_seed": None,
                "train_start": None,
                "train_end": None,
                "validation_start": None,
                "validation_end": None,
                "holdout_start": None,
                "candidate_count": len(result.get("results", [])),
                "status": "COMPLETED",
                "config": {},
            }
        with self.connect() as db:
            db.execute(
                "INSERT INTO strategy_lab_runs(run_id, created_at, dataset_hash, dataset_rows, dataset_first_issue, dataset_last_issue, code_version, config_json, generator_version, random_seed, train_start, train_end, validation_start, validation_end, holdout_start, candidate_count, status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    manifest["run_id"], manifest.get("created_at", now), manifest.get("dataset_hash", ""),
                    int(manifest.get("dataset_rows", 0)), manifest.get("dataset_first_issue"),
                    manifest.get("dataset_last_issue"), manifest.get("code_version", APP_VERSION),
                    json.dumps(manifest.get("config", {}), ensure_ascii=False, sort_keys=True),
                    manifest.get("generator_version", GENERATOR_VERSION), manifest.get("random_seed"),
                    manifest.get("train_start"), manifest.get("train_end"), manifest.get("validation_start"),
                    manifest.get("validation_end"), manifest.get("holdout_start"),
                    int(manifest.get("candidate_count", len(result.get("results", [])))), manifest.get("status", "COMPLETED"),
                ),
            )
            cursor = db.execute(
                "INSERT INTO lab_runs(manifest_run_id, source_type, generated_candidates, tested_candidates, training_passed, validation_tested, plan_json, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (manifest["run_id"], result["source_type"], result["generated_candidates"], result["tested_candidates"], result["training_passed"], result["validation_tested"], json.dumps(result["plan"], ensure_ascii=False, sort_keys=True), now),
            )
            run_id = int(cursor.lastrowid)
            for candidate in result["results"]:
                overall = candidate.get("overall") or {}
                conditions_json = json.dumps(candidate["conditions"], ensure_ascii=False, sort_keys=True)
                db.execute(
                    "INSERT INTO lab_candidates(run_id, source_type, candidate_key, conditions_json, result_json, created_at, rule_hash, rule_json, trigger_count, hit_count, hit_rate, wilson_lower, wilson_upper, baseline_rate, lift, raw_p_value, fdr_q_value, reject_reason, status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id, result["source_type"], candidate["condition_key"], conditions_json,
                        json.dumps(candidate, ensure_ascii=False), now, candidate.get("rule_hash", candidate["condition_key"]),
                        conditions_json, int(overall.get("matched_periods", candidate.get("trigger_count", 0) or 0)),
                        overall.get("hits"), overall.get("hit_rate"), None, None, None, None, None, None,
                        candidate.get("status_reason"), candidate.get("status"),
                    ),
                )
        return run_id

    def create_profile(
        self,
        profile_name: str,
        source_type: str,
        conditions: Mapping[str, Any],
        frozen_at_issue: str,
        training: Mapping[str, Any],
        validation: Mapping[str, Any],
        *,
        dataset_hash_at_freeze: str = "",
        freeze_config: Mapping[str, Any] | None = None,
        code_version: str = APP_VERSION,
    ) -> dict[str, Any]:
        normalized = canonical_conditions(conditions)
        content = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        hashed_rule = rule_hash(normalized)
        effective_freeze_config = dict(freeze_config or {})
        effective_freeze_config.setdefault("source_type", source_type)
        effective_freeze_config.setdefault("frozen_at_issue", str(frozen_at_issue))
        freeze_json = json.dumps(effective_freeze_config, ensure_ascii=False, sort_keys=True)
        version_id = strategy_version_id(
            hashed_rule,
            dataset_hash=dataset_hash_at_freeze,
            freeze_config=effective_freeze_config,
            code_version=code_version,
        )
        with self.connect() as db:
            previous = db.execute("SELECT * FROM strategy_profiles WHERE profile_name=? AND source_type=? ORDER BY version DESC LIMIT 1", (profile_name, source_type)).fetchone()
            if previous and previous["conditions_json"] == content and str(previous["dataset_hash_at_freeze"] or "") == str(dataset_hash_at_freeze or "") and str(previous["freeze_config_json"] or "{}") == freeze_json:
                item = dict(previous)
                item["conditions"] = json.loads(item.pop("conditions_json"))
                item["training"] = json.loads(item.pop("training_stats_json"))
                item["validation"] = json.loads(item.pop("validation_stats_json"))
                item["rule_hash"] = item.get("rule_hash") or hashed_rule
                item["strategy_version_id"] = item.get("strategy_version_id") or item.get("strategy_id")
                return item
            version = int(previous["version"]) + 1 if previous else 1
            strategy_id = version_id
            now = datetime.now().isoformat(timespec="seconds")
            db.execute(
                "INSERT INTO strategy_profiles(strategy_id, profile_name, version, source_type, conditions_json, frozen_at_issue, training_stats_json, validation_stats_json, created_at, rule_hash, strategy_version_id, dataset_hash_at_freeze, freeze_config_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (strategy_id, profile_name, version, source_type, content, str(frozen_at_issue), json.dumps(training, ensure_ascii=False), json.dumps(validation, ensure_ascii=False), now, hashed_rule, version_id, str(dataset_hash_at_freeze or ""), freeze_json),
            )
        return {"strategy_id": strategy_id, "strategy_version_id": version_id, "rule_hash": hashed_rule, "profile_name": profile_name, "version": version, "source_type": source_type, "conditions": normalized, "frozen_at_issue": str(frozen_at_issue), "training": dict(training), "validation": dict(validation), "dataset_hash_at_freeze": str(dataset_hash_at_freeze or ""), "freeze_config": effective_freeze_config}

    def save_forward_result(self, profile: Mapping[str, Any], result: Mapping[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO strategy_forward_results(strategy_id, source_type, frozen_at_issue, result_json, created_at) VALUES(?,?,?,?,?) ON CONFLICT(strategy_id, frozen_at_issue) DO UPDATE SET result_json=excluded.result_json, created_at=excluded.created_at",
                (profile["strategy_id"], profile["source_type"], profile["frozen_at_issue"], json.dumps(result, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
            )

    def list_profiles(self, source_type: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM strategy_profiles" + (" WHERE source_type=?" if source_type else "") + " ORDER BY id DESC", (source_type,) if source_type else ()).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["conditions"] = json.loads(item.pop("conditions_json"))
            item["training"] = json.loads(item.pop("training_stats_json"))
            item["validation"] = json.loads(item.pop("validation_stats_json"))
            result.append(item)
        return result


__all__ = [
    "StrategyLabStore", "canonical_conditions", "choose_lab_plan", "condition_key", "dataset_hash",
    "rule_hash", "strategy_version_id",
    "evaluate_forward_profile", "generate_lab_candidates", "generate_vip100_candidates",
    "run_strategy_lab_scan", "run_vip100_strategy_search",
]
