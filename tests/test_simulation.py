import pytest
import pandas as pd


def test_stress_portfolio_calculates_impact_for_all_positions():
    from soldoni.core.simulation import stress_portfolio

    result = stress_portfolio(
        {"A": 600.0, "B": 400.0}, {"A": -0.20, "B": 0.10})

    assert result.coverage == pytest.approx(1.0)
    assert result.impact_eur == pytest.approx(-80.0)
    assert result.stressed_covered_value_eur == pytest.approx(920.0)


def test_stress_portfolio_reports_partial_coverage_without_inventing_shocks():
    from soldoni.core.simulation import stress_portfolio

    result = stress_portfolio({"A": 600.0, "B": 400.0}, {"A": -0.20})

    assert result.coverage == pytest.approx(0.6)
    assert result.covered_value_eur == pytest.approx(600.0)
    assert result.stressed_covered_value_eur == pytest.approx(480.0)
    assert [line.isin for line in result.lines] == ["A"]


def test_stress_portfolio_rejects_loss_below_minus_one_hundred_percent():
    from soldoni.core.simulation import stress_portfolio

    with pytest.raises(ValueError, match="-100%"):
        stress_portfolio({"A": 100.0}, {"A": -1.01})


def test_months_to_target_without_return_is_hand_calculable():
    from soldoni.core.simulation import months_to_target

    assert months_to_target(
        initial_value_eur=0.0,
        monthly_contribution_eur=1000.0,
        target_eur=12000.0,
        annual_return=0.0,
        annual_inflation=0.0,
        target_in_today_euros=False,
        max_months=24,
    ) == 12


def test_months_to_target_returns_zero_when_already_reached():
    from soldoni.core.simulation import months_to_target

    assert months_to_target(1_000_000.0, 0.0, 1_000_000.0, 0.05) == 0


def test_months_to_target_returns_none_inside_insufficient_horizon():
    from soldoni.core.simulation import months_to_target

    assert months_to_target(0.0, 100.0, 2000.0, 0.0, max_months=12) is None


def test_simulate_goal_zero_volatility_has_deterministic_result():
    from soldoni.core.simulation import simulate_goal

    result = simulate_goal(
        initial_value_eur=0.0,
        monthly_contribution_eur=100.0,
        target_eur=1200.0,
        expected_annual_return=0.0,
        annual_volatility=0.0,
        annual_inflation=0.0,
        years=1,
        simulations=20,
        seed=7,
    )

    assert result.success_probability == pytest.approx(1.0)
    assert result.p10_goal_month == 12
    assert result.median_goal_month == 12
    assert result.p90_goal_month == 12
    assert result.median_values_eur[-1] == pytest.approx(1200.0)


def test_simulate_goal_reports_unreached_percentiles_as_none():
    from soldoni.core.simulation import simulate_goal

    result = simulate_goal(
        initial_value_eur=0.0,
        monthly_contribution_eur=100.0,
        target_eur=2000.0,
        expected_annual_return=0.0,
        annual_volatility=0.0,
        annual_inflation=0.0,
        years=1,
        simulations=20,
        seed=7,
    )

    assert result.success_probability == 0.0
    assert result.p10_goal_month is None
    assert result.median_goal_month is None
    assert result.p90_goal_month is None


def test_simulate_goal_is_reproducible_with_same_seed():
    from soldoni.core.simulation import simulate_goal

    args = dict(
        initial_value_eur=100_000.0,
        monthly_contribution_eur=1000.0,
        target_eur=1_000_000.0,
        expected_annual_return=0.06,
        annual_volatility=0.15,
        annual_inflation=0.02,
        years=30,
        simulations=50,
        seed=42,
    )

    assert simulate_goal(**args) == simulate_goal(**args)


def test_historical_assumptions_annualizes_total_return():
    from soldoni.core.simulation import historical_assumptions

    values = pd.Series(
        [100.0, 121.0],
        index=pd.to_datetime(["2024-01-01 00:00", "2025-12-31 12:00"]),
    )

    result = historical_assumptions(values)

    assert result.annual_return == pytest.approx(0.10)
    assert result.start_date.isoformat() == "2024-01-01"
    assert result.end_date.isoformat() == "2025-12-31"


def test_historical_assumptions_constant_series_has_zero_volatility():
    from soldoni.core.simulation import historical_assumptions

    dates = pd.bdate_range("2025-01-01", "2026-01-01")
    result = historical_assumptions(pd.Series(100.0, index=dates))

    assert result.annual_return == pytest.approx(0.0)
    assert result.annual_volatility == pytest.approx(0.0)


def test_historical_assumptions_rejects_less_than_one_year():
    from soldoni.core.simulation import historical_assumptions

    values = pd.Series(
        [100.0, 110.0],
        index=pd.to_datetime(["2025-01-01", "2025-12-31"]),
    )

    with pytest.raises(ValueError, match="almeno un anno"):
        historical_assumptions(values)
