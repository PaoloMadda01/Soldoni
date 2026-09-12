from datetime import date

import pandas as pd
import pytest

from soldoni.core.models import Instrument, OpType, Transaction
from soldoni.core.portfolio_comparison import (
    group_portfolio_transactions, portfolio_group_index, compare_portfolio_histories,
    portfolio_prices_eur)


def tx(day, isin="E", operation=OpType.BUY, quantity=1.0, amount=100.0, fee=0.0):
    traded = date(2026, 1, day)
    return Transaction(traded, traded, isin, operation, quantity, amount, amount, 1.0, fee)


def prices(values, first="2026-01-01"):
    return pd.DataFrame(values,
                        index=pd.date_range(first, periods=len(next(iter(values.values())))))


def test_grouping_keeps_sold_instruments_and_legacy_stocks_but_respects_exclusions():
    instruments = {
        isin: Instrument(isin, isin, isin, "EUR", kind, "Europa", excluded=excluded)
        for isin, kind, excluded in (
            ("E", "etf", False), ("A", "azione", False), ("S", "stock", False),
            ("X", "etf", True), ("B", "obbligazione", False))
    }
    transactions = [tx(2, isin) for isin in instruments]
    transactions.append(tx(3, operation=OpType.SELL, amount=110.0))
    groups = group_portfolio_transactions(transactions, instruments)
    assert [item.isin for item in groups["I miei ETF"]] == ["E", "E"]
    assert {item.isin for item in groups["Le mie azioni"]} == {"A", "S"}


def test_missing_instrument_metadata_cannot_silently_remove_an_investment():
    with pytest.raises(ValueError, match="anagrafica"):
        group_portfolio_transactions([tx(2)], {})


def test_sold_holding_contributes_until_exit_without_requiring_later_quotes():
    transactions = [tx(2), tx(2, "A"), tx(4, operation=OpType.SELL, amount=120.0)]
    close = prices({"E": [None, 100., 110., None, None], "A": [None, 100., 100., 100., 100.]})
    index = portfolio_group_index(transactions, close)
    assert index.tolist() == pytest.approx([100.0, 100.0, 105.0, 110.0, 110.0])


def test_new_invested_money_is_not_counted_as_performance():
    transactions = [tx(2), tx(3, quantity=9.0, amount=990.0)]
    index = portfolio_group_index(transactions, prices({"E": [None, 100., 110., 121.]}))
    assert index.tolist() == pytest.approx([100.0, 100.0, 110.0, 121.0])


def test_first_purchase_commission_is_included():
    index = portfolio_group_index([tx(2, fee=1.0)], prices({"E": [None, 100., 100.]}))
    assert index.iloc[0] == 100.0
    assert index.iloc[-1] == pytest.approx(99.00990099)


@pytest.mark.parametrize("operation, quantity, amount, quote", [
    (OpType.DIVIDEND, 0.0, 10.0, 100.0),
    (OpType.SELL, 1.0, 110.0, None),
])
def test_first_day_dividend_or_sale_uses_the_full_purchase_capital(
    operation, quantity, amount, quote,
):
    transactions = [tx(2), tx(2, operation=operation, quantity=quantity, amount=amount)]
    index = portfolio_group_index(transactions, prices({"E": [None, quote, quote]}))
    assert index.tolist() == pytest.approx([100.0, 110.0, 110.0])


def test_cash_dividend_offsets_price_drop_once_and_fees_reduce_return():
    transactions = [tx(2), tx(3, operation=OpType.DIVIDEND, quantity=0.0, amount=10.0),
                    tx(4, operation=OpType.SELL, amount=90.0, fee=1.0)]
    index = portfolio_group_index(transactions, prices({"E": [None, 100., 90., None]}))
    assert index.tolist() == pytest.approx([100.0, 100.0, 100.0, 98.88888889])


def test_full_sale_idle_days_and_reentry_preserve_previous_performance():
    transactions = [tx(2), tx(3, operation=OpType.SELL, amount=110.0),
                    tx(5, "B", quantity=2.0, amount=200.0)]
    index = portfolio_group_index(transactions, prices({
        "E": [None, 100., None, None, None, None],
        "B": [None, None, None, None, 100., 110.],
    }))
    assert index.tolist() == pytest.approx([100.0, 100.0, 110.0, 110.0, 110.0, 121.0])


@pytest.mark.parametrize("close", [
    prices({"OTHER": [1., 1., 1.]}),
    prices({"E": [None, None, 100.]}),
    prices({"E": [None, float("inf"), 100.]}),
    prices({"E": [None, -1., 100.]}),
])
def test_missing_or_invalid_held_prices_prevent_a_partial_total(close):
    with pytest.raises(ValueError, match="[Pp]rezz"):
        portfolio_group_index([tx(2)], close)


def test_sale_without_imported_purchase_is_reported():
    with pytest.raises(ValueError, match="acquisti|negativa"):
        portfolio_group_index([tx(2, operation=OpType.SELL)], prices({"E": [100., 100.]}))


def test_long_gap_in_held_quotes_is_not_filled_with_an_old_price():
    close = prices({"E": [None, 100.] + [None] * 9 + [110.]})
    with pytest.raises(ValueError, match="[Pp]rezz"):
        portfolio_group_index([tx(2)], close)


def test_dividend_after_complete_exit_has_no_invented_return():
    transactions = [tx(2), tx(3, operation=OpType.SELL),
                    tx(4, operation=OpType.DIVIDEND, quantity=0.0, amount=5.0)]
    with pytest.raises(ValueError, match="capitale"):
        portfolio_group_index(transactions, prices({"E": [None, 100., 100., None]}))


def test_common_period_rebases_later_start_and_limits_to_benchmark_coverage():
    dates = pd.date_range("2026-01-01", periods=5)
    histories = {
        "Le mie azioni": pd.Series([100., 200., 220., 198., 230.], index=dates),
        "I miei ETF": pd.Series([100., 120., 125.], index=dates[2:]),
        "S&P 500": pd.Series([100., 105., 110., 121.], index=dates[:4]),
    }
    common, summary = compare_portfolio_histories(histories)
    assert list(common.index) == list(dates[2:4])
    assert common.iloc[0].tolist() == pytest.approx([100., 100., 100.])
    assert common.iloc[-1].tolist() == pytest.approx([90., 120., 110.])
    assert summary.loc["Le mie azioni", "Calo massimo %"] == pytest.approx(-10.0)
    assert summary.loc["I miei ETF", "Rendimento %"] == pytest.approx(20.0)
    assert summary.loc["I miei ETF", "Vantaggio S&P 500 (p.p.)"] == pytest.approx(10.0)


def test_missing_benchmark_still_allows_etfs_and_stocks_to_be_compared():
    dates = pd.date_range("2026-01-01", periods=2)
    common, summary = compare_portfolio_histories({
        "I miei ETF": pd.Series([100., 110.], index=dates),
        "Le mie azioni": pd.Series([100., 90.], index=dates),
    })
    assert len(common.columns) == 2
    assert summary["Vantaggio S&P 500 (p.p.)"].isna().all()


def test_non_overlapping_histories_have_no_winner():
    with pytest.raises(ValueError, match="comun"):
        compare_portfolio_histories({
            "I miei ETF": pd.Series([100., 110.], index=pd.date_range("2026-01-01", periods=2)),
            "Le mie azioni": pd.Series([100., 90.], index=pd.date_range("2026-02-01", periods=2)),
        })


def test_currency_conversion_uses_only_known_exchange_rates_and_their_actual_coverage():
    dates = pd.date_range("2026-01-01", periods=5)
    native = pd.Series([100., 100., 100., 100., 100.], index=dates)
    exchange = pd.Series([2., 4.], index=dates[[1, 3]])
    converted = portfolio_prices_eur(native, exchange)
    assert list(converted.index) == list(dates[1:4])
    assert converted.tolist() == pytest.approx([50., 50., 25.])


@pytest.mark.parametrize("rate", [0.0, -1.0, float("inf")])
def test_invalid_exchange_rate_is_reported(rate):
    dates = pd.date_range("2026-01-01", periods=2)
    with pytest.raises(ValueError, match="[Cc]ambi"):
        portfolio_prices_eur(pd.Series([100., 100.], index=dates),
                             pd.Series([rate, rate], index=dates))


def test_loader_uses_previous_quote_when_the_initial_benchmark_date_is_a_weekend(monkeypatch):
    from soldoni.app import dashboard
    from soldoni.data import store

    instrument = Instrument("E", "E", "ETF", "EUR", "etf", "Europa")
    close = pd.Series([200., 220., 240.],
                      index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]))
    monkeypatch.setattr(dashboard.prices, "get_price_history", lambda *args:
                        pd.DataFrame({"close": close, "adj_close": close}))
    monkeypatch.setattr(dashboard.prices, "get_fx_history", lambda *args:
                        pd.Series(2.0, index=close.index))
    conn = store.init_db(":memory:")
    try:
        data = dashboard._load_portfolio_comparison(
            conn, {"I miei ETF": [tx(5, amount=220.)]}, {"E": instrument})
    finally:
        conn.close()
    benchmark = data["histories"]["S&P 500"]
    assert benchmark.index.min() == pd.Timestamp("2026-01-04")
    assert benchmark.tolist() == pytest.approx([100., 110., 120.])


def test_fx_change_is_applied_before_a_purchase_on_a_day_without_a_local_quote():
    dates = pd.date_range("2026-01-02", periods=3)
    close = portfolio_prices_eur(pd.Series([100., 100.], index=dates[[0, 2]]),
                                 pd.Series([1., 2., 2.], index=dates))
    index = portfolio_group_index([tx(2), tx(3, amount=50.)], close.to_frame("E"))
    assert index.tolist() == pytest.approx([100., 100., 50., 50.])


def test_loader_does_not_drop_purchases_after_the_last_available_quote(monkeypatch):
    from soldoni.app import dashboard
    from soldoni.data import store

    instruments = {isin: Instrument(isin, isin, isin, "EUR", "etf", "Europa")
                   for isin in ("A", "B")}

    def history(ticker, start, end):
        dates = pd.date_range("2026-01-02", periods=2 if ticker == "B" else 5)
        return pd.DataFrame({"close": 100., "adj_close": 100.}, index=dates)

    monkeypatch.setattr(dashboard.prices, "get_price_history", history)
    monkeypatch.setattr(dashboard.prices, "get_fx_history", lambda *args:
                        pd.Series(1.0, index=pd.date_range("2026-01-02", periods=5)))
    conn = store.init_db(":memory:")
    try:
        data = dashboard._load_portfolio_comparison(
            conn, {"I miei ETF": [tx(2, "A"), tx(5, "B")]}, instruments)
    finally:
        conn.close()
    assert "I miei ETF" not in data["histories"]
    assert any("operazioni più recenti" in error for error in data["errors"])
