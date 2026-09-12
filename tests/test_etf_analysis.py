from datetime import date
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from soldoni.core.etf_profile import EtfHolding, EtfHoldings, EtfProfile, filter_non_hedged


def test_filter_keeps_only_verified_non_hedged_and_reports_both_exclusions():
    candidates = [SimpleNamespace(symbol=s) for s in ["YES", "NO", "UNKNOWN", "MISSING"]]
    profiles = {"YES": EtfProfile("YES", hedged=True), "NO": EtfProfile("NO", hedged=False),
                "UNKNOWN": EtfProfile("UNKNOWN")}
    eligible, hedged, unknown = filter_non_hedged(candidates, profiles)
    assert [c.symbol for c in eligible] == ["NO"]
    assert hedged == ["YES"]
    assert unknown == ["UNKNOWN", "MISSING"]


def setup_view(monkeypatch, *, partial=False, hedged=False):
    from soldoni.app import etf_analysis
    profile = EtfProfile("TEST.L", "IE00B4L5Y983", "Test ETF", hedged, "EUR" if hedged else "",
                         replication="Fisica", distribution="Accumulo", benchmark="World",
                         source_url="https://www.ishares.com/uk/individual/en/products/251882",
                         retrieved_on=date(2026, 9, 11))
    holdings = EtfHoldings((EtfHolding("Apple", "AAPL", 5.29, country="United States"),
                            EtfHolding("Small company", "SMALL", 0.0, country="Japan")),
                           "https://www.ishares.com/holdings.csv",
                           None if partial else date(2026, 9, 10), not partial)
    calls = []
    monkeypatch.setattr(etf_analysis, "cached_etf_profile", lambda *args: profile)
    def load(profile):
        calls.append(profile.ticker)
        return holdings
    monkeypatch.setattr(etf_analysis, "_cached_holdings", load)
    app = AppTest.from_string("""
from soldoni.app.etf_analysis import render_etf_analysis
render_etf_analysis('TEST.L', 'IE00B4L5Y983')
""").run()
    return app, calls


def test_composition_loads_on_click_and_search_does_not_download_again(monkeypatch):
    app, calls = setup_view(monkeypatch)
    assert not app.exception
    assert calls == []
    next(b for b in app.button if b.label == "Carica composizione ETF").click().run()
    assert not app.exception
    assert calls == ["TEST.L"]
    assert len(app.dataframe[-1].value) == 2
    assert any("10/09/2026" in c.value for c in app.caption)
    app.text_input(key="etf_holdings_search_TEST.L_IE00B4L5Y983").set_value("Small").run()
    assert not app.exception
    assert list(app.dataframe[-1].value["Nome"]) == ["Small company"]
    assert calls == ["TEST.L"]


def test_partial_composition_and_unknown_observation_date_are_visible(monkeypatch):
    app, _ = setup_view(monkeypatch, partial=True)
    next(b for b in app.button if b.label == "Carica composizione ETF").click().run()
    assert not app.exception
    assert any("parziale" in w.value.lower() for w in app.warning)
    assert any("Data della composizione: non disponibile" in c.value for c in app.caption)


def test_hedged_profile_is_marked_incompatible_with_preference(monkeypatch):
    app, _ = setup_view(monkeypatch, hedged=True)
    assert not app.exception
    assert any("hedged" in w.value.lower() for w in app.warning)
    assert any(m.value == "Sì (EUR)" for m in app.metric)


def test_source_failure_is_shown_and_does_not_break_analyzer(monkeypatch):
    from soldoni.app import etf_analysis
    def fail(*args):
        raise ValueError("Fonte offline")
    monkeypatch.setattr(etf_analysis, "cached_etf_profile", fail)
    app = AppTest.from_string("""
from soldoni.app.etf_analysis import render_etf_analysis
render_etf_analysis('TEST.L')
""").run()
    assert not app.exception
    assert any("Fonte offline" in e.value for e in app.error)
    assert any(m.value == "Non verificata" for m in app.metric)


def test_discovery_defaults_to_non_hedged_and_can_show_excluded_profiles(monkeypatch):
    import pandas as pd
    from soldoni.app import dashboard
    from soldoni.core.scoring import score_instrument
    from soldoni.core.screen_metrics import price_metrics
    from soldoni.data.fundamentals import get_fundamentals
    from soldoni.data.screener import Candidate

    candidates = [Candidate(s, s, "ETF") for s in ["NO.L", "YES.L", "UNKNOWN.L"]]
    monkeypatch.setattr(dashboard.screener, "screen_candidates", lambda *a, **kw: candidates)
    def analyze(conn, ticker):
        fund = get_fundamentals(ticker, fetch=lambda _: {"quoteType": "ETF", "shortName": ticker})
        close = pd.Series([100., 102., 103.], index=pd.date_range("2026-01-01", periods=3))
        return fund, score_instrument("etf", fund, price_metrics(close)), close, {}
    monkeypatch.setattr(dashboard, "_analyze", analyze)
    monkeypatch.setattr(dashboard, "cached_etf_profile", lambda ticker, **kw:
                        EtfProfile(ticker, hedged={"NO.L": False, "YES.L": True}.get(ticker)))
    app = AppTest.from_string("""
import streamlit as st
from soldoni.app.dashboard import page_discover
from soldoni.data.store import init_db
if 'conn' not in st.session_state:
    st.session_state['conn'] = init_db(':memory:')
page_discover(st.session_state['conn'])
""").run()
    app.radio(key="discover_asset").set_value("ETF").run()
    assert app.checkbox(key="discover_non_hedged").value is True
    next(b for b in app.button if "Cerca" in b.label).click().run(timeout=10)
    assert not app.exception
    assert list(app.dataframe[0].value["Ticker"]) == ["NO.L"]
    assert any("YES.L" in c.value for c in app.caption)
    assert any("UNKNOWN.L" in c.value for c in app.caption)
    app.checkbox(key="discover_non_hedged").uncheck().run()
    next(b for b in app.button if "Cerca" in b.label).click().run(timeout=10)
    assert not app.exception
    assert set(app.dataframe[0].value["Ticker"]) == {"NO.L", "YES.L", "UNKNOWN.L"}
    assert "Copertura valutaria" in app.dataframe[0].value


def test_unavailable_catalog_is_requested_once_per_market_in_a_search():
    from soldoni.app.etf_analysis import load_etf_profiles
    from soldoni.data.etf_data import CatalogUnavailable
    calls = []
    def offline(ticker, **kwargs):
        calls.append(ticker)
        raise CatalogUnavailable("Catalogo offline: " + ticker.rsplit(".", 1)[-1])
    candidates = [SimpleNamespace(symbol=s) for s in ["ONE.L", "TWO.L", "THREE.MI"]]
    profiles, errors = load_etf_profiles(candidates, offline)
    assert calls == ["ONE.L", "THREE.MI"]
    assert all(p.hedged is None for p in profiles.values())
    assert len(errors) == 2
