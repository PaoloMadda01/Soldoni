from datetime import date
from soldoni.core.holdings import RealizedSale
from soldoni.core.models import Instrument
from soldoni.core.tax import compute_zainetto


def _sale(isin, year, gain):
    return RealizedSale(isin=isin, date=date(year, 6, 1), quantity=1.0,
                        proceeds_eur=0.0, cost_basis_eur=0.0, gain_eur=gain)


def _inst(isin, asset_class):
    return Instrument(isin, "T", "n", "EUR", asset_class, "Area")


def test_minus_then_plus_stock_fully_offset():
    sales = [_sale("A", 2025, -100.0), _sale("A", 2026, 100.0)]
    insts = {"A": _inst("A", "azione")}
    z = compute_zainetto(sales, insts, today_year=2026)
    assert z.capital_tax_eur == 0.0
    assert z.minus_generated_eur == 100.0
    assert z.minus_used_eur == 100.0
    assert z.taxable_gains_eur == 0.0
    assert z.residual_by_expiry == {}


def test_plus_etf_full_tax_no_offset():
    sales = [_sale("E", 2026, 100.0)]
    insts = {"E": _inst("E", "etf")}
    z = compute_zainetto(sales, insts, today_year=2026)
    assert round(z.capital_tax_eur, 2) == 26.0
    assert z.minus_used_eur == 0.0
    assert z.taxable_gains_eur == 100.0


def test_minus_stock_then_plus_etf_not_offset():
    sales = [_sale("A", 2025, -50.0), _sale("E", 2026, 100.0)]
    insts = {"A": _inst("A", "azione"), "E": _inst("E", "etf")}
    z = compute_zainetto(sales, insts, today_year=2026)
    assert round(z.capital_tax_eur, 2) == 26.0    # ETF: 0.26*100, niente compensazione
    assert z.minus_used_eur == 0.0
    assert z.residual_by_expiry == {2029: 50.0}   # minus 2025 -> scade fine 2029


def test_minus_expired_not_offset():
    sales = [_sale("A", 2020, -100.0), _sale("A", 2026, 100.0)]
    insts = {"A": _inst("A", "azione")}
    z = compute_zainetto(sales, insts, today_year=2026)
    assert round(z.capital_tax_eur, 2) == 26.0    # 2026-2020=6 > 4 -> scaduta
    assert z.minus_used_eur == 0.0
    assert z.residual_by_expiry == {}


def test_residual_by_expiry_depends_on_today_year():
    sales = [_sale("A", 2025, -30.0)]
    insts = {"A": _inst("A", "azione")}
    assert compute_zainetto(sales, insts, today_year=2026).residual_by_expiry == {2029: 30.0}
    assert compute_zainetto(sales, insts, today_year=2030).residual_by_expiry == {}
