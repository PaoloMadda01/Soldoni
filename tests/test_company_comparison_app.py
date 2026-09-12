from streamlit.testing.v1 import AppTest


def _comparison_app(fail=False, current_only=False):
    import pandas as pd
    import streamlit as st
    from soldoni.app.company_comparison import render_company_comparison
    from soldoni.core.scoring import score_instrument
    from soldoni.core.screen_metrics import price_metrics
    from soldoni.data.fundamentals import get_fundamentals

    def fund(ticker):
        return get_fundamentals(ticker, fetch=lambda _: {
            "shortName": "Azienda", "quoteType": "EQUITY", "currency": "USD",
            "financialCurrency": "USD", "currentPrice": 20,
            "trailingAnnualDividendRate": 2, "trailingEps": 4, "bookValue": 40,
            "sharesOutstanding": 20, "marketCap": 400, "trailingPE": 5})

    def analyze(ticker, full=True):
        st.session_state["analysis_calls"] = st.session_state.get("analysis_calls", 0) + 1
        if fail and ticker == "BBB":
            raise ValueError("Storico prezzi non disponibile")
        close = pd.Series([10., 15., 20.], index=pd.date_range("2025-01-01", periods=3))
        f = fund(ticker)
        return f, score_instrument("stock", f, price_metrics(close)), close, {}

    def financials(ticker, frequency):
        st.session_state["financial_calls"] = st.session_state.get("financial_calls", 0) + 1
        if fail and ticker == "BBB":
            raise ValueError("Bilancio non disponibile")
        return (pd.DataFrame({"operating_cashflow": [120.], "capex": [-20.], "net_borrowing": [0.]},
                             index=pd.to_datetime(["2025-12-31"]))
                if frequency == "annual" else pd.DataFrame())

    f, score, close, extras = analyze("AAA") if current_only else (None, None, None, None)
    current = {"ticker": "AAA", "fund": f, "res": score, "close": close, "extras": extras} if current_only else None
    watchlist = [] if current_only else [{"ticker": t, "name": "Azienda", "asset_class": "stock"}
                                         for t in ("AAA", "BBB")]
    render_company_comparison(watchlist, current, analyze, fund, financials)


def _run(**kwargs):
    return AppTest.from_function(_comparison_app, kwargs=kwargs, default_timeout=20).run()


def _load(app):
    return app.button(key="load_company_comparison").click().run()


def _table(app, indicator):
    return next(df.value.set_index("Indicatore") for df in app.dataframe
                if "Indicatore" in df.value and indicator in df.value["Indicatore"].tolist())


def test_companies_are_columns_and_filters_do_not_reload_data():
    app = _run()
    assert not app.exception
    assert "analysis_calls" not in app.session_state
    app = _load(app)
    assert not app.exception
    table = _table(app, "Gordon — valore")
    assert list(table.columns) == ["Azienda (AAA)", "Azienda (BBB)"]
    assert table.loc["Gordon — valore"].tolist() == ["25.50 USD", "25.50 USD"]
    calls = app.session_state["analysis_calls"], app.session_state["financial_calls"]
    app.number_input(key="valuation_return_comparison").set_value(12.0).run()
    assert not app.exception
    assert _table(app, "Gordon — valore").loc["Gordon — valore"].tolist() == ["20.40 USD", "20.40 USD"]
    app.text_input(key="company_metric_filter").set_value("Gordon").run()
    assert not app.exception
    assert _table(app, "Gordon — valore").index.str.contains("Gordon").all()
    assert calls == (app.session_state["analysis_calls"], app.session_state["financial_calls"])


def test_incomplete_company_keeps_fundamentals_and_column_with_visible_errors():
    app = _load(_run(fail=True))
    assert not app.exception
    assert any("BBB" in warning.value and "Bilancio" in warning.value for warning in app.warning)
    assert _table(app, "P/E trailing").loc["P/E trailing", "Azienda (BBB)"] == "5.00x"
    assert _table(app, "Cash flow operativo").loc["Cash flow operativo", "Azienda (BBB)"] == "n/d"


def test_selection_change_hides_previous_results_until_loaded():
    app = _load(_run())
    app.multiselect(key="company_comparison_selection").set_value(["AAA"]).run()
    assert not app.exception
    assert not app.dataframe
    app = _load(app)
    assert not app.exception
    assert list(_table(app, "P/E trailing").columns) == ["Azienda (AAA)"]


def test_current_company_is_available_without_watchlist():
    app = _run(current_only=True)
    assert not app.exception
    assert app.multiselect(key="company_comparison_selection").value == ["AAA"]
    app = _load(app)
    assert not app.exception
    assert _table(app, "Gordon — valore").loc["Gordon — valore", "Azienda (AAA)"] == "25.50 USD"


def test_common_scenario_and_history_controls_recalculate_without_errors():
    app = _load(_run())
    app.radio(key="company_comparison_scenario").set_value("Prudente").run()
    assert not app.exception
    assert _table(app, "Gordon — valore").loc["Gordon — valore"].tolist() == ["18.36 USD", "18.36 USD"]
    app.selectbox(key="company_history_metric").set_value("operating_cashflow").run()
    app.selectbox(key="company_history_frequency").set_value("quarterly").run()
    app.selectbox(key="company_history_view").set_value("TTM").run()
    assert not app.exception
    assert any("AAA" in info.value and "Storico" in info.value for info in app.info)
    app.selectbox(key="company_history_metric").set_value("drawdown").run()
    assert not app.exception
    assert app.selectbox(key="company_history_view").value == "Assoluto"


def _dashboard_app():
    from unittest.mock import patch
    import pandas as pd
    from soldoni.app import dashboard
    from soldoni.data.fundamentals import get_fundamentals

    def fundamental(ticker):
        return get_fundamentals(ticker, fetch=lambda _: {
            "shortName": ticker, "quoteType": "ETF" if ticker == "FUND" else "EQUITY",
            "currency": "EUR", "financialCurrency": "EUR", "currentPrice": 20,
            "trailingAnnualDividendRate": 2, "trailingEps": 4, "bookValue": 40,
            "sharesOutstanding": 20, "marketCap": 400})

    history = pd.DataFrame({"close": [20.] * 420}, index=pd.date_range("2025-01-01", periods=420))
    annual = pd.DataFrame({"operating_cashflow": [120.], "capex": [-20.], "net_borrowing": [0.]},
                          index=pd.to_datetime(["2025-12-31"]))
    conn = dashboard.store.init_db(":memory:")
    dashboard.store.add_to_watchlist(conn, "AAA", None, "AAA", "stock")
    dashboard.store.add_to_watchlist(conn, "FUND", None, "FUND", "etf")
    try:
        with (patch.object(dashboard, "_resolve_input", side_effect=lambda ticker: ticker),
              patch.object(dashboard.prices, "get_price_history_cached", return_value=history),
              patch.object(dashboard, "_cached_fundamentals", side_effect=fundamental),
              patch.object(dashboard, "_cached_eps", return_value=pd.Series(dtype=float)),
              patch.object(dashboard, "_cached_financials", side_effect=lambda ticker, frequency:
                           annual if frequency == "annual" else pd.DataFrame())):
            dashboard.page_analyzer(conn)
    finally:
        conn.close()


def test_full_analyzer_search_comparison_and_etf_watchlist_coexist():
    app = AppTest.from_function(_dashboard_app, default_timeout=20).run()
    assert not app.exception
    app.text_input[0].set_value("BBB")
    next(button for button in app.button if button.label == "Analizza").click().run()
    assert not app.exception
    app.multiselect(key="company_comparison_selection").set_value(["AAA", "BBB"]).run()
    app = _load(app)
    assert not app.exception
    assert list(_table(app, "Gordon — valore").columns) == ["AAA (AAA)", "BBB (BBB)"]
    assert any("Modello" in frame.value for frame in app.dataframe)
    assert any(header.value == "Confronto ETF (watchlist)" for header in app.subheader)
    assert any(select.label == "Rimuovi dalla watchlist" for select in app.selectbox)


def _fiscal_history_app():
    import pandas as pd
    import streamlit as st
    from soldoni.app.company_comparison import _render_history
    from soldoni.core.company_comparison import CompanySnapshot
    from soldoni.data.fundamentals import get_fundamentals

    snapshots = []
    for ticker, month in (("AAA", "03"), ("BBB", "04")):
        fund = get_fundamentals(ticker, fetch=lambda _: {"currency": "USD", "financialCurrency": "USD"})
        dates = pd.to_datetime([f"2023-{month}-30", f"2024-{month}-30", f"2025-{month}-30"])
        annual = pd.DataFrame({"revenue": [10., float("nan"), 30.]}, index=dates)
        snapshots.append(CompanySnapshot(ticker, fund, annual=annual))
    st.session_state["company_history_metric"] = "revenue"
    st.session_state["company_history_view"] = "Assoluto"
    _render_history(snapshots)


def test_history_traces_use_each_company_fiscal_dates_and_keep_its_missing_values():
    import json
    app = AppTest.from_function(_fiscal_history_app, default_timeout=15).run()
    assert not app.exception
    chart = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert len(chart["data"]) == 2
    assert all(len(trace["x"]) == 3 for trace in chart["data"])
