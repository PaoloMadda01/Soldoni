import json
import hashlib
from io import BytesIO
import logging
import os
import sys
import calendar
from dataclasses import replace
from datetime import date, timedelta
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_option_menu import option_menu

from soldoni.core.models import OpType, Transaction, Instrument
from soldoni.core.holdings import build_portfolio_state
from soldoni.core.net_gain import (
    realized_net_gain, latent_net_gain, dividend_net, country_from_isin)
from soldoni.core.tax import compute_zainetto, compute_zainetto_for_year
from soldoni.core.tax_report import build_tax_report_xlsx, realized_rows
from soldoni.core.valuation import (
    quantity_timeline, portfolio_value_eur,
    invested_timeline, drawdown, monthly_net_invested, average_monthly_purchases)
from soldoni.core.twr import twr_index
from soldoni.core.returns import xirr
from soldoni.core.risk import (
    business_day_returns, annualized_volatility, sharpe, sortino, beta,
    rolling_volatility, rolling_beta, correlation_matrix, monthly_returns_table)
from soldoni.core.allocation import geo_breakdown, sector_breakdown
from soldoni.core.attribution import pnl_attribution, attribution_shares
from soldoni.core.concentration import (
    herfindahl, effective_positions, top_n_weight, concentration_alerts)
from soldoni.core.currency import (
    currency_exposure, weighted_entry_fx, fx_price_decomposition)
from soldoni.data import store
from soldoni.data.fineco_import import parse_fineco_export_with_instruments
from soldoni.data import prices
from soldoni.data import fundamentals
from soldoni.data import valuation_history
from soldoni.core.screen_metrics import price_metrics, trailing_return
from soldoni.core import scoring
from soldoni.data import financials
from soldoni.core import financial_trends
from soldoni.data import screener
from soldoni.core import discovery
from soldoni.core.rebalancing import (
    validate_target_weights, rebalance_trades, allocate_contribution,
    estimate_trade_costs)
from soldoni.core.simulation import (
    stress_portfolio, months_to_target, simulate_goal, historical_assumptions)
from soldoni.core.financing import FinancingOption, simulate_financing_decision
from soldoni.core.period_summary import required_price_isins, summarize_period
from soldoni.data import backups, import_preview
from soldoni.core.etf_costs import summarize_etf_costs
from soldoni.core.comparison import adjusted_prices_eur, base100_comparison
from soldoni.core.portfolio_comparison import (
    group_portfolio_transactions, portfolio_group_index, compare_portfolio_histories,
    portfolio_prices_eur)
from soldoni.app.company_analysis import render_company_analysis
from soldoni.app.company_comparison import render_company_comparison
from soldoni.app.currency_simulation import render_currency_simulation
from soldoni.app.etf_analysis import cached_etf_profile, load_etf_profiles, render_etf_analysis
from soldoni.core.etf_profile import EtfProfile, filter_non_hedged, hedge_label

logger = logging.getLogger(__name__)


def _db_path():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        message = "Variabile LOCALAPPDATA non disponibile"
        logger.error(message)
        raise RuntimeError(message)
    data_dir = os.path.join(local_app_data, "Soldoni")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "soldoni.db")

BENCHMARKS = {"S&P 500": ("^SP500TR", "USD"), "MSCI World": ("EUNL.DE", "EUR")}


@st.cache_resource
def get_conn():
    return store.init_db(_db_path())


def _auto_create_instruments(conn, imported_instruments):
    existing = store.get_instruments(conn)
    created = 0
    warnings = []
    for isin, imported in imported_instruments.items():
        if isin in existing:
            continue

        ticker = ""
        fund = None
        try:
            ticker = prices.resolve_ticker(
                isin, name=imported.name,
                base_currency=imported.native_currency or "EUR")
        except Exception as e:
            logger.exception("Risoluzione ticker fallita per %s", isin)
            warnings.append(f"{isin}: ticker non trovato ({e})")

        if ticker:
            try:
                fund = fundamentals.get_fundamentals(ticker)
            except Exception as e:
                logger.exception("Download anagrafica Yahoo fallito per %s [%s]", isin, ticker)
                warnings.append(f"{isin} [{ticker}]: dettagli Yahoo non disponibili ({e})")

        quote_type = fund.quote_type.upper() if fund and fund.quote_type else ""
        asset_class = "etf" if quote_type in {"ETF", "MUTUALFUND"} else "azione"
        macro_area = (fundamentals.macro_area_from_country(fund.country)
                      if fund and asset_class != "etf" else "Non disponibile")
        store.upsert_instrument(conn, Instrument(
            isin=isin,
            yahoo_ticker=ticker,
            name=(fund.name if fund and fund.name else imported.name),
            native_currency=(fund.currency if fund and fund.currency
                             else imported.native_currency or "EUR"),
            asset_class=asset_class,
            macro_area=macro_area,
            sector=(fund.sector if fund and fund.sector else "Non disponibile"),
        ))
        created += 1
    return created, warnings


def _transaction_rows(transactions):
    return pd.DataFrame([
        {
            "Data": tx.trade_date,
            "ISIN": tx.isin,
            "Tipo": tx.op_type.value,
            "Quantità": tx.quantity,
            "Controvalore EUR": tx.amount_eur,
            "Commissioni EUR": tx.commission_eur,
        }
        for tx in transactions
    ])


def _pending_import(conn, uploaded):
    content = uploaded.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    if st.session_state.get("completed_import_digest") == digest:
        return None
    pending = st.session_state.get("pending_import")
    if pending and pending["digest"] == digest:
        return pending
    transactions, instruments = parse_fineco_export_with_instruments(BytesIO(content))
    preview = import_preview.classify_import(transactions, store.get_transactions(conn))
    pending = {
        "digest": digest,
        "transactions": transactions,
        "instruments": instruments,
        "preview": preview,
    }
    st.session_state["pending_import"] = pending
    return pending


def _render_import_preview(conn, uploaded):
    if st.session_state.get("completed_import_digest") == hashlib.sha256(
            uploaded.getvalue()).hexdigest():
        st.info("Questo file è già stato confermato in questa sessione.")
        return
    try:
        pending = _pending_import(conn, uploaded)
    except ValueError as e:
        st.session_state.pop("pending_import", None)
        logger.warning("Anteprima import Fineco non disponibile: %s", e)
        st.error(f"Errore nell'import: {e}")
        return
    if pending is None:
        return

    preview = pending["preview"]
    existing_instruments = store.get_instruments(conn)
    new_instrument_isins = sorted(set(pending["instruments"]) - set(existing_instruments))
    st.subheader("Anteprima importazione")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Operazioni lette", len(pending["transactions"]))
    c2.metric("Nuove", len(preview.new_transactions))
    c3.metric("Duplicate", len(preview.duplicates))
    c4.metric("Nuove anagrafiche", len(new_instrument_isins))
    if pending["transactions"]:
        trade_dates = [tx.trade_date for tx in pending["transactions"]]
        st.caption(f"Periodo del file: {min(trade_dates):%d/%m/%Y} – "
                   f"{max(trade_dates):%d/%m/%Y}")
    if preview.new_transactions:
        st.dataframe(_transaction_rows(preview.new_transactions),
                     width="stretch", hide_index=True)
    if preview.duplicates:
        with st.expander(f"Operazioni duplicate ({len(preview.duplicates)})"):
            st.dataframe(_transaction_rows(preview.duplicates),
                         width="stretch", hide_index=True)
    if preview.conflicts:
        st.error("Esistono operazioni con la stessa chiave ma dati contabili diversi. "
                 "Correggi il file prima di importarlo.")
        st.dataframe(pd.DataFrame([
            {
                "Data": conflict.incoming.trade_date,
                "ISIN": conflict.incoming.isin,
                "Tipo": conflict.incoming.op_type.value,
                "Commissione esistente": conflict.existing.commission_eur,
                "Commissione nel file": conflict.incoming.commission_eur,
                "Data valuta esistente": conflict.existing.value_date,
                "Data valuta nel file": conflict.incoming.value_date,
            }
            for conflict in preview.conflicts
        ]), width="stretch", hide_index=True)
        return

    has_writes = bool(preview.new_transactions or new_instrument_isins)
    if not has_writes:
        st.info("Non ci sono nuove operazioni o anagrafiche da salvare.")
        return
    if st.button("Conferma importazione", type="primary"):
        refreshed = import_preview.classify_import(
            pending["transactions"], store.get_transactions(conn))
        if refreshed.conflicts:
            pending["preview"] = refreshed
            st.error("Il database è cambiato dopo l'anteprima: ricontrolla i conflitti.")
            return
        current_instruments = store.get_instruments(conn)
        missing_instruments = set(pending["instruments"]) - set(current_instruments)
        if not refreshed.new_transactions and not missing_instruments:
            st.info("Le operazioni risultano già presenti: nessuna modifica eseguita.")
            return
        try:
            backup_path = backups.create_backup(
                conn, backups.backup_directory(conn), "prima_dell_import")
            inserted = store.insert_transactions(conn, list(refreshed.new_transactions))
            with st.spinner("Completo automaticamente l'anagrafica strumenti…"):
                created, warnings = _auto_create_instruments(conn, pending["instruments"])
        except Exception as e:
            logger.exception("Importazione Fineco fallita")
            st.error(f"Importazione non riuscita: {e}")
            return
        st.session_state["completed_import_digest"] = pending["digest"]
        st.session_state.pop("pending_import", None)
        st.success(f"Importate {inserted} nuove operazioni; create {created} nuove anagrafiche. "
                   f"Backup: {backup_path.name}")
        if warnings:
            st.warning("Anagrafica automatica parziale:\n\n- " + "\n- ".join(warnings))


def _render_backups(conn):
    st.subheader("Backup e ripristino")
    restore_success = st.session_state.pop("restore_success", None)
    if restore_success:
        st.success(restore_success)
    try:
        directory = backups.backup_directory(conn)
    except ValueError as e:
        st.error(str(e))
        return
    if st.button("Crea backup adesso"):
        try:
            path = backups.create_backup(conn, directory, "manuale")
            st.success(f"Backup creato: {path.name}")
        except Exception as e:
            logger.exception("Backup manuale fallito")
            st.error(f"Backup non riuscito: {e}")

    available = backups.list_backups(directory)
    if not available:
        st.caption("Nessun backup disponibile.")
        return
    selected_name = st.selectbox("Copia disponibile", [info.path.name for info in available])
    selected = next(info for info in available if info.path.name == selected_name)
    st.caption(f"Creato il {selected.modified_at:%d/%m/%Y alle %H:%M:%S} · "
               f"{selected.size_bytes / 1024 / 1024:.1f} MB")
    st.download_button(
        "Scarica copia", data=selected.path.read_bytes(), file_name=selected.path.name,
        mime="application/vnd.sqlite3")
    confirmed = st.checkbox(
        f"Confermo il ripristino di {selected.path.name}: i dati correnti saranno sostituiti",
        key=f"confirm_restore_{selected.path.name}")
    if st.button("Ripristina copia", disabled=not confirmed):
        try:
            safety = backups.restore_backup(conn, selected.path, directory)
        except Exception as e:
            logger.exception("Ripristino backup fallito")
            st.error(f"Ripristino non riuscito: {e}")
            return
        for key in ("pending_import", "completed_import_digest", "goal_result",
                    "price_refresh_result", "instrument_comparison", "portfolio_comparison"):
            st.session_state.pop(key, None)
        st.cache_data.clear()
        st.session_state["restore_success"] = (
            f"Ripristino completato. Copia preventiva: {safety.name}")
        st.rerun()


def page_import(conn):
    st.header("Import & Anagrafica")

    up = st.file_uploader("Export Fineco (.xlsx)", type=["xlsx"])
    if up is not None:
        _render_import_preview(conn, up)

    _render_backups(conn)

    st.subheader("Inserimento manuale operazione")
    with st.form("manual_tx"):
        c1, c2, c3 = st.columns(3)
        d = c1.date_input("Data", value=date.today())
        isin = c2.text_input("ISIN")
        op = c3.selectbox("Tipo", [o.value for o in OpType])
        c4, c5 = st.columns(2)
        qty = c4.number_input("Quantità", min_value=0.0, step=1.0)
        amount = c5.number_input("Controvalore EUR", min_value=0.0, step=10.0)
        apply_comm = st.checkbox("Applica commissione", value=True)
        comm = st.number_input("Commissione EUR", value=2.95, step=0.05,
                               disabled=not apply_comm)
        if st.form_submit_button("Aggiungi"):
            commission = comm if apply_comm else 0.0
            tx = Transaction(d, d, isin.strip(), OpType(op), qty, amount, 0.0, 1.0,
                             commission, source="manual")
            store.insert_transactions(conn, [tx])
            st.success("Operazione aggiunta.")

    st.subheader("Anagrafica strumenti")
    txs = store.get_transactions(conn)
    instruments = store.get_instruments(conn)
    isins = sorted({t.isin for t in txs})
    missing = [i for i in isins if i not in instruments]
    if missing:
        st.warning(f"ISIN da mappare: {', '.join(missing)}")
    if isins:
        with st.form("anagrafica"):
            sel = st.selectbox("ISIN", isins)
            cur = instruments.get(sel)
            ticker = st.text_input("Ticker Yahoo", value=cur.yahoo_ticker if cur else "")
            excl = st.checkbox("Escludi dalle analisi",
                               value=cur.excluded if cur else False)
            auto_resolve = st.checkbox(
                "Verifica/risolvi ticker su Yahoo al salvataggio", value=True)
            name = st.text_input("Nome", value=cur.name if cur else "")
            curr = st.text_input("Valuta nativa", value=cur.native_currency if cur else "EUR")
            area = st.text_input("Macro-area", value=cur.macro_area if cur else "")
            _asset_opts = ["azione", "etf", "obbligazione"]
            cur_asset = cur.asset_class if cur and cur.asset_class in _asset_opts else "azione"
            asset = st.selectbox("Tipo strumento", _asset_opts,
                                 index=_asset_opts.index(cur_asset))
            weights_raw = st.text_input(
                "Ripartizione geo opzionale (JSON area->peso)",
                value=json.dumps(cur.geo_weights) if cur and cur.geo_weights else "")
            sector = st.text_input("Settore", value=cur.sector if cur else "")
            sweights_raw = st.text_input(
                "Ripartizione settori opzionale (JSON settore->peso)",
                value=json.dumps(cur.sector_weights) if cur and cur.sector_weights else "")
            if st.form_submit_button("Salva anagrafica"):
                gw = json.loads(weights_raw) if weights_raw.strip() else None
                sw = json.loads(sweights_raw) if sweights_raw.strip() else None
                final_ticker = ticker.strip()
                if auto_resolve:
                    try:
                        with st.spinner("Verifica ticker su Yahoo…"):
                            final_ticker = prices.resolve_ticker(
                                sel, name=name.strip() or None,
                                ticker=ticker.strip() or None,
                                base_currency=curr.strip() or "EUR")
                        if final_ticker != ticker.strip():
                            st.info(f"Ticker risolto automaticamente: {final_ticker}")
                    except ValueError as e:
                        st.warning(f"Ticker non verificato ({e}); salvo '{final_ticker}' così com'è.")
                store.upsert_instrument(conn, Instrument(sel, final_ticker, name.strip(),
                                                         curr.strip(), asset, area.strip(), gw,
                                                         sector.strip(), sw, excluded=excl))
                st.success("Anagrafica salvata.")


def _eur_price_frame(conn, instruments, isins, dates, start_dates=None):
    """Costruisce prezzi EUR (close) e total-return EUR (adj) per gli ISIN dati su 'dates'.
    Ritorna anche le serie dei cambi EUR->valuta per ogni valuta non-EUR incontrata."""
    start = dates.min().date()
    end = dates.max().date()
    fx_by_ccy = {}
    close_eur = {}
    adj_eur = {}
    for isin in isins:
        inst = instruments[isin]
        price_start = start_dates.get(isin, start) if start_dates else start
        try:
            hist = prices.get_price_history_cached(
                conn, inst.yahoo_ticker, price_start, end).reindex(dates).ffill()
            if inst.native_currency == "EUR":
                rate = pd.Series(1.0, index=dates)
            else:
                if inst.native_currency not in fx_by_ccy:
                    pair = f"EUR{inst.native_currency}=X"
                    fx_by_ccy[inst.native_currency] = (
                        prices.get_fx_history_cached(conn, pair, start, end).reindex(dates).ffill())
                rate = fx_by_ccy[inst.native_currency]
        except ValueError:
            continue  # nessun dato per questo ticker: escluso con avviso a valle
        close_eur[isin] = hist["close"] / rate
        adj_eur[isin] = hist["adj_close"] / rate
    return (pd.DataFrame(close_eur, index=dates),
            pd.DataFrame(adj_eur, index=dates), fx_by_ccy)


def _render_held_instruments(conn, txs, instruments):
    state = build_portfolio_state(txs, on_oversell="skip")
    held = sorted(
        (isin for isin in state.positions
         if isin in instruments and instruments[isin].asset_class in ("azione", "stock", "etf")),
        key=lambda isin: (instruments[isin].name or isin).lower(),
    )
    if not held:
        return

    st.subheader("Strumenti posseduti")
    st.caption("Seleziona un'azienda o un ETF per visualizzare i dettagli e scegliere se "
               "considerarlo nelle analisi.")
    rows = []
    for isin in held:
        inst = instruments[isin]
        rows.append({
            "Nome": inst.name or isin,
            "Tipo": "ETF" if inst.asset_class == "etf" else "Azione",
            "Quantità": round(state.positions[isin].quantity, 6),
            "Stato": "Esclusa" if inst.excluded else "Considerata",
        })
    selection = st.dataframe(
        pd.DataFrame(rows), width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row", key="held_instruments")
    if selection.selection.rows:
        isin = held[selection.selection.rows[0]]
        inst = instruments[isin]
        with st.container(border=True):
            st.markdown(f"**{inst.name or isin}**")
            st.caption(f"ISIN: {isin} · Ticker: {inst.yahoo_ticker or 'n/d'}")
            action = "Considera di nuovo" if inst.excluded else "Non considerare"
            if st.button(action, key=f"toggle_analysis_{isin}"):
                store.upsert_instrument(conn, replace(inst, excluded=not inst.excluded))
                st.rerun()


def _render_etf_costs(conn, instruments, held, current_values):
    etfs = sorted(
        (isin for isin in held
         if instruments[isin].asset_class == "etf" and not instruments[isin].excluded),
        key=lambda isin: (instruments[isin].name or isin).lower(),
    )
    if not etfs:
        return
    st.subheader("Quanto mi costano gli ETF")
    success = st.session_state.pop("etf_costs_success", None)
    if success:
        st.success(success)
    st.caption("Stima annua a valore costante: valore detenuto × TER. Il TER è già "
               "incorporato nel valore del fondo e non viene sottratto di nuovo dai rendimenti. "
               "Commissioni di negoziazione e altri costi non sono compresi nella stima.")
    stored = store.get_etf_expense_ratios(conn)
    if st.button("Aggiorna TER", key="refresh_etf_expense_ratios"):
        updated = manual = 0
        errors = []
        with st.spinner("Recupero i TER da Yahoo…"):
            for isin in etfs:
                if isin in stored and stored[isin].source == "Manuale":
                    manual += 1
                    continue
                try:
                    ratio = fundamentals.get_etf_expense_ratio(instruments[isin].yahoo_ticker)
                    updated += store.upsert_etf_expense_ratio(conn, isin, ratio, "Yahoo")
                except ValueError as e:
                    logger.warning("TER non disponibile per %s: %s", isin, e)
                    errors.append(f"{instruments[isin].name or isin}: {e}")
                except Exception as e:
                    logger.exception("Aggiornamento TER fallito per %s", isin)
                    errors.append(f"{instruments[isin].name or isin}: {e}")
        st.info(f"TER aggiornati: {updated}. Valori manuali conservati: {manual}.")
        if errors:
            st.warning("I dati salvati degli ETF non aggiornati sono mantenuti.\n\n- "
                       + "\n- ".join(errors))
        stored = store.get_etf_expense_ratios(conn)

    with st.expander("Inserisci o modifica un TER"):
        selected = st.selectbox(
            "ETF", etfs, format_func=lambda isin: f"{instruments[isin].name or isin} [{isin}]",
            key="etf_expense_ratio_instrument")
        saved = stored.get(selected)
        st.caption("Inserisci il TER in percentuale: per esempio 0.20 per lo 0.20%. "
                   "Un valore manuale ha precedenza su Yahoo. Rimuovilo per usare di nuovo "
                   "il recupero automatico.")
        with st.form(f"etf_expense_ratio_form_{selected}"):
            ter_percent = st.number_input(
                "TER annuo (%)", min_value=0.0, max_value=100.0,
                value=saved.value * 100.0 if saved else None, step=0.01, format="%.3f",
                key=f"etf_ter_{selected}_{saved.value if saved else 'missing'}_"
                    f"{saved.source if saved else ''}")
            save = st.form_submit_button("Salva TER manuale")
            remove = st.form_submit_button("Rimuovi TER salvato", disabled=saved is None)
        if save or remove:
            try:
                if save:
                    if ter_percent is None:
                        raise ValueError("Inserisci il TER prima di salvare.")
                    store.upsert_etf_expense_ratio(
                        conn, selected, ter_percent / 100.0, "Manuale")
                else:
                    store.delete_etf_expense_ratio(conn, selected)
            except Exception as e:
                logger.exception("Modifica TER fallita per %s", selected)
                st.error(f"Modifica del TER non riuscita: {e}")
            else:
                st.session_state["etf_costs_success"] = (
                    "TER manuale salvato." if save else "TER salvato rimosso.")
                st.rerun()

    values = {isin: current_values.get(isin) for isin in etfs}
    values = {isin: None if pd.isna(value) else value for isin, value in values.items()}
    summary = summarize_etf_costs(values, {isin: item.value for isin, item in stored.items()})
    c1, c2, c3 = st.columns(3)
    c1.metric("Costo annuo stimato" + (" (parziale)" if not summary.complete else ""),
              "n/d" if summary.annual_cost_eur is None else f"{summary.annual_cost_eur:,.2f} €")
    c2.metric("TER ponderato (dati disponibili)", "n/d" if summary.weighted_expense_ratio
              is None else f"{summary.weighted_expense_ratio * 100:.3f}%")
    c3.metric("ETF con prezzo e TER", f"{summary.covered_count} / {len(summary.rows)}")
    if summary.priced_value_eur:
        coverage = summary.covered_value_eur / summary.priced_value_eur * 100.0
        st.caption(f"Valore coperto: {summary.covered_value_eur:,.2f} € su "
                   f"{summary.priced_value_eur:,.2f} € di ETF con prezzo ({coverage:.1f}%).")
    if not summary.complete:
        st.warning("Riepilogo parziale: gli ETF senza prezzo o TER restano indicati come n/d. "
                   "Il TER ponderato considera soltanto il valore con entrambi i dati.")
    st.dataframe(pd.DataFrame([
        {
            "ETF": instruments[row.isin].name or row.isin,
            "ISIN": row.isin,
            "Valore attuale EUR": "n/d" if row.value_eur is None else f"{row.value_eur:,.2f}",
            "TER %": "n/d" if row.expense_ratio is None else f"{row.expense_ratio * 100:.3f}",
            "Costo annuo stimato EUR": "n/d" if row.annual_cost_eur is None
                                      else f"{row.annual_cost_eur:,.2f}",
            "Fonte TER": stored[row.isin].source if row.isin in stored else "n/d",
            "TER salvato il": stored[row.isin].saved_on.strftime("%d/%m/%Y")
                               if row.isin in stored else "n/d",
        }
        for row in summary.rows
    ]), width="stretch", hide_index=True)


def _cache_observation(frame, on_or_before=None):
    if frame.empty:
        return None
    if on_or_before is not None:
        frame = frame.loc[frame.index <= pd.Timestamp(on_or_before)]
    if isinstance(frame, pd.DataFrame):
        frame = frame.dropna(how="all")
    else:
        frame = frame.dropna()
    return None if frame.empty else frame.index.max().date()


def _observation_text(observation):
    if observation is None:
        return "n/d"
    age = max((date.today() - observation).days, 0)
    return f"{observation:%d/%m/%Y} ({age} gg fa)"


def _render_refresh_result():
    result = st.session_state.get("price_refresh_result")
    if result is None:
        return
    updated = len(result.updated_tickers) + len(result.updated_pairs)
    errors = [
        *(f"Prezzo {ticker}: {message}" for ticker, message in result.price_errors),
        *(f"Cambio {pair}: {message}" for pair, message in result.fx_errors),
    ]
    if updated:
        st.success(f"Aggiornamento completato per {len(result.updated_tickers)} prezzi e "
                   f"{len(result.updated_pairs)} cambi.")
    if errors:
        st.warning("Aggiornamento parziale:\n\n- " + "\n- ".join(errors))
    elif not updated:
        st.info("Nessun prezzo o cambio da aggiornare.")


def _render_data_status(conn, txs, instruments):
    state = build_portfolio_state(txs, on_oversell="skip")
    held = sorted(state.positions, key=lambda isin: (
        instruments[isin].name.lower() if isin in instruments and instruments[isin].name
        else isin))
    rows = []
    considered = 0
    excluded = 0
    unavailable = 0
    for isin in held:
        inst = instruments.get(isin)
        if inst is None:
            rows.append({
                "Nome": isin, "Ticker": "n/d", "Ultimo prezzo": "n/d",
                "Ultimo cambio": "n/d", "Stato": "Anagrafica mancante",
            })
            unavailable += 1
            continue
        price_date = _cache_observation(
            store.read_prices_cache(conn, inst.yahoo_ticker)) if inst.yahoo_ticker else None
        if inst.native_currency == "EUR":
            fx_date = None
            fx_text = "Non necessario"
        else:
            pair = f"EUR{inst.native_currency}=X"
            fx_date = _cache_observation(store.read_fx_cache(conn, pair))
            fx_text = _observation_text(fx_date)
        if inst.excluded:
            status = "Escluso manualmente"
            excluded += 1
        elif not inst.yahoo_ticker:
            status = "Ticker mancante"
            unavailable += 1
        elif price_date is None:
            status = "Prezzo non disponibile"
            unavailable += 1
        elif inst.native_currency != "EUR" and fx_date is None:
            status = "Cambio non disponibile"
            unavailable += 1
        else:
            status = "Considerato"
            considered += 1
        rows.append({
            "Nome": inst.name or isin,
            "Ticker": inst.yahoo_ticker or "n/d",
            "Ultimo prezzo": _observation_text(price_date),
            "Ultimo cambio": fx_text,
            "Stato": status,
        })
    with st.expander("Stato dei dati", expanded=True):
        c1, c2, c3 = st.columns(3)
        c1.metric("Strumenti considerati", considered)
        c2.metric("Esclusi manualmente", excluded)
        c3.metric("Dati non disponibili", unavailable)
        st.caption("Le date sono quelle delle osservazioni originali in cache; weekend e "
                   "festività possono spiegare alcuni giorni di distanza.")
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _period_selection(txs):
    mode = st.selectbox(
        "Intervallo", ["Mese", "Trimestre", "Anno", "Personalizzato"], index=2,
        key="period_summary_mode")
    today = date.today()
    first = min(tx.trade_date for tx in txs)
    if mode == "Mese":
        months = []
        year, month = today.year, today.month
        while (year, month) >= (first.year, first.month):
            months.append((year, month))
            month -= 1
            if month == 0:
                year -= 1
                month = 12
        selected_year, selected_month = st.selectbox(
            "Mese", months, format_func=lambda value: f"{value[1]:02d}/{value[0]}")
        start = date(selected_year, selected_month, 1)
        end = date(selected_year, selected_month,
                   calendar.monthrange(selected_year, selected_month)[1])
    elif mode == "Trimestre":
        quarters = []
        for year in range(today.year, first.year - 1, -1):
            for quarter in range(4, 0, -1):
                quarter_start = date(year, (quarter - 1) * 3 + 1, 1)
                quarter_end_month = quarter_start.month + 2
                quarter_end = date(
                    year, quarter_end_month, calendar.monthrange(year, quarter_end_month)[1])
                if quarter_end >= first and quarter_start <= today:
                    quarters.append((year, quarter))
        selected_year, quarter = st.selectbox(
            "Trimestre", quarters, format_func=lambda value: f"T{value[1]} {value[0]}")
        first_month = (quarter - 1) * 3 + 1
        last_month = first_month + 2
        start = date(selected_year, first_month, 1)
        end = date(selected_year, last_month,
                   calendar.monthrange(selected_year, last_month)[1])
    elif mode == "Anno":
        selected_year = st.selectbox(
            "Anno", list(range(today.year, first.year - 1, -1)))
        start = date(selected_year, 1, 1)
        end = date(selected_year, 12, 31)
    else:
        c1, c2 = st.columns(2)
        start = c1.date_input("Dal", value=date(today.year, 1, 1), max_value=today)
        end = c2.date_input("Al", value=today, max_value=today)
    return start, min(end, today)


def _period_benchmark_eur(conn, name, dates):
    ticker, currency = BENCHMARKS[name]
    history = prices.get_price_history_cached(
        conn, ticker, dates.min().date(), dates.max().date()).reindex(dates).ffill()
    benchmark = history["adj_close"]
    if currency != "EUR":
        rate = prices.get_fx_history_cached(
            conn, f"EUR{currency}=X", dates.min().date(),
            dates.max().date()).reindex(dates).ffill()
        benchmark = benchmark / rate
    return benchmark


def _period_market_data_end(conn, instruments, isins, end):
    observations = []
    for isin in isins:
        instrument = instruments[isin]
        price_date = _cache_observation(
            store.read_prices_cache(conn, instrument.yahoo_ticker), end)
        if price_date is not None:
            observations.append(price_date)
        if instrument.native_currency != "EUR":
            fx_date = _cache_observation(
                store.read_fx_cache(conn, f"EUR{instrument.native_currency}=X"), end)
            if fx_date is not None:
                observations.append(fx_date)
    return min(observations) if observations else None


def _render_period_summary(conn, txs, instruments, benchmark_name):
    st.subheader("Riepilogo per periodo")
    st.caption("Risultato del portafoglio titoli nel periodo scelto, confrontato con lo stesso "
               "intervallo del benchmark.")
    start, end = _period_selection(txs)
    if start > end:
        st.error("La data iniziale deve precedere la data finale.")
        return
    required = required_price_isins(txs, start, end)
    missing_instruments = sorted(required - set(instruments))
    if missing_instruments:
        st.error("Completa l'anagrafica per: " + ", ".join(missing_instruments))
        return
    range_start = start - timedelta(days=14)
    dates = pd.date_range(range_start, end, freq="D")
    first_trade_dates = {
        isin: max(range_start, min(
            tx.trade_date for tx in txs
            if tx.isin == isin and tx.op_type is not OpType.DIVIDEND))
        for isin in required
    }
    close_eur, _, _ = _eur_price_frame(
        conn, instruments, sorted(required), dates, first_trade_dates)
    missing_prices = sorted(required - set(close_eur.dropna(axis=1, how="all").columns))
    if missing_prices:
        st.warning("Riepilogo non calcolabile: prezzi o cambi mancanti per " + ", ".join(
            instruments[isin].name or isin for isin in missing_prices))
        return
    try:
        benchmark = _period_benchmark_eur(conn, benchmark_name, dates)
    except ValueError as e:
        logger.warning("Benchmark del periodo non disponibile: %s", e)
        benchmark = None
    try:
        summary = summarize_period(txs, close_eur, start, end, benchmark)
    except ValueError as e:
        st.warning(f"Riepilogo non calcolabile: {e}")
        return

    st.caption(f"Periodo effettivo: {summary.effective_start:%d/%m/%Y} – "
               f"{summary.effective_end:%d/%m/%Y}; valore iniziale alla chiusura precedente.")
    market_data_end = _period_market_data_end(conn, instruments, required, end)
    if market_data_end is not None:
        st.caption(f"La copertura comune meno recente tra prezzi e cambi arriva al "
                   f"{market_data_end:%d/%m/%Y}.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Risultato", f"{summary.result_eur:,.2f} €")
    c2.metric("TWR", "n/d" if summary.twr_return is None
              else f"{summary.twr_return * 100:.2f}%")
    c3.metric(benchmark_name, "n/d" if summary.benchmark_return is None
              else f"{summary.benchmark_return * 100:.2f}%")
    difference = (None if summary.twr_return is None or summary.benchmark_return is None
                  else summary.twr_return - summary.benchmark_return)
    c4.metric("Differenza", "n/d" if difference is None else f"{difference * 100:.2f} p.p.")
    st.dataframe(pd.DataFrame([
        {"Voce": "Valore iniziale", "EUR": round(summary.initial_value_eur, 2)},
        {"Voce": "Acquisti", "EUR": round(summary.purchases_eur, 2)},
        {"Voce": "Vendite", "EUR": round(summary.sales_eur, 2)},
        {"Voce": "Dividendi", "EUR": round(summary.dividends_eur, 2)},
        {"Voce": "Commissioni", "EUR": round(summary.commissions_eur, 2)},
        {"Voce": "Valore finale", "EUR": round(summary.final_value_eur, 2)},
    ]), width="stretch", hide_index=True)
    if summary.contributions:
        st.markdown("**Contributori**")
        st.dataframe(pd.DataFrame([
            {
                "Nome": instruments[item.isin].name if item.isin in instruments else item.isin,
                "Risultato EUR": round(item.result_eur, 2),
                "Acquisti EUR": round(item.purchases_eur, 2),
                "Vendite EUR": round(item.sales_eur, 2),
                "Dividendi EUR": round(item.dividends_eur, 2),
                "Commissioni EUR": round(item.commissions_eur, 2),
            }
            for item in summary.contributions
        ]), width="stretch", hide_index=True)
    st.caption("Risultato prima delle imposte e al netto delle commissioni registrate. Acquisti "
               "e vendite sono movimenti del portafoglio, non bonifici del conto.")


def _render_capital_gains_positions(conn, state, instruments, today):
    st.subheader("Plus/minus potenziali — posizioni aperte")
    st.caption(f"Portafoglio al {today:%d/%m/%Y}, indipendente dall'anno selezionato. "
               "Risultato prima di imposte e commissioni di un'eventuale vendita. "
               "Le perdite potenziali non sono ancora minus fiscali.")
    if not state.positions:
        st.info("Nessuna posizione aperta.")
        return
    held = [isin for isin in state.positions
            if isin in instruments and instruments[isin].yahoo_ticker
            and instruments[isin].native_currency]
    dates = pd.date_range(today - timedelta(days=30), today, freq="D")
    try:
        close_eur, _, _ = _eur_price_frame(conn, instruments, held, dates)
    except Exception as e:
        logger.exception("Prezzi per le plus/minus potenziali non disponibili")
        st.error(f"Prezzi non disponibili: {e}")
        close_eur = pd.DataFrame()
    rows = []
    gains = []
    for isin, position in sorted(state.positions.items()):
        inst = instruments.get(isin)
        series = close_eur[isin].dropna() if isin in close_eur else pd.Series(dtype=float)
        price = float(series.iloc[-1]) if not series.empty else None
        value = (position.quantity * price
                 if price is not None and 0 <= price < float("inf") else None)
        gain = value - position.total_cost_eur if value is not None else None
        observation = (_period_market_data_end(conn, instruments, [isin], today)
                       if value is not None else None)
        if gain is not None:
            gains.append(gain)
        rows.append({
            "Nome": (inst.name or isin) if inst else isin, "ISIN": isin,
            "Quantità": position.quantity,
            "Costo di carico EUR": round(position.total_cost_eur, 2),
            "Valore attuale EUR": round(value, 2) if value is not None else None,
            "Plus/minus potenziale EUR": round(gain, 2) if gain is not None else None,
            "Plus/minus %": (round(gain / position.total_cost_eur * 100, 2)
                            if gain is not None and position.total_cost_eur > 0 else None),
            "Data prezzi/cambi": observation.strftime("%d/%m/%Y") if observation else "n/d",
        })
    partial = len(gains) < len(rows) or bool(state.warnings)
    if len(gains) < len(rows):
        logger.warning("Plus/minus potenziali parziali: prezzi, cambi o anagrafica mancanti")
        st.warning("Totali parziali: i titoli senza prezzi, cambi o anagrafica restano in "
                   "tabella con valori non disponibili, senza essere conteggiati come zero.")
    c1, c2, c3 = st.columns(3)
    for column, label, amount in (
        (c1, "Plus potenziali", sum(gain for gain in gains if gain > 0)),
        (c2, "Minus potenziali", sum(-gain for gain in gains if gain < 0)),
        (c3, "Saldo potenziale", sum(gains)),
    ):
        column.metric(label + (" (parziale)" if partial else ""),
                      f"{amount:,.2f} €" if gains else "n/d")
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def page_capital_gains(conn):
    st.header("Plus/minusvalenze")
    st.caption("Vendite realizzate, minus fiscali e posizioni aperte. Sono incluse tutte le "
               "operazioni importate, anche dei titoli esclusi dalle analisi. "
               "Dividendi e cedole non fanno parte delle plus/minus mostrate qui.")
    today = date.today()
    try:
        txs = store.get_transactions(conn)
        instruments = store.get_instruments(conn)
        if any(tx.trade_date > today for tx in txs):
            logger.warning("Plus/minusvalenze: operazioni future non considerate")
            st.warning("Le operazioni con data futura non sono considerate.")
        txs = [tx for tx in txs if tx.trade_date <= today]
        state = build_portfolio_state(txs, on_oversell="skip")
    except Exception as e:
        logger.exception("Ricostruzione delle plus/minusvalenze non riuscita")
        st.error(f"Plus/minusvalenze non disponibili: {e}")
        return
    if not txs:
        st.info("Nessuna operazione: importa un export nella pagina Import & Anagrafica.")
        return
    if state.warnings:
        logger.warning("Plus/minusvalenze parziali: storico acquisti incompleto")
        st.warning("Storico incompleto: i risultati economici sono parziali e lo zainetto "
                   "non è determinabile.\n\n- " + "\n- ".join(state.warnings))
    first_year = min(tx.trade_date.year for tx in txs)
    choice = st.selectbox(
        "Anno delle vendite e del riepilogo fiscale",
        [str(year) for year in range(today.year, first_year - 1, -1)] + ["Tutti"],
        key="capital_gains_year")
    year = None if choice == "Tutti" else int(choice)
    cutoff = min(today, date(year, 12, 31)) if year is not None else today
    sales = [sale for sale in state.realized_sales if year is None or sale.date.year == year]
    st.subheader("Plus/minus realizzate")
    start = date(year, 1, 1) if year is not None else min(tx.trade_date for tx in txs)
    st.caption(f"Dal {start:%d/%m/%Y} al {cutoff:%d/%m/%Y}. Ricavi meno costo medio di "
               "carico, incluse le commissioni registrate di acquisto e vendita, prima "
               "delle imposte.")
    plus = sum(sale.gain_eur for sale in sales if sale.gain_eur > 0)
    minus = sum(-sale.gain_eur for sale in sales if sale.gain_eur < 0)
    c1, c2, c3 = st.columns(3)
    for column, label, amount in (
        (c1, "Plus realizzate", plus), (c2, "Minus realizzate", minus),
        (c3, "Saldo realizzato", plus - minus),
    ):
        column.metric(label + (" (parziale)" if state.warnings else ""), f"{amount:,.2f} €")
    if sales:
        st.dataframe(pd.DataFrame(realized_rows(sales, instruments)),
                     width="stretch", hide_index=True)
    else:
        st.info("Nessuna vendita ricostruibile nel periodo selezionato.")

    st.subheader("Zainetto fiscale stimato")
    st.caption(f"Saldo delle minus al {cutoff:%d/%m/%Y}, comprese quelle riportate dagli "
               "anni precedenti. Le minus residue riducono future plus compensabili: "
               "non sono un importo rimborsabile.")
    unknown = {sale.isin for sale in state.realized_sales if sale.date <= cutoff
               and (sale.isin not in instruments or instruments[sale.isin].asset_class
                    not in {"azione", "stock", "etf", "obbligazione"})}
    if unknown:
        logger.warning("Zainetto non determinabile: classificazione strumenti mancante")
        st.warning("Completa il tipo di strumento in anagrafica per stimare lo zainetto: "
                   + ", ".join(sorted(unknown)))
    if not state.warnings and not unknown:
        try:
            zai = compute_zainetto_for_year(state.realized_sales, instruments, year, today)
        except Exception as e:
            logger.exception("Calcolo dello zainetto per anno non riuscito")
            st.error(f"Zainetto non disponibile: {e}")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Minus generate nel periodo", f"{zai.minus_generated_eur:,.2f} €")
            c2.metric("Minus utilizzate nel periodo", f"{zai.minus_used_eur:,.2f} €")
            c3.metric("Minus residue disponibili", f"{sum(zai.residual_by_expiry.values()):,.2f} €")
            c1, c2 = st.columns(2)
            c1.metric("Plus imponibili nel periodo", f"{zai.taxable_gains_eur:,.2f} €")
            c2.metric("Imposta stimata nel periodo", f"{zai.capital_tax_eur:,.2f} €")
            if zai.residual_by_expiry:
                st.dataframe(pd.DataFrame([
                    {"Scadenza": f"31/12/{expiry}", "Minus residue EUR": round(amount, 2)}
                    for expiry, amount in sorted(zai.residual_by_expiry.items())
                ]), width="stretch", hide_index=True)
                expiring = zai.residual_by_expiry.get(cutoff.year, 0)
                if expiring:
                    st.warning(f"Minus in scadenza al 31/12/{cutoff.year}: {expiring:,.2f} €.")
            else:
                st.info("Nessuna minus residua disponibile alla data indicata.")
    st.caption("Stima semplificata al 26% con compensazione cronologica: le plus da ETF/OICR "
               "non consumano lo zainetto. Aliquote agevolate (es. titoli di Stato), "
               "rettifiche fiscali e minus esterne allo storico importato non sono gestite. "
               "Confronta i valori con il prospetto fiscale del broker.")
    _render_capital_gains_positions(conn, state, instruments, today)


def page_dashboard(conn):
    st.header("Dashboard")
    txs = store.get_transactions(conn)
    instruments = store.get_instruments(conn)
    if st.button("🔄 Aggiorna prezzi"):
        tickers = sorted(set(store.cached_tickers(conn)) | {
            instrument.yahoo_ticker for instrument in instruments.values()
            if instrument.yahoo_ticker
        })
        pairs = sorted(set(store.cached_pairs(conn)) | {
            f"EUR{instrument.native_currency}=X" for instrument in instruments.values()
            if instrument.native_currency and instrument.native_currency != "EUR"
        })
        with st.spinner("Aggiorno i prezzi recenti…"):
            st.session_state["price_refresh_result"] = prices.refresh_recent(
                conn, tickers, pairs)
        st.rerun()
    _render_refresh_result()
    if not txs:
        st.info("Nessuna operazione: importa un export nella pagina Import.")
        return
    _render_data_status(conn, txs, instruments)
    _render_held_instruments(conn, txs, instruments)
    excluded = {isin for isin, inst in instruments.items() if inst.excluded}
    if excluded:
        names = ", ".join(instruments[i].name for i in sorted(excluded))
        st.caption(f"Escluse dalle analisi: {names}")
        txs = [t for t in txs if t.isin not in excluded]
        if not txs:
            st.info("Tutte le posizioni sono escluse dalle analisi.")
            return
    try:
        _render_dashboard(conn, txs, instruments)
    except ValueError as e:
        st.error(str(e))


def _render_dashboard(conn, txs, instruments):
    state = build_portfolio_state(txs, on_oversell="skip")
    if state.warnings:
        st.warning("Storico incompleto:\n\n- " + "\n- ".join(state.warnings))

    held = sorted(state.positions)
    missing = [i for i in held if i not in instruments]
    if missing:
        st.error("Completa l'anagrafica (ticker/valuta/area/settore) per: " + ", ".join(missing))
        return

    dividends = [t for t in txs if t.op_type is OpType.DIVIDEND]
    held_txs = [t for t in txs if t.isin in state.positions]
    first_trade_dates = {}
    for t in held_txs:
        first_trade_dates[t.isin] = min(
            t.trade_date, first_trade_dates.get(t.isin, t.trade_date))

    dates = pd.date_range(min(t.trade_date for t in txs), date.today(), freq="D")
    close_eur, adj_eur, fx_by_ccy = _eur_price_frame(
        conn, instruments, held, dates, first_trade_dates)
    priced = [i for i in held if i in close_eur.columns]
    unpriced = [i for i in held if i not in priced]
    if unpriced:
        st.warning("Prezzo non disponibile su Yahoo (verifica il ticker): "
                   + ", ".join(f"{instruments[i].name} [{instruments[i].yahoo_ticker}]"
                               for i in unpriced))
    priced_positions = {i: state.positions[i] for i in priced}
    priced_txs = [t for t in held_txs if t.isin in priced]

    qty = quantity_timeline(priced_txs, dates)
    current_value = {i: state.positions[i].quantity * float(close_eur[i].ffill().iloc[-1])
                     for i in priced}

    realized = realized_net_gain(state, dividends)
    zai = compute_zainetto(state.realized_sales, instruments, today_year=date.today().year)
    realized_net_total = (zai.gross_realized_eur - zai.capital_tax_eur) + realized.dividends_net_eur
    latent = latent_net_gain(priced_positions, current_value)
    invested = sum(p.total_cost_eur for p in priced_positions.values())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Investito (residuo)", f"{invested:,.0f} €")
    c2.metric("Valore attuale", f"{sum(current_value.values()):,.0f} €")
    c3.metric("Netto realizzato", f"{realized_net_total:,.0f} €")
    c4.metric("Netto latente", f"{latent.total_eur:,.0f} €")
    st.metric("Guadagno netto totale", f"{realized_net_total + latent.total_eur:,.0f} €")
    st.caption("Realizzato = utile/perdita già incassato (vendite e dividendi, al netto di "
               "tasse). Latente = quello ancora \"sulla carta\" delle posizioni aperte.")

    try:
        _render_etf_costs(conn, instruments, held, current_value)
    except Exception as e:
        logger.exception("Riepilogo costi ETF non disponibile")
        st.error(f"Riepilogo costi ETF non disponibile: {e}")

    port_value = portfolio_value_eur(qty, close_eur)
    cashflows = pd.Series(0.0, index=dates)
    for t in priced_txs:
        if t.op_type is OpType.BUY:
            cashflows.loc[pd.Timestamp(t.trade_date)] += t.amount_eur + t.commission_eur
        elif t.op_type is OpType.SELL:
            cashflows.loc[pd.Timestamp(t.trade_date)] -= t.amount_eur - t.commission_eur
    twr_cashflows = cashflows.copy()
    for t in priced_txs:
        if t.op_type is OpType.DIVIDEND:
            twr_cashflows.loc[pd.Timestamp(t.trade_date)] -= t.amount_eur
    port_value = port_value[port_value > 0]
    port_twr = twr_index(port_value, twr_cashflows.reindex(port_value.index).fillna(0.0))

    bench_name = st.selectbox("Benchmark", list(BENCHMARKS))
    bench_ticker, bench_ccy = BENCHMARKS[bench_name]
    bench = prices.get_price_history_cached(conn, bench_ticker,
                                            port_value.index.min().date(), date.today())
    if bench_ccy == "EUR":
        bench_eur = bench["adj_close"].reindex(port_value.index).ffill()
    else:
        bfx = prices.get_fx_history_cached(conn, f"EUR{bench_ccy}=X",
                                           port_value.index.min().date(), date.today())
        bench_eur = (bench["adj_close"].reindex(port_value.index).ffill()
                     / bfx.reindex(port_value.index).ffill())
    bench_twr = twr_index(bench_eur, pd.Series(0.0, index=bench_eur.index))

    fig = go.Figure()
    fig.add_scatter(x=port_twr.index, y=port_twr.values, name="Portafoglio")
    fig.add_scatter(x=bench_twr.index, y=bench_twr.values, name=bench_name)
    fig.update_layout(title="TWR — base 100", yaxis_title="Indice")
    st.caption("Crescita di 100 € depurata da versamenti e prelievi (time-weighted): isola la "
               "bontà delle scelte dal *quando* hai messo i soldi. La linea del portafoglio "
               "sopra il benchmark = hai fatto meglio del mercato.")
    st.plotly_chart(fig, use_container_width=True)

    _render_period_summary(conn, txs, instruments, bench_name)

    st.subheader("Rendimento & rischio")
    st.caption("Quanto rende il portafoglio e con quanta oscillazione. XIRR = rendimento annuo "
               "che pesa importi e date dei versamenti; Volatilità/Max drawdown = ampiezza degli "
               "sbalzi e perdita massima dal picco; Sharpe/Sortino = rendimento per unità di "
               "rischio (più alti = meglio); Beta = quanto ti muovi rispetto al benchmark "
               "(1 = come il mercato).")
    flows = []
    for t in priced_txs:
        if t.op_type is OpType.BUY:
            flows.append((t.trade_date, -(t.amount_eur + t.commission_eur)))
        elif t.op_type is OpType.SELL:
            flows.append((t.trade_date, t.amount_eur - t.commission_eur))
    for d in dividends:
        if d.isin in priced:
            flows.append((d.trade_date, d.amount_eur))
    flows.append((dates.max().date(), sum(current_value.values())))
    flows.sort(key=lambda x: x[0])
    rate = xirr([a for _, a in flows], [dt for dt, _ in flows])

    rp = business_day_returns(port_twr)
    rb = business_day_returns(bench_twr)
    vol = annualized_volatility(rp)
    shp = sharpe(rp)
    srt = sortino(rp)
    bta = beta(rp, rb)
    mdd = drawdown(port_twr).min() * 100

    def _fmt(x, suffix="", dec=2):
        return ("n/d" if x is None or (isinstance(x, float) and pd.isna(x))
                else f"{x:.{dec}f}{suffix}")

    m1, m2, m3 = st.columns(3)
    m1.metric("XIRR (money-weighted)", _fmt(rate * 100 if rate is not None else None, "%", 1))
    m2.metric("Volatilità annua", _fmt(vol * 100, "%", 1))
    m3.metric("Max drawdown", _fmt(mdd, "%", 1))
    m4, m5, m6 = st.columns(3)
    m4.metric("Sharpe", _fmt(shp))
    m5.metric("Sortino", _fmt(srt))
    m6.metric(f"Beta vs {bench_name}", _fmt(bta))

    geo = geo_breakdown(current_value, instruments)
    if geo:
        st.plotly_chart(px.pie(names=list(geo), values=list(geo.values()),
                               title="Distribuzione geografica"), use_container_width=True)
    sectors = sector_breakdown(current_value, instruments)
    if sectors:
        st.plotly_chart(px.pie(names=list(sectors), values=list(sectors.values()),
                               title="Distribuzione settoriale"), use_container_width=True)

    rows = []
    for isin, pos in priced_positions.items():
        val = current_value.get(isin, 0.0)
        rows.append({"ISIN": isin, "Nome": instruments[isin].name,
                     "Quantità": pos.quantity, "Costo medio": round(pos.avg_cost_eur, 2),
                     "Valore EUR": round(val, 2),
                     "P/L lordo": round(val - pos.total_cost_eur, 2)})
    st.dataframe(pd.DataFrame(rows))

    contribs = pnl_attribution(state.positions, current_value, state.realized_sales)
    st.subheader("Attribuzione P/L (lordo)")
    st.caption("Da quali titoli arriva il risultato: barre verdi = chi ha fatto guadagnare, "
               "rosse = chi ha pesato. Serve a capire se il P/L dipende da pochi nomi.")
    st.caption("Valori lordi (no dividendi, no tasse/commissioni): il totale non coincide con il "
               "Guadagno netto totale. La % è sul risultato complessivo e può superare il 100% "
               "o essere negativa.")
    if not contribs:
        st.info("Nessuna posizione con P/L da attribuire.")
    else:
        shares = attribution_shares(contribs)

        def _label(isin):
            return instruments[isin].name if isin in instruments else isin

        totals = [c.total_eur for c in contribs]
        labels = [_label(c.isin) for c in contribs]
        colors = ["#2ca02c" if v >= 0 else "#d62728" for v in totals]
        fig_attr = go.Figure(go.Bar(x=totals, y=labels, orientation="h", marker_color=colors))
        fig_attr.update_layout(title="Contributo al risultato (€)",
                               yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_attr, use_container_width=True)
        st.dataframe(pd.DataFrame([
            {"Nome": _label(c.isin), "Latente €": round(c.latent_eur, 2),
             "Realizzato €": round(c.realized_eur, 2), "Totale €": round(c.total_eur, 2),
             "% del totale": f"{shares[c.isin] * 100:.1f}%"}
            for c in contribs
        ]))

    st.subheader("Diversificazione & valuta")
    st.caption("Quanto sei concentrato. HHI = indice di concentrazione (più alto = più "
               "sbilanciato); Posizioni effettive = quante posizioni equipesate \"equivalenti\" "
               "hai davvero; Top 3/5 = quota dei maggiori titoli.")
    if not current_value:
        st.info("Nessuna posizione prezzata: niente da analizzare.")
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("HHI", f"{herfindahl(current_value):.2f}")
        k2.metric("Posizioni effettive", f"{effective_positions(current_value):.1f}")
        k3.metric("Top 3", f"{top_n_weight(current_value, 3) * 100:.0f}%")
        k4.metric("Top 5", f"{top_n_weight(current_value, 5) * 100:.0f}%")
        alerts = concentration_alerts(current_value, 0.20)
        if alerts:
            st.warning("Posizioni oltre il 20%:\n\n- " + "\n- ".join(
                f"{instruments[i].name}: {w * 100:.1f}%" for i, w in alerts))

        exposure = currency_exposure(current_value, instruments)
        st.plotly_chart(px.pie(names=list(exposure), values=list(exposure.values()),
                               title="Esposizione valutaria (valuta di quotazione)"),
                        use_container_width=True)
        st.caption("Esposizione per valuta di quotazione, non economica/look-through.")

        def _rate_at(isin, when):
            ccy = instruments[isin].native_currency
            series = fx_by_ccy.get(ccy)
            if ccy == "EUR" or series is None:
                return 1.0
            r = series.asof(pd.Timestamp(when))
            if pd.isna(r):
                r = series.dropna().iloc[0]
            return float(r)

        cost_eur = {i: state.positions[i].total_cost_eur for i in priced}
        entry_fx = weighted_entry_fx(priced_txs, lambda t: _rate_at(t.isin, t.trade_date))
        current_fx = {i: _rate_at(i, dates.max()) for i in priced}
        splits = fx_price_decomposition(cost_eur, current_value, entry_fx, current_fx)
        st.markdown("**P/L latente: prezzo vs cambio**")
        st.caption("Scompone il guadagno latente in due cause: quanto viene dal prezzo del "
                   "titolo e quanto dal cambio valutario. Aiuta a capire se guadagni "
                   "sull'azienda o solo sul cambio.")
        st.caption("Cambio d'ingresso dallo storico Yahoo alla data di acquisto "
                   "(approssimato al cambio del giorno; commissioni EUR e vendite parziali).")
        if not splits:
            st.info("Nessuna posizione scomponibile.")
        else:
            names = [instruments[s.isin].name for s in splits]
            fig_fx = go.Figure()
            fig_fx.add_bar(x=names, y=[s.price_eur for s in splits], name="Prezzo")
            fig_fx.add_bar(x=names, y=[s.fx_eur for s in splits], name="Cambio")
            fig_fx.update_layout(barmode="group", title="Contributo prezzo vs cambio (€)")
            st.plotly_chart(fig_fx, use_container_width=True)
            st.dataframe(pd.DataFrame([
                {"Nome": instruments[s.isin].name, "Prezzo €": round(s.price_eur, 2),
                 "Cambio €": round(s.fx_eur, 2), "Totale €": round(s.total_eur, 2)}
                for s in splits
            ]))

    st.subheader("Investito vs valore")
    invested = invested_timeline(cashflows).reindex(port_value.index).ffill()
    fig_iv = go.Figure()
    fig_iv.add_scatter(x=port_value.index, y=invested.values, name="Investito")
    fig_iv.add_scatter(x=port_value.index, y=port_value.values, name="Valore di mercato")
    fig_iv.update_layout(title="Investito vs valore nel tempo", yaxis_title="EUR")
    st.plotly_chart(fig_iv, use_container_width=True)

    st.subheader("Mappa del portafoglio")
    st.caption("Treemap: l'area è il peso in portafoglio, il colore il guadagno/perdita % "
               "(verde = su, rosso = giù). Colpo d'occhio su dove sono i soldi e come vanno.")
    tdf = pd.DataFrame([
        {"Area": instruments[i].macro_area, "Nome": instruments[i].name,
         "Valore": current_value[i],
         "P/L %": ((current_value[i] - priced_positions[i].total_cost_eur)
                   / priced_positions[i].total_cost_eur * 100)
                  if priced_positions[i].total_cost_eur else 0.0}
        for i in priced])
    fig_tm = px.treemap(tdf, path=["Area", "Nome"], values="Valore", color="P/L %",
                        color_continuous_scale="RdYlGn", color_continuous_midpoint=0)
    st.plotly_chart(fig_tm, use_container_width=True)

    st.subheader("Drawdown (TWR)")
    st.caption("Quanto sei sotto il massimo storico, istante per istante (0% = nuovi massimi). "
               "È la perdita peggiore che avresti dovuto sopportare: valli profonde = periodi "
               "duri da tenere.")
    dd = drawdown(port_twr) * 100
    fig_dd = go.Figure(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy",
                                  line=dict(color="#d62728")))
    fig_dd.update_layout(title="Drawdown dal massimo (TWR)", yaxis_title="%")
    st.plotly_chart(fig_dd, use_container_width=True)

    st.subheader("Investimenti per mese")
    monthly = monthly_net_invested(txs)
    if monthly.empty:
        st.info("Nessun movimento di capitale da mostrare.")
    else:
        fig_dca = px.bar(x=monthly.index, y=monthly.values,
                         labels={"x": "Mese", "y": "Netto investito (EUR)"},
                         title="Netto investito per mese")
        st.plotly_chart(fig_dca, use_container_width=True)

    st.subheader("Reddito (dividendi)")
    st.caption("Cedole incassate. Yield on cost = dividendo annuo rispetto a quanto hai speso; "
               "Stima annua = proiezione su base 365 giorni. Curva cumulata più ripida = più "
               "reddito generato.")
    if not dividends:
        st.info("Nessun dividendo registrato.")
    else:
        gross_total = sum(d.amount_eur for d in dividends)
        net_total = sum(dividend_net(d.amount_eur, country_from_isin(d.isin)) for d in dividends)
        cost_basis = sum(p.total_cost_eur for p in priced_positions.values())
        yoc = gross_total / cost_basis * 100 if cost_basis else 0.0
        span_days = max((date.today() - min(t.trade_date for t in txs)).days, 1)
        annual_est = gross_total / span_days * 365
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Dividendi lordi", f"{gross_total:,.0f} €")
        d2.metric("Dividendi netti", f"{net_total:,.0f} €")
        d3.metric("Yield on cost (lordo)", f"{yoc:.1f}%")
        d4.metric("Stima annua (lordo)", f"{annual_est:,.0f} €")
        ds = sorted(dividends, key=lambda d: d.trade_date)
        cum = pd.Series([d.amount_eur for d in ds],
                        index=pd.to_datetime([d.trade_date for d in ds])).cumsum()
        fig_div = go.Figure(go.Scatter(x=cum.index, y=cum.values, fill="tozeroy"))
        fig_div.update_layout(title="Dividendi cumulati (lordo)", yaxis_title="EUR")
        st.plotly_chart(fig_div, use_container_width=True)

    st.subheader("Fisco")
    st.caption("Plus/minusvalenze realizzate e relativa imposta. Lo \"zainetto\" è il credito di "
               "minus compensabili con future plus entro la scadenza. Stima il carico fiscale, "
               "non sostituisce l'estratto del broker.")
    if not state.realized_sales:
        st.info("Nessuna vendita realizzata: niente plus/minus da dichiarare.")
    else:
        plus = sum(s.gain_eur for s in state.realized_sales if s.gain_eur > 0)
        minus = sum(-s.gain_eur for s in state.realized_sales if s.gain_eur < 0)
        f1, f2, f3 = st.columns(3)
        f1.metric("Plus realizzate", f"{plus:,.0f} €")
        f2.metric("Minus realizzate", f"{minus:,.0f} €")
        f3.metric("Imposta capital gain", f"{zai.capital_tax_eur:,.0f} €")
        g1, g2 = st.columns(2)
        g1.metric("Minus generate", f"{zai.minus_generated_eur:,.0f} €")
        g2.metric("Minus usate", f"{zai.minus_used_eur:,.0f} €")
        if zai.residual_by_expiry:
            st.markdown("**Zainetto residuo** (minus a credito):")
            st.dataframe(pd.DataFrame([
                {"Scade a fine": y, "Importo €": round(a, 2)}
                for y, a in sorted(zai.residual_by_expiry.items())
            ]))
        else:
            st.caption("Nessuna minusvalenza residua a credito.")
        st.caption("Stima: compensazione cronologica FIFO; le plus da ETF/OICR non sono "
                   "compensabili. Verifica sempre con l'estratto fiscale del broker.")

    if state.realized_sales or dividends:
        years = sorted({s.date.year for s in state.realized_sales}
                       | {d.trade_date.year for d in dividends})
        choice = st.selectbox("Anno fiscale", ["Tutti"] + [str(y) for y in years])
        year = None if choice == "Tutti" else int(choice)
        xlsx = build_tax_report_xlsx(state.realized_sales, dividends, instruments, year)
        st.download_button(
            "📄 Scarica report fiscale (.xlsx)", data=xlsx,
            file_name=f"report_fiscale_{choice.lower()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.subheader("Rischio nel tempo (finestra 60 giorni)")
    st.caption("Come cambiano rischio e sensibilità al mercato su finestre mobili di 60 giorni. "
               "Volatilità in salita = fase più nervosa; Beta in salita = ti muovi sempre più "
               "come (o più di) il benchmark.")
    WIN = 60
    rvol = rolling_volatility(rp, WIN) * 100
    rbeta = rolling_beta(rp, rb, WIN)
    if rvol.dropna().empty:
        st.info("Storia troppo breve per le metriche rolling.")
    else:
        fig_rv = go.Figure(go.Scatter(x=rvol.index, y=rvol.values))
        fig_rv.update_layout(title="Volatilità rolling 60gg (%)", yaxis_title="%")
        st.plotly_chart(fig_rv, use_container_width=True)
        fig_rb = go.Figure(go.Scatter(x=rbeta.index, y=rbeta.values))
        fig_rb.update_layout(title=f"Beta rolling 60gg vs {bench_name}", yaxis_title="beta")
        st.plotly_chart(fig_rb, use_container_width=True)

    st.subheader("Correlazioni tra posizioni")
    st.caption("Quanto i titoli si muovono insieme (da -1 a +1). Valori alti/rossi = stessa "
               "direzione, diversificano poco; negativi/blu = si compensano. Per diversificare "
               "davvero servono correlazioni basse.")
    corr = correlation_matrix(close_eur)
    if corr.empty or corr.shape[0] < 2:
        st.info("Servono almeno 2 posizioni prezzate.")
    else:
        cnames = [instruments[i].name if i in instruments else i for i in corr.columns]
        fig_corr = px.imshow(corr.values, x=cnames, y=cnames, zmin=-1, zmax=1,
                             color_continuous_scale="RdBu", text_auto=".2f",
                             title="Correlazione rendimenti giornalieri")
        st.plotly_chart(fig_corr, use_container_width=True)

    st.subheader("Rendimenti mensili (%)")
    st.caption("Heatmap del rendimento mese per mese (verde positivo, rosso negativo). Per "
               "cogliere a colpo d'occhio mesi/anni buoni e cattivi ed eventuale stagionalità.")
    mtab = monthly_returns_table(port_twr)
    if mtab.empty:
        st.info("Storia troppo breve per i rendimenti mensili.")
    else:
        fig_m = px.imshow(mtab.values, x=[str(c) for c in mtab.columns],
                          y=[str(i) for i in mtab.index],
                          color_continuous_scale="RdYlGn", color_continuous_midpoint=0,
                          text_auto=".1f", title="Rendimenti mensili (TWR, %)")
        fig_m.update_layout(xaxis_title="Mese", yaxis_title="Anno")
        st.plotly_chart(fig_m, use_container_width=True)

    st.subheader("Rendimento per posizione")
    st.caption("XIRR = rendimento annualizzato (money-weighted): su titoli tenuti pochi mesi "
               "l'annualizzazione gonfia i valori. 'Rendimento totale' è il guadagno di periodo "
               "(valore attuale vs costo), non annualizzato.")
    pos_rows = []
    for isin in priced:
        flows = []
        for t in priced_txs:
            if t.isin != isin:
                continue
            if t.op_type is OpType.BUY:
                flows.append((t.trade_date, -(t.amount_eur + t.commission_eur)))
            elif t.op_type is OpType.SELL:
                flows.append((t.trade_date, t.amount_eur - t.commission_eur))
        for d in dividends:
            if d.isin == isin:
                flows.append((d.trade_date, d.amount_eur))
        flows.append((dates.max().date(), current_value[isin]))
        flows.sort(key=lambda x: x[0])
        r = xirr([a for _, a in flows], [dt for dt, _ in flows])
        cost = priced_positions[isin].total_cost_eur
        total_ret = (current_value[isin] - cost) / cost if cost else None
        pos_rows.append((instruments[isin].name, r, total_ret))
    pos_rows.sort(key=lambda x: (x[1] is None, -(x[1] or 0)))
    priced_rows = [(n, r) for n, r, _ in pos_rows if r is not None]
    if priced_rows:
        fig_x = go.Figure(go.Bar(x=[r * 100 for _, r in priced_rows],
                                 y=[n for n, _ in priced_rows], orientation="h"))
        fig_x.update_layout(title="XIRR per posizione (%)", yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_x, use_container_width=True)
    st.dataframe(pd.DataFrame([
        {"Nome": n,
         "Rendimento totale": "n/d" if tr is None else f"{tr * 100:.1f}%",
         "XIRR (annualizz.)": "n/d" if r is None else f"{r * 100:.1f}%"}
        for n, r, tr in pos_rows]))


@st.cache_data(ttl=86400, show_spinner=False)
def _cached_fundamentals(ticker: str):
    """Fondamentali con dati per azione, valute e base azionaria per la valutazione."""
    return fundamentals.get_fundamentals(ticker)


@st.cache_data(ttl=86400, show_spinner=False)
def _cached_eps(ticker: str):
    return valuation_history.get_eps_quarterly(ticker)


@st.cache_data(ttl=86400, show_spinner=False)
def _cached_financials(ticker: str, freq: str):
    """Bilanci normalizzati, inclusi indebitamento netto e dividendi pagati."""
    return financials.get_financials(ticker, freq)


_BAND_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "na": "⚪"}

_METRIC_LABEL = {
    "trailing_pe": "P/E", "price_to_book": "P/B", "ev_to_ebitda": "EV/EBITDA", "peg": "PEG",
    "roe": "ROE", "net_margin": "Margine netto", "debt_to_equity": "Debt/Equity",
    "free_cashflow": "Free cash flow", "return_12m": "Rendimento 12m",
    "vs_ma200": "Prezzo vs MA200", "dist_from_52w_high": "Dist. max 52w",
    "volatility": "Volatilità annua", "dividend_yield": "Dividend yield",
    "payout_ratio": "Payout", "expense_ratio": "TER", "max_drawdown_1y": "Max drawdown 1Y",
    "top10_weight": "Peso top-10", "holdings_count": "N° holdings",
}

# metriche mostrate in percentuale (valore frazione -> *100)
_PCT_METRICS = {
    "roe", "net_margin", "return_12m", "vs_ma200", "dist_from_52w_high", "volatility",
    "dividend_yield", "payout_ratio", "expense_ratio", "max_drawdown_1y", "top10_weight",
}


def _fmt_metric(name: str, value) -> str:
    if value is None:
        return "n/d"
    if name == "holdings_count":
        return f"{int(value)}"
    if name == "free_cashflow":
        return f"{value:,.0f}"
    if name in _PCT_METRICS:
        return f"{value * 100:.1f}%"
    return f"{value:.2f}"


def _resolve_input(raw: str) -> str:
    """ISIN o ticker -> ticker Yahoo con prezzi. Solleva ValueError se non risolvibile."""
    return prices.resolve_ticker(raw, ticker=raw)


def _return_12m_eur(conn, close, currency, native_return):
    """Rendimento 12m convertito in EUR. Per titoli già in EUR coincide col nativo.
    None se manca il cambio."""
    if not currency or currency == "EUR":
        return native_return
    try:
        fx = prices.get_fx_history_cached(
            conn, f"EUR{currency}=X", close.index.min().date(), date.today())
    except ValueError:
        return None
    close_eur = (close / fx.reindex(close.index).ffill()).dropna()
    return trailing_return(close_eur, 365)


def _analyze(conn, ticker: str, full: bool = False):
    """Ritorna (fund, ScoreResult, close, extras). Solleva ValueError se mancano i prezzi.
    `full=True` (scheda singola) calcola anche rendimento EUR e serie storica del P/E."""
    start = date.today() - timedelta(days=420)
    hist = prices.get_price_history_cached(conn, ticker, start, date.today())
    close = hist["close"]
    pm = price_metrics(close)
    fund = _cached_fundamentals(ticker)
    asset_class = scoring.asset_class_from_quote_type(fund.quote_type)
    res = scoring.score_instrument(asset_class, fund, pm)
    extras = {"return_12m_native": pm.return_12m}
    if full:
        extras["return_12m_eur"] = _return_12m_eur(conn, close, fund.currency, pm.return_12m)
        extras["pe_series"] = valuation_history.pe_history(close, _cached_eps(ticker))
    return fund, res, close, extras


def _pct(x):
    return "n/d" if x is None else f"{x * 100:+.1f}%"


def _render_scorecard(res, fund, extras):
    title = f"{fund.name or fund.ticker} — {res.asset_class.upper()}"
    if fund.sector:
        title += f" · {fund.sector}"
    st.subheader(title)
    st.caption("Punteggio 0–100 sintetico e per pilastri (valore, qualità, ecc.): più alto = "
               "profilo migliore secondo le soglie. Confronta strumenti su una scala comune, "
               "non è un consiglio d'acquisto.")
    if res.asset_class != "etf":
        st.caption("Soglie di valore/qualità tarate sul settore quando disponibile "
                   "(default approssimativi); n/d = metrica non significativa per il settore.")
    head = st.columns(2)
    head[0].metric("Prezzo", f"{fund.price:.2f}" if fund.price else "n/d")
    head[1].metric("Punteggio", f"{res.composite:.0f}/100" if res.composite is not None else "n/d")
    st.caption(f"Rendimento 12m — nativo: {_pct(extras.get('return_12m_native'))} · "
               f"EUR: {_pct(extras.get('return_12m_eur'))}")
    cols = st.columns(len(res.pillars))
    for col, (pillar, score) in zip(cols, res.pillars.items()):
        col.metric(pillar.capitalize(), f"{score:.0f}" if score is not None else "n/d")
    rows = []
    for pillar, items in res.metrics.items():
        for m in items:
            rows.append({"Pilastro": pillar, "Metrica": _METRIC_LABEL.get(m.name, m.name),
                         "Valore": _fmt_metric(m.name, m.value),
                         "Giudizio": _BAND_EMOJI[m.band]})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _gauge(name, value, thr):
    """Indicatore gauge di una metrica con bande verde/giallo/rosso. None se non disegnabile."""
    if value is None or thr is None or thr.kind != "monotone":
        return None
    pct = name in _PCT_METRICS
    v = value * 100 if pct else value
    g = thr.green * 100 if pct else thr.green
    y = thr.yellow * 100 if pct else thr.yellow
    green, yellow, red = "#c8e6c9", "#fde7b0", "#f4c7c3"
    if thr.higher_is_better:
        hi = max(v, g) * 1.3 if max(v, g) > 0 else g * 1.3
        steps = [{"range": [0, y], "color": red}, {"range": [y, g], "color": yellow},
                 {"range": [g, hi], "color": green}]
    else:
        hi = max(v, y) * 1.3 if max(v, y) > 0 else y * 1.3
        steps = [{"range": [0, g], "color": green}, {"range": [g, y], "color": yellow},
                 {"range": [y, hi], "color": red}]
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=v, title={"text": _METRIC_LABEL.get(name, name)},
        number={"suffix": "%" if pct else "", "valueformat": ".1f"},
        gauge={"axis": {"range": [0, hi]}, "bar": {"color": "#37474f"}, "steps": steps}))
    fig.update_layout(height=220, margin=dict(t=50, b=10, l=20, r=20))
    return fig


def _render_indicators(res, fund):
    pillars = {k: v for k, v in res.pillars.items() if v is not None}
    if len(pillars) >= 3:
        cats = [k.capitalize() for k in pillars] + [next(iter(pillars)).capitalize()]
        vals = list(pillars.values()) + [next(iter(pillars.values()))]
        radar = go.Figure(go.Scatterpolar(r=vals, theta=cats, fill="toself", name="Pilastri"))
        radar.update_layout(polar=dict(radialaxis=dict(range=[0, 100])),
                            title="Profilo per pilastro", height=320,
                            margin=dict(t=50, b=20, l=40, r=40))
        st.caption("Radar: profilo dello strumento sui pilastri (0–100), per vedere dov'è forte "
                   "o debole. I tachimetri sotto mostrano le metriche chiave con bande "
                   "verde/giallo/rosso rispetto alle soglie.")
        st.plotly_chart(radar, use_container_width=True)
    if res.asset_class == "etf":
        keys = [("expense_ratio", fund.expense_ratio)]
    else:
        keys = [("trailing_pe", fund.trailing_pe), ("price_to_book", fund.price_to_book),
                ("roe", fund.roe), ("net_margin", fund.net_margin)]
    figs = [(name, _gauge(name, value, scoring.effective_threshold(name, fund.sector,
            res.asset_class))) for name, value in keys]
    figs = [g for _, g in figs if g is not None]
    if figs:
        cols = st.columns(len(figs))
        for col, g in zip(cols, figs):
            col.plotly_chart(g, use_container_width=True)


def _render_analysts(fund):
    if not fund.num_analysts and fund.target_mean_price is None:
        return
    st.markdown("**Giudizio analisti**")
    upside = ((fund.target_mean_price / fund.price - 1) * 100
              if fund.target_mean_price and fund.price else None)
    cols = st.columns(4)
    cols[0].metric("Target medio",
                   f"{fund.target_mean_price:.2f}" if fund.target_mean_price else "n/d")
    cols[1].metric("Upside", f"{upside:+.1f}%" if upside is not None else "n/d")
    cols[2].metric("Giudizio",
                   fund.recommendation_key.replace("_", " ").title()
                   if fund.recommendation_key else "n/d")
    cols[3].metric("N° analisti", f"{fund.num_analysts}" if fund.num_analysts else "n/d")
    if fund.target_low_price and fund.target_high_price:
        st.caption(f"Range target: {fund.target_low_price:.2f} – {fund.target_high_price:.2f}")


def _render_pe_band(pe):
    st.markdown("**P/E storico (TTM)**")
    if pe is None or pe.empty:
        st.caption("Non disponibile: dati EPS insufficienti su yfinance per questo strumento.")
        return
    mean, std = float(pe.mean()), float(pe.std())
    st.caption("P/E nel tempo con media e banda ±1σ: sotto la media = storicamente più "
               "economico del solito, sopra = più caro. Inquadra il prezzo attuale nel suo "
               "contesto storico.")
    fig = go.Figure(go.Scatter(x=pe.index, y=pe.values, name="P/E"))
    fig.add_hline(y=mean, line_dash="dash", annotation_text="media")
    fig.add_hline(y=mean + std, line_dash="dot")
    fig.add_hline(y=max(mean - std, 0), line_dash="dot")
    fig.update_layout(title="P/E nel tempo — media ±1σ", yaxis_title="P/E", height=300)
    st.plotly_chart(fig, use_container_width=True)


def _render_price_charts(close):
    last_year = close[close.index >= close.index.max() - pd.Timedelta(days=365)]
    fig = go.Figure(go.Scatter(x=last_year.index, y=last_year.values, name="Prezzo"))
    fig.update_layout(title="Prezzo 1Y", yaxis_title="Valuta nativa")
    st.plotly_chart(fig, use_container_width=True)
    dd = (last_year / last_year.cummax() - 1.0) * 100
    fig_dd = go.Figure(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy",
                                  line=dict(color="#d62728")))
    fig_dd.update_layout(title="Drawdown 1Y", yaxis_title="%")
    st.plotly_chart(fig_dd, use_container_width=True)


_FIN_LABEL = {
    "revenue": "Ricavi", "net_income": "Utile netto", "operating_income": "Utile operativo",
    "free_cashflow": "Free cash flow", "operating_cashflow": "Operating cash flow",
    "capex": "Capex", "eps": "EPS",
}


def _render_financials_annual(df):
    with st.expander("Annuale — trend pluriennale", expanded=True):
        base100 = st.radio("Vista", ["Assoluto", "Base 100"], horizontal=True,
                           key="fin_annual_view") == "Base 100"
        fig = go.Figure()
        for k in ("revenue", "net_income", "free_cashflow"):
            if k not in df:
                continue
            s = financial_trends.indexed_to_100(df[k]) if base100 else df[k].dropna()
            if not s.empty:
                fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines+markers",
                                         name=_FIN_LABEL[k]))
        fig.update_layout(title="Ricavi / Utile / FCF",
                          yaxis_title="Base 100" if base100 else "Valuta nativa", height=320)
        st.plotly_chart(fig, use_container_width=True)

        cols = st.columns(3)
        for col, k in zip(cols, ("revenue", "net_income", "free_cashflow")):
            c = financial_trends.cagr(df[k]) if k in df else None
            col.metric(f"CAGR {_FIN_LABEL[k]}", _pct(c))

        marg = go.Figure()
        if "revenue" in df:
            for num, lbl in (("net_income", "Margine netto"),
                             ("operating_income", "Margine operativo"),
                             ("free_cashflow", "Margine FCF")):
                if num in df:
                    m = financial_trends.margin(df[num], df["revenue"])
                    if not m.empty:
                        marg.add_trace(go.Scatter(x=m.index, y=(m * 100).values,
                                                  mode="lines+markers", name=lbl))
        marg.update_layout(title="Margini % sul fatturato", yaxis_title="%", height=300)
        st.plotly_chart(marg, use_container_width=True)

        yoy = go.Figure()
        for k in ("revenue", "net_income"):
            if k in df:
                g = financial_trends.yoy_growth(df[k], periods=1)
                if not g.empty:
                    yoy.add_trace(go.Bar(x=g.index, y=(g * 100).values, name=f"YoY {_FIN_LABEL[k]}"))
        yoy.update_layout(title="Crescita anno-su-anno", yaxis_title="%", height=300,
                          barmode="group")
        st.plotly_chart(yoy, use_container_width=True)

        if "eps" in df:
            eps = df["eps"].dropna()
            fig_eps = go.Figure(go.Scatter(x=eps.index, y=eps.values, mode="lines+markers",
                                           name="EPS"))
            fig_eps.update_layout(title="EPS nel tempo", yaxis_title="EPS", height=280)
            st.plotly_chart(fig_eps, use_container_width=True)

        if "operating_cashflow" in df or "capex" in df:
            cf = go.Figure()
            if "operating_cashflow" in df:
                ocf = df["operating_cashflow"].dropna()
                cf.add_trace(go.Bar(x=ocf.index, y=ocf.values, name="Operating CF"))
            if "capex" in df:
                cx = df["capex"].dropna()
                cf.add_trace(go.Bar(x=cx.index, y=cx.values, name="Capex"))
            if "free_cashflow" in df:
                fcf = df["free_cashflow"].dropna()
                cf.add_trace(go.Scatter(x=fcf.index, y=fcf.values, mode="lines+markers", name="FCF"))
            cf.update_layout(title="Cash flow operativo, capex e FCF", yaxis_title="Valuta nativa",
                             height=300, barmode="relative")
            st.plotly_chart(cf, use_container_width=True)


def _render_financials_quarterly(df):
    with st.expander("Trimestrale — momentum recente", expanded=False):
        bars = go.Figure()
        for k in ("revenue", "net_income", "free_cashflow"):
            if k in df:
                s = df[k].dropna().tail(5)
                if not s.empty:
                    bars.add_trace(go.Bar(x=s.index, y=s.values, name=_FIN_LABEL[k]))
        bars.update_layout(title="Ultimi trimestri", yaxis_title="Valuta nativa", height=300,
                           barmode="group")
        st.plotly_chart(bars, use_container_width=True)

        yoy_cols = st.columns(3)
        for col, k in zip(yoy_cols, ("revenue", "net_income", "free_cashflow")):
            g = financial_trends.yoy_growth(df[k], periods=4) if k in df else None
            val = float(g.iloc[-1]) if (g is not None and not g.empty) else None
            col.metric(f"YoY {_FIN_LABEL[k]} (ult. trim.)", _pct(val))

        ttm_cols = st.columns(3)
        for col, k in zip(ttm_cols, ("revenue", "net_income", "free_cashflow")):
            t = financial_trends.ttm(df[k]) if k in df else None
            if t is None or t.empty:
                col.metric(f"TTM {_FIN_LABEL[k]}", "n/d")
            else:
                delta = (float(t.iloc[-1]) - float(t.iloc[-2])) if len(t) >= 2 else None
                col.metric(f"TTM {_FIN_LABEL[k]}", f"{t.iloc[-1]:,.0f}",
                           delta=f"{delta:,.0f}" if delta is not None else None)


def _render_financials(ticker):
    st.markdown("**Andamento fondamentale (storico)**")
    try:
        annual = _cached_financials(ticker, "annual")
    except ValueError:
        st.caption("Dati di bilancio non disponibili su yfinance per questo strumento.")
        return
    if not annual.empty:
        _render_financials_annual(annual)
    try:
        quarterly = _cached_financials(ticker, "quarterly")
    except ValueError:
        quarterly = pd.DataFrame()
    if not quarterly.empty:
        _render_financials_quarterly(quarterly)


def _load_portfolio_comparison(conn, groups, instruments):
    start = min(tx.trade_date for txs in groups.values() for tx in txs) - timedelta(days=7)
    end = date.today()
    market, exchanges, histories, errors, notices = {}, {}, {}, [], []

    def market_series(ticker, currency, column="close"):
        ticker = (ticker or "").strip().upper()
        currency = (currency or "").strip()
        scale = 0.01 if currency in ("GBp", "GBX") else 1.0
        currency = "GBP" if scale == 0.01 else currency.upper()
        if not ticker or len(currency) != 3 or not currency.isalpha():
            raise ValueError("Completa ticker e valuta nell'anagrafica.")
        if ticker not in market:
            try:
                market[ticker] = prices.get_price_history(ticker, start, end + timedelta(days=1))
            except Exception:
                cached = store.read_prices_cache(conn, ticker)
                if cached.empty:
                    raise
                cached = cached.loc[str(start):str(end)]
                if cached.empty:
                    raise
                logger.exception("Yahoo non disponibile per %s: uso la cache locale", ticker)
                notices.append(f"{ticker}: uso lo storico salvato; Yahoo non è disponibile.")
                market[ticker] = cached
        rate = None
        if currency != "EUR":
            if currency not in exchanges:
                exchanges[currency] = prices.get_fx_history(
                    f"EUR{currency}=X", start, end + timedelta(days=1))
            rate = exchanges[currency]
        return portfolio_prices_eur(market[ticker][column] * scale, rate).loc[str(start):str(end)]

    for name, transactions in groups.items():
        if not transactions:
            continue
        try:
            isins = sorted({tx.isin for tx in transactions})
            quantities = quantity_timeline(transactions, pd.date_range(start, end))
            close, available_end = {}, pd.Timestamp(end)
            for isin in isins:
                instrument = instruments[isin]
                try:
                    close[isin] = market_series(instrument.yahoo_ticker, instrument.native_currency)
                    if close[isin].empty:
                        raise ValueError("Nessun prezzo nel periodo richiesto.")
                except Exception as e:
                    raise ValueError(f"{instrument.name or isin} [{isin}]: {e}") from e
                if isin in quantities and quantities[isin].iloc[-1] > 1e-6:
                    available_end = min(available_end, close[isin].index.max())
            dates = pd.date_range(min(tx.trade_date for tx in transactions), available_end)
            frame = pd.DataFrame(close)
            frame = frame.reindex(frame.index.union(dates)).sort_index().loc[:available_end]
            histories[name] = portfolio_group_index(transactions, frame)
        except Exception as e:
            logger.exception("Confronto storico non disponibile per %s", name)
            errors.append(f"{name}: {e}")
    try:
        ticker, currency = BENCHMARKS["S&P 500"]
        benchmark = market_series(ticker, currency, "adj_close")
        first = min(tx.trade_date for txs in groups.values() for tx in txs) - timedelta(days=1)
        dates = pd.date_range(first, benchmark.index.max())
        benchmark = benchmark.reindex(benchmark.index.union(dates)).sort_index().ffill()
        benchmark = benchmark.reindex(dates).dropna()
        histories["S&P 500"] = benchmark / benchmark.iloc[0] * 100.0
    except Exception as e:
        logger.exception("S&P 500 non disponibile per il confronto storico")
        errors.append(f"S&P 500: {e}")
    return {"histories": histories, "errors": errors, "notices": notices}


def _render_portfolio_comparison(conn):
    st.subheader("I miei ETF vs le mie azioni vs S&P 500")
    st.caption("Tutto lo storico delle tue operazioni, incluse le posizioni vendute. "
               "Il rendimento TWR in euro tiene conto di dividendi e commissioni registrati; "
               "acquisti e vendite non sono guadagni o perdite.")
    transactions = store.get_transactions(conn)
    instruments = store.get_instruments(conn)
    groups = group_portfolio_transactions(transactions, instruments)
    if not any(groups.values()):
        st.session_state.pop("portfolio_comparison", None)
        st.info("Importa operazioni su ETF o azioni per confrontare i tuoi investimenti.")
        return
    st.caption(" · ".join(
        f"{name}: {len({tx.isin for tx in txs})} strumenti, "
        f"dal {min(tx.trade_date for tx in txs):%d/%m/%Y}"
        for name, txs in groups.items() if txs))
    if any(inst.excluded for inst in instruments.values()):
        st.caption("Gli strumenti esclusi dalle analisi non partecipano a questo confronto.")
    request = (tuple(transactions), tuple(
        (isin, inst.yahoo_ticker, inst.native_currency, inst.asset_class, inst.excluded, inst.name)
        for isin, inst in sorted(instruments.items())), date.today())
    data = st.session_state.get("portfolio_comparison")
    if data and data["request"] != request:
        st.session_state.pop("portfolio_comparison", None)
    if st.button("Confronta tutto il mio storico", key="compare_portfolio_history"):
        st.session_state.pop("portfolio_comparison", None)
        with st.spinner("Ricostruisco ETF, azioni e S&P 500…"):
            data = _load_portfolio_comparison(conn, groups, instruments)
        data["request"] = request
        st.session_state["portfolio_comparison"] = data
    data = st.session_state.get("portfolio_comparison")
    if not data:
        return
    for notice in data["notices"]:
        st.warning(notice)
    if data["errors"]:
        st.warning("Confronto incompleto:\n\n- " + "\n- ".join(data["errors"]))
    histories = data["histories"]
    if not any(name in histories for name in groups):
        st.info("Nessun gruppo dispone di dati sufficienti per il confronto.")
        return
    view = st.radio("Vista del confronto", ["Dall'inizio", "Stesso periodo"],
                    horizontal=True, key="portfolio_comparison_view")
    try:
        common, summary = compare_portfolio_histories(histories)
    except ValueError as e:
        logger.warning("Periodo comune non disponibile: %s", e)
        st.warning(str(e))
        common, summary = pd.DataFrame(), pd.DataFrame()
    plotted = common if view == "Stesso periodo" else pd.concat(histories, axis=1)
    if not plotted.empty:
        fig = go.Figure()
        for name in plotted:
            line = plotted[name].dropna()
            fig.add_scatter(x=line.index, y=line, name=name, mode="lines", customdata=line - 100.0,
                            hovertemplate="Indice: %{y:.2f}<br>%{customdata:+.2f}%<extra></extra>")
        fig.add_hline(y=100.0, line_dash="dot", line_color="gray")
        fig.update_layout(title="I miei investimenti — rendimento TWR in EUR",
                          yaxis_title="Indice (base 100)", hovermode="x unified", height=440)
        st.plotly_chart(fig, width="stretch")
    st.caption("Dall'inizio: ogni gruppo parte da 100 alla chiusura precedente la prima "
               "operazione. Nei giorni senza titoli il suo indice resta invariato. "
               "Stesso periodo: le linee ripartono da 100 sulla prima data comune.")
    if not common.empty:
        st.caption(f"Riepilogo sullo stesso periodo: {common.index.min():%d/%m/%Y} – "
                   f"{common.index.max():%d/%m/%Y}.")
        st.dataframe(summary.round(2).rename_axis("Gruppo").reset_index(),
                     width="stretch", hide_index=True)
        if all(name in summary.index for name in groups):
            difference = (summary.loc["I miei ETF", "Rendimento %"]
                          - summary.loc["Le mie azioni", "Rendimento %"])
            if abs(difference) < 0.005:
                st.info("Nello stesso periodo ETF e azioni hanno ottenuto lo stesso rendimento.")
            else:
                winner = "gli ETF" if difference > 0.0 else "le azioni"
                st.info(f"Nello stesso periodo hai ottenuto un rendimento maggiore con "
                        f"{winner} di {abs(difference):.2f} punti percentuali.")
    st.caption("Il calo massimo misura la perdita dal picco precedente. Lo S&P 500 include "
               "i dividendi, è convertito in euro ed è al lordo di imposte e commissioni; "
               "i tuoi dividendi sono quelli registrati nell'importazione.")


def _render_instrument_comparison(conn):
    st.subheader("Confronto ETF e azioni")
    st.caption("Confronta il rendimento totale in euro, con dividendi reinvestiti, "
               "al lordo di imposte e commissioni. Tutti partono da 100: 110 equivale a +10%.")
    instruments = store.get_instruments(conn)
    state = build_portfolio_state(store.get_transactions(conn), on_oversell="skip")
    if state.warnings:
        logger.warning("Storico incompleto nella selezione degli strumenti da confrontare")
        st.warning("Storico incompleto:\n\n- " + "\n- ".join(state.warnings))
    mapped = {inst.yahoo_ticker.strip().upper(): inst for inst in instruments.values()
              if inst.yahoo_ticker}
    excluded = {isin for isin, inst in instruments.items() if inst.excluded}
    excluded_tickers = {inst.yahoo_ticker.strip().upper() for inst in instruments.values()
                        if inst.excluded and inst.yahoo_ticker}
    candidates = {
        inst.yahoo_ticker.strip().upper(): {
            "name": inst.name or inst.yahoo_ticker, "currency": inst.native_currency}
        for inst in instruments.values()
        if inst.yahoo_ticker and inst.yahoo_ticker.strip()
        and inst.isin in state.positions and not inst.excluded
        and inst.asset_class in ("azione", "stock", "etf")
    }
    for item in store.get_watchlist(conn):
        ticker = item["ticker"].strip().upper()
        if (ticker and ticker not in excluded_tickers and item["isin"] not in excluded
                and item["asset_class"] in ("azione", "stock", "etf")):
            known = mapped.get(ticker)
            candidates.setdefault(ticker, {"name": item["name"] or ticker,
                                          "currency": known.native_currency if known else None})
    if len(candidates) < 2:
        st.session_state.pop("instrument_comparison", None)
        st.info("Servono almeno due ETF o azioni nel portafoglio o nella watchlist, con ticker.")
        return
    options = sorted(candidates, key=lambda ticker: candidates[ticker]["name"].lower())
    if any(ticker not in candidates for ticker in st.session_state.get("comparison_symbols", [])):
        st.session_state.pop("comparison_symbols", None)
    period = st.selectbox(
        "Periodo del confronto", ["1 anno", "3 anni", "5 anni", "Date personalizzate"],
        key="comparison_period")
    end = date.today()
    years = 1 if period == "Date personalizzate" else int(period[0])
    start = (pd.Timestamp(end) - pd.DateOffset(years=years)).date()
    with st.form("instrument_comparison_form"):
        selected = st.multiselect(
            "ETF e azioni da confrontare", options, default=options[:2], max_selections=6,
            format_func=lambda ticker: f"{candidates[ticker]['name']} [{ticker}]",
            key="comparison_symbols")
        if period == "Date personalizzate":
            c1, c2 = st.columns(2)
            start = c1.date_input("Dal", value=start, max_value=end, key="comparison_start")
            end = c2.date_input("Al", value=end, max_value=end, key="comparison_end")
        submitted = st.form_submit_button("Confronta")
    request = (tuple((ticker, candidates[ticker]["currency"]) for ticker in selected), start, end)
    data = st.session_state.get("instrument_comparison")
    if data and data["request"] != request:
        st.session_state.pop("instrument_comparison", None)
    if submitted:
        st.session_state.pop("instrument_comparison", None)
        errors = []
        try:
            if not 2 <= len(selected) <= 6:
                raise ValueError("Seleziona da 2 a 6 ETF o azioni.")
            if start >= end or end > date.today():
                raise ValueError("Scegli una data iniziale precedente alla finale, entro oggi.")
            series, fx_by_currency = {}, {}
            with st.spinner("Carico gli storici per il confronto…"):
                for ticker in selected:
                    try:
                        currency = candidates[ticker]["currency"]
                        if not currency:
                            currency = _cached_fundamentals(ticker).currency
                        currency = (currency or "").strip()
                        scale = 0.01 if currency in ("GBp", "GBX") else 1.0
                        currency = "GBP" if scale == 0.01 else currency.upper()
                        if len(currency) != 3 or not currency.isalpha():
                            raise ValueError("Valuta di quotazione non disponibile.")
                        hist = prices.get_price_history(ticker, start, end + timedelta(days=1))
                        adjusted = hist["adj_close"].loc[str(start):str(end)] * scale
                        rate = None
                        if currency != "EUR":
                            if currency not in fx_by_currency:
                                fx_by_currency[currency] = prices.get_fx_history(
                                    f"EUR{currency}=X", start - timedelta(days=7),
                                    end + timedelta(days=1))
                            rate = fx_by_currency[currency]
                        converted = adjusted_prices_eur(adjusted, rate)
                        if len(converted) < 2:
                            raise ValueError("Meno di due quotazioni disponibili nel periodo.")
                        series[ticker] = converted
                    except Exception as e:
                        logger.exception("Dati confronto non disponibili per %s", ticker)
                        errors.append(f"{candidates[ticker]['name']} [{ticker}]: {e}")
                index = base100_comparison(series)
            st.session_state["instrument_comparison"] = {
                "request": request, "index": index, "errors": errors,
                "labels": {ticker: f"{candidates[ticker]['name']} [{ticker}]" for ticker in index},
            }
        except Exception as e:
            logger.exception("Confronto ETF e azioni non disponibile")
            st.error(f"Confronto non disponibile: {e}")
            if errors:
                st.warning("Dati mancanti:\n\n- " + "\n- ".join(errors))
    data = st.session_state.get("instrument_comparison")
    if not data:
        return
    if data["errors"]:
        st.warning("Strumenti esclusi dal confronto:\n\n- " + "\n- ".join(data["errors"]))
    index = data["index"]
    st.caption(f"Periodo effettivo comune: {index.index.min():%d/%m/%Y} – "
               f"{index.index.max():%d/%m/%Y}. Fonte: Yahoo Finance, prezzi rettificati. "
               "Usa la legenda per mostrare o nascondere le linee.")
    fig = go.Figure()
    for ticker in index:
        fig.add_scatter(
            x=index.index, y=index[ticker], name=data["labels"][ticker], mode="lines",
            customdata=index[ticker] - 100.0,
            hovertemplate="Indice: %{y:.2f}<br>Rendimento: %{customdata:+.2f}%<extra></extra>")
    fig.add_hline(y=100.0, line_dash="dot", line_color="gray")
    fig.update_layout(title="ETF e azioni — rendimento totale in EUR",
                      yaxis_title="Indice (base 100)", hovermode="x unified", height=440)
    st.plotly_chart(fig, width="stretch")


def page_analyzer(conn):
    st.header("Analizzatore aziende & ETF")

    raw = st.text_input("ISIN o ticker da analizzare").strip()
    if st.button("Analizza") and raw:
        try:
            with st.spinner("Analizzo…"):
                ticker = _resolve_input(raw)
                fund, res, close, extras = _analyze(conn, ticker, full=True)
        except ValueError as e:
            st.session_state.pop("analysis", None)
            st.error(str(e))
        else:
            st.session_state["analysis"] = {
                "ticker": ticker, "raw": raw, "fund": fund, "res": res,
                "close": close, "extras": extras}

    analysis = st.session_state.get("analysis")
    if analysis:
        _render_scorecard(analysis["res"], analysis["fund"], analysis["extras"])
        if analysis["res"].asset_class == "etf":
            raw_isin = analysis["raw"].upper()
            if not (len(raw_isin) == 12 and raw_isin[:2].isalpha() and
                    raw_isin.isalnum() and raw_isin[-1].isdigit()):
                raw_isin = next((inst.isin for inst in store.get_instruments(conn).values()
                                 if (inst.yahoo_ticker or "").upper() == analysis["ticker"].upper()), "")
            render_etf_analysis(analysis["ticker"], raw_isin)
        render_company_analysis(analysis["fund"], _cached_financials)
        _render_indicators(analysis["res"], analysis["fund"])
        _render_analysts(analysis["fund"])
        _render_price_charts(analysis["close"])
        if analysis["res"].asset_class != "etf":
            _render_pe_band(analysis["extras"].get("pe_series"))
            _render_financials(analysis["ticker"])
        if st.button("➕ Aggiungi alla watchlist"):
            store.add_to_watchlist(
                conn, analysis["ticker"],
                analysis["raw"] if analysis["raw"] != analysis["ticker"] else None,
                analysis["fund"].name, analysis["res"].asset_class)
            st.success(f"{analysis['fund'].name or analysis['ticker']} aggiunto alla watchlist.")

    try:
        _render_portfolio_comparison(conn)
    except Exception as e:
        st.session_state.pop("portfolio_comparison", None)
        logger.exception("Caricamento confronto del portafoglio fallito")
        st.error(f"Confronto del portafoglio non disponibile: {e}")

    try:
        _render_instrument_comparison(conn)
    except Exception as e:
        logger.exception("Caricamento confronto ETF e azioni fallito")
        st.error(f"Confronto ETF e azioni non disponibile: {e}")

    wl = store.get_watchlist(conn)
    render_company_comparison(wl, analysis, lambda ticker, full: _analyze(conn, ticker, full),
                              _cached_fundamentals, _cached_financials)
    if not wl:
        st.info("Watchlist vuota: analizza uno strumento e aggiungilo.")
        return
    rows = []
    for item in (entry for entry in wl if entry["asset_class"] == "etf"):
        try:
            fund, res, _close, _extras = _analyze(conn, item["ticker"])
        except ValueError as e:
            logger.exception("Confronto ETF non disponibile: %s", item["ticker"])
            st.warning(f"{item['ticker']}: {e}")
            rows.append({"Nome": item["name"] or item["ticker"], "Ticker": item["ticker"],
                         "Punteggio": None})
            continue
        row = {"Nome": fund.name or item["ticker"], "Ticker": item["ticker"],
               "Punteggio": round(res.composite, 0) if res.composite is not None else None}
        for pillar, score in res.pillars.items():
            row[pillar.capitalize()] = round(score, 0) if score is not None else None
        rows.append(row)
    if rows:
        st.subheader("Confronto ETF (watchlist)")
        df = pd.DataFrame(rows).sort_values("Punteggio", ascending=False, na_position="last")
        st.dataframe(df, use_container_width=True, hide_index=True)
        ranked = df.dropna(subset=["Punteggio"])
        if not ranked.empty:
            st.plotly_chart(px.bar(ranked, x="Nome", y="Punteggio", title="Punteggio composito"),
                            use_container_width=True)
    to_remove = st.selectbox("Rimuovi dalla watchlist", [""] + [r["ticker"] for r in wl])
    if to_remove and st.button("Rimuovi"):
        store.remove_from_watchlist(conn, to_remove)
        st.rerun()


_DISCOVER_REGIONS = {
    "USA": "us", "Italia": "it", "Germania": "de", "Francia": "fr",
    "Regno Unito": "gb", "Paesi Bassi": "nl", "Spagna": "es", "Svizzera": "ch",
}
_DISCOVER_MARKET_CAP = {"Qualsiasi": None, "Mid+ (≥2 mld)": 2e9, "Large (≥10 mld)": 10e9}

# Scala unità campi Yahoo (CALIBRATA in Task 2 via probe live su yf.screen):
# - azioni % (ROE/ROA/margini/crescita/dividendo) ED ETF rendimenti 1/3/5y: PERCENTO -> _PCT = 1.0
# - ETF expense ratio: FRAZIONE (0.0020 = 0.20%) -> _TER = 0.01
# - debt/equity: ratio as-is (0.5 = 0.5x) -> _DE = 1.0
_PCT = 1.0
_TER = 0.01
_DE = 1.0

# Preset filtri avanzati AZIONI (None = nessun filtro).
_DISCOVER_PE_MAX = {"(qualsiasi)": None, "≤ 15": 15, "≤ 25": 25, "≤ 40": 40}
_DISCOVER_PB_MAX = {"(qualsiasi)": None, "≤ 1.5": 1.5, "≤ 3": 3, "≤ 6": 6}
_DISCOVER_PEG_MAX = {"(qualsiasi)": None, "≤ 1": 1, "≤ 1.5": 1.5, "≤ 2": 2}
_DISCOVER_EV_EBITDA_MAX = {"(qualsiasi)": None, "≤ 10": 10, "≤ 16": 16, "≤ 25": 25}
_DISCOVER_ROE_MIN = {"(qualsiasi)": None, "≥ 8%": 8 * _PCT, "≥ 15%": 15 * _PCT, "≥ 20%": 20 * _PCT}
_DISCOVER_ROA_MIN = {"(qualsiasi)": None, "≥ 5%": 5 * _PCT, "≥ 10%": 10 * _PCT}
_DISCOVER_NET_MARGIN_MIN = {"(qualsiasi)": None, "≥ 5%": 5 * _PCT, "≥ 10%": 10 * _PCT, "≥ 20%": 20 * _PCT}
_DISCOVER_GROSS_MARGIN_MIN = {"(qualsiasi)": None, "≥ 20%": 20 * _PCT, "≥ 40%": 40 * _PCT}
_DISCOVER_REV_GROWTH_MIN = {"(qualsiasi)": None, "≥ 5%": 5 * _PCT, "≥ 10%": 10 * _PCT, "≥ 20%": 20 * _PCT}
_DISCOVER_EPS_GROWTH_MIN = {"(qualsiasi)": None, "≥ 5%": 5 * _PCT, "≥ 10%": 10 * _PCT, "≥ 20%": 20 * _PCT}
_DISCOVER_DIV_YIELD_MIN = {"(qualsiasi)": None, "≥ 2%": 2 * _PCT, "≥ 3%": 3 * _PCT, "≥ 4%": 4 * _PCT}
_DISCOVER_DIV_GROWTH_YEARS_MIN = {"(qualsiasi)": None, "≥ 5": 5, "≥ 10": 10, "≥ 25": 25}
_DISCOVER_DEBT_EQUITY_MAX = {"(qualsiasi)": None, "≤ 0.5": 0.5 * _DE, "≤ 1": 1 * _DE, "≤ 2": 2 * _DE}
_DISCOVER_CURRENT_RATIO_MIN = {"(qualsiasi)": None, "≥ 1": 1, "≥ 1.5": 1.5, "≥ 2": 2}

# Preset filtri avanzati ETF (None = nessun filtro).
_DISCOVER_ETF_EXPENSE_MAX = {"(qualsiasi)": None, "≤ 0.20%": 0.20 * _TER, "≤ 0.50%": 0.50 * _TER, "≤ 1%": 1.0 * _TER}
_DISCOVER_ETF_RET_1Y_MIN = {"(qualsiasi)": None, "≥ 0%": 0.0, "≥ 5%": 5 * _PCT, "≥ 10%": 10 * _PCT}
_DISCOVER_ETF_RET_3Y_MIN = {"(qualsiasi)": None, "≥ 0%": 0.0, "≥ 5%": 5 * _PCT, "≥ 10%": 10 * _PCT}
_DISCOVER_ETF_RET_5Y_MIN = {"(qualsiasi)": None, "≥ 0%": 0.0, "≥ 5%": 5 * _PCT, "≥ 10%": 10 * _PCT}
_DISCOVER_ETF_RATING_MIN = {"(qualsiasi)": None, "≥ 3★": 3, "≥ 4★": 4, "= 5★": 5}
_DISCOVER_ETF_AUM_MIN = {"(qualsiasi)": None, "≥ 100 mln": 1e8, "≥ 500 mln": 5e8, "≥ 1 mld": 1e9}

_DISCOVER_ETF_CATEGORIES = [
    "(qualsiasi)", "Large Blend", "Large Growth", "Large Value", "Mid-Cap Blend",
    "Small Blend", "Foreign Large Blend", "Europe Stock", "Japan Stock",
    "Diversified Emerging Mkts", "China Region", "Pacific/Asia ex-Japan Stk",
    "Health", "Financial", "Equity Energy", "Equity Precious Metals",
    "Natural Resources", "Real Estate", "Global Real Estate", "Infrastructure",
    "Commodities Broad Basket", "Intermediate-Term Bond", "Corporate Bond",
    "High Yield Bond", "Inflation-Protected Bond", "Emerging Markets Bond",
    "Short-Term Bond",
]


_BAND_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴", "na": "⚪"}

# Metriche grezze (nomi come in scoring) mostrate in tabella: (etichetta, nome, formato).
_STOCK_RAW_COLS = [
    ("P/E", "trailing_pe", "ratio"),
    ("ROE", "roe", "pct"),
    ("Margine netto", "net_margin", "pct"),
    ("Debt/Equity", "debt_to_equity", "ratio"),
    ("Div yield", "dividend_yield", "pct"),
    ("Cresc. ricavi", "revenue_growth", "pct"),
    ("Rend. 12m", "return_12m", "pct"),
]
_ETF_RAW_COLS = [
    ("Expense ratio", "expense_ratio", "pct"),
    ("Rend. 12m", "return_12m", "pct"),
    ("Volatilità", "volatility", "pct"),
    ("Max DD 1y", "max_drawdown_1y", "pct"),
]


def _metric_values(res) -> dict:
    """Mappa nome_metrica -> valore grezzo da ScoreResult.metrics."""
    out = {}
    for row in res.metrics.values():
        for m in row:
            out[m.name] = m.value
    return out


def _fmt(value, kind: str):
    """Formatta un valore metrica: 'pct' come percentuale, 'ratio' arrotondato."""
    if value is None:
        return None
    if kind == "pct":
        return f"{value * 100:.1f}%"
    return round(value, 2)


def _pick(label: str, preset_map: dict, active: list[str]):
    """Selectbox da una mappa label->valore; ritorna il valore (None se '(qualsiasi)').

    Se il valore scelto non è None, aggiunge "label: scelta" a `active` (per il riepilogo).
    """
    choice = st.selectbox(label, list(preset_map))
    value = preset_map[choice]
    if value is not None:
        active.append(f"{label}: {choice}")
    return value


def _excluded_tickers(conn, txs, instruments) -> set[str]:
    """Ticker già posseduti (posizioni aperte) o in watchlist, da escludere dai candidati."""
    exclude = set()
    try:
        state = build_portfolio_state(txs, on_oversell="skip")
        for isin in state.positions:
            inst = instruments.get(isin)
            if inst and inst.yahoo_ticker:
                exclude.add(inst.yahoo_ticker)
    except ValueError:
        pass
    for item in store.get_watchlist(conn):
        exclude.add(item["ticker"])
    return exclude


def page_discover(conn):
    st.header("Scopri nuovi strumenti")
    st.caption("Imposta pochi criteri: Yahoo restituisce un bacino ampio e il punteggio "
               "composito ordina i candidati, esclusi quelli già in portafoglio o in watchlist.")

    asset = st.radio("Tipo", ["Azioni", "ETF"], horizontal=True, key="discover_asset")
    is_etf = asset == "ETF"
    with st.form("discover"):
        default_regions = ["Italia", "Germania"] if is_etf else ["USA"]
        region_labels = st.multiselect("Regione", list(_DISCOVER_REGIONS),
                                       default=default_regions, key=f"discover_regions_{asset}")
        sector = min_cap = category = None
        active: list[str] = []
        filters: dict[str, float | None] = {}
        if is_etf:
            st.caption("Gli ETF region=USA non sono acquistabili da un investitore IT: "
                       "preferisci ETF UCITS quotati in EU (Italia/Germania/…).")
            only_non_hedged = st.checkbox("Solo ETF non hedged (dato verificato)", value=True,
                                          key="discover_non_hedged")
            st.caption("Il filtro ammette solo ETF verificati senza copertura valutaria. "
                       "La verifica automatica usa il catalogo iShares; gli altri emittenti "
                       "restano non verificati. La valuta di quotazione non prova la copertura.")
            if only_non_hedged:
                active.append("Solo ETF non hedged verificati")
        else:
            sec_choice = st.selectbox("Settore", ["(qualsiasi)"] + sorted(scoring.SECTOR_THRESHOLDS))
            sector = None if sec_choice == "(qualsiasi)" else sec_choice
            cap_choice = st.selectbox("Capitalizzazione minima", list(_DISCOVER_MARKET_CAP), index=1)
            min_cap = _DISCOVER_MARKET_CAP[cap_choice]
        with st.expander("Filtri avanzati", expanded=False):
            if is_etf:
                cat_choice = st.selectbox("Categoria", _DISCOVER_ETF_CATEGORIES)
                category = None if cat_choice == "(qualsiasi)" else cat_choice
                if category:
                    active.append(f"Categoria: {category}")
                st.caption("La categoria combinata con regioni EU può ridurre molto i risultati.")
                filters["expense_ratio_max"] = _pick("TER massimo", _DISCOVER_ETF_EXPENSE_MAX, active)
                filters["return_1y_min"] = _pick("Rendimento 1 anno minimo", _DISCOVER_ETF_RET_1Y_MIN, active)
                filters["return_3y_min"] = _pick("Rendimento 3 anni minimo", _DISCOVER_ETF_RET_3Y_MIN, active)
                filters["return_5y_min"] = _pick("Rendimento 5 anni minimo", _DISCOVER_ETF_RET_5Y_MIN, active)
                filters["morningstar_rating_min"] = _pick("Rating minimo", _DISCOVER_ETF_RATING_MIN, active)
                filters["aum_min"] = _pick("AUM minimo", _DISCOVER_ETF_AUM_MIN, active)
            else:
                col1, col2 = st.columns(2)
                with col1:
                    filters["pe_max"] = _pick("P/E max", _DISCOVER_PE_MAX, active)
                    filters["pb_max"] = _pick("P/B max", _DISCOVER_PB_MAX, active)
                    filters["peg_max"] = _pick("PEG max", _DISCOVER_PEG_MAX, active)
                    filters["ev_ebitda_max"] = _pick("EV/EBITDA max", _DISCOVER_EV_EBITDA_MAX, active)
                    filters["roe_min"] = _pick("ROE min", _DISCOVER_ROE_MIN, active)
                    filters["roa_min"] = _pick("ROA min", _DISCOVER_ROA_MIN, active)
                    filters["net_margin_min"] = _pick("Margine netto min", _DISCOVER_NET_MARGIN_MIN, active)
                with col2:
                    filters["gross_margin_min"] = _pick("Margine lordo min", _DISCOVER_GROSS_MARGIN_MIN, active)
                    filters["rev_growth_min"] = _pick("Cresc. ricavi min", _DISCOVER_REV_GROWTH_MIN, active)
                    filters["eps_growth_min"] = _pick("Cresc. EPS min", _DISCOVER_EPS_GROWTH_MIN, active)
                    filters["div_yield_min"] = _pick("Dividend yield min", _DISCOVER_DIV_YIELD_MIN, active)
                    filters["div_growth_years_min"] = _pick("Anni cresc. dividendo min", _DISCOVER_DIV_GROWTH_YEARS_MIN, active)
                    filters["debt_equity_max"] = _pick("Debt/Equity max", _DISCOVER_DEBT_EQUITY_MAX, active)
                    filters["current_ratio_min"] = _pick("Current ratio min", _DISCOVER_CURRENT_RATIO_MIN, active)
        n = st.slider("N° candidati da valutare", 5, 50, 25)
        submitted = st.form_submit_button("🔎 Cerca")

    if submitted:
        regions = [_DISCOVER_REGIONS[lbl] for lbl in region_labels]
        try:
            with st.spinner("Interrogo lo screener Yahoo…"):
                candidates = screener.screen_candidates(
                    "etf" if is_etf else "stock", regions, sector=sector,
                    min_market_cap=min_cap, category=category, filters=filters,
                    size=min(250, n * 5))
            txs = store.get_transactions(conn)
            instruments = store.get_instruments(conn)
            exclude = _excluded_tickers(conn, txs, instruments)

            def _analyze_pair(sym):
                fund, res, _close, _extras = _analyze(conn, sym)
                return fund, res

            with st.spinner(f"Valuto fino a {n} candidati…"):
                ranked, skipped = discovery.rank_candidates(candidates, exclude, _analyze_pair, n)
            etf_profiles, hedge_errors = {}, []
            excluded_hedged, excluded_unknown = [], []
            if is_etf:
                with st.spinner("Verifico la copertura valutaria…"):
                    etf_profiles, hedge_errors = load_etf_profiles(ranked, cached_etf_profile)
                if only_non_hedged:
                    ranked, excluded_hedged, excluded_unknown = filter_non_hedged(ranked, etf_profiles)
        except ValueError as e:
            st.session_state.pop("discover_results", None)
            st.error(str(e))
        else:
            st.session_state["discover_results"] = {
                "ranked": ranked, "skipped": skipped, "active": active,
                "etf_profiles": etf_profiles, "hedge_errors": hedge_errors,
                "excluded_hedged": excluded_hedged, "excluded_unknown": excluded_unknown}

    data = st.session_state.get("discover_results")
    if not data:
        return
    ranked, skipped = data["ranked"], data["skipped"]
    for error in dict.fromkeys(data.get("hedge_errors", [])):
        st.warning(error)
    if data.get("excluded_hedged"):
        st.caption("Esclusi perché hedged: " + ", ".join(data["excluded_hedged"]))
    if data.get("excluded_unknown"):
        st.caption("Esclusi perché la copertura non è verificata: " + ", ".join(data["excluded_unknown"]))
    if not ranked:
        st.info("Nessun candidato valutabile con questi filtri.")
        active = data.get("active")
        if active:
            st.caption("Filtri attivi: " + " · ".join(active))
    else:
        rows = []
        for r in ranked:
            row = {"Nome": r.name or r.symbol, "Ticker": r.symbol,
                   "Punteggio": round(r.result.composite, 0)
                   if r.result.composite is not None else None}
            if r.result.asset_class == "etf":
                profile = data.get("etf_profiles", {}).get(r.symbol, EtfProfile(r.symbol))
                row["Copertura valutaria"] = hedge_label(profile)
                row["Proventi"] = profile.distribution or "Non disponibile"
                row["Fonte caratteristiche"] = profile.source_url or "Non disponibile"
            for pillar, score in r.result.pillars.items():
                row[pillar.capitalize()] = round(score, 0) if score is not None else None
            raw_cols = _ETF_RAW_COLS if r.result.asset_class == "etf" else _STOCK_RAW_COLS
            vals = _metric_values(r.result)
            for label, name, kind in raw_cols:
                row[label] = _fmt(vals.get(name), kind)
            rows.append(row)
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        by_sym = {r.symbol: r for r in ranked}
        sel = st.selectbox("Dettaglio candidato", [""] + list(by_sym),
                           format_func=lambda s: (by_sym[s].name or s) if s else "(scegli un candidato)")
        if sel:
            detail = []
            for pillar, mlist in by_sym[sel].result.metrics.items():
                for m in mlist:
                    detail.append({
                        "Pillar": pillar.capitalize(), "Metrica": m.name,
                        "Valore": round(m.value, 4) if m.value is not None else None,
                        "Banda": _BAND_ICON.get(m.band, m.band)})
            st.dataframe(pd.DataFrame(detail), use_container_width=True, hide_index=True)
            if by_sym[sel].result.asset_class == "etf":
                profile = data.get("etf_profiles", {}).get(sel, EtfProfile(sel))
                render_etf_analysis(sel, profile.isin)
        scored = df.dropna(subset=["Punteggio"])
        if not scored.empty:
            st.plotly_chart(px.bar(scored, x="Nome", y="Punteggio",
                                   title="Punteggio composito dei candidati"),
                            use_container_width=True)
        names = {r.symbol: (r.name or r.symbol) for r in ranked}
        chosen = st.multiselect("Aggiungi alla watchlist", list(names),
                                format_func=lambda s: names[s])
        if chosen and st.button("➕ Aggiungi selezionati"):
            for s in chosen:
                r = by_sym[s]
                store.add_to_watchlist(conn, r.symbol, None, r.name, r.result.asset_class)
            st.success(f"Aggiunti {len(chosen)} strumenti alla watchlist.")
    if skipped:
        st.caption("Saltati (prezzi/fondamentali non disponibili): " + ", ".join(skipped))


def _planning_portfolio(conn):
    txs = store.get_transactions(conn)
    instruments = store.get_instruments(conn)
    excluded = {isin for isin, inst in instruments.items() if inst.excluded}
    txs = [tx for tx in txs if tx.isin not in excluded]
    if not txs:
        raise ValueError("Nessuna operazione disponibile per l'analisi.")
    state = build_portfolio_state(txs, on_oversell="skip")
    held = sorted(state.positions)
    missing = [isin for isin in held if isin not in instruments]
    if missing:
        raise ValueError("Completa l'anagrafica per: " + ", ".join(missing))
    if not held:
        raise ValueError("Nessuna posizione aperta da analizzare.")

    dates = pd.date_range(date.today() - timedelta(days=30), date.today(), freq="D")
    close_eur, _adj_eur, _fx = _eur_price_frame(conn, instruments, held, dates)
    current_values = {}
    unpriced = []
    for isin in held:
        series = close_eur[isin].dropna() if isin in close_eur else pd.Series(dtype=float)
        if series.empty:
            unpriced.append(isin)
            continue
        current_values[isin] = state.positions[isin].quantity * float(series.iloc[-1])
    if not current_values:
        raise ValueError("Nessuna posizione dispone di un prezzo recente.")
    return instruments, state, current_values, unpriced


def page_rebalancing(conn):
    st.header("Ribilanciamento")
    st.caption("Confronta il peso attuale con l'allocazione desiderata e simula le operazioni. "
               "Sono incluse le posizioni aperte con prezzo disponibile; non vengono inviati "
               "ordini al broker.")
    try:
        instruments, state, current_values, unpriced = _planning_portfolio(conn)
    except ValueError as e:
        st.error(str(e))
        return
    average_purchase = average_monthly_purchases(
        store.get_transactions(conn), as_of=date.today())
    if state.warnings:
        st.warning("Storico incompleto:\n\n- " + "\n- ".join(state.warnings))
    if unpriced:
        st.warning("Escluse perché senza prezzo recente: " + ", ".join(
            instruments[isin].name for isin in unpriced))

    total = sum(current_values.values())
    current_weights = {isin: value / total for isin, value in current_values.items()}
    saved_targets = store.get_allocation_targets(conn)
    target_weights = ({isin: saved_targets.get(isin, 0.0) for isin in current_values}
                      if saved_targets else current_weights)
    target_percentages = {isin: weight * 100.0 for isin, weight in target_weights.items()}
    ordered_isins = sorted(current_values, key=lambda isin: instruments[isin].name)
    if ordered_isins and abs(sum(target_percentages.values()) - 100.0) < 1e-6:
        rounded = {isin: round(target_percentages[isin], 2) for isin in ordered_isins}
        rounded[ordered_isins[-1]] += 100.0 - sum(rounded.values())
        target_percentages = rounded

    target_rows = pd.DataFrame([
        {
            "ISIN": isin,
            "Nome": instruments[isin].name,
            "Valore attuale EUR": round(current_values[isin], 2),
            "Peso attuale %": round(current_weights[isin] * 100.0, 2),
            "Target %": target_percentages[isin],
        }
        for isin in ordered_isins
    ])
    edited = st.data_editor(
        target_rows,
        width="stretch",
        hide_index=True,
        disabled=["ISIN", "Nome", "Valore attuale EUR", "Peso attuale %"],
        column_config={
            "ISIN": None,
            "Target %": st.column_config.NumberColumn(
                "Target %", min_value=0.0, max_value=100.0, step=0.1, format="%.2f"),
        },
        key="allocation_target_editor",
    )
    targets = {row["ISIN"]: float(row["Target %"]) / 100.0
               for _, row in edited.iterrows()}
    target_sum = sum(targets.values())
    st.caption(f"Totale target: {target_sum * 100:.2f}%")
    try:
        validate_target_weights(targets)
    except ValueError as e:
        targets_valid = False
        st.error(str(e))
    else:
        targets_valid = True

    if st.button("Salva allocazione obiettivo", disabled=not targets_valid):
        store.replace_allocation_targets(conn, targets)
        st.success("Allocazione obiettivo salvata.")

    st.subheader("Operazioni simulate")
    st.caption(f"Media acquisti degli ultimi 12 mesi completi: "
               f"{average_purchase:,.2f} € (commissioni incluse; vendite e dividendi esclusi).")
    c1, c2, c3 = st.columns(3)
    new_cash = c1.number_input(
        "Nuova liquidità EUR", min_value=0.0, value=round(average_purchase, 2),
        step=100.0)
    mode = c2.radio(
        "Modalità", ["Acquisti e vendite", "Solo nuova liquidità"], horizontal=False)
    commission = c3.number_input(
        "Commissione per operazione EUR", min_value=0.0, value=2.95, step=0.05)
    if not targets_valid:
        return

    if mode == "Solo nuova liquidità":
        lines = allocate_contribution(current_values, targets, new_cash)
    else:
        lines = rebalance_trades(current_values, targets, new_cash)
    trades = {line.isin: line.trade_eur for line in lines
              if abs(line.trade_eur) >= 0.01}
    costs = estimate_trade_costs(
        trades,
        current_values,
        {isin: state.positions[isin].total_cost_eur for isin in current_values},
        commission_per_trade_eur=commission,
    )

    operation_rows = []
    for line in lines:
        if abs(line.trade_eur) < 0.01:
            continue
        price_eur = (line.current_value_eur / state.positions[line.isin].quantity
                     if state.positions[line.isin].quantity else None)
        operation_rows.append({
            "Nome": instruments[line.isin].name,
            "Operazione": "Compra" if line.trade_eur > 0 else "Vendi",
            "Importo EUR": round(abs(line.trade_eur), 2),
            "Quantità indicativa": (round(abs(line.trade_eur) / price_eur, 4)
                                      if price_eur else None),
            "Peso finale %": round(
                (line.current_value_eur + line.trade_eur)
                / (total + new_cash) * 100.0, 2) if total + new_cash else 0.0,
        })
    if operation_rows:
        st.dataframe(pd.DataFrame(operation_rows), width="stretch", hide_index=True)
    else:
        st.info("Nessuna operazione necessaria con questi target e questa liquidità.")
    k1, k2, k3 = st.columns(3)
    k1.metric("Operazioni", len(operation_rows))
    k2.metric("Commissioni stimate", f"{costs.commissions_eur:,.2f} €")
    k3.metric("Imposte stimate sulle vendite", f"{costs.estimated_tax_eur:,.2f} €")
    st.caption("La stima fiscale applica il 26% alla plusvalenza proporzionale, al netto della "
               "commissione ipotizzata; non considera compensazioni o zainetto fiscale e non "
               "sostituisce il conteggio del broker.")

    comparison = pd.DataFrame([
        row
        for line in lines
        for row in (
            {"Nome": instruments[line.isin].name, "Scenario": "Attuale",
             "Peso %": line.current_value_eur / total * 100.0},
            {"Nome": instruments[line.isin].name, "Scenario": "Dopo",
             "Peso %": ((line.current_value_eur + line.trade_eur)
                        / (total + new_cash) * 100.0 if total + new_cash else 0.0)},
        )
    ])
    st.plotly_chart(
        px.bar(comparison, x="Nome", y="Peso %", color="Scenario", barmode="group",
               title="Allocazione attuale e simulata"),
        width="stretch",
    )


def _render_stress_result(result, instruments):
    c1, c2, c3 = st.columns(3)
    c1.metric("Valore coperto", f"{result.covered_value_eur:,.0f} €")
    c2.metric("Impatto stimato", f"{result.impact_eur:,.0f} €",
              f"{result.impact_eur / result.covered_value_eur * 100:.1f}%"
              if result.covered_value_eur else None)
    c3.metric("Copertura", f"{result.coverage * 100:.1f}%")
    st.dataframe(pd.DataFrame([
        {
            "Nome": instruments[line.isin].name,
            "Valore attuale EUR": round(line.current_value_eur, 2),
            "Shock %": round(line.shock * 100.0, 2),
            "Impatto EUR": round(line.impact_eur, 2),
            "Valore dopo EUR": round(line.stressed_value_eur, 2),
        }
        for line in result.lines
    ]), width="stretch", hide_index=True)
    if result.coverage < 0.999999:
        st.warning("Il risultato riguarda soltanto la parte coperta: gli strumenti senza dati "
                   "non sono stati considerati invariati.")


def _portfolio_goal_history(conn, txs, instruments):
    state = build_portfolio_state(txs, on_oversell="skip")
    held = sorted(state.positions)
    held_txs = [tx for tx in txs if tx.isin in state.positions]
    if not held_txs:
        raise ValueError("Nessuna posizione aperta con storico disponibile.")
    first_trade_dates = {}
    for tx in held_txs:
        first_trade_dates[tx.isin] = min(
            tx.trade_date, first_trade_dates.get(tx.isin, tx.trade_date))
    dates = pd.date_range(min(first_trade_dates.values()), date.today(), freq="D")
    close_eur, _adjusted_eur, _fx = _eur_price_frame(
        conn, instruments, held, dates, first_trade_dates)
    priced = [isin for isin in held if isin in close_eur]
    if not priced:
        raise ValueError("Nessuna posizione dispone di uno storico prezzi.")
    priced_txs = [tx for tx in held_txs if tx.isin in priced]
    quantities = quantity_timeline(priced_txs, dates)
    values = portfolio_value_eur(quantities, close_eur)
    values = values[values > 0.0]
    if values.empty:
        raise ValueError("Lo storico del portafoglio è vuoto.")
    cashflows = pd.Series(0.0, index=dates)
    for tx in priced_txs:
        timestamp = pd.Timestamp(tx.trade_date)
        if tx.op_type is OpType.BUY:
            cashflows.loc[timestamp] += tx.amount_eur + tx.commission_eur
        elif tx.op_type is OpType.SELL:
            cashflows.loc[timestamp] -= tx.amount_eur - tx.commission_eur
        elif tx.op_type is OpType.DIVIDEND:
            cashflows.loc[timestamp] -= tx.amount_eur
    return twr_index(values, cashflows.reindex(values.index).fillna(0.0))


def _benchmark_goal_history(conn, name, start, end):
    ticker, currency = BENCHMARKS[name]
    dates = pd.date_range(start, end, freq="D")
    history = prices.get_price_history_cached(conn, ticker, start, end)
    values = history["adj_close"].reindex(dates).ffill()
    if currency != "EUR":
        rate = prices.get_fx_history_cached(
            conn, f"EUR{currency}=X", start, end).reindex(dates).ffill()
        values = values / rate
    values = values.dropna()
    if values.empty:
        raise ValueError("storico prezzi non disponibile")
    return values


def _goal_historical_assumptions(conn, txs, instruments):
    histories = {}
    errors = []
    try:
        histories["Portafoglio"] = _portfolio_goal_history(conn, txs, instruments)
    except Exception as e:
        logger.exception("Performance storica del portafoglio non disponibile")
        errors.append(f"Portafoglio: {e}")
    start = min(tx.trade_date for tx in txs)
    end = date.today()
    for name in BENCHMARKS:
        try:
            histories[name] = _benchmark_goal_history(conn, name, start, end)
        except Exception as e:
            logger.exception("Performance storica di %s non disponibile", name)
            errors.append(f"{name}: {e}")
    valid_histories = {}
    for name, values in histories.items():
        try:
            historical_assumptions(values)
        except ValueError as e:
            logger.warning("Performance storica di %s non utilizzabile: %s", name, e)
            errors.append(f"{name}: {e}")
        else:
            valid_histories[name] = values
    if not valid_histories:
        return {}, errors
    common_start = max(values.index.min() for values in valid_histories.values())
    common_end = min(values.index.max() for values in valid_histories.values())
    assumptions = {}
    for name, values in valid_histories.items():
        try:
            assumptions[name] = historical_assumptions(values.loc[common_start:common_end])
        except ValueError as e:
            logger.warning("Periodo comune di %s non utilizzabile: %s", name, e)
            errors.append(f"{name}: {e}")
    return assumptions, errors


def _format_months(months):
    if months is None:
        return "Oltre l'orizzonte"
    years, remaining = divmod(months, 12)
    if years and remaining:
        return f"{years} anni e {remaining} mesi"
    if years:
        return f"{years} anni"
    return f"{remaining} mesi"


def _render_financing_decision(conn, instruments, state, current_values,
                               analysis_txs, average_purchase):
    current_total = sum(current_values.values())
    st.subheader("Finanziare o vendere")
    st.caption("Confronta la vendita dei titoli con prestito personale e mutuo, usando "
               "lo stesso budget mensile.")
    with st.form("financing_simulation"):
        f1, f2, f3 = st.columns(3)
        expense = f1.number_input(
            "Importo della spesa EUR", min_value=1.0, value=50_000.0, step=5_000.0)
        available_cash = f2.number_input(
            "Liquidità già destinata alla spesa EUR", min_value=0.0,
            value=0.0, step=1_000.0)
        monthly_budget = f3.number_input(
            "Budget mensile per rate e investimenti EUR", min_value=0.0,
            value=round(average_purchase, 2), step=100.0)
        net_needed = max(expense - available_cash, 0.0)
        st.caption(f"Somma ancora da coprire: {net_needed:,.2f} €")

        st.markdown("**Vendita dei titoli**")
        s1, s2 = st.columns(2)
        sale_tax_rate_pct = s1.number_input(
            "Aliquota fiscale stimata sulle plusvalenze %",
            min_value=0.0, max_value=100.0, value=26.0, step=1.0)
        sale_commission = s2.number_input(
            "Commissioni di vendita stimate EUR", min_value=0.0,
            value=0.0, step=10.0)

        st.markdown("**Prestito personale**")
        include_loan = st.checkbox("Confronta prestito personale", value=True)
        l1, l2, l3 = st.columns(3)
        loan_amount = l1.number_input(
            "Importo prestito EUR", min_value=0.0,
            value=float(round(net_needed, 2)), step=1_000.0)
        loan_months = int(l2.number_input(
            "Durata prestito (mesi)", min_value=1, max_value=480,
            value=60, step=12))
        loan_tan_pct = l3.number_input(
            "TAN prestito %", min_value=0.0, max_value=100.0,
            value=8.0, step=0.1)
        l4, l5, l6 = st.columns(3)
        loan_taeg_pct = l4.number_input(
            "TAEG prestito %", min_value=0.0, max_value=100.0,
            value=9.0, step=0.1)
        loan_upfront_cost = l5.number_input(
            "Spese iniziali prestito EUR", min_value=0.0,
            value=0.0, step=100.0)
        loan_monthly_cost = l6.number_input(
            "Costi mensili prestito EUR", min_value=0.0,
            value=0.0, step=5.0)

        st.markdown("**Mutuo**")
        include_mortgage = st.checkbox("Confronta mutuo", value=True)
        m1, m2, m3 = st.columns(3)
        mortgage_amount = m1.number_input(
            "Importo mutuo EUR", min_value=0.0,
            value=float(round(net_needed, 2)), step=5_000.0)
        mortgage_years = int(m2.number_input(
            "Durata mutuo (anni)", min_value=1, max_value=40,
            value=20, step=1))
        mortgage_tan_pct = m3.number_input(
            "TAN mutuo %", min_value=0.0, max_value=100.0,
            value=3.5, step=0.1)
        m4, m5, m6 = st.columns(3)
        mortgage_taeg_pct = m4.number_input(
            "TAEG mutuo %", min_value=0.0, max_value=100.0,
            value=4.0, step=0.1)
        mortgage_upfront_cost = m5.number_input(
            "Spese iniziali mutuo EUR", min_value=0.0,
            value=0.0, step=250.0)
        mortgage_monthly_cost = m6.number_input(
            "Costi mensili mutuo EUR", min_value=0.0,
            value=0.0, step=5.0)
        mortgage_tax_benefit = st.number_input(
            "Beneficio fiscale annuo stimato EUR", min_value=0.0,
            value=0.0, step=100.0)

        active_terms = []
        if include_loan:
            active_terms.append(loan_months)
        if include_mortgage:
            active_terms.append(mortgage_years * 12)
        default_horizon = max(active_terms, default=120)
        default_horizon = min(max((default_horizon + 11) // 12, 1), 60)
        h1, h2 = st.columns(2)
        horizon_years = int(h1.number_input(
            "Orizzonte del confronto (anni)", min_value=1,
            max_value=60, value=default_horizon, step=1))
        inflation_pct = h2.number_input(
            "Inflazione annua %", min_value=-20.0, max_value=50.0,
            value=2.0, step=0.5, key="financing_inflation")
        st.caption("La rata è calcolata da TAN e durata. Il TAEG resta visibile come "
                   "riferimento del preventivo; non viene sommato nuovamente ai costi.")
        submitted = st.form_submit_button(
            "Confronta le alternative", type="primary")

    if submitted:
        if net_needed <= 0.0:
            st.error("La liquidità destinata alla spesa copre già tutto l'importo.")
            return
        options = []
        offer_rates = {}
        if include_loan:
            options.append(FinancingOption(
                "Prestito personale", loan_amount, loan_tan_pct / 100.0,
                loan_months, loan_upfront_cost, loan_monthly_cost))
            offer_rates["Prestito personale"] = (loan_tan_pct, loan_taeg_pct)
        if include_mortgage:
            options.append(FinancingOption(
                "Mutuo", mortgage_amount, mortgage_tan_pct / 100.0,
                mortgage_years * 12, mortgage_upfront_cost,
                mortgage_monthly_cost, mortgage_tax_benefit))
            offer_rates["Mutuo"] = (mortgage_tan_pct, mortgage_taeg_pct)
        if not options:
            st.error("Attiva almeno un finanziamento da confrontare con la vendita.")
            return

        cost_basis = {
            isin: state.positions[isin].total_cost_eur
            for isin in current_values if isin in state.positions
        }
        decisions = {}
        with st.spinner("Calcolo performance storiche e alternative…"):
            historical, errors = _goal_historical_assumptions(
                conn, analysis_txs, instruments)
            for name in ["Portafoglio", *BENCHMARKS]:
                if name not in historical:
                    continue
                assumptions = historical[name]
                try:
                    decision = simulate_financing_decision(
                        current_values_eur=current_values,
                        cost_basis_eur=cost_basis,
                        net_needed_eur=net_needed,
                        monthly_budget_eur=monthly_budget,
                        horizon_years=horizon_years,
                        expected_annual_return=assumptions.annual_return,
                        annual_volatility=assumptions.annual_volatility,
                        annual_inflation=inflation_pct / 100.0,
                        financing_options=tuple(options),
                        tax_rate=sale_tax_rate_pct / 100.0,
                        sale_commission_eur=sale_commission,
                        simulations=2000,
                        seed=42,
                    )
                except Exception as e:
                    logger.exception("Confronto finanziario %s non riuscito", name)
                    errors.append(f"{name}: {e}")
                    continue
                decisions[name] = {
                    "decision": decision,
                    "return": assumptions.annual_return,
                    "volatility": assumptions.annual_volatility,
                    "period": (f"{assumptions.start_date:%d/%m/%Y} – "
                               f"{assumptions.end_date:%d/%m/%Y}"),
                }
                for error in decision.errors:
                    logger.warning("Confronto finanziario %s: %s", name, error)
                    errors.append(f"{name}: {error}")
        st.session_state["financing_result"] = {
            "decisions": decisions,
            "errors": list(dict.fromkeys(errors)),
            "offer_rates": offer_rates,
            "current_total": current_total,
            "net_needed": net_needed,
            "monthly_budget": monthly_budget,
        }

    data = st.session_state.get("financing_result")
    if not data:
        return
    if data["errors"]:
        st.warning("Alternative non disponibili:\n\n- " + "\n- ".join(data["errors"]))
    if not data["decisions"]:
        return

    r1, r2, r3 = st.columns(3)
    r1.metric("Portafoglio considerato", f"{data['current_total']:,.0f} €")
    r2.metric("Spesa residua", f"{data['net_needed']:,.0f} €")
    r3.metric("Budget mensile", f"{data['monthly_budget']:,.0f} €")

    summary_rows = []
    detail_rows = []
    for scenario_name, scenario in data["decisions"].items():
        decision = scenario["decision"]
        sale = decision.strategies.get("Vendita titoli")
        for strategy in decision.strategies.values():
            difference = (strategy.median_net_worth_eur - sale.median_net_worth_eur
                          if sale is not None else None)
            probability = strategy.probability_beats_sale
            summary_rows.append({
                "Scenario": scenario_name,
                "Strategia": strategy.name,
                "Uscita mensile": f"{strategy.monthly_outflow_eur:,.0f} €",
                "Patrimonio mediano": f"{strategy.median_net_worth_eur:,.0f} €",
                "Differenza dalla vendita": (
                    f"{difference:+,.0f} €" if difference is not None else "n.d."),
                "Probabilità migliore": (
                    f"{probability * 100:.1f}%" if probability is not None else "n.d."),
                "Scenario sfavorevole": f"{strategy.p10_net_worth_eur:,.0f} €",
                "Debito residuo": f"{strategy.residual_debt_eur:,.0f} €",
            })
            tan, taeg = data["offer_rates"].get(strategy.name, (None, None))
            detail_rows.append({
                "Scenario": scenario_name,
                "Strategia": strategy.name,
                "Rendimento storico": f"{scenario['return'] * 100:.1f}%",
                "Volatilità": f"{scenario['volatility'] * 100:.1f}%",
                "Periodo": scenario["period"],
                "TAN": f"{tan:.2f}%" if tan is not None else "—",
                "TAEG dichiarato": f"{taeg:.2f}%" if taeg is not None else "—",
                "Rata": f"{strategy.monthly_payment_eur:,.2f} €",
                "Costi finanziamento netti": f"{strategy.financing_cost_eur:,.0f} €",
                "Titoli venduti": f"{strategy.gross_sale_eur:,.0f} €",
                "Imposte vendita stimate": f"{strategy.estimated_sale_tax_eur:,.0f} €",
                "Mediana in euro di oggi": f"{strategy.median_real_net_worth_eur:,.0f} €",
                "Rendimento di pareggio": (
                    f"{strategy.break_even_annual_return * 100:.2f}%"
                    if strategy.break_even_annual_return is not None else "n.d."),
            })
    st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)

    chart_columns = st.columns(len(data["decisions"]))
    colors = {
        "Vendita titoli": "#d62728",
        "Prestito personale": "#1f77b4",
        "Mutuo": "#2ca02c",
    }
    for column, (scenario_name, scenario) in zip(
            chart_columns, data["decisions"].items()):
        decision = scenario["decision"]
        years_axis = [month / 12.0 for month in decision.months]
        fig = go.Figure()
        for strategy in decision.strategies.values():
            fig.add_scatter(
                x=years_axis, y=strategy.median_path_eur,
                name=strategy.name,
                line=dict(color=colors.get(strategy.name)))
        fig.update_layout(
            title=scenario_name, xaxis_title="Anni", yaxis_title="Patrimonio netto EUR",
            height=360, legend=dict(orientation="h"))
        column.plotly_chart(fig, width="stretch")

    with st.expander("Dettagli del confronto"):
        st.dataframe(pd.DataFrame(detail_rows), width="stretch", hide_index=True)
        st.caption("La vendita è proporzionale alle posizioni considerate. La fiscalità è "
                   "una stima sulle plusvalenze positive e non applica compensazioni. Il "
                   "beneficio fiscale del mutuo è usato solo se inserito manualmente.")
    st.caption("Le probabilità derivano da simulazioni basate sulle performance storiche in "
               "EUR. Non sono previsioni né garanzie di rendimento.")


def page_simulation(conn):
    st.header("Simulazione")
    render_currency_simulation()
    st.divider()
    st.caption("Scenari ipotetici sul portafoglio titoli: non sono previsioni né garanzie di "
               "rendimento. Liquidità, stipendi, depositi e prelievi del conto non sono inclusi.")
    try:
        instruments, state, current_values, unpriced = _planning_portfolio(conn)
    except ValueError as e:
        st.error(str(e))
        return
    excluded = {isin for isin, inst in instruments.items() if inst.excluded}
    analysis_txs = [tx for tx in store.get_transactions(conn) if tx.isin not in excluded]
    average_purchase = average_monthly_purchases(
        analysis_txs, as_of=date.today())
    if unpriced:
        st.warning("Escluse perché senza prezzo recente: " + ", ".join(
            instruments[isin].name for isin in unpriced))
    current_total = sum(current_values.values())

    goal_section = st.container()
    st.divider()
    financing_section = st.container()
    st.divider()
    stress_section = st.container()
    with stress_section:
        st.subheader("Stress test")
        custom_tab, historical_tab = st.tabs(["Shock personalizzato", "Replay storico"])
        with custom_tab:
            presets = {
                "Personalizzato": 0.0,
                "Correzione uniforme -10%": -10.0,
                "Ribasso uniforme -20%": -20.0,
                "Stress uniforme -35%": -35.0,
            }
            preset = st.selectbox("Scenario rapido", list(presets))
            shock_rows = pd.DataFrame([
                {"ISIN": isin, "Nome": instruments[isin].name,
                 "Valore attuale EUR": round(value, 2), "Shock %": presets[preset]}
                for isin, value in sorted(
                    current_values.items(), key=lambda item: instruments[item[0]].name)
            ])
            edited = st.data_editor(
                shock_rows,
                width="stretch",
                hide_index=True,
                disabled=["ISIN", "Nome", "Valore attuale EUR"],
                column_config={
                    "ISIN": None,
                    "Shock %": st.column_config.NumberColumn(
                        "Shock %", min_value=-100.0, max_value=200.0, step=1.0,
                        format="%.1f"),
                },
                key=f"stress_editor_{preset}",
            )
            shocks = {row["ISIN"]: float(row["Shock %"]) / 100.0
                      for _, row in edited.iterrows()}
            try:
                _render_stress_result(stress_portfolio(current_values, shocks), instruments)
            except ValueError as e:
                st.error(str(e))

        with historical_tab:
            st.caption("Applica al valore attuale il rendimento total-return in EUR osservato "
                       "per ciascuno strumento nel periodo selezionato.")
            h1, h2 = st.columns(2)
            start = h1.date_input(
                "Inizio periodo", value=date.today() - timedelta(days=365),
                max_value=date.today(), key="stress_history_start")
            end = h2.date_input(
                "Fine periodo", value=date.today(), max_value=date.today(),
                key="stress_history_end")
            if st.button("Calcola replay storico"):
                if start >= end:
                    st.error("La data iniziale deve precedere la data finale.")
                else:
                    try:
                        with st.spinner("Carico lo storico del periodo…"):
                            dates = pd.date_range(start, end, freq="D")
                            _close, adjusted_eur, _fx = _eur_price_frame(
                                conn, instruments, list(current_values), dates)
                        historical_returns = {}
                        for isin in current_values:
                            series = (adjusted_eur[isin].dropna()
                                      if isin in adjusted_eur else pd.Series(dtype=float))
                            if len(series) >= 2 and series.iloc[0] > 0.0:
                                historical_returns[isin] = float(
                                    series.iloc[-1] / series.iloc[0] - 1.0)
                        result = stress_portfolio(current_values, historical_returns)
                    except Exception as e:
                        logger.exception("Replay storico non riuscito")
                        st.error(f"Replay storico non riuscito: {e}")
                    else:
                        _render_stress_result(result, instruments)

    with goal_section:
        st.subheader("Obiettivo capitale")
        summary_1, summary_2 = st.columns(2)
        summary_1.metric("Valore corrente dei titoli", f"{current_total:,.0f} €")
        summary_2.metric(
            "Media acquisti mensile (12 mesi)", f"{average_purchase:,.2f} €")
        st.caption("Media sui 12 mesi completi precedenti: commissioni incluse; "
                   "vendite e dividendi esclusi. È una stima degli acquisti, non dei "
                   "bonifici effettuati sul conto.")
        with st.form("goal_simulation"):
            g1, g2 = st.columns(2)
            target = g1.number_input(
                "Obiettivo EUR", min_value=1_000.0, value=1_000_000.0, step=50_000.0)
            contribution = g2.number_input(
                "Versamento mensile EUR", min_value=0.0,
                value=round(average_purchase, 2), step=100.0)
            g3, g4, g5 = st.columns(3)
            expected_return_pct = g3.number_input(
                "Scenario personalizzato — rendimento annuo %",
                min_value=-99.0, max_value=100.0,
                value=6.0, step=0.5)
            volatility_pct = g4.number_input(
                "Scenario personalizzato — volatilità annua %",
                min_value=0.0, max_value=200.0,
                value=15.0, step=1.0)
            inflation_pct = g5.number_input(
                "Inflazione annua %", min_value=-20.0, max_value=50.0,
                value=2.0, step=0.5)
            horizon = st.slider("Orizzonte massimo (anni)", 5, 60, 40)
            real_target = st.checkbox(
                "Mantieni l'obiettivo nel valore di oggi (cresce con l'inflazione)", value=False)
            submitted = st.form_submit_button("Esegui simulazione", type="primary")

        if submitted:
            expected_return = expected_return_pct / 100.0
            volatility = volatility_pct / 100.0
            inflation = inflation_pct / 100.0
            scenario_inputs = {
                "Personalizzato": {
                    "annual_return": expected_return,
                    "annual_volatility": volatility,
                    "period": "Valori manuali",
                },
            }
            with st.spinner("Calcolo le performance storiche e le simulazioni…"):
                historical, history_errors = _goal_historical_assumptions(
                    conn, analysis_txs, instruments)
                for name, assumptions in historical.items():
                    scenario_inputs[name] = {
                        "annual_return": assumptions.annual_return,
                        "annual_volatility": assumptions.annual_volatility,
                        "period": (f"{assumptions.start_date:%d/%m/%Y} – "
                                   f"{assumptions.end_date:%d/%m/%Y}"),
                    }
                scenarios = {}
                for name, scenario in scenario_inputs.items():
                    try:
                        central_months = months_to_target(
                            current_total, contribution, target,
                            scenario["annual_return"], inflation,
                            real_target, horizon * 12)
                        result = simulate_goal(
                            current_total, contribution, target,
                            scenario["annual_return"], scenario["annual_volatility"],
                            inflation, horizon, simulations=2000, seed=42,
                            target_in_today_euros=real_target)
                    except ValueError as e:
                        logger.warning("Simulazione %s non disponibile: %s", name, e)
                        history_errors.append(f"{name}: {e}")
                        continue
                    scenarios[name] = {
                        **scenario,
                        "result": result,
                        "central_months": central_months,
                    }
            if scenarios:
                st.session_state["goal_result"] = {
                    "scenarios": scenarios,
                    "errors": history_errors,
                    "target": target,
                    "contribution": contribution,
                    "inflation": inflation,
                    "horizon": horizon,
                    "real_target": real_target,
                    "initial": current_total,
                }

        goal_data = st.session_state.get("goal_result")
        if goal_data and "scenarios" in goal_data:
            if goal_data["errors"]:
                st.warning("Scenari storici non disponibili:\n\n- "
                           + "\n- ".join(goal_data["errors"]))
            scenarios = goal_data["scenarios"]
            order = ["Personalizzato", "Portafoglio", *BENCHMARKS]
            ordered = [(name, scenarios[name]) for name in order if name in scenarios]
            months = goal_data["horizon"] * 12
            contributed = goal_data["initial"] + goal_data["contribution"] * months
            st.metric("Capitale iniziale + versamenti", f"{contributed:,.0f} €")
            real_factor = (1.0 + goal_data["inflation"]) ** goal_data["horizon"]
            st.dataframe(pd.DataFrame([
                {
                    "Scenario": name,
                    "Rendimento annuo": f"{scenario['annual_return'] * 100:.1f}%",
                    "Volatilità annua": f"{scenario['annual_volatility'] * 100:.1f}%",
                    "Periodo": scenario["period"],
                    "Stima centrale": _format_months(scenario["central_months"]),
                    "Mediana": _format_months(scenario["result"].median_goal_month),
                    "Probabilità": f"{scenario['result'].success_probability * 100:.1f}%",
                    "Tempo favorevole": _format_months(scenario["result"].p10_goal_month),
                    "Tempo prudente": _format_months(scenario["result"].p90_goal_month),
                    "Capitale finale mediano":
                        f"{scenario['result'].median_values_eur[-1]:,.0f} €",
                    "Finale in euro di oggi":
                        f"{scenario['result'].median_values_eur[-1] / real_factor:,.0f} €",
                }
                for name, scenario in ordered
            ]), width="stretch", hide_index=True)

            first_result = ordered[0][1]["result"]
            years_axis = [month / 12.0 for month in first_result.months]
            target_curve = [
                goal_data["target"] * (1.0 + goal_data["inflation"]) ** year
                if goal_data["real_target"] else goal_data["target"]
                for year in years_axis
            ]
            fig = go.Figure()
            manual = scenarios.get("Personalizzato")
            if manual:
                fig.add_scatter(
                    x=years_axis, y=manual["result"].p90_values_eur,
                    line=dict(width=0), showlegend=False)
                fig.add_scatter(
                    x=years_axis, y=manual["result"].p10_values_eur,
                    name="Fascia personalizzata 10°–90°", fill="tonexty",
                    fillcolor="rgba(112,109,218,0.16)", line=dict(width=0))
            colors = {
                "Personalizzato": "#706dda",
                "Portafoglio": "#1f77b4",
                "S&P 500": "#2ca02c",
                "MSCI World": "#ff7f0e",
            }
            for name, scenario in ordered:
                fig.add_scatter(
                    x=years_axis, y=scenario["result"].median_values_eur,
                    name=name, line=dict(color=colors[name]))
            fig.add_scatter(
                x=years_axis, y=target_curve, name="Obiettivo",
                line=dict(color="#d62728", dash="dash"))
            fig.update_layout(
                title="Confronto delle proiezioni del capitale", xaxis_title="Anni",
                yaxis_title="EUR")
            st.plotly_chart(fig, width="stretch")
            st.caption("Portafoglio e benchmark usano performance storiche in EUR sul periodo "
                       "comune indicato in tabella. Sono scenari basati sul passato, non "
                       "previsioni o garanzie di rendimento.")

    with financing_section:
        _render_financing_decision(
            conn, instruments, state, current_values, analysis_txs, average_purchase)


def main():
    st.set_page_config(page_title="Soldoni", layout="wide")
    conn = get_conn()
    with st.sidebar:
        page = option_menu(
            "Soldoni",
            ["Dashboard", "Plus/minusvalenze", "Ribilanciamento", "Simulazione",
             "Analizzatore", "Scopri", "Import & Anagrafica"],
            icons=["speedometer2", "cash-coin", "pie-chart", "calculator", "graph-up", "compass",
                   "upload"],
            menu_icon="cash-coin",
            default_index=0,
        )
    if page == "Dashboard":
        page_dashboard(conn)
    elif page == "Plus/minusvalenze":
        page_capital_gains(conn)
    elif page == "Ribilanciamento":
        page_rebalancing(conn)
    elif page == "Simulazione":
        page_simulation(conn)
    elif page == "Analizzatore":
        page_analyzer(conn)
    elif page == "Scopri":
        page_discover(conn)
    else:
        page_import(conn)


if __name__ == "__main__":
    main()
