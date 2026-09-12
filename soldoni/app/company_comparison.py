"""Confronto affiancato delle aziende nell'Analizzatore."""

import logging

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from soldoni.app.company_analysis import render_valuation_assumptions, _render_formulas
from soldoni.core.company_comparison import (
    GROUPS, HISTORY_FIELDS, MARGINS, CompanySnapshot, company_metrics, comparison_history,
)
from soldoni.core.company_valuation import scenario_assumptions
from soldoni.core.scoring import score_instrument
from soldoni.core.screen_metrics import price_metrics

logger = logging.getLogger(__name__)


def _load_company(ticker, current, load_analysis, load_fundamentals, load_financials):
    snapshot = CompanySnapshot(ticker)
    issues = []
    if current and current["ticker"] == ticker:
        snapshot.fund, snapshot.score = current["fund"], current["res"]
        snapshot.close, snapshot.extras = current["close"], current["extras"]
    else:
        for full in (True, False):
            try:
                snapshot.fund, snapshot.score, snapshot.close, snapshot.extras = load_analysis(ticker, full=full)
                break
            except Exception as e:
                logger.exception("Analisi per confronto non disponibile: %s (full=%s)", ticker, full)
                issues.append(f"Analisi {'completa' if full else 'prezzi'}: {e}")
        if snapshot.fund is None:
            try:
                snapshot.fund = load_fundamentals(ticker)
                snapshot.score = score_instrument("stock", snapshot.fund, price_metrics(snapshot.close))
            except Exception as e:
                logger.exception("Fondamentali per confronto non disponibili: %s", ticker)
                issues.append(f"Fondamentali: {e}")
    if snapshot.fund and snapshot.fund.quote_type != "EQUITY":
        issues.append("Lo strumento non è un'azienda quotata: indicatori aziendali non applicabili.")
        snapshot.fund = None
    if snapshot.fund:
        for frequency in ("annual", "quarterly"):
            try:
                setattr(snapshot, frequency, load_financials(ticker, frequency))
            except Exception as e:
                logger.exception("Bilancio %s per confronto non disponibile: %s", frequency, ticker)
                issues.append(f"Bilancio {frequency}: {e}")
    snapshot.issues = tuple(issues)
    return snapshot


def _render_history(snapshots):
    st.subheader("Storici a confronto")
    left, middle, right = st.columns(3)
    metric = left.selectbox("Indicatore storico", list(HISTORY_FIELDS),
                            format_func=HISTORY_FIELDS.get, key="company_history_metric")
    financial = metric not in {"price", "drawdown", "pe"}
    frequency = middle.selectbox("Bilanci", ["annual", "quarterly"],
        format_func=lambda value: "Annuali" if value == "annual" else "Trimestrali",
        disabled=not financial, key="company_history_frequency")
    views = ["Base 100", "Assoluto"]
    if financial and metric not in MARGINS:
        views.append("YoY %")
        if frequency == "quarterly":
            views.append("TTM")
    if metric in MARGINS or metric == "drawdown":
        views = ["Assoluto"]
    if st.session_state.get("company_history_view") not in views:
        st.session_state["company_history_view"] = views[0]
    view = right.selectbox("Vista storico", views, key="company_history_view")
    frame, issues = comparison_history(snapshots, metric, frequency, view)
    for ticker, reason in issues.items():
        st.info(f"{ticker}: {reason}")
    if frame.empty:
        return
    unit = ("Base 100" if view == "Base 100" else "%" if view == "YoY %" or metric in MARGINS
            or metric == "drawdown" else "P/E" if metric == "pe" else next(
                (s.fund.financial_currency if financial else s.fund.currency)
                for s in snapshots if s.fund and s.label in frame.columns))
    fig = go.Figure()
    for snapshot in snapshots:
        if snapshot.label not in frame:
            continue
        dates = (snapshot.annual if frequency == "annual" else snapshot.quarterly).index if financial else frame.index
        values = frame[snapshot.label].reindex(frame.index.intersection(dates))
        fig.add_trace(go.Scatter(x=values.index, y=values, name=snapshot.label,
                                 mode="lines+markers" if financial else "lines", connectgaps=False))
    fig.update_layout(title=f"{HISTORY_FIELDS[metric]} — {view}", yaxis_title=unit,
                       height=400, hovermode="x unified", legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Prezzi in valuta nativa: Base 100 parte dalla prima data comune. "
               "Per i bilanci, Base 100 parte dal primo periodo disponibile di ciascuna azienda; "
               "le date fiscali restano quelle della fonte. CapEx e dividendi pagati sono uscite positive. "
               "YoY richiede il periodo di un anno prima; TTM richiede quattro trimestri consecutivi.")


def render_company_comparison(watchlist, current, load_analysis, load_fundamentals,
                              load_financials) -> None:
    """Carica le aziende scelte e confronta gli stessi dati con ipotesi comuni."""
    st.subheader("Confronto aziende")
    names = {item["ticker"]: f"{item['name'] or item['ticker']} ({item['ticker']})"
             for item in watchlist if item["asset_class"] != "etf"}
    if current and current["fund"].quote_type == "EQUITY":
        names[current["ticker"]] = f"{current['fund'].name or current['ticker']} ({current['ticker']})"
    if not names:
        st.info("Analizza un'azienda o aggiungi azioni alla watchlist per confrontarle.")
        return
    st.caption("Aziende in colonne, indicatori in righe. Seleziona dalla watchlist o usa "
               "l'azienda appena analizzata; filtra i dati da affiancare.")
    key = "company_comparison_selection"
    if key in st.session_state:
        st.session_state[key] = [ticker for ticker in st.session_state[key] if ticker in names]
    chosen = st.multiselect("Aziende da confrontare", list(names), default=list(names)[:4],
                            format_func=names.get, key=key)
    if st.button("Confronta aziende", key="load_company_comparison", disabled=not chosen):
        with st.spinner("Carico i dati delle aziende selezionate…"):
            st.session_state["company_comparison_data"] = [
                _load_company(ticker, current, load_analysis, load_fundamentals, load_financials)
                for ticker in chosen]
    snapshots = st.session_state.get("company_comparison_data", [])
    if not chosen:
        st.info("Seleziona almeno un'azienda.")
        return
    if [snapshot.ticker for snapshot in snapshots] != chosen:
        st.info("Premi Confronta aziende per caricare questa selezione.")
        return
    for snapshot in snapshots:
        for issue in snapshot.issues:
            st.warning(f"{snapshot.ticker}: {issue}")
    if not any(snapshot.fund for snapshot in snapshots):
        st.info("Dati aziendali non disponibili per la selezione. Riprova con Confronta aziende.")
        return
    selected_groups = st.multiselect("Gruppi di dati", list(GROUPS), default=list(GROUPS),
                                     key="company_comparison_groups")
    query = st.text_input("Cerca indicatore", placeholder="Es. margine, cash flow, Gordon…",
                          key="company_metric_filter").strip().casefold()
    assumptions = render_valuation_assumptions("comparison", "Ipotesi comuni per il confronto")
    scenario = st.radio("Scenario comune", ["Base", "Prudente", "Ottimista"],
                         horizontal=True, key="company_comparison_scenario")
    effective = scenario_assumptions(assumptions, scenario)
    st.caption(f"Ipotesi applicate a tutte le aziende: rendimento {effective.required_return:.1%}; "
               f"crescita perpetua {effective.terminal_growth:.1%}; dividendi {effective.dividend_growth:.1%}; "
               f"FCFE {effective.fcfe_growth:.1%}; {effective.years} anni; "
               f"P/E {effective.multiple:g}; margine {effective.margin:.0%}. Scenari ipotetici, non previsioni.")
    st.caption("Fonte: Yahoo Finance. Importi nella valuta indicata in ciascuna cella; nessuna conversione "
               "automatica tra bilanci. Rapporti percentuali e multipli usano scale comuni. "
               "Punteggi su soglie anche settoriali, calcolati sui dati disponibili. "
               "Il periodo dei flussi e le date degli storici sono nel Riepilogo; "
               "la fonte non fornisce una data di osservazione per ogni fondamentale o target analisti.")
    results = {snapshot.ticker: company_metrics(snapshot, effective) for snapshot in snapshots}
    missing = []
    shown = False
    for group in selected_groups:
        labels = dict.fromkeys(label for result in results.values() for label in result[group]
                               if query in label.casefold())
        if not labels:
            continue
        rows = []
        for label in labels:
            row = {"Indicatore": label}
            for snapshot in snapshots:
                metric = results[snapshot.ticker][group].get(label)
                row[snapshot.label] = metric.display() if metric else "n/d"
                if metric is None or metric.reason:
                    reason = metric.reason if metric else " · ".join(snapshot.issues) or "Dati aziendali assenti."
                    missing.append({"Azienda": snapshot.label, "Indicatore": label, "Motivo": reason})
            rows.append(row)
        with st.expander(group, expanded=True):
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        shown = True
    if not shown:
        st.info("Nessun indicatore corrisponde ai filtri selezionati.")
    if missing:
        with st.expander(f"Dati non disponibili: motivi ({len(missing)})"):
            st.dataframe(pd.DataFrame(missing), hide_index=True, width="stretch")
    _render_formulas()
    _render_history(snapshots)
