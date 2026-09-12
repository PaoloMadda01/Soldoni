import pytest

from soldoni.data import store


def _trades_by_isin(lines):
    return {line.isin: line.trade_eur for line in lines}


def test_validate_target_weights_requires_exactly_one_hundred_percent():
    from soldoni.core.rebalancing import validate_target_weights

    validate_target_weights({"A": 0.6, "B": 0.4})

    with pytest.raises(ValueError, match="100%"):
        validate_target_weights({"A": 0.6, "B": 0.3})
    with pytest.raises(ValueError, match="negativo"):
        validate_target_weights({"A": 1.1, "B": -0.1})


def test_rebalance_trades_uses_value_after_new_cash():
    from soldoni.core.rebalancing import rebalance_trades

    lines = rebalance_trades(
        {"A": 70.0, "B": 30.0}, {"A": 0.5, "B": 0.5}, new_cash_eur=20.0)

    assert _trades_by_isin(lines) == pytest.approx({"A": -10.0, "B": 30.0})
    assert sum(line.trade_eur for line in lines) == pytest.approx(20.0)


def test_allocate_contribution_never_sells_overweight_positions():
    from soldoni.core.rebalancing import allocate_contribution

    lines = allocate_contribution(
        {"A": 70.0, "B": 30.0}, {"A": 0.5, "B": 0.5}, new_cash_eur=20.0)

    assert _trades_by_isin(lines) == pytest.approx({"A": 0.0, "B": 20.0})
    assert all(line.trade_eur >= 0.0 for line in lines)


def test_allocate_contribution_from_empty_portfolio_follows_targets():
    from soldoni.core.rebalancing import allocate_contribution

    lines = allocate_contribution(
        {"A": 0.0, "B": 0.0}, {"A": 0.75, "B": 0.25}, new_cash_eur=1000.0)

    assert _trades_by_isin(lines) == pytest.approx({"A": 750.0, "B": 250.0})


def test_estimate_trade_costs_taxes_only_realized_gain_fraction():
    from soldoni.core.rebalancing import estimate_trade_costs

    result = estimate_trade_costs(
        trades_eur={"A": -500.0, "B": 200.0},
        current_values_eur={"A": 1000.0, "B": 400.0},
        cost_basis_eur={"A": 800.0, "B": 350.0},
        commission_per_trade_eur=2.95,
        tax_rate=0.26,
    )

    assert result.commissions_eur == pytest.approx(5.90)
    assert result.estimated_tax_eur == pytest.approx(25.233)
    assert result.total_eur == pytest.approx(31.133)


def test_allocation_targets_replace_previous_values(tmp_path):
    conn = store.init_db(str(tmp_path / "targets.db"))

    store.replace_allocation_targets(conn, {"A": 0.6, "B": 0.4})
    assert store.get_allocation_targets(conn) == {"A": 0.6, "B": 0.4}

    store.replace_allocation_targets(conn, {"A": 1.0})
    assert store.get_allocation_targets(conn) == {"A": 1.0}


def test_invalid_allocation_targets_do_not_replace_saved_values(tmp_path):
    conn = store.init_db(str(tmp_path / "targets.db"))
    store.replace_allocation_targets(conn, {"A": 0.6, "B": 0.4})

    with pytest.raises(ValueError, match="100%"):
        store.replace_allocation_targets(conn, {"A": 0.6, "B": 0.3})

    assert store.get_allocation_targets(conn) == {"A": 0.6, "B": 0.4}
