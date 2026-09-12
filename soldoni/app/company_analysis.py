"""Valutazione per azione nella scheda azienda."""

import logging
import math
from typing import Callable

import pandas as pd
import streamlit as st

from soldoni.core import company_valuation as valuation
from soldoni.core.cash_flow import latest_cash_flow_period, summarize_cash_flow
from soldoni.data.fundamentals import Fundamentals

logger = logging.getLogger(__name__)


def _fmt(value):
    return f"{value:,.2f}" if value is not None and math.isfinite(value) else "n/d"


def _render_cash_flow(fund, period):
    st.subheader("Cash flow dell'azienda")
    st.caption(f"{period.label} · Valuta di bilancio: {fund.financial_currency or 'n/d'} · "
               "Fonte: Yahoo Finance. Importi totali dell'azienda.")
    if period.notice:
        st.caption(period.notice)
    metrics = summarize_cash_flow(period.values, fund.market_cap,
                                  fund.financial_currency, fund.currency)
    for reason in dict.fromkeys(metric.reason for metric in metrics.values() if metric.reason):
        logger.warning("Cash flow %s: %s", fund.ticker, reason)
    cols = st.columns(3)
    for col, key, label in zip(cols, ("operating_cashflow", "capex", "free_cashflow"),
                               ("Cash flow operativo", "Investimenti (CapEx)", "Free cash flow")):
        col.metric(label, _fmt(metrics[key].value))
        if metrics[key].reason:
            col.caption(metrics[key].reason)
    st.caption("FCF = cash flow operativo − investimenti. CapEx e dividendi sono mostrati "
               "come uscite positive. Tutti i flussi si riferiscono allo stesso periodo.")
    if metrics["free_cashflow"].value is not None and metrics["free_cashflow"].value < 0:
        st.warning("Free cash flow negativo nel periodo: il cash flow operativo non copre gli investimenti.")
    rows = []
    for key, label, formula, percent in (
        ("fcf_margin", "Margine FCF", "FCF / ricavi", True),
        ("cash_conversion", "Conversione utili in cassa", "Cash flow operativo / utile netto", False),
        ("fcf_yield", "FCF yield", "FCF / capitalizzazione attuale", True),
        ("dividend_coverage", "Copertura dividendi", "FCF / dividendi pagati", False),
    ):
        metric = metrics[key]
        value = "n/d" if metric.value is None else (
            f"{metric.value * 100:.2f}%" if percent else f"{metric.value:.2f}x")
        rows.append({"Indicatore": label, "Valore": value, "Formula": formula,
                     "Esito": metric.reason or "Calcolato"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(f"Dividendi pagati nel periodo: {_fmt(metrics['dividends_paid'].value)} · "
               f"Capitalizzazione attuale ({fund.currency or 'n/d'}): {_fmt(fund.market_cap)}.")
    st.caption("Conversione utili: 1x significa cassa operativa pari all'utile netto. "
               "Copertura dividendi: sotto 1x il FCF del periodo non copre i dividendi pagati. "
               "FCF yield confronta il flusso del periodo con il valore di mercato attuale.")


def _render_formulas():
    with st.expander("Formule e limiti dei modelli"):
        st.markdown("**Gordon** — dividendi con crescita costante e rendimento r maggiore di g.")
        st.latex(r"V_G = \frac{D_0(1+g)}{r-g}")
        st.markdown("**DDM a due fasi** — crescita iniziale dei dividendi, poi crescita perpetua.")
        st.latex(r"V_{DDM}=\sum_{t=1}^{n}\frac{D_0(1+g_D)^t}{(1+r)^t}"
                 r"+\frac{D_0(1+g_D)^n(1+g)}{(r-g)(1+r)^n}")
        st.markdown("**Graham** — riferimento storico basato su P/E 15 e P/B 1,5; "
                    "richiede EPS e patrimonio per azione positivi. Il patrimonio contabile "
                    "può rappresentare poco le aziende con molti beni immateriali.")
        st.latex(r"V_{Graham}=\sqrt{22.5\,EPS\,BVPS}")
        st.markdown("**P/E obiettivo** — multiplo scelto dall'utente applicato agli utili "
                    "degli ultimi 12 mesi; richiede utili positivi.")
        st.latex(r"V_{PE}=EPS_{TTM}\,(P/E)_{obiettivo}")
        st.markdown("**DCF (FCFE)** — flussi disponibili agli azionisti, con numero di azioni "
                    "costante. Il debito è già incluso attraverso emissioni e rimborsi. "
                    "Questo modello a crescita proporzionale richiede FCFE iniziale positivo. "
                    "La base azionaria è confrontata con azioni equivalenti e capitalizzazione "
                    "disponibili, con tolleranza dell'1% per arrotondamenti e disallineamenti.")
        st.latex(r"FCFE_0=CFO_0-|CapEx_0|+Debito\ emesso_0-Debito\ rimborsato_0")
        st.latex(r"V_{DCF}=\frac{1}{N}\left[\sum_{t=1}^{n}"
                 r"\frac{FCFE_0(1+g_F)^t}{(1+r)^t}"
                 r"+\frac{FCFE_0(1+g_F)^n(1+g)}{(r-g)(1+r)^n}\right]")
        st.markdown("**Gordon inverso** — crescita dei dividendi implicita nel prezzo P, "
                    "dato il rendimento richiesto; non è una previsione della crescita.")
        st.latex(r"g_{implicita}=\frac{P\,r-D_0}{P+D_0}")
        st.markdown("**Margine di sicurezza** — sconto m applicato a ciascuna stima.")
        st.latex(r"P_{soglia}=V(1-m),\qquad Scostamento=\left(\frac{V}{P}-1\right)100")
        st.caption("D₀: dividendo annuo ultimi 12 mesi; EPS: utile per azione; BVPS: patrimonio "
                   "contabile per azione; N: azioni in circolazione; r: rendimento richiesto; "
                   "g: crescita perpetua; gD/gF: crescita iniziale dividendi/FCFE; n: anni.")
        st.caption("Riferimenti: [dividendi e Gordon](https://www.cfainstitute.org/insights/"
                   "professional-learning/refresher-readings/2026/discounted-dividend-valuation), "
                   "[FCFE](https://www.cfainstitute.org/insights/professional-learning/"
                   "refresher-readings/2026/free-cash-flow-valuation).")


def render_valuation_assumptions(key_suffix: str, title: str = "Ipotesi di valutazione") -> valuation.ValuationAssumptions:
    """Raccoglie le ipotesi per una scheda o per tutte le aziende del confronto."""
    with st.expander(title, expanded=True):
        left, right = st.columns(2)
        rate = left.number_input("Rendimento richiesto (%)", min_value=0.1, max_value=50.0,
                                 value=10.0, step=0.5, key=f"valuation_return_{key_suffix}") / 100
        terminal = right.number_input("Crescita perpetua (%)", min_value=-10.0, max_value=15.0,
                                      value=2.0, step=0.5, key=f"valuation_terminal_{key_suffix}") / 100
        dividend_growth = left.number_input(
            "Crescita iniziale dividendi (%)", min_value=-50.0, max_value=50.0,
            value=5.0, step=0.5, key=f"valuation_dividend_growth_{key_suffix}") / 100
        fcfe_growth = right.number_input(
            "Crescita iniziale FCFE (%)", min_value=-50.0, max_value=50.0,
            value=5.0, step=0.5, key=f"valuation_fcfe_growth_{key_suffix}") / 100
        years = left.number_input("Anni di crescita iniziale", min_value=1, max_value=30,
                                  value=5, key=f"valuation_years_{key_suffix}")
        multiple = right.number_input("P/E obiettivo", min_value=1.0, max_value=100.0,
                                       value=15.0, step=0.5, key=f"valuation_pe_{key_suffix}")
        margin = left.number_input("Margine di sicurezza (%)", min_value=0.0, max_value=90.0,
                                   value=20.0, step=5.0, key=f"valuation_margin_{key_suffix}") / 100
    return valuation.ValuationAssumptions(rate, terminal, dividend_growth, fcfe_growth,
                                          years, multiple, margin)


def render_company_analysis(fund: Fundamentals,
                            load_financials: Callable[[str, str], pd.DataFrame]) -> None:
    """Mostra modelli indipendenti, ipotesi e dati di bilancio per sole azioni."""
    if fund.quote_type != "EQUITY":
        return
    st.subheader("Valutazione dell'azienda")
    st.caption("Stime per azione basate sulle ipotesi qui sotto. I valori iniziali sono "
               "esempi modificabili, non previsioni specifiche dell'azienda.")
    assumptions = render_valuation_assumptions(fund.ticker)
    statements = {}
    for frequency, label in (("annual", "annuale"), ("quarterly", "trimestrale")):
        try:
            statements[frequency] = load_financials(fund.ticker, frequency)
        except Exception as e:
            logger.exception("Bilancio %s per valutazione non disponibile: %s", label, fund.ticker)
            st.warning(f"Bilancio {label} per DCF e cash flow non disponibile: {e}")
            statements[frequency] = pd.DataFrame()
    period = latest_cash_flow_period(statements["annual"], statements["quarterly"])
    result = valuation.evaluate_company(fund, period, assumptions)
    if result.currency_issue:
        st.info(result.currency_issue)
    st.caption(f"Fonte: Yahoo Finance · Quotazione: {fund.currency or 'n/d'} · "
               f"Bilancio: {fund.financial_currency or 'n/d'} · {period.label}.")
    st.caption(f"Dati per azione: prezzo {_fmt(fund.price)}; dividendo ultimi 12 mesi "
               f"{_fmt(fund.annual_dividend)}; EPS trailing {_fmt(fund.trailing_eps)}; "
               f"valore contabile {_fmt(fund.book_value)}. FCFE totale: {_fmt(result.fcfe.value)}; "
               f"azioni in circolazione: {_fmt(fund.shares_outstanding)}; "
               f"azioni equivalenti: {_fmt(fund.implied_shares_outstanding)}.")
    rows = [{"Modello": name, "Valore stimato": estimate.value,
             "Scostamento %": estimate.upside, "Prezzo con margine": estimate.safety_price,
             "Esito": estimate.reason or "Calcolato"}
            for name, estimate in result.models.items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        name: st.column_config.NumberColumn(format="%.2f")
        for name in ("Valore stimato", "Scostamento %", "Prezzo con margine")})
    st.caption(f"Importi per azione in {fund.currency or 'valuta non disponibile'}. "
               "Scostamento positivo: stima superiore al prezzo. Il prezzo con margine "
               "applica lo sconto scelto alla stima; non è un rendimento garantito.")
    if fund.price is None or not math.isfinite(fund.price) or fund.price <= 0:
        st.info("Prezzo attuale non disponibile: scostamenti e crescita implicita non calcolabili.")
    implied = result.implied_growth
    st.metric("Crescita dividendi implicita nel prezzo",
              f"{implied.value * 100:.2f}%" if implied.value is not None else "n/d")
    if implied.reason:
        st.caption(implied.reason)
    with st.expander("Scenari prudente, base e ottimista", expanded=False):
        st.caption("Sensibilità alle ipotesi: rendimento ±2 punti, crescita perpetua ±1 punto, "
                   "crescita iniziale ±2 punti. Le etichette indicano scenari ipotetici, "
                   "non probabilità. Graham e P/E restano nella tabella principale.")
        scenarios = []
        for label in ("Prudente", "Base", "Ottimista"):
            a = valuation.scenario_assumptions(assumptions, label)
            estimates = valuation.evaluate_company(fund, period, a).models
            scenario = {"Scenario": label, "Rendimento %": a.required_return * 100,
                        "Crescita perpetua %": a.terminal_growth * 100,
                        "Crescita dividendi %": a.dividend_growth * 100,
                        "Crescita FCFE %": a.fcfe_growth * 100}
            issues = []
            for name, model in (("Gordon", "Gordon"), ("DDM", "DDM a due fasi"),
                                ("DCF", "DCF (FCFE)")):
                estimate = estimates[model]
                scenario[name] = estimate.value
                if estimate.reason:
                    issues.append(f"{name}: {estimate.reason}")
            scenario["Esito"] = " · ".join(issues) or "Calcolato"
            scenarios.append(scenario)
        st.dataframe(pd.DataFrame(scenarios), hide_index=True, width="stretch")
    _render_formulas()
    _render_cash_flow(fund, period)
