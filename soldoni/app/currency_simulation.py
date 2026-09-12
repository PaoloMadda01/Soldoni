"""Manual EUR/USD scenarios for the Simulazione page."""

import logging

import plotly.graph_objects as go
import streamlit as st

from soldoni.core.currency import simulate_currency

logger = logging.getLogger(__name__)


def _number(value: float, decimals: int = 2) -> str:
    if abs(value) < 0.5 * 10 ** -decimals:
        value = 0.0
    return f"{value:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def render_currency_simulation() -> None:
    """Show an independent, manual scenario with returns measured in USD."""
    st.subheader("Quanto pesa il cambio?")
    st.write("Scopri come un rendimento in dollari diventa un guadagno o una perdita "
             "in euro. Modifica i valori: risultati e grafico si aggiornano subito.")
    st.caption("Simulazione manuale senza copertura valutaria, costi, imposte o versamenti "
               "intermedi. I valori iniziali sono un esempio, non il cambio attuale.")

    left, right = st.columns(2)
    initial_eur = left.number_input(
        "Capitale iniziale (€)", min_value=0.01, value=10_000.0, step=1_000.0,
        key="currency_initial_eur")
    usd_return_pct = right.number_input(
        "Rendimento dell'investimento in dollari (%)", min_value=-100.0,
        value=10.0, step=1.0, key="currency_usd_return",
        help="Rendimento complessivo del periodo scelto, non annuo. "
             "Deve essere espresso in USD: un rendimento già in EUR include il cambio.")
    left, right = st.columns(2)
    initial_fx = left.number_input(
        "Cambio iniziale: 1 euro = quanti dollari?", min_value=0.0001,
        value=1.10, step=0.01, format="%.4f", key="currency_initial_fx")
    final_fx = right.number_input(
        "Cambio finale: 1 euro = quanti dollari?", min_value=0.0001,
        value=1.21, step=0.01, format="%.4f", key="currency_final_fx")
    st.caption("Se questo numero sale, l'euro si rafforza e gli stessi dollari valgono "
               "meno euro. Se scende, l'euro si indebolisce e valgono più euro.")

    try:
        result = simulate_currency(initial_eur, usd_return_pct / 100.0, initial_fx, final_fx)
        rates = [initial_fx, final_fx]
        if result.break_even_eur_usd is not None:
            rates.append(result.break_even_eur_usd)
        lower, upper = min(rates) * 0.8, max(rates) * 1.2
        rates = sorted(set(rates + [lower + (upper - lower) * i / 80 for i in range(81)]))
        curve = [simulate_currency(
            initial_eur, usd_return_pct / 100.0, initial_fx, rate).final_value_eur
            for rate in rates]
    except ValueError as e:
        logger.warning("Simulazione del cambio non disponibile: %s", e)
        st.error(str(e))
        return

    first, second, third = st.columns(3)
    first.metric("Valore finale in euro", f"{_number(result.final_value_eur)} €")
    second.metric("Guadagno / perdita in euro", f"{_number(result.total_gain_eur)} €")
    third.metric("Rendimento in euro", f"{_number(result.total_return * 100)}%")
    st.dataframe([
        {"Voce": "Guadagno / perdita a cambio invariato", "Importo EUR": result.market_gain_eur},
        {"Voce": "Effetto del cambio rispetto al cambio iniziale", "Importo EUR": result.fx_impact_eur},
        {"Voce": "Guadagno / perdita finale", "Importo EUR": result.total_gain_eur},
    ], hide_index=True, width="stretch", column_config={
        "Importo EUR": st.column_config.NumberColumn("Importo EUR", format="%.2f €"),
    })
    if abs(result.fx_impact_eur) < 0.005:
        explanation = "Il cambio non modifica il risultato in euro al centesimo."
    else:
        direction = "ridotto" if result.fx_impact_eur < 0.0 else "aumentato"
        explanation = (f"Il movimento del cambio ha {direction} il risultato di "
                       f"{_number(abs(result.fx_impact_eur))} €.")
    st.info(f"A cambio invariato il valore finale sarebbe "
            f"{_number(result.constant_fx_value_eur)} €. {explanation} "
            f"Il guadagno / perdita finale è {_number(result.total_gain_eur)} €.")

    fig = go.Figure()
    fig.add_scatter(x=rates, y=curve, name="Valore finale in euro", mode="lines",
                    line=dict(color="#1f77b4"),
                    hovertemplate="1 € = %{x:.4f} $<br>Valore finale: %{y:,.2f} €<extra></extra>")
    fig.add_hline(y=initial_eur, line_dash="dash", line_color="gray",
                  annotation_text="Capitale iniziale")
    if result.break_even_eur_usd is not None:
        break_even = result.break_even_eur_usd
        fig.add_scatter(x=[break_even], y=[initial_eur], name="Pareggio",
                        mode="markers", marker=dict(size=12, symbol="diamond", color="#2ca02c"))
        st.write(f"**Cambio di pareggio: 1 euro = {_number(break_even, 4)} dollari.** "
                 "Con il rendimento in USD inserito, sotto questo cambio guadagni in euro; "
                 "sopra questo cambio perdi.")
    else:
        st.info("Con una perdita del 100% in dollari il capitale finale è zero: "
                "nessun cambio positivo permette di tornare in pareggio.")
    fig.add_scatter(x=[final_fx], y=[result.final_value_eur], name="Scenario scelto",
                    mode="markers", marker=dict(size=12, symbol="x", color="#ff7f0e"))
    fig.update_layout(
        title="Come cambia il valore finale al variare del cambio",
        xaxis_title="Cambio finale: dollari per 1 euro", yaxis_title="Valore finale (€)",
        separators=",.", legend=dict(orientation="h"), height=380)
    st.plotly_chart(fig, width="stretch", key="currency_scenario_chart")
    st.caption("Il grafico mantiene fisso il rendimento in dollari e modifica soltanto "
               "il cambio finale. È una relazione matematica, non una previsione.")

    with st.expander("ETF: quotazione, valuta del fondo e rischio cambio"):
        st.markdown(
            "- **Valuta di quotazione:** quella con cui compri e vendi la quota. "
            "Comprare in euro non elimina automaticamente il rischio dollaro.\n"
            "- **Valuta del fondo:** quella usata per esprimere il valore del fondo. "
            "La scritta USD nel nome non significa che tutti i titoli siano in dollari.\n"
            "- **Valute dei titoli contenuti:** un ETF globale può includerne diverse. "
            "Questo calcolo converte un rendimento complessivo da USD a EUR; "
            "non ricostruisce le singole esposizioni valutarie.\n"
            "- **EUR Hedged:** la copertura cerca di ridurre il rischio cambio, "
            "con costi ed eventuali effetti residui. Questo simulatore non modella "
            "una classe coperta."
        )
        st.warning("Se il rendimento dell'ETF è già espresso in euro, il cambio è già "
                   "incluso: non inserirlo come rendimento in dollari.")
        st.caption("La sezione Diversificazione & valuta della Dashboard usa la valuta "
                   "di quotazione: per un ETF quotato in euro non separa il cambio "
                   "già incorporato nel prezzo.")
        st.markdown(
            "Approfondimenti: [valute degli ETF — justETF]"
            "(https://www.justetf.com/en/news/etf/the-effect-of-currencies-on-etfs.html), "
            "[copertura valutaria — iShares]"
            "(https://www.blackrock.com/au/education/ishares/what-is-currency-hedging)."
        )
    with st.expander("Come viene calcolato"):
        st.latex(r"V_{EUR} = C_{EUR} \times (1 + r_{USD}) \times \frac{c_0}{c_1}")
        st.caption("C è il capitale iniziale; r è il rendimento in dollari (10% = 0,10); "
                   "c₀ e c₁ sono i cambi iniziale e finale, entrambi in dollari per 1 euro. "
                   "L'effetto del cambio è la differenza rispetto al valore finale "
                   "calcolato mantenendo il cambio iniziale.")
