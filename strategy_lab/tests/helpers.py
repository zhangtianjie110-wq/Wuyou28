from __future__ import annotations


def make_records(count: int = 300) -> list[dict]:
    combinations = ("大单", "大双", "小单", "小双")
    records = []
    for index in range(1, count + 1):
        records.append(
            {
                "id": index,
                "issue_no": f"20260928{index:04d}",
                "source_type": "VIP",
                "big_single": 10 + index % 2,
                "big_double": 20 - index % 2,
                "small_single": 30,
                "small_double": 40,
                "actual_combo": combinations[index % len(combinations)],
                "status": "已完成",
            }
        )
    return records


def make_metrics(
    rate: float | None,
    *,
    samples: int = 100,
    triggers: int | None = None,
    misses: int = 5,
):
    from strategy_lab.models import EvaluationMetrics

    valid = samples if rate is not None else 0
    hits = round(valid * float(rate or 0) / 100)
    return EvaluationMetrics(
        total_samples=samples,
        trigger_count=samples if triggers is None else triggers,
        valid_samples=valid,
        hit_count=hits,
        hit_rate=rate,
        recent_30=rate,
        recent_50=rate,
        recent_100=rate,
        max_consecutive_hits=4,
        max_consecutive_misses=misses,
        average_trigger_interval=2.0,
    )


def make_candidate(
    condition_id: str = "LAB-1",
    *,
    train_rate: float = 65.0,
    validation_rate: float = 60.0,
    triggers: int = 100,
    samples: int = 100,
    misses: int = 5,
    walk_forward_rates: tuple[float, ...] = (60.0, 62.0),
):
    from strategy_lab.models import CandidateResult, StrategyCondition, WalkForwardWindow

    train = make_metrics(train_rate, samples=samples, triggers=triggers, misses=misses)
    validation = make_metrics(validation_rate, samples=samples, triggers=triggers, misses=misses)
    overall = make_metrics(validation_rate, samples=samples, triggers=triggers, misses=misses)
    windows = tuple(
        WalkForwardWindow(
            index=index,
            train_issue_range=("1", "200"),
            validation_issue_range=("201", "250"),
            train=train,
            validation=make_metrics(rate, samples=50, triggers=50, misses=misses),
        )
        for index, rate in enumerate(walk_forward_rates, start=1)
    )
    return CandidateResult(
        condition=StrategyCondition(
            condition_id,
            f"策略{condition_id}",
            {"min_groups": 2, "condition_id": condition_id},
        ),
        train=train,
        validation=validation,
        overall=overall,
        walk_forward=windows,
        score=train_rate,
        status="候选",
    )
