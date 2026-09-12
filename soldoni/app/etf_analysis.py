from dataclasses import asdict
import logging

import pandas as pd
import streamlit as st

from soldoni.core.etf_profile import EtfProfile, hedge_label
from soldoni.data import etf_data

logger = logging.getLogger(__name__)


@st.cache_data(ttl=86400, show_spinner=False)
def _cached_catalog(market):
    return etf_data.get_ishares_catalog(market)


@st.cache_data(ttl=86400, show_spinner=False)
def cached_etf_profile(ticker: str, isin: str = "", details: bool = True) -> EtfProfile:
    """Cache verified characteristics without caching failures as valid profiles."""
    market = ticker.upper().rsplit(".", 1)[-1]
    if market not in {"L", "MI", "DE"}:
        if not isin:
            return EtfProfile(ticker, note="Mercato non coperto: analizza tramite ISIN.")
        market = "L"
    return etf_data.get_etf_profile(ticker, isin, catalog=_cached_catalog(market), details=details)


@st.cache_data(ttl=86400, show_spinner=False)
def _cached_holdings(profile):
    return etf_data.get_etf_holdings(profile)


def load_etf_profiles(candidates, loader=cached_etf_profile):
    """Classify candidates, requesting a failed shared catalog only once per search."""
    profiles, errors, failed_markets = {}, [], set()
    for candidate in candidates:
        market = candidate.symbol.upper().rsplit(".", 1)[-1]
        if market in failed_markets:
            profiles[candidate.symbol] = EtfProfile(candidate.symbol)
            continue
        try:
            profiles[candidate.symbol] = loader(candidate.symbol, details=False)
        except ValueError as e:
            logger.exception("Verifica copertura ETF fallita: %s", candidate.symbol)
            profiles[candidate.symbol] = EtfProfile(candidate.symbol)
            errors.append(str(e))
            if isinstance(e, etf_data.CatalogUnavailable):
                failed_markets.add(market)
    return profiles, errors


def render_etf_analysis(ticker: str, isin: str = "") -> None:
    """Render characteristics and an explicitly loaded, searchable ETF portfolio."""
    st.subheader("Caratteristiche ETF")
    identity = f"{ticker}_{isin}"
    state_key = f"etf_holdings_{identity}"
    if st.button("Aggiorna caratteristiche ETF", key=f"etf_refresh_{identity}"):
        cached_etf_profile.clear()
        _cached_catalog.clear()
        st.session_state.pop(state_key, None)
    try:
        with st.spinner("Leggo le caratteristiche ETF…"):
            profile = cached_etf_profile(ticker, isin)
    except ValueError as e:
        logger.exception("Scheda ETF non disponibile per %s", ticker)
        st.error(str(e))
        profile = EtfProfile(ticker, isin)
    columns = st.columns(3)
    columns[0].metric("Copertura valutaria", hedge_label(profile))
    columns[1].metric("Replica", profile.replication or "Non disponibile")
    columns[2].metric("Proventi", profile.distribution or "Non disponibile")
    st.write("**Indice replicato:** " + (profile.benchmark or "Non disponibile"))
    if profile.isin:
        st.caption("ISIN: " + profile.isin)
    if profile.expense_ratio is not None:
        st.caption(f"TER dell'emittente: {profile.expense_ratio * 100:.3f}% annuo")
    if profile.source_url:
        st.link_button("Scheda ufficiale dell'ETF", profile.source_url)
        if profile.retrieved_on:
            st.caption("Caratteristiche consultate il " + profile.retrieved_on.strftime("%d/%m/%Y") +
                       ". La data di pubblicazione delle caratteristiche non è fornita.")
    if profile.hedged is True:
        st.warning("ETF hedged: non rispetta la tua preferenza per ETF senza copertura valutaria.")
    elif profile.hedged is None:
        st.warning("Copertura valutaria non verificata: questo ETF non supera il filtro non hedged.")
    if profile.note:
        st.info(profile.note)
    if "Sintetica" in profile.replication:
        st.info("La composizione mostra il paniere detenuto dal fondo. Per una replica sintetica "
                "può essere diverso dai titoli dell'indice replicato.")

    st.subheader("Titoli nell'ETF")
    load = st.button("Carica composizione ETF", key=f"etf_holdings_load_{identity}")
    refresh = st.button("Aggiorna composizione ETF", key=f"etf_holdings_refresh_{identity}",
                        disabled=state_key not in st.session_state)
    if load or refresh:
        if refresh:
            _cached_holdings.clear()
        try:
            with st.spinner("Scarico la composizione ETF…"):
                holdings = _cached_holdings(profile)
        except ValueError as e:
            logger.exception("Visualizzazione composizione ETF fallita per %s", ticker)
            st.session_state.pop(state_key, None)
            st.error(str(e))
        else:
            st.session_state[state_key] = holdings
    holdings = st.session_state.get(state_key)
    if holdings is None:
        st.caption("Carica l'elenco dell'emittente dove disponibile. Per gli altri ETF, "
                   "Yahoo può fornire soltanto le principali posizioni.")
        return
    if holdings.complete:
        st.caption("Elenco dell'emittente: tutte le righe pubblicate nel download.")
    else:
        st.warning("Composizione parziale: sono disponibili soltanto le principali posizioni. "
                   "Il numero mostrato non è il numero totale dei titoli dell'ETF.")
    st.caption("Data della composizione: " + (
        holdings.as_of.strftime("%d/%m/%Y") if holdings.as_of else "non disponibile"))
    st.link_button("Fonte della composizione", holdings.source_url)
    columns = st.columns(2)
    columns[0].metric("Posizioni pubblicate", len(holdings.rows))
    columns[1].metric("Somma dei pesi pubblicati", f"{sum(r.weight_pct for r in holdings.rows):.2f}%")
    st.caption("I pesi originali non sono riscalati al 100%. Sono incluse anche le posizioni "
               "con peso arrotondato a zero, la liquidità e i derivati quando pubblicati.")
    query = st.text_input("Cerca titolo, ticker o ISIN", key=f"etf_holdings_search_{identity}")
    frame = pd.DataFrame(asdict(row) for row in holdings.rows).rename(columns={
        "name": "Nome", "ticker": "Ticker", "isin": "ISIN", "weight_pct": "Peso %",
        "sector": "Settore", "country": "Paese", "asset_class": "Tipo", "currency": "Valuta"})
    if query.strip():
        mask = frame[["Nome", "Ticker", "ISIN"]].apply(
            lambda col: col.str.contains(query.strip(), case=False, regex=False)).any(axis=1)
        frame = frame[mask]
    frame = frame.sort_values("Peso %", ascending=False, kind="stable")
    st.caption(f"Posizioni visualizzate: {len(frame)} / {len(holdings.rows)}")
    st.dataframe(frame, hide_index=True, use_container_width=True,
                 column_config={"Peso %": st.column_config.NumberColumn(format="%.2f")})
