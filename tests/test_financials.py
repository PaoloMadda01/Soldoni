import pandas as pd
import pytest

from soldoni.data import financials


def _income(rows: dict, dates):
    return pd.DataFrame({d: [rows[r][i] for r in rows] for i, d in enumerate(dates)},
                        index=list(rows))


# dates "più recente prima", come yfinance
_DATES = [pd.Timestamp("2023-12-31"), pd.Timestamp("2022-12-31"), pd.Timestamp("2021-12-31")]


def _fetch_full(ticker, freq):
    income = _income({
        "Total Revenue": [300, 200, 100],
        "Net Income": [30, 20, 10],
        "Operating Income": [45, 30, 15],
        "Diluted EPS": [3.0, 2.0, 1.0],
    }, _DATES)
    cashflow = _income({
        "Free Cash Flow": [25, 18, 9],
        "Operating Cash Flow": [40, 28, 14],
        "Capital Expenditure": [-15, -10, -5],
    }, _DATES)
    return income, cashflow


def test_columns_sorted_ascending():
    df = financials.get_financials("X", "annual", fetch=_fetch_full)
    assert list(df.index) == sorted(df.index)
    assert df["revenue"].tolist() == [100, 200, 300]
    assert df["net_income"].tolist() == [10, 20, 30]
    assert df["eps"].tolist() == [1.0, 2.0, 3.0]


def test_capex_sign_preserved():
    df = financials.get_financials("X", "annual", fetch=_fetch_full)
    assert df["capex"].tolist() == [-5, -10, -15]


def test_label_fallbacks():
    def fetch(ticker, freq):
        income = _income({"Operating Revenue": [200, 100], "Basic EPS": [2.0, 1.0]},
                         _DATES[:2])
        cashflow = _income({"Total Cash From Operating Activities": [30, 20]}, _DATES[:2])
        return income, cashflow
    df = financials.get_financials("X", "annual", fetch=fetch)
    assert df["revenue"].tolist() == [100, 200]
    assert df["eps"].tolist() == [1.0, 2.0]
    assert df["operating_cashflow"].tolist() == [20, 30]


def test_missing_row_omits_column():
    def fetch(ticker, freq):
        income = _income({"Total Revenue": [200, 100]}, _DATES[:2])
        return income, pd.DataFrame()
    df = financials.get_financials("X", "annual", fetch=fetch)
    assert "revenue" in df.columns
    assert "net_income" not in df.columns
    assert "free_cashflow" not in df.columns


def test_both_empty_raises():
    def fetch(ticker, freq):
        return pd.DataFrame(), pd.DataFrame()
    with pytest.raises(ValueError):
        financials.get_financials("X", "annual", fetch=fetch)
