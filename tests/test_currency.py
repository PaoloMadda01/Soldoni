from datetime import date
import pytest
from soldoni.core.models import Instrument, OpType, Transaction
from soldoni.core.currency import (
    currency_exposure, weighted_entry_fx, FxSplit, fx_price_decomposition)


def _inst(isin, ccy):
    return Instrument(isin, "T", "n", ccy, "stock", "Area")


def _buy_on(isin, day, amount_eur):
    return Transaction(date(2026, 1, day), date(2026, 1, day), isin, OpType.BUY,
                       1.0, amount_eur, 0.0, 1.0, 0.0)


def test_currency_exposure_groups_by_native_currency():
    insts = {"A": _inst("A", "EUR"), "B": _inst("B", "USD"), "C": _inst("C", "USD")}
    cv = {"A": 1000.0, "B": 500.0, "C": 300.0}
    assert currency_exposure(cv, insts) == {"EUR": 1000.0, "USD": 800.0}


def test_currency_exposure_missing_instrument_raises():
    with pytest.raises(ValueError):
        currency_exposure({"X": 1.0}, {})


def test_weighted_entry_fx_weighted_over_buys():
    txs = [_buy_on("U", 1, 1000.0), _buy_on("U", 2, 3000.0)]
    rate_by_day = {1: 1.1, 2: 1.3}
    entry = lambda t: rate_by_day[t.trade_date.day]
    # (1000*1.1 + 3000*1.3) / 4000 = 1.25
    assert round(weighted_entry_fx(txs, entry)["U"], 6) == 1.25


def test_weighted_entry_fx_ignores_non_buys():
    sell = Transaction(date(2026, 1, 2), date(2026, 1, 2), "U", OpType.SELL,
                       1.0, 5000.0, 0.0, 1.0, 0.0)
    txs = [_buy_on("U", 1, 1000.0), sell]
    assert round(weighted_entry_fx(txs, lambda t: 1.1)["U"], 6) == 1.1


def test_fx_price_decomposition_eur_position_no_fx():
    splits = fx_price_decomposition({"E": 1000.0}, {"E": 1200.0}, {"E": 1.0}, {"E": 1.0})
    assert len(splits) == 1
    assert splits[0].fx_eur == 0.0
    assert splits[0].price_eur == 200.0
    assert splits[0].total_eur == 200.0


def test_fx_price_decomposition_sums_to_latent():
    splits = fx_price_decomposition({"U": 1000.0}, {"U": 1200.0}, {"U": 1.0}, {"U": 1.2})
    s = splits[0]
    assert round(s.price_eur, 6) == 440.0          # 1200*(1.2/1.0) - 1000
    assert round(s.fx_eur, 6) == -240.0            # 1200*(1 - 1.2)
    assert round(s.price_eur + s.fx_eur, 6) == 200.0


def test_fx_price_decomposition_skips_zero_entry_fx():
    assert fx_price_decomposition({"Z": 100.0}, {"Z": 100.0}, {"Z": 0.0}, {"Z": 1.0}) == []


def test_fx_price_decomposition_sorted_desc():
    cost = {"A": 100.0, "B": 100.0}
    val = {"A": 150.0, "B": 120.0}
    e = {"A": 1.0, "B": 1.0}
    c = {"A": 1.0, "B": 1.0}
    splits = fx_price_decomposition(cost, val, e, c)
    assert [s.isin for s in splits] == ["A", "B"]   # totali 50, 20
