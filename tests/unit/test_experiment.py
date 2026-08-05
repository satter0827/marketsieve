from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from marketsieve import (
    BalancedMediumTermPolicy,
    ExperimentRun,
    ExperimentSpec,
    ReplayWindow,
    compare_experiments,
    run_experiment,
)
from marketsieve.data.daily import DailyBar
from marketsieve.synthetic.daily import JP_INSTRUMENT, fixture_bars


def bars() -> tuple[DailyBar, ...]:
    return fixture_bars(
        JP_INSTRUMENT,
        tuple(str(100 + index // 5) for index in range(300)),
        dataset="experiment-v1",
    )


def spec(data_id: str = "a" * 64) -> ExperimentSpec:
    policy = BalancedMediumTermPolicy()
    history = bars()
    return ExperimentSpec(
        policy.name,
        policy.version,
        policy.settings,
        ReplayWindow(history[199].trading_date, history[-1].trading_date),
        (("XTKS:7203", data_id),),
    )


def test_replay_is_deterministic_and_reports_non_profit_metrics() -> None:
    history = bars()
    policy = BalancedMediumTermPolicy()
    experiment = spec()

    first = run_experiment(experiment, policy, (("a" * 64, JP_INSTRUMENT, history),))
    second = run_experiment(experiment, policy, (("a" * 64, JP_INSTRUMENT, history),))

    assert first == second
    assert not experiment.is_profit_simulation
    assert len(first.run_id) == 64
    metrics = {item.name: item.value for item in first.metrics}
    assert metrics["decision_count"] == Decimal(101)
    assert Decimal(0) <= metrics["data_coverage"] <= Decimal(1)
    assert metrics["maximum_drawdown"] <= 0


def test_replay_excludes_bars_not_yet_available() -> None:
    history = bars()
    delayed = replace(history[100], available_at=history[-1].available_at + timedelta(days=1))
    delayed_bars = (*history[:100], delayed, *history[101:])

    run = run_experiment(
        spec(), BalancedMediumTermPolicy(), (("a" * 64, JP_INSTRUMENT, delayed_bars),)
    )

    assert run.decisions


def test_spec_requires_complete_costs_and_exact_datasets() -> None:
    with pytest.raises(ValueError, match="together"):
        replace(spec(), execution_costs=(("commission_rate", "0.001"),))

    history = bars()
    with pytest.raises(ValueError, match="datasets"):
        run_experiment(spec(), BalancedMediumTermPolicy(), (("b" * 64, JP_INSTRUMENT, history),))

    complete = replace(
        spec(),
        execution_costs=(
            ("commission_rate", "0.001"),
            ("fx_cost_rate", "0.002"),
            ("tax_rate", "0.2"),
        ),
    )
    assert complete.is_profit_simulation


def test_contract_rejects_invalid_windows_specs_policies_and_bars() -> None:
    history = bars()
    with pytest.raises(ValueError, match="ascending"):
        ReplayWindow(history[-1].trading_date, history[0].trading_date)
    with pytest.raises(ValueError, match="dataset"):
        replace(spec(), datasets=())
    with pytest.raises(ValueError, match="policy"):
        run_experiment(
            replace(spec(), policy_version="different"),
            BalancedMediumTermPolicy(),
            (("a" * 64, JP_INSTRUMENT, history),),
        )
    with pytest.raises(ValueError, match="bars"):
        run_experiment(
            spec(),
            BalancedMediumTermPolicy(),
            (("a" * 64, JP_INSTRUMENT, tuple(reversed(history))),),
        )
    with pytest.raises(ValueError, match="no observations"):
        run_experiment(
            replace(
                spec(),
                window=ReplayWindow(
                    history[-1].trading_date + timedelta(days=10),
                    history[-1].trading_date + timedelta(days=20),
                ),
            ),
            BalancedMediumTermPolicy(),
            (("a" * 64, JP_INSTRUMENT, history),),
        )


def test_comparison_uses_right_minus_left() -> None:
    history = bars()
    left = run_experiment(spec(), BalancedMediumTermPolicy(), (("a" * 64, JP_INSTRUMENT, history),))
    right = run_experiment(
        spec(),
        BalancedMediumTermPolicy(),
        (
            (
                "a" * 64,
                JP_INSTRUMENT,
                tuple(
                    replace(
                        item,
                        open=item.open + 1,
                        high=item.high + 1,
                        low=item.low + 1,
                        close=item.close + 1,
                    )
                    for item in history
                ),
            ),
        ),
    )

    comparison = compare_experiments(left, right)

    assert comparison.left_run_id == left.run_id
    assert comparison.right_run_id == right.run_id
    assert {item.name for item in comparison.metric_deltas} == {item.name for item in left.metrics}
    incompatible = replace(right, metrics=right.metrics[:-1])
    with pytest.raises(ValueError, match="incompatible"):
        compare_experiments(left, incompatible)
    with pytest.raises(ValueError, match="SHA-256"):
        ExperimentRun("bad", left.spec, left.decisions, left.metrics)


def test_experiment_value_objects_reject_ambiguous_or_invalid_values() -> None:
    policy = BalancedMediumTermPolicy()
    history = bars()
    with pytest.raises(TypeError, match="dates"):
        ReplayWindow(history[0].available_at, history[-1].trading_date)
    with pytest.raises(ValueError, match="identity"):
        replace(spec(), policy_name="")
    with pytest.raises(ValueError, match="unique sorted"):
        replace(spec(), datasets=(("B", "1"), ("A", "2")))
    with pytest.raises(ValueError, match="between zero and one"):
        replace(
            spec(),
            execution_costs=(
                ("commission_rate", "2"),
                ("fx_cost_rate", "0"),
                ("tax_rate", "0"),
            ),
        )
    with pytest.raises(ValueError, match="finite and identified"):
        replace(
            run_experiment(spec(), policy, (("a" * 64, JP_INSTRUMENT, history),)).metrics[0],
            name="",
        )
    with pytest.raises(ValueError, match="unique sorted"):
        valid = run_experiment(spec(), policy, (("a" * 64, JP_INSTRUMENT, history),))
        replace(valid, metrics=tuple(reversed(valid.metrics)))
