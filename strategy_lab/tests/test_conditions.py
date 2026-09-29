from strategy_lab.conditions import COMBINATION_CODES, StrategyConditionGenerator


def test_generator_is_deterministic_and_bounded_to_one_hundred():
    generator = StrategyConditionGenerator()
    first = generator.generate(500)
    second = generator.generate(500)
    assert len(first) == 100
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    assert all(
        item.params.get("min_groups") == 2
        or len(item.params.get("selected_groups", ())) == 2
        for item in first
    )


def test_generator_accepts_all_public_combination_codes():
    pairs = [("BD", "BS"), ("SD", "SS")]
    results = StrategyConditionGenerator().generate(100, specified_pairs=pairs)
    selected = {
        tuple(item.params["selected_groups"])
        for item in results
        if "selected_groups" in item.params
    }
    assert (COMBINATION_CODES["BD"], COMBINATION_CODES["BS"]) in selected
    assert (COMBINATION_CODES["SD"], COMBINATION_CODES["SS"]) in selected


def test_generator_rejects_invalid_pair():
    try:
        StrategyConditionGenerator().generate(specified_pairs=[("BD", "UNKNOWN")])
    except ValueError as exc:
        assert "无效双组合" in str(exc)
    else:
        raise AssertionError("invalid pair must be rejected")
