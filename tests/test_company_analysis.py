import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest


_INFO = {
    "quoteType": "EQUITY", "currency": "USD", "financialCurrency": "USD",
    "currentPrice": 20.0, "trailingAnnualDividendRate": 2.0,
    "trailingEps": 4.0, "bookValue": 40.0, "sharesOutstanding": 20,
    "marketCap": 400.0, "sector": "Industrials",
}
_CASH = {"operating_cashflow": 120.0, "capex": -20.0, "net_borrowing": 0.0}


def _company_app(info, cash, fail_fetch=False):
    import pandas as pd
    from soldoni.app.company_analysis import render_company_analysis
    from soldoni.data.fundamentals import get_fundamentals

    def load(ticker, frequency):
        if fail_fetch:
            raise ValueError("Bilancio non disponibile")
        if frequency == "quarterly":
            return pd.DataFrame()
        return pd.DataFrame([cash], index=pd.to_datetime(["2025-12-31"]))

    fund = get_fundamentals("ACME", fetch=lambda _: info)
    render_company_analysis(fund, load)


def _run(info=None, cash=None, fail_fetch=False):
    return AppTest.from_function(
        _company_app, args=(info or _INFO, _CASH if cash is None else cash, fail_fetch),
        default_timeout=15).run()


def _valuations(app):
    return next(frame.value.set_index("Modello") for frame in app.dataframe
                if "Modello" in frame.value.columns)


def test_renders_formulas_prices_and_safety_margin():
    app = _run()
    assert not app.exception
    values = _valuations(app)
    assert values.loc["Gordon", "Valore stimato"] == pytest.approx(25.5)
    assert values.loc["Gordon", "Scostamento %"] == pytest.approx(27.5)
    assert values.loc["Gordon", "Prezzo con margine"] == pytest.approx(20.4)
    assert values.loc["Graham", "Valore stimato"] == pytest.approx(60.0)
    assert values.loc["P/E obiettivo", "Valore stimato"] == pytest.approx(60.0)
    assert values.loc["DCF (FCFE)", "Valore stimato"] > 0
    assert len(app.latex) >= 5


def test_changing_return_recalculates_gordon():
    app = _run()
    app.number_input(key="valuation_return_ACME").set_value(12.0).run()
    assert not app.exception
    assert _valuations(app).loc["Gordon", "Valore stimato"] == pytest.approx(20.4)


def test_non_dividend_payer_keeps_earnings_models():
    app = _run({**_INFO, "trailingAnnualDividendRate": 0})
    assert not app.exception
    values = _valuations(app)
    assert pd.isna(values.loc["Gordon", "Valore stimato"])
    assert values.loc["Gordon", "Esito"]
    assert values.loc["P/E obiettivo", "Valore stimato"] == pytest.approx(60.0)


def test_mismatched_currency_disables_comparisons_of_financial_values():
    app = _run({**_INFO, "financialCurrency": "EUR"})
    assert not app.exception
    values = _valuations(app)
    for name in ("Graham", "P/E obiettivo", "DCF (FCFE)"):
        assert pd.isna(values.loc[name, "Valore stimato"])
        assert "valut" in values.loc[name, "Esito"].lower()


def test_missing_net_borrowing_does_not_assume_zero():
    app = _run(cash={"operating_cashflow": 120, "capex": -20})
    assert not app.exception
    values = _valuations(app)
    assert pd.isna(values.loc["DCF (FCFE)", "Valore stimato"])
    assert "indebitamento" in values.loc["DCF (FCFE)", "Esito"].lower()


def test_fetch_failure_is_visible_without_losing_other_models():
    app = _run(fail_fetch=True)
    assert not app.exception
    assert len(app.warning) > 0
    assert _valuations(app).loc["Gordon", "Valore stimato"] == pytest.approx(25.5)


def test_generic_dcf_is_not_applied_to_financial_sector():
    app = _run({**_INFO, "sector": "Financial Services"})
    assert not app.exception
    values = _valuations(app)
    assert pd.isna(values.loc["DCF (FCFE)", "Valore stimato"])
    assert values.loc["DCF (FCFE)", "Esito"]


@pytest.mark.parametrize("changes", [
    {"impliedSharesOutstanding": 22}, {"marketCap": 440},
    {"marketCap": None, "impliedSharesOutstanding": None},
])
def test_dcf_rejects_inconsistent_or_unverifiable_share_basis(changes):
    app = _run({**_INFO, **changes})
    assert not app.exception
    values = _valuations(app)
    assert pd.isna(values.loc["DCF (FCFE)", "Valore stimato"])
    assert "azion" in values.loc["DCF (FCFE)", "Esito"].lower()
    assert values.loc["Gordon", "Valore stimato"] == pytest.approx(25.5)


def test_dcf_share_check_tolerates_rounding():
    app = _run({**_INFO, "impliedSharesOutstanding": 20.01, "marketCap": 400.1})
    assert not app.exception
    assert _valuations(app).loc["DCF (FCFE)", "Valore stimato"] > 0


def test_etf_has_no_company_models_or_financial_fetch():
    app = _run({**_INFO, "quoteType": "ETF"}, fail_fetch=True)
    assert not app.exception
    assert not app.dataframe
    assert not app.warning


def _analyzer_app():
    from datetime import date
    from unittest.mock import patch
    import pandas as pd
    from soldoni.app import dashboard
    from soldoni.data.fundamentals import get_fundamentals

    fund = get_fundamentals("ACME", fetch=lambda _: {
        "quoteType": "EQUITY", "currency": "EUR", "financialCurrency": "EUR",
        "currentPrice": 20, "trailingAnnualDividendRate": 2,
        "trailingEps": 4, "bookValue": 40, "sharesOutstanding": 20,
    })
    history = pd.DataFrame({"close": [20.0] * 300},
                           index=pd.date_range(end=date.today(), periods=300))
    annual = pd.DataFrame([{"operating_cashflow": 120, "capex": -20,
                            "net_borrowing": 0, "free_cashflow": 100}],
                          index=pd.to_datetime(["2025-12-31"]))
    conn = dashboard.store.init_db(":memory:")
    try:
        with (patch.object(dashboard.prices, "resolve_ticker", return_value="ACME"),
              patch.object(dashboard.prices, "get_price_history_cached", return_value=history),
              patch.object(dashboard, "_cached_fundamentals", return_value=fund),
              patch.object(dashboard, "_cached_eps", return_value=pd.Series(dtype=float)),
              patch.object(dashboard, "_cached_financials", side_effect=lambda ticker, frequency:
                           annual if frequency == "annual" else pd.DataFrame())):
            dashboard.page_analyzer(conn)
    finally:
        conn.close()


def test_search_analyze_displays_company_valuation():
    app = AppTest.from_function(_analyzer_app, default_timeout=20).run()
    assert not app.exception
    app.text_input[0].set_value("ACME")
    next(button for button in app.button if button.label == "Analizza").click().run()
    assert not app.exception
    assert _valuations(app).loc["Gordon", "Valore stimato"] == pytest.approx(25.5)


def _cash_ratios(app):
    return next(frame.value.set_index("Indicatore") for frame in app.dataframe
                if "Indicatore" in frame.value.columns)


def test_cash_flow_screen_displays_amounts_and_ratios():
    app = _run(cash={**_CASH, "revenue": 400, "net_income": 80, "dividends_paid": -50})
    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Cash flow operativo"] == "120.00"
    assert metrics["Investimenti (CapEx)"] == "20.00"
    assert metrics["Free cash flow"] == "100.00"
    ratios = _cash_ratios(app)
    assert ratios.loc["Margine FCF", "Valore"] == "25.00%"
    assert ratios.loc["Conversione utili in cassa", "Valore"] == "1.50x"
    assert ratios.loc["Copertura dividendi", "Valore"] == "2.00x"


def test_cash_flow_screen_explains_currency_and_missing_dividends():
    app = _run({**_INFO, "financialCurrency": "EUR"}, cash={**_CASH, "net_income": 80})
    assert not app.exception
    ratios = _cash_ratios(app)
    assert ratios.loc["FCF yield", "Valore"] == "n/d"
    assert "valut" in ratios.loc["FCF yield", "Esito"].lower()
    assert ratios.loc["Copertura dividendi", "Valore"] == "n/d"
    assert ratios.loc["Copertura dividendi", "Esito"]
    assert ratios.loc["Conversione utili in cassa", "Valore"] == "1.50x"


def test_cash_flow_screen_preserves_and_explains_negative_cash():
    app = _run(cash={**_CASH, "operating_cashflow": 10})
    assert not app.exception
    assert next(metric.value for metric in app.metric if metric.label == "Free cash flow") == "-10.00"
    assert any("negativo" in message.value.lower() for message in app.warning)


def _quarterly_company_app():
    import pandas as pd
    from soldoni.app.company_analysis import render_company_analysis
    from soldoni.data.fundamentals import get_fundamentals

    fund = get_fundamentals("ACME", fetch=lambda _: {
        "quoteType": "EQUITY", "currency": "USD", "financialCurrency": "USD",
        "currentPrice": 20, "trailingAnnualDividendRate": 2,
        "trailingEps": 4, "bookValue": 40, "sharesOutstanding": 20, "marketCap": 400,
    })

    def load(ticker, frequency):
        if frequency == "annual":
            raise ValueError("Dati annuali non disponibili")
        return pd.DataFrame([{"operating_cashflow": 120, "capex": -20, "net_borrowing": 0}] * 4,
                            index=pd.to_datetime(["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]))

    render_company_analysis(fund, load)


def test_ttm_cash_flow_and_dcf_work_when_annual_fetch_fails():
    app = AppTest.from_function(_quarterly_company_app, default_timeout=15).run()
    assert not app.exception
    assert next(metric.value for metric in app.metric if metric.label == "Free cash flow") == "400.00"
    assert _valuations(app).loc["DCF (FCFE)", "Valore stimato"] == pytest.approx(289.2423779967214)
    assert any("TTM" in caption.value and "31/12/2025" in caption.value for caption in app.caption)
