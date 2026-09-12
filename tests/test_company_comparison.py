from dataclasses import replace

import pandas as pd
import pytest

from soldoni.core.cash_flow import latest_cash_flow_period
from soldoni.data.fundamentals import get_fundamentals


def _fund(ticker="AAA", **changes):
    info = {"shortName": "Azienda", "quoteType": "EQUITY", "currency": "USD",
            "financialCurrency": "USD", "currentPrice": 20, "trailingAnnualDividendRate": 2,
            "trailingEps": 4, "bookValue": 40, "sharesOutstanding": 20, "marketCap": 400,
            "trailingPE": 5, "returnOnEquity": 0.2, "targetMeanPrice": 30}
    info.update(changes)
    return get_fundamentals(ticker, fetch=lambda _: info)


def _annual():
    return pd.DataFrame({"revenue": [200.0, 400.0], "net_income": [40.0, 80.0],
                         "operating_cashflow": [60.0, 120.0], "capex": [-10.0, -20.0],
                         "free_cashflow": [50.0, 100.0], "net_borrowing": [0.0, 0.0],
                         "dividends_paid": [-25.0, -50.0], "eps": [2.0, 4.0]},
                        index=pd.to_datetime(["2024-12-31", "2025-12-31"]))


def test_shared_evaluation_preserves_values_and_assumptions():
    from soldoni.core.company_valuation import ValuationAssumptions, evaluate_company
    period = latest_cash_flow_period(_annual(), pd.DataFrame())
    assumptions = ValuationAssumptions()
    result = evaluate_company(_fund(), period, assumptions)
    assert result.models["Gordon"].value == pytest.approx(25.5)
    assert result.models["Gordon"].upside == pytest.approx(27.5)
    assert result.models["Gordon"].safety_price == pytest.approx(20.4)
    assert result.models["Graham"].value == pytest.approx(60)
    assert result.fcfe.value == 100
    changed = evaluate_company(_fund(), period, replace(assumptions, required_return=0.12))
    assert changed.models["Gordon"].value == pytest.approx(20.4)


@pytest.mark.parametrize("changes,model,reason", [
    ({"financialCurrency": "EUR"}, "Gordon", "Valute"),
    ({"impliedSharesOutstanding": 22}, "DCF (FCFE)", "azioni"),
    ({"trailingAnnualDividendRate": 0}, "Gordon", "Dividendo"),
])
def test_shared_evaluation_retains_applicability_guards(changes, model, reason):
    from soldoni.core.company_valuation import ValuationAssumptions, evaluate_company
    result = evaluate_company(_fund(**changes), latest_cash_flow_period(_annual(), pd.DataFrame()),
                              ValuationAssumptions())
    assert result.models[model].value is None
    assert reason in result.models[model].reason


def test_shared_scenarios_show_exact_effective_assumptions():
    from soldoni.core.company_valuation import ValuationAssumptions, scenario_assumptions
    base = ValuationAssumptions()
    prudent = scenario_assumptions(base, "Prudente")
    assert prudent.required_return == pytest.approx(0.12)
    assert prudent.terminal_growth == pytest.approx(0.01)
    assert prudent.dividend_growth == pytest.approx(0.03)
    assert prudent.fcfe_growth == pytest.approx(0.03)
    assert scenario_assumptions(base, "Base") == base


def _snapshot(ticker="AAA", **changes):
    from soldoni.core.company_comparison import CompanySnapshot
    from soldoni.core.scoring import score_instrument
    from soldoni.core.screen_metrics import price_metrics
    close = pd.Series([10.0, 15.0, 20.0], index=pd.date_range("2025-01-01", periods=3))
    fund = _fund(ticker, **changes)
    return CompanySnapshot(ticker, fund, score_instrument("stock", fund, price_metrics(close)),
                           close, {"return_12m_eur": 0.15}, _annual(), pd.DataFrame())


def test_comparison_includes_raw_data_cash_models_and_observation_periods():
    from soldoni.core.company_comparison import company_metrics
    from soldoni.core.company_valuation import ValuationAssumptions
    groups = company_metrics(_snapshot(), ValuationAssumptions())
    assert groups["Fondamentali"]["P/E trailing"].value == 5
    assert groups["Cash flow e dividendi"]["Free cash flow (CFO − CapEx)"].value == 100
    assert groups["Cash flow e dividendi"]["Margine FCF"].display() == "25.00%"
    assert groups["Valutazioni"]["Gordon — valore"].display() == "25.50 USD"
    assert groups["Analisti"]["Scostamento target medio"].display() == "50.00%"
    assert "31/12/2025" in groups["Riepilogo"]["Periodo cash flow"].value
    assert groups["Bilanci"]["Ricavi — ultimo esercizio"].value == 400
    assert groups["Mercato"]["Rendimento 12 mesi EUR"].value == 0.15


def test_missing_data_has_reason_and_negative_flows_remain_visible():
    from soldoni.core.company_comparison import company_metrics
    from soldoni.core.company_valuation import ValuationAssumptions
    snapshot = _snapshot(financialCurrency="EUR", trailingPE=float("nan"))
    snapshot.annual.loc[pd.Timestamp("2025-12-31"), "operating_cashflow"] = 10
    groups = company_metrics(snapshot, ValuationAssumptions())
    assert groups["Fondamentali"]["P/E trailing"].display() == "n/d"
    assert groups["Fondamentali"]["P/E trailing"].reason
    assert groups["Cash flow e dividendi"]["Free cash flow (CFO − CapEx)"].value == -10
    assert "Valute" in groups["Valutazioni"]["Gordon — valore"].reason


def test_absolute_history_rejects_mixed_currency_but_base100_aligns_price_dates():
    from soldoni.core.company_comparison import comparison_history
    first, second = _snapshot(), _snapshot("BBB", currency="EUR", financialCurrency="EUR")
    second.close = pd.Series([30.0, 60.0], index=pd.date_range("2025-01-02", periods=2))
    frame, issues = comparison_history([first, second], "price", "annual", "Assoluto")
    assert frame.empty
    assert issues
    frame, issues = comparison_history([first, second], "price", "annual", "Base 100")
    assert not issues
    assert frame.index[0] == pd.Timestamp("2025-01-02")
    assert frame.iloc[0].tolist() == [100.0, 100.0]
    assert frame.iloc[-1, 0] == pytest.approx(400 / 3)
    assert frame.iloc[-1, 1] == 200


def test_failed_company_is_named_in_history_not_silently_skipped():
    from soldoni.core.company_comparison import CompanySnapshot, comparison_history
    failed = CompanySnapshot("BAD", issues=("Servizio non disponibile",))
    frame, issues = comparison_history([_snapshot(), failed], "revenue", "annual", "Base 100")
    assert len(frame.columns) == 1
    assert "BAD" in issues


def test_yoy_and_ttm_do_not_bridge_missing_fiscal_quarters():
    from soldoni.core.company_comparison import comparison_history
    snapshot = _snapshot()
    snapshot.quarterly = pd.DataFrame({"revenue": [10., 20., 30., 40., 50.]},
        index=pd.to_datetime(["2024-03-31", "2024-06-30", "2024-12-31", "2025-03-31", "2025-06-30"]))
    for view in ("YoY %", "TTM"):
        frame, issues = comparison_history([snapshot], "revenue", "quarterly", view)
        assert frame.empty
        assert issues


def test_complete_quarters_produce_ttm_and_yoy_without_changing_capex_sign():
    from soldoni.core.company_comparison import comparison_history
    snapshot = _snapshot()
    snapshot.quarterly = pd.DataFrame({"capex": [-10., -20., -30., -40., -50.]},
        index=pd.date_range("2024-03-31", periods=5, freq="QE"))
    ttm, issues = comparison_history([snapshot], "capex", "quarterly", "TTM")
    assert not issues
    assert ttm.iloc[-1, 0] == 140
    yoy, issues = comparison_history([snapshot], "capex", "quarterly", "YoY %")
    assert not issues
    assert yoy.iloc[-1, 0] == 400


def test_history_preserves_missing_periods_as_visible_gaps():
    from soldoni.core.company_comparison import comparison_history
    snapshot = _snapshot()
    snapshot.quarterly = pd.DataFrame({"revenue": [10., float("nan"), 30.]},
                                      index=pd.date_range("2025-03-31", periods=3, freq="QE"))
    frame, issues = comparison_history([snapshot], "revenue", "quarterly", "Assoluto")
    assert len(frame) == 3
    assert pd.isna(frame.iloc[1, 0])


def test_matrix_includes_latest_ttm_yoy_and_pe_bands():
    from soldoni.core.company_comparison import company_metrics
    from soldoni.core.company_valuation import ValuationAssumptions
    snapshot = _snapshot()
    snapshot.quarterly = pd.DataFrame({"revenue": [10., 20., 30., 40., 50.]},
                                      index=pd.date_range("2024-03-31", periods=5, freq="QE"))
    snapshot.extras["pe_series"] = pd.Series([10., 20., 30.], index=snapshot.close.index)
    groups = company_metrics(snapshot, ValuationAssumptions())
    assert groups["Bilanci"]["Ricavi — TTM"].value == 140
    assert groups["Bilanci"]["Ricavi — YoY ultimo trimestre"].display() == "400.00%"
    assert groups["Mercato"]["P/E storico medio"].value == 20
    assert groups["Mercato"]["P/E storico media − 1σ"].value == 10
    assert groups["Mercato"]["P/E storico media + 1σ"].value == 30
