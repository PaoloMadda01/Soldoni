import pytest
from datetime import date
from soldoni.core.models import OpType, Transaction
from soldoni.core.holdings import build_portfolio_state


def _tx(d, isin, op, qty, amount, comm=0.0):
    return Transaction(
        trade_date=date(2026, 1, d), value_date=date(2026, 1, d), isin=isin,
        op_type=op, quantity=qty, amount_eur=amount, price_native=0.0,
        fx_rate=1.0, commission_eur=comm,
    )


def test_weighted_average_cost_and_realized_gain():
    txs = [
        _tx(1, "X", OpType.BUY, 10, 1000.0, 2.95),
        _tx(2, "X", OpType.BUY, 10, 1200.0, 2.95),
        _tx(3, "X", OpType.SELL, 5, 700.0, 2.95),
    ]
    state = build_portfolio_state(txs)

    pos = state.positions["X"]
    assert pos.quantity == 15
    assert round(pos.total_cost_eur, 3) == 1654.425
    assert round(pos.avg_cost_eur, 3) == 110.295

    assert len(state.realized_sales) == 1
    sale = state.realized_sales[0]
    assert sale.quantity == 5
    assert round(sale.proceeds_eur, 2) == 697.05
    assert round(sale.cost_basis_eur, 3) == 551.475
    assert round(sale.gain_eur, 3) == 145.575


def test_dividend_does_not_change_position():
    txs = [
        _tx(1, "X", OpType.BUY, 10, 1000.0, 2.95),
        _tx(2, "X", OpType.DIVIDEND, 10, 33.19, 0.0),
    ]
    state = build_portfolio_state(txs)
    assert state.positions["X"].quantity == 10
    assert round(state.positions["X"].total_cost_eur, 2) == 1002.95
    assert state.realized_sales == []


def test_oversell_raises_in_strict_mode():
    txs = [_tx(1, "X", OpType.SELL, 5, 700.0, 2.95)]
    with pytest.raises(ValueError, match="storico acquisti incompleto"):
        build_portfolio_state(txs)


def test_oversell_skipped_in_tolerant_mode():
    txs = [
        _tx(1, "X", OpType.BUY, 10, 1000.0, 2.95),
        _tx(2, "Y", OpType.SELL, 5, 700.0, 2.95),  # vendita orfana di Y
    ]
    state = build_portfolio_state(txs, on_oversell="skip")
    assert state.realized_sales == []          # vendita orfana saltata
    assert "Y" not in state.positions
    assert state.positions["X"].quantity == 10  # il resto resta corretto
    assert len(state.warnings) == 1
    assert "Y" in state.warnings[0]
