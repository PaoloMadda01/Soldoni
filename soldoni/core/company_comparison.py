"""Indicatori e storici aziendali, con unità e periodi espliciti."""

from dataclasses import dataclass, field
import math
from numbers import Real

import pandas as pd

from soldoni.core.cash_flow import latest_cash_flow_period, summarize_cash_flow
from soldoni.core.company_valuation import ValuationAssumptions, evaluate_company
from soldoni.core.financial_trends import cagr
from soldoni.core.scoring import ScoreResult
from soldoni.core.screen_metrics import price_metrics
from soldoni.data.fundamentals import Fundamentals


GROUPS = ("Riepilogo", "Fondamentali", "Cash flow e dividendi", "Valutazioni",
          "Analisti", "Mercato", "Bilanci")
FINANCIAL_FIELDS = {
    "revenue": "Ricavi", "net_income": "Utile netto", "operating_income": "Utile operativo",
    "eps": "EPS", "operating_cashflow": "Cash flow operativo", "capex": "CapEx",
    "free_cashflow": "Free cash flow di bilancio", "net_borrowing": "Indebitamento netto",
    "dividends_paid": "Dividendi pagati",
}
MARGINS = {"net_margin": ("Margine netto", "net_income"),
           "operating_margin": ("Margine operativo", "operating_income"),
           "fcf_margin": ("Margine FCF", "free_cashflow")}
HISTORY_FIELDS = {"price": "Prezzo", "drawdown": "Drawdown %", "pe": "P/E storico",
                  **FINANCIAL_FIELDS, **{key: label + " %" for key, (label, _) in MARGINS.items()}}


@dataclass
class CompanySnapshot:
    ticker: str
    fund: Fundamentals | None = None
    score: ScoreResult | None = None
    close: pd.Series = field(default_factory=lambda: pd.Series(dtype=float, index=pd.DatetimeIndex([])))
    extras: dict = field(default_factory=dict)
    annual: pd.DataFrame = field(default_factory=pd.DataFrame)
    quarterly: pd.DataFrame = field(default_factory=pd.DataFrame)
    issues: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.fund.name} ({self.ticker})" if self.fund and self.fund.name else self.ticker


@dataclass(frozen=True)
class ComparisonMetric:
    value: float | str | None
    unit: str = ""
    reason: str = ""

    def display(self) -> str:
        """Formatta le frazioni in percentuale e mantiene la valuta degli importi."""
        if self.value is None:
            return "n/d"
        if isinstance(self.value, str):
            return self.value
        if self.unit == "%":
            return f"{self.value * 100:.2f}%"
        if self.unit == "x":
            return f"{self.value:.2f}x"
        return f"{self.value:,.2f}{' ' + self.unit if self.unit else ''}"


def _metric(value, unit="", reason=""):
    if value is None or (not isinstance(value, str) and (
            not isinstance(value, Real) or not math.isfinite(value))):
        return ComparisonMetric(None, unit, reason or "Dato assente o non finito nella fonte.")
    return ComparisonMetric(value, unit)


def _series(frame, key):
    if frame.empty or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans or not frame.index.is_unique:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    frame = frame.sort_index()
    if key in MARGINS:
        numerator = _series(frame, MARGINS[key][1])
        revenue = _series(frame, "revenue")
        return numerator.div(revenue.where(revenue > 0)) * 100
    if key not in frame:
        return pd.Series(dtype=float, index=frame.index)
    result = pd.to_numeric(frame[key], errors="coerce").replace([math.inf, -math.inf], float("nan"))
    return result.abs() if key in {"capex", "dividends_paid"} else result


def _last(series):
    return series.iloc[-1] if not series.empty else None


def _yoy(values, frequency):
    lag = 1 if frequency == "annual" else 4
    days = values.index.to_series().diff(lag).dt.days
    base = values.shift(lag)
    return ((values / base.where(base > 0) - 1) * 100).where(days.between(350, 380))


def _ttm(values):
    gaps = values.index.to_series().diff().dt.days
    consecutive = gaps.between(75, 105).rolling(3).sum().eq(3)
    span = values.index.to_series().diff(3).dt.days.between(255, 290)
    return values.rolling(4, min_periods=4).sum().where(consecutive & span)


def company_metrics(snapshot: CompanySnapshot, assumptions: ValuationAssumptions) -> dict:
    """Raccoglie dati già esposti nella scheda azienda, senza accesso alla rete."""
    groups = {name: {} for name in GROUPS}
    fund = snapshot.fund
    if fund is None:
        return groups
    quote, currency = fund.currency or "valuta n/d", fund.financial_currency or "valuta n/d"
    period = latest_cash_flow_period(snapshot.annual, snapshot.quarterly)
    valuation = evaluate_company(fund, period, assumptions)
    cash = summarize_cash_flow(period.values, fund.market_cap, fund.financial_currency, fund.currency)
    overview = groups["Riepilogo"]
    for label, value, unit in (
        ("Ticker", snapshot.ticker, ""), ("Settore", fund.sector, ""), ("Paese", fund.country, ""),
        ("Valuta quotazione", fund.currency, ""), ("Valuta bilancio", fund.financial_currency, ""),
        ("Prezzo", fund.price, quote), ("Capitalizzazione", fund.market_cap, quote),
        ("Ultima data storico prezzi", f"{snapshot.close.index.max():%d/%m/%Y}" if not snapshot.close.empty else None, ""),
        ("Periodo cash flow", period.label, ""), ("Disponibilità cash flow", period.notice or "TTM completo", ""),
        ("Punteggio composito", snapshot.score.composite if snapshot.score else None, "/100"),
    ):
        overview[label] = _metric(value, unit)
    for key, label in (("value", "Valore"), ("quality", "Qualità"), ("growth", "Crescita"),
                       ("momentum", "Momentum"), ("dividend", "Dividendi")):
        overview[f"Punteggio {label}"] = _metric(snapshot.score.pillars.get(key) if snapshot.score else None, "/100")
    for key, label, unit in (
        ("trailing_pe", "P/E trailing", "x"), ("forward_pe", "P/E forward", "x"),
        ("price_to_book", "P/B", "x"), ("ev_to_ebitda", "EV/EBITDA", "x"), ("peg", "PEG", "x"),
        ("roe", "ROE", "%"), ("net_margin", "Margine netto", "%"),
        ("operating_margin", "Margine operativo", "%"), ("debt_to_equity", "Debito / patrimonio", "x"),
        ("revenue_growth", "Crescita ricavi", "%"), ("earnings_growth", "Crescita utili", "%"),
        ("trailing_eps", "EPS trailing", currency), ("book_value", "Valore contabile per azione", currency),
        ("shares_outstanding", "Azioni in circolazione", ""),
        ("implied_shares_outstanding", "Azioni equivalenti", ""),
        ("free_cashflow", "Free cash flow del profilo (periodo non fornito)", currency),
    ):
        groups["Fondamentali"][label] = _metric(getattr(fund, key), unit)
    for key, label, unit in (
        ("operating_cashflow", "Cash flow operativo", currency), ("capex", "CapEx", currency),
        ("free_cashflow", "Free cash flow (CFO − CapEx)", currency),
        ("dividends_paid", "Dividendi pagati", currency), ("fcf_margin", "Margine FCF", "%"),
        ("cash_conversion", "Conversione utili in cassa", "x"), ("fcf_yield", "FCF yield", "%"),
        ("dividend_coverage", "Copertura dividendi", "x"),
    ):
        groups["Cash flow e dividendi"][label] = _metric(cash[key].value, unit, cash[key].reason)
    for label, value, unit in (
        ("FCFE", valuation.fcfe.value, currency),
        ("Indebitamento netto", period.values.get("net_borrowing"), currency),
        ("Dividendo annuo per azione (12 mesi)", fund.annual_dividend, currency),
        ("Dividend yield", fund.dividend_yield, "%"), ("Payout ratio", fund.payout_ratio, "%"),
    ):
        groups["Cash flow e dividendi"][label] = _metric(value, unit,
            valuation.fcfe.reason if label == "FCFE" else "")
    for name, estimate in valuation.models.items():
        for suffix, value, unit in (("valore", estimate.value, quote),
                                    ("scostamento", estimate.upside / 100 if estimate.upside is not None else None, "%"),
                                    ("prezzo con margine", estimate.safety_price, quote)):
            groups["Valutazioni"][f"{name} — {suffix}"] = _metric(value, unit, estimate.reason)
    groups["Valutazioni"]["Crescita dividendi implicita nel prezzo"] = _metric(
        valuation.implied_growth.value, "%", valuation.implied_growth.reason)
    for key, label, unit in (("target_mean_price", "Target medio", quote),
                              ("target_low_price", "Target minimo", quote),
                              ("target_high_price", "Target massimo", quote),
                              ("recommendation_key", "Raccomandazione", ""),
                              ("recommendation_mean", "Giudizio medio (1 acquisto – 5 vendita)", ""),
                              ("num_analysts", "Numero analisti", "")):
        groups["Analisti"][label] = _metric(getattr(fund, key), unit)
    upside = (fund.target_mean_price / fund.price - 1
              if fund.target_mean_price is not None and fund.price is not None and fund.price > 0 else None)
    groups["Analisti"]["Scostamento target medio"] = _metric(upside, "%")
    pm = price_metrics(snapshot.close)
    for key, label in (("return_6m", "Rendimento 6 mesi nativo"), ("return_12m", "Rendimento 12 mesi nativo"),
                       ("vs_ma200", "Distanza dalla media 200"), ("dist_from_52w_high", "Distanza dal massimo 52 settimane"),
                       ("volatility", "Volatilità annualizzata"), ("max_drawdown_1y", "Massimo drawdown 1 anno")):
        groups["Mercato"][label] = _metric(getattr(pm, key), "%", "Storico prezzi insufficiente o non disponibile.")
    groups["Mercato"]["Rendimento 12 mesi EUR"] = _metric(snapshot.extras.get("return_12m_eur"), "%",
        "Storico prezzi o conversione valutaria non disponibile.")
    groups["Mercato"]["Media mobile 200"] = _metric(snapshot.close.tail(200).mean() if len(snapshot.close) >= 200 else None, quote)
    pe = snapshot.extras.get("pe_series", pd.Series(dtype=float)).dropna()
    mean, std = (pe.mean(), pe.std()) if not pe.empty else (float("nan"), float("nan"))
    for label, value in (("P/E storico ultimo", _last(pe)), ("P/E storico medio", mean),
                         ("P/E storico media − 1σ", max(mean - std, 0)),
                         ("P/E storico media + 1σ", mean + std)):
        groups["Mercato"][label] = _metric(value if not valuation.currency_issue else None, "x", valuation.currency_issue)
    for frequency, frame, suffix in (("annual", snapshot.annual, "ultimo esercizio"),
                                      ("quarterly", snapshot.quarterly, "ultimo trimestre")):
        dates = frame.index.sort_values() if isinstance(frame.index, pd.DatetimeIndex) else pd.DatetimeIndex([])
        overview[f"Bilanci: {suffix}"] = _metric(f"{dates[-1]:%d/%m/%Y}" if len(dates) else None)
        overview[f"Storico bilanci {frequency}"] = _metric(
            f"{dates[0]:%d/%m/%Y} – {dates[-1]:%d/%m/%Y}" if len(dates) else None)
        for key, label in FINANCIAL_FIELDS.items():
            series = _series(frame, key)
            groups["Bilanci"][f"{label} — {suffix}"] = _metric(_last(series), currency)
            if frequency == "annual" and key in {"revenue", "net_income", "free_cashflow"}:
                valid = series.dropna()
                growth = cagr(valid) if len(valid) > 1 and valid.iloc[0] > 0 and valid.iloc[-1] >= 0 else None
                groups["Bilanci"][f"CAGR {label} (storico annuale)"] = _metric(growth, "%",
                    "Servono almeno due esercizi, base positiva e valore finale non negativo.")
            if frequency == "quarterly" and key in {"revenue", "net_income", "free_cashflow"}:
                ttm, yoy = _ttm(series), _yoy(series, frequency)
                groups["Bilanci"][f"{label} — TTM"] = _metric(_last(ttm), currency,
                    "Servono quattro trimestri consecutivi completi.")
                latest_yoy = _last(yoy)
                groups["Bilanci"][f"{label} — YoY ultimo trimestre"] = _metric(
                    latest_yoy / 100 if latest_yoy is not None else None, "%",
                    "Periodo di un anno prima assente o non positivo.")
        for key, (label, _) in MARGINS.items():
            value = _last(_series(frame, key))
            groups["Bilanci"][f"{label} — {suffix}"] = _metric(value / 100 if value is not None else None, "%")
    return groups


def comparison_history(snapshots: list[CompanySnapshot], metric: str,
                       frequency: str, view: str) -> tuple[pd.DataFrame, dict[str, str]]:
    """Serie sovrapposte; segnala esclusioni, valute miste e periodi discontinui."""
    if metric not in HISTORY_FIELDS or frequency not in {"annual", "quarterly"}:
        raise ValueError("Indicatore o frequenza non validi.")
    financial = metric not in {"price", "drawdown", "pe"}
    allowed = {"Assoluto", "Base 100"}
    if financial and metric not in MARGINS:
        allowed.add("YoY %")
        if frequency == "quarterly":
            allowed.add("TTM")
    if metric in MARGINS or metric == "drawdown":
        allowed = {"Assoluto"}
    if view not in allowed:
        raise ValueError("Vista non applicabile all'indicatore selezionato.")
    series, issues, currencies = {}, {}, set()
    for snapshot in snapshots:
        if snapshot.fund is None:
            issues[snapshot.ticker] = " · ".join(snapshot.issues) or "Dati aziendali assenti."
            continue
        if metric == "price":
            values = snapshot.close.copy()
        elif metric == "drawdown":
            values = (snapshot.close / snapshot.close.cummax() - 1) * 100
        elif metric == "pe":
            if not snapshot.fund.currency or snapshot.fund.currency != snapshot.fund.financial_currency:
                issues[snapshot.ticker] = "P/E storico: valute del prezzo e degli utili assenti o diverse."
                continue
            values = snapshot.extras.get("pe_series", pd.Series(dtype=float))
        else:
            values = _series(snapshot.annual if frequency == "annual" else snapshot.quarterly, metric)
        values = values.replace([math.inf, -math.inf], float("nan")).sort_index()
        if not isinstance(values.index, pd.DatetimeIndex) or values.index.hasnans or not values.index.is_unique:
            issues[snapshot.ticker] = "Date dello storico assenti o duplicate."
            continue
        if view == "YoY %":
            values = _yoy(values, frequency)
        elif view == "TTM":
            values = _ttm(values)
        if values.dropna().empty:
            issues[snapshot.ticker] = "Storico assente o periodi insufficienti/consecutivi non disponibili."
            continue
        if view == "Base 100" and financial:
            base = values.dropna().iloc[0]
            if base <= 0:
                issues[snapshot.ticker] = "Base 100 non applicabile: il primo valore deve essere positivo."
                continue
            values = values / base * 100
        series[snapshot.label] = values
        currencies.add(snapshot.fund.financial_currency if financial else snapshot.fund.currency)
    monetary = metric not in MARGINS and metric not in {"drawdown", "pe"}
    if monetary and view in {"Assoluto", "TTM"} and (len(currencies) > 1 or None in currencies or "" in currencies):
        return pd.DataFrame(), {**issues, "Valute": "Valori assoluti richiedono la stessa valuta nota. Usa Base 100 o YoY %."}
    frame = pd.concat(series, axis=1, sort=True) if series else pd.DataFrame()
    if view == "Base 100" and not financial and not frame.empty:
        frame = frame.dropna()
        if len(frame) < 2 or (frame.iloc[0] <= 0).any():
            return pd.DataFrame(), {**issues, "Periodo": "Servono almeno due date comuni e valori iniziali positivi."}
        frame = frame / frame.iloc[0] * 100
    return frame, issues
