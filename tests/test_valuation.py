import pandas as pd
import pytest
from datetime import date
from soldoni.core import valuation
from soldoni.core.models import OpType, Transaction
from soldoni.core.valuation import (
    quantity_timeline, portfolio_value_eur,
    invested_timeline, drawdown, monthly_net_invested)


def _buy(d, isin, qty):
    return Transaction(date(2026, 1, d), date(2026, 1, d), isin, OpType.BUY,
                       qty, 0.0, 0.0, 1.0, 0.0)


def test_quantity_timeline_cumulative_forward_fill():
    txs = [_buy(1, "X", 10), _buy(3, "X", 5)]
    dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"])
    qt = quantity_timeline(txs, dates)
    assert list(qt["X"]) == [10, 10, 15]


def test_portfolio_value_eur():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    qty = pd.DataFrame({"X": [10, 10]}, index=dates)
    prices = pd.DataFrame({"X": [100.0, 110.0]}, index=dates)
    val = portfolio_value_eur(qty, prices)
    assert list(val) == [1000.0, 1100.0]


def _tx(month, day, isin, op, amount):
    return Transaction(date(2026, month, day), date(2026, month, day), isin, op,
                       1.0, amount, 0.0, 1.0, 0.0)


def test_invested_timeline_cumsum():
    cf = pd.Series([100.0, 0.0, 50.0],
                   index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]))
    assert list(invested_timeline(cf)) == [100.0, 100.0, 150.0]


def test_drawdown_basic():
    s = pd.Series([100.0, 120.0, 90.0, 130.0])
    dd = drawdown(s)
    assert round(dd.iloc[0], 4) == 0.0
    assert round(dd.iloc[1], 4) == 0.0                      # nuovo massimo
    assert round(dd.iloc[2], 4) == round(90.0 / 120.0 - 1.0, 4)   # -0.25
    assert round(dd.iloc[3], 4) == 0.0                      # nuovo massimo


def test_drawdown_monotonic_increasing_all_zero():
    s = pd.Series([100.0, 110.0, 120.0])
    assert (drawdown(s) == 0.0).all()


def test_drawdown_empty():
    assert drawdown(pd.Series(dtype=float)).empty


def test_monthly_net_invested_groups_and_signs():
    txs = [
        _tx(1, 5, "A", OpType.BUY, 1000.0),
        _tx(1, 20, "B", OpType.BUY, 500.0),
        _tx(2, 10, "A", OpType.SELL, 300.0),
        _tx(2, 15, "A", OpType.DIVIDEND, 50.0),
    ]
    out = monthly_net_invested(txs)
    assert out[pd.Timestamp("2026-01-01")] == 1500.0
    assert out[pd.Timestamp("2026-02-01")] == -300.0        # vendita; dividendo ignorato


def test_monthly_net_invested_only_dividends_empty():
    txs = [_tx(1, 1, "A", OpType.DIVIDEND, 50.0)]
    assert monthly_net_invested(txs).empty


def _cash_tx(year, month, day, op, amount, commission=0.0):
    return Transaction(date(year, month, day), date(year, month, day), "A", op,
                       1.0, amount, 0.0, 1.0, commission)


def test_average_monthly_purchases_uses_complete_months_and_counts_zero_months():
    txs = [
        _cash_tx(2026, 1, 10, OpType.BUY, 300.0, 3.0),
        _cash_tx(2026, 3, 10, OpType.BUY, 600.0, 3.0),
        _cash_tx(2026, 4, 10, OpType.BUY, 900.0, 3.0),
    ]

    result = valuation.average_monthly_purchases(
        txs, as_of=date(2026, 4, 15), months=3)

    assert result == pytest.approx(302.0)


def test_average_monthly_purchases_ignores_sales_and_dividends():
    txs = [
        _cash_tx(2026, 1, 10, OpType.BUY, 200.0, 2.0),
        _cash_tx(2026, 2, 10, OpType.SELL, 100.0, 1.0),
        _cash_tx(2026, 2, 15, OpType.DIVIDEND, 50.0),
    ]

    result = valuation.average_monthly_purchases(
        txs, as_of=date(2026, 3, 15), months=2)

    assert result == pytest.approx(101.0)


def test_average_monthly_purchases_without_buys_is_zero():
    txs = [
        _cash_tx(2026, 1, 10, OpType.SELL, 100.0),
        _cash_tx(2026, 2, 15, OpType.DIVIDEND, 50.0),
    ]

    result = valuation.average_monthly_purchases(
        txs, as_of=date(2026, 3, 15), months=2)

    assert result == 0.0


def test_average_monthly_purchases_rejects_non_positive_window():
    with pytest.raises(ValueError, match="positivo"):
        valuation.average_monthly_purchases([], as_of=date(2026, 3, 15), months=0)
