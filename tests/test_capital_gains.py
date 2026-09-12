from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from soldoni.core import tax
from soldoni.core.holdings import RealizedSale
from soldoni.core.models import Instrument


def _sale(when, gain, isin="A"):
    return RealizedSale(isin, when, 1.0, 1000.0 + gain, 1000.0, gain)


INSTRUMENTS = {
    isin: Instrument(isin, isin, isin, "EUR", kind, "Europa")
    for isin, kind in (("A", "azione"), ("E", "etf"))
}


def test_year_carries_previous_losses_without_including_previous_income():
    sales = [
        _sale(date(2024, 1, 1), 40), _sale(date(2024, 11, 1), -100),
        _sale(date(2025, 1, 1), 60), _sale(date(2025, 2, 1), 20, "E"),
        _sale(date(2025, 9, 1), -10), _sale(date(2026, 1, 1), 500),
    ]
    result = tax.compute_zainetto_for_year(sales, INSTRUMENTS, 2025, date(2026, 9, 10))

    assert result.gross_realized_eur == 70
    assert result.capital_tax_eur == pytest.approx(5.2)
    assert result.taxable_gains_eur == 20
    assert result.minus_generated_eur == 10
    assert result.minus_used_eur == 60
    assert result.residual_by_expiry == {2028: 40, 2029: 10}


@pytest.mark.parametrize(("year", "used", "due"), [(2025, 100, 0), (2026, 0, 26)])
def test_year_respects_last_valid_year_for_compensation(year, used, due):
    sales = [_sale(date(2021, 1, 1), -100), _sale(date(year, 6, 1), 100)]
    result = tax.compute_zainetto_for_year(sales, INSTRUMENTS, year, date(2026, 12, 31))

    assert result.minus_used_eur == used
    assert result.capital_tax_eur == due
    assert result.residual_by_expiry == {}


def test_later_loss_does_not_offset_an_earlier_sale():
    sales = [_sale(date(2025, 1, 1), 100), _sale(date(2025, 11, 1), -50)]
    result = tax.compute_zainetto_for_year(sales, INSTRUMENTS, 2025, date(2026, 9, 10))

    assert result.capital_tax_eur == 26
    assert result.minus_used_eur == 0
    assert result.residual_by_expiry == {2029: 50}


def test_year_without_sales_keeps_unexpired_carry_and_zero_period_totals():
    sales = [_sale(date(2021, 1, 1), -100), _sale(date(2024, 1, 1), -60)]
    result = tax.compute_zainetto_for_year(sales, INSTRUMENTS, 2026, date(2026, 9, 10))

    assert result.gross_realized_eur == result.minus_generated_eur == 0
    assert result.minus_used_eur == result.capital_tax_eur == 0
    assert result.residual_by_expiry == {2028: 60}


@pytest.mark.parametrize("year", [None, 2026])
def test_as_of_excludes_future_sales_including_later_in_the_same_year(year):
    sales = [_sale(date(2026, 1, 1), -60), _sale(date(2026, 10, 1), 100)]
    result = tax.compute_zainetto_for_year(sales, INSTRUMENTS, year, date(2026, 9, 10))

    assert result.gross_realized_eur == -60
    assert result.capital_tax_eur == 0
    assert result.residual_by_expiry == {2030: 60}


def test_empty_history_has_no_income_or_losses():
    result = tax.compute_zainetto_for_year([], {}, 2026, date(2026, 9, 10))

    assert result.gross_realized_eur == result.capital_tax_eur == 0
    assert result.minus_generated_eur == result.minus_used_eur == 0
    assert result.residual_by_expiry == {}


@pytest.mark.parametrize("year", [0, 2027])
def test_invalid_or_future_year_is_rejected(year):
    with pytest.raises(ValueError):
        tax.compute_zainetto_for_year([], {}, year, date(2026, 9, 10))


def _capital_gains_app():
    from datetime import date, timedelta
    from unittest.mock import patch

    import pandas as pd
    import streamlit as st

    from soldoni.app import dashboard
    from soldoni.core.models import Instrument, OpType, Transaction
    from soldoni.data import store

    year = date.today().year
    conn = store.init_db(":memory:")
    try:
        entries = [
            (year - 2, 1, "A", OpType.BUY, 4, 400, 4),
            (year - 2, 6, "A", OpType.SELL, 1, 81, 1),
            (year - 1, 1, "E", OpType.BUY, 1, 100, 0),
            (year - 1, 6, "A", OpType.SELL, 1, 151, 1),
            (year - 1, 6, "E", OpType.SELL, 1, 120, 0),
        ]
        if st.session_state.get("incomplete_history"):
            entries.insert(0, (year - 3, 1, "A", OpType.SELL, 1, 100, 0))
        store.insert_transactions(conn, [
            Transaction(date(y, month, 1), date(y, month, 1), isin, op,
                        qty, amount, 0, 1, fee)
            for y, month, isin, op, qty, amount, fee in entries
        ])
        for isin, kind in (("A", "azione"), ("E", "etf")):
            if isin == "A" and st.session_state.get("missing_instrument"):
                continue
            store.upsert_instrument(conn, Instrument(
                isin, isin, "Titolo " + isin, "EUR", kind, "Europa", excluded=True))
        if not st.session_state.get("missing_price"):
            store.write_prices_cache(conn, "A", pd.DataFrame(
                {"close": [120.0], "adj_close": [120.0]},
                index=pd.to_datetime([date.today() - timedelta(days=1)])))

        def cached_prices(connection, ticker, start, end):
            history = store.read_prices_cache(connection, ticker)
            if history.empty:
                raise ValueError("Prezzo non disponibile")
            return history

        with patch.object(dashboard.prices, "get_price_history_cached", cached_prices):
            dashboard.page_capital_gains(conn)
    finally:
        conn.close()


def test_page_filters_realized_income_but_keeps_current_and_excluded_positions():
    app = AppTest.from_function(_capital_gains_app, default_timeout=20).run()
    assert not app.exception
    app.selectbox(key="capital_gains_year").select(str(date.today().year - 1)).run()

    assert not app.exception
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["Plus realizzate"] == "69.00 €"
    assert metrics["Minus realizzate"] == "0.00 €"
    assert metrics["Imposta stimata nel periodo"] == "12.48 €"
    assert metrics["Minus utilizzate nel periodo"] == "21.00 €"
    positions = app.dataframe[-1].value
    assert positions.iloc[0]["ISIN"] == "A"
    assert positions.iloc[0]["Plus/minus potenziale EUR"] == 38.0
    assert positions.iloc[0]["Plus/minus %"] == pytest.approx(18.81)

    app.selectbox(key="capital_gains_year").select(str(date.today().year - 2)).run()
    assert not app.exception
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["Plus realizzate"] == "0.00 €"
    assert metrics["Minus realizzate"] == "21.00 €"
    assert metrics["Minus residue disponibili"] == "21.00 €"
    assert app.dataframe[-1].value.iloc[0]["Plus/minus potenziale EUR"] == 38.0


@pytest.mark.parametrize("missing", ["missing_price", "missing_instrument"])
def test_page_keeps_positions_with_unavailable_values_visible(missing):
    app = AppTest.from_function(_capital_gains_app, default_timeout=20)
    app.session_state[missing] = True
    app.run()

    assert not app.exception
    assert app.warning
    positions = app.dataframe[-1].value
    assert positions.iloc[0]["ISIN"] == "A"
    assert positions.iloc[0]["Plus/minus potenziale EUR"] is None
    assert "n/d" in [item.value for item in app.metric]


def test_page_does_not_estimate_tax_from_incomplete_history():
    app = AppTest.from_function(_capital_gains_app, default_timeout=20)
    app.session_state["incomplete_history"] = True
    app.run()

    assert not app.exception
    assert any("Storico incompleto" in item.value for item in app.warning)
    assert "Imposta stimata nel periodo" not in [item.label for item in app.metric]
