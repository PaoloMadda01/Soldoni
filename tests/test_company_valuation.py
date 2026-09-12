import math

import pandas as pd
import pytest

from soldoni.data.fundamentals import get_fundamentals
from soldoni.data.financials import get_financials


def test_gordon_uses_next_year_dividend():
    from soldoni.core.company_valuation import gordon_value
    assert gordon_value(2.0, 0.10, 0.02) == pytest.approx(25.5)


def test_graham_and_earnings_multiple():
    from soldoni.core.company_valuation import graham_number, earnings_multiple_value
    assert graham_number(4.0, 40.0) == pytest.approx(60.0)
    assert earnings_multiple_value(4.0, 15.0) == pytest.approx(60.0)


def test_inverse_gordon_recovers_growth_and_accepts_decline():
    from soldoni.core.company_valuation import implied_dividend_growth
    assert implied_dividend_growth(2.0, 25.5, 0.10) == pytest.approx(0.02)
    assert implied_dividend_growth(2.0, 10.0, 0.10) == pytest.approx(-1 / 12)


def test_two_stage_discounts_terminal_value_and_first_dividend():
    from soldoni.core.company_valuation import two_stage_dividend_value
    # D1=2.2, terminal=2.2/10%=22, both paid/valued at the end of year 1.
    assert two_stage_dividend_value(2.0, 0.10, 0.0, 0.10, 1) == pytest.approx(22.0)


def test_flat_fcfe_values_equity_per_share_without_subtracting_debt_again():
    from soldoni.core.company_valuation import dcf_equity_value
    # Perpetuity 100/10%=1000 of equity, divided by 20 shares.
    assert dcf_equity_value(100, 20, 0.0, 0.0, 0.10, 5) == pytest.approx(50.0)


def test_safety_margin_is_discount_on_value_not_expected_return():
    from soldoni.core.company_valuation import margin_of_safety_price
    assert margin_of_safety_price(100, 0.25) == pytest.approx(75.0)
    assert margin_of_safety_price(100, 0.0) == pytest.approx(100.0)


@pytest.mark.parametrize("dividend,rate,growth", [
    (0, 0.10, 0.02), (-2, 0.10, 0.02), (None, 0.10, 0.02),
    (2, 0.02, 0.02), (2, 0.01, 0.02), (2, 0, -0.01),
    (2, 0.10, -1.0), (2, math.nan, 0.02), (math.inf, 0.10, 0.02),
])
def test_gordon_rejects_invalid_inputs(dividend, rate, growth):
    from soldoni.core.company_valuation import gordon_value
    with pytest.raises(ValueError):
        gordon_value(dividend, rate, growth)


@pytest.mark.parametrize("eps,book", [(-4, -40), (0, 40), (4, None), (4, math.inf)])
def test_graham_requires_both_factors_positive(eps, book):
    from soldoni.core.company_valuation import graham_number
    with pytest.raises(ValueError):
        graham_number(eps, book)


@pytest.mark.parametrize("years", [0, -1, 1.5, True, 101])
def test_discounted_models_reject_invalid_horizon(years):
    from soldoni.core.company_valuation import dcf_equity_value
    with pytest.raises(ValueError):
        dcf_equity_value(100, 20, 0.05, 0.02, 0.10, years)


@pytest.mark.parametrize("fcfe,shares,growth,terminal,rate", [
    (-100, 20, 0.05, 0.02, 0.10), (100, 0, 0.05, 0.02, 0.10),
    (100, 20, -1.0, 0.02, 0.10), (100, 20, 0.05, 0.10, 0.10),
    (100, 20, 0.05, math.nan, 0.10),
])
def test_dcf_rejects_inapplicable_base_or_assumptions(fcfe, shares, growth, terminal, rate):
    from soldoni.core.company_valuation import dcf_equity_value
    with pytest.raises(ValueError):
        dcf_equity_value(fcfe, shares, growth, terminal, rate, 5)


@pytest.mark.parametrize("margin", [-0.01, 1.0, math.nan])
def test_invalid_safety_margin(margin):
    from soldoni.core.company_valuation import margin_of_safety_price
    with pytest.raises(ValueError):
        margin_of_safety_price(100, margin)


def test_provider_uses_trailing_dividend_not_forward_rate_or_yield():
    fund = get_fundamentals("ACME", fetch=lambda _: {
        "quoteType": "EQUITY", "currency": "USD", "financialCurrency": "USD",
        "trailingAnnualDividendRate": 2.0, "dividendRate": 3.0, "dividendYield": 1.5,
        "trailingEps": 4.0, "bookValue": 40.0, "sharesOutstanding": 20,
        "marketCap": 2000,
    })
    assert fund.annual_dividend == 2.0
    assert fund.trailing_eps == 4.0
    assert fund.book_value == 40.0
    assert fund.shares_outstanding == 20
    assert fund.financial_currency == "USD"
    assert fund.market_cap == 2000


def test_provider_leaves_missing_valuation_data_absent():
    fund = get_fundamentals("ACME", fetch=lambda _: {"quoteType": "EQUITY"})
    assert fund.annual_dividend is None
    assert fund.trailing_eps is None
    assert fund.shares_outstanding is None
    assert fund.financial_currency is None


def test_financials_exposes_net_borrowing_with_its_sign():
    dates = pd.to_datetime(["2024-12-31", "2025-12-31"])
    frame = pd.DataFrame([[10, -20]], index=["Net Issuance Payments Of Debt"], columns=dates)
    result = get_financials("ACME", "annual", fetch=lambda *_: (pd.DataFrame(), frame))
    assert result["net_borrowing"].tolist() == [10, -20]


def test_fcfe_preserves_debt_repayments_and_normalizes_capex_outflow():
    from soldoni.core.company_valuation import fcfe_from_cashflow
    assert fcfe_from_cashflow(100, -20, -10) == pytest.approx(70)
    assert fcfe_from_cashflow(100, 20, 10) == pytest.approx(90)
    assert fcfe_from_cashflow(-100, -20, 10) == pytest.approx(-110)
    with pytest.raises(ValueError):
        fcfe_from_cashflow(100, -20, None)
