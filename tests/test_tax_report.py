import io
from datetime import date
import pandas as pd
from soldoni.core.holdings import RealizedSale
from soldoni.core.models import Instrument, OpType, Transaction
from soldoni.core.tax_report import (
    realized_rows, dividend_rows, zainetto_rows, build_tax_report_xlsx)


def _sale(isin, year, gain):
    return RealizedSale(isin=isin, date=date(year, 6, 1), quantity=2.0,
                        proceeds_eur=1000.0, cost_basis_eur=1000.0 - gain, gain_eur=gain)


def _inst(isin, name, asset_class="azione"):
    return Instrument(isin, "T", name, "EUR", asset_class, "Area")


def _div(isin, year, amount):
    return Transaction(date(year, 3, 1), date(year, 3, 1), isin, OpType.DIVIDEND,
                       1.0, amount, 0.0, 1.0, 0.0)


def test_realized_rows_filter_year():
    sales = [_sale("A", 2025, 50.0), _sale("A", 2026, -30.0)]
    insts = {"A": _inst("A", "Acme")}
    rows = realized_rows(sales, insts, year=2025)
    assert len(rows) == 1
    assert rows[0]["Nome"] == "Acme"
    assert rows[0]["Plus/Minus €"] == 50.0
    assert rows[0]["Data"] == "2025-06-01"


def test_realized_rows_missing_instrument_uses_isin():
    sales = [_sale("A", 2025, 50.0), _sale("A", 2026, -30.0)]
    rows = realized_rows(sales, {}, year=None)
    assert len(rows) == 2
    assert rows[0]["Nome"] == "A"


def test_dividend_rows_net_it_and_us():
    divs = [_div("IT0001", 2025, 100.0), _div("US0001", 2025, 100.0)]
    insts = {"IT0001": _inst("IT0001", "MedioFoo"), "US0001": _inst("US0001", "USco")}
    by_isin = {r["ISIN"]: r for r in dividend_rows(divs, insts, year=2025)}
    assert by_isin["IT0001"]["Netto €"] == 74.0      # 100 * 0.74
    assert by_isin["US0001"]["Netto €"] == 62.9      # 100 * 0.85 * 0.74


def test_dividend_rows_filter_year():
    divs = [_div("A", 2025, 50.0), _div("A", 2026, 60.0)]
    assert len(dividend_rows(divs, {}, year=2026)) == 1


def test_build_tax_report_xlsx_three_sheets():
    sales = [_sale("A", 2025, 50.0)]
    divs = [_div("A", 2025, 100.0)]
    insts = {"A": _inst("A", "Acme")}
    data = build_tax_report_xlsx(sales, divs, insts, year=2025)
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
    assert set(sheets) == {"Plus-Minus", "Dividendi", "Zainetto"}
    assert sheets["Plus-Minus"].iloc[0]["Plus/Minus €"] == 50.0
    assert "Imposta capital gain" in list(sheets["Zainetto"]["Voce"])


def test_build_tax_report_xlsx_empty_year_has_headers():
    data = build_tax_report_xlsx([_sale("A", 2025, 10.0)], [], {}, year=2099)
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
    assert list(sheets["Plus-Minus"].columns) == ["Data", "ISIN", "Nome", "Tipo", "Quantità",
                                                  "Proventi €", "Costo €", "Plus/Minus €"]
    assert len(sheets["Plus-Minus"]) == 0
