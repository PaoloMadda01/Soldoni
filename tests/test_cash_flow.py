import math

import pandas as pd
import pytest

from soldoni.data.financials import get_financials


_DATES = pd.to_datetime(["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"])
_VALUES = {"operating_cashflow": 120.0, "capex": -20.0, "net_borrowing": -10.0,
           "revenue": 400.0, "net_income": 80.0, "dividends_paid": -50.0}


def _annual():
    return pd.DataFrame([_VALUES], index=pd.to_datetime(["2024-12-31"]))


def _quarterly():
    return pd.DataFrame([_VALUES] * 4, index=_DATES)


def test_ttm_sums_complete_quarters_and_normalizes_outflow_signs_before_sum():
    from soldoni.core.cash_flow import latest_cash_flow_period
    quarterly = _quarterly()
    quarterly.loc[_DATES[0], "capex"] = 20.0
    quarterly.loc[_DATES[0], "dividends_paid"] = 50.0
    period = latest_cash_flow_period(_annual(), quarterly.iloc[::-1])
    assert period.end == pd.Timestamp("2025-12-31")
    assert "TTM" in period.label
    assert period.values["operating_cashflow"] == 480
    assert period.values["capex"] == 80
    assert period.values["dividends_paid"] == 200
    assert period.values["net_borrowing"] == -40


@pytest.mark.parametrize("case", ["too_few", "gap", "duplicate", "missing_cfo", "missing_capex"])
def test_incomplete_ttm_falls_back_to_annual_with_reason(case):
    from soldoni.core.cash_flow import latest_cash_flow_period
    quarterly = _quarterly()
    if case == "too_few":
        quarterly = quarterly.iloc[:3]
    elif case == "gap":
        quarterly.index = pd.to_datetime(["2024-12-31", "2025-06-30", "2025-09-30", "2025-12-31"])
    elif case == "duplicate":
        quarterly.index = pd.to_datetime(["2025-03-31", "2025-06-30", "2025-06-30", "2025-12-31"])
    else:
        quarterly.loc[_DATES[1], "operating_cashflow" if case == "missing_cfo" else "capex"] = math.nan
    period = latest_cash_flow_period(_annual(), quarterly)
    assert period.end == pd.Timestamp("2024-12-31")
    assert "TTM" not in period.label
    assert period.values["operating_cashflow"] == 120
    assert period.notice


def test_ratios_never_fill_missing_ttm_inputs_with_another_period():
    from soldoni.core.cash_flow import latest_cash_flow_period, summarize_cash_flow
    quarterly = _quarterly()
    quarterly.loc[_DATES[0], "dividends_paid"] = math.nan
    quarterly.loc[_DATES[1], "net_income"] = math.inf
    quarterly.loc[_DATES[2], "net_borrowing"] = math.nan
    period = latest_cash_flow_period(_annual(), quarterly)
    assert "TTM" in period.label
    assert "net_borrowing" not in period.values
    result = summarize_cash_flow(period.values, 4000, "USD", "USD")
    assert result["dividend_coverage"].value is None
    assert result["cash_conversion"].value is None
    assert result["fcf_margin"].value == pytest.approx(0.25)


def test_newer_annual_is_preferred_to_older_ttm():
    from soldoni.core.cash_flow import latest_cash_flow_period
    annual = _annual()
    annual.index = pd.to_datetime(["2026-06-30"])
    assert latest_cash_flow_period(annual, _quarterly()).end == pd.Timestamp("2026-06-30")


def test_no_complete_period_does_not_invent_annual_cash_flow():
    from soldoni.core.cash_flow import latest_cash_flow_period
    period = latest_cash_flow_period(pd.DataFrame(), _quarterly().iloc[:3])
    assert period.end is None
    assert not period.values
    assert period.notice


def test_cash_flow_ratios_have_independently_known_values():
    from soldoni.core.cash_flow import summarize_cash_flow
    result = summarize_cash_flow(_VALUES, 2000, "USD", "USD")
    assert result["operating_cashflow"].value == 120
    assert result["capex"].value == 20
    assert result["free_cashflow"].value == 100
    assert result["fcf_margin"].value == pytest.approx(0.25)
    assert result["cash_conversion"].value == pytest.approx(1.5)
    assert result["fcf_yield"].value == pytest.approx(0.05)
    assert result["dividend_coverage"].value == pytest.approx(2.0)


def test_negative_fcf_remains_negative_and_reported_fcf_is_not_substituted():
    from soldoni.core.cash_flow import summarize_cash_flow
    result = summarize_cash_flow({**_VALUES, "operating_cashflow": 10, "free_cashflow": 999},
                                 2000, "USD", "USD")
    assert result["free_cashflow"].value == -10
    assert result["fcf_yield"].value == pytest.approx(-0.005)
    assert result["dividend_coverage"].value == pytest.approx(-0.2)


@pytest.mark.parametrize("financial,market", [("EUR", "USD"), (None, "USD"), ("GBP", "GBp")])
def test_currency_mismatch_blocks_only_market_yield(financial, market):
    from soldoni.core.cash_flow import summarize_cash_flow
    result = summarize_cash_flow(_VALUES, 2000, financial, market)
    assert result["fcf_yield"].value is None
    assert "valut" in result["fcf_yield"].reason.lower()
    assert result["cash_conversion"].value == pytest.approx(1.5)


@pytest.mark.parametrize("field,metric,value", [
    ("revenue", "fcf_margin", 0), ("net_income", "cash_conversion", -10),
    ("dividends_paid", "dividend_coverage", 0),
    ("dividends_paid", "dividend_coverage", None),
    ("operating_cashflow", "free_cashflow", math.inf),
    ("capex", "free_cashflow", None),
])
def test_inapplicable_ratios_have_visible_reason(field, metric, value):
    from soldoni.core.cash_flow import summarize_cash_flow
    result = summarize_cash_flow({**_VALUES, field: value}, 2000, "USD", "USD")
    assert result[metric].value is None
    assert result[metric].reason


def test_dividend_provider_prefers_total_payments_preserving_sign_and_zero():
    frame = pd.DataFrame([[-50, 0], [-40, 0]],
                         index=["Cash Dividends Paid", "Common Stock Dividend Paid"],
                         columns=pd.to_datetime(["2024-12-31", "2025-12-31"]))
    result = get_financials("ACME", "annual", fetch=lambda *_: (pd.DataFrame(), frame))
    assert result["dividends_paid"].tolist() == [-50, 0]
