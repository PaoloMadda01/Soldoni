"""Riepilogo dei flussi aziendali con periodi omogenei e disponibilità esplicita."""

from dataclasses import dataclass
import math
from numbers import Real

import pandas as pd


@dataclass(frozen=True)
class CashFlowPeriod:
    end: pd.Timestamp | None
    label: str
    values: dict[str, float]
    notice: str = ""


@dataclass(frozen=True)
class CashFlowMetric:
    value: float | None
    reason: str = ""


_FLOW_FIELDS = ("operating_cashflow", "capex", "net_borrowing", "dividends_paid",
                "revenue", "net_income")


def _finite(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _ordered(frame):
    if (frame.empty or not isinstance(frame.index, pd.DatetimeIndex)
            or frame.index.hasnans or not frame.index.is_unique):
        return pd.DataFrame()
    return frame.sort_index()


def _period_values(frame):
    values = {}
    for name in _FLOW_FIELDS:
        if name not in frame or not all(_finite(value) for value in frame[name]):
            continue
        series = frame[name].astype(float)
        if name in {"capex", "dividends_paid"}:
            series = series.abs()
        total = float(series.sum())
        if math.isfinite(total):
            values[name] = total
    return values


def latest_cash_flow_period(annual: pd.DataFrame, quarterly: pd.DataFrame) -> CashFlowPeriod:
    """Ultimo TTM completo per CFO/CapEx; altrimenti ultimo esercizio, senza mescolarli."""
    annual = _ordered(annual)
    quarters = _ordered(quarterly).tail(4)
    values = _period_values(quarters)
    consecutive = False
    if len(quarters) == 4:
        gaps = quarters.index.to_series().diff().dropna().dt.days
        span = (quarters.index[-1] - quarters.index[0]).days
        # Tolleranza per trimestri fiscali di 12–14 settimane, compresi esercizi a 53 settimane.
        consecutive = gaps.between(75, 105).all() and 255 <= span <= 290
    complete = consecutive and {"operating_cashflow", "capex"} <= values.keys()
    if complete and (annual.empty or quarters.index[-1] >= annual.index[-1]):
        end = quarters.index[-1]
        return CashFlowPeriod(end, f"TTM — ultimi 12 mesi al {end:%d/%m/%Y}", values)
    if not annual.empty:
        end = annual.index[-1]
        notice = ("L'esercizio annuale è più recente dei trimestri disponibili." if complete else
                  "TTM non disponibile: servono quattro trimestri consecutivi con CFO e CapEx completi.")
        return CashFlowPeriod(end, f"Esercizio al {end:%d/%m/%Y}",
                              _period_values(annual.tail(1)), notice)
    return CashFlowPeriod(None, "Periodo annuo non disponibile", {},
                          "Non sono disponibili né un esercizio annuale né quattro trimestri completi.")


def _amount(value, name, outflow=False):
    if not _finite(value):
        return CashFlowMetric(None, f"{name}: dato assente o non finito nel periodo selezionato.")
    return CashFlowMetric(abs(float(value)) if outflow else float(value))


def _ratio(numerator, denominator, name):
    if numerator.value is None:
        return CashFlowMetric(None, numerator.reason)
    if denominator.value is None:
        return CashFlowMetric(None, denominator.reason)
    if denominator.value <= 0:
        return CashFlowMetric(None, f"Denominatore non positivo ({name}): rapporto non applicabile.")
    return _amount(numerator.value / denominator.value, "Rapporto")


def summarize_cash_flow(values: dict[str, float], market_cap: float | None,
                        financial_currency: str | None,
                        market_currency: str | None) -> dict[str, CashFlowMetric]:
    """Importi e rapporti sul medesimo periodo; FCF yield solo con valute coerenti."""
    operating = _amount(values.get("operating_cashflow"), "Cash flow operativo")
    capex = _amount(values.get("capex"), "Investimenti", outflow=True)
    dividends = _amount(values.get("dividends_paid"), "Dividendi pagati", outflow=True)
    if operating.value is None or capex.value is None:
        fcf = CashFlowMetric(None, operating.reason or capex.reason)
    else:
        fcf = _amount(operating.value - capex.value, "Free cash flow")
    yield_metric = _ratio(fcf, _amount(market_cap, "Capitalizzazione"), "Capitalizzazione")
    if (not financial_currency or financial_currency != market_currency
            or len(financial_currency) != 3 or not financial_currency.isalpha()
            or not financial_currency.isupper()):
        yield_metric = CashFlowMetric(None, "Valute di bilancio e capitalizzazione assenti o diverse.")
    return {
        "operating_cashflow": operating, "capex": capex, "free_cashflow": fcf,
        "dividends_paid": dividends,
        "fcf_margin": _ratio(fcf, _amount(values.get("revenue"), "Ricavi"), "Ricavi"),
        "cash_conversion": _ratio(operating, _amount(values.get("net_income"), "Utile netto"),
                                   "Utile netto"),
        "fcf_yield": yield_metric,
        "dividend_coverage": _ratio(fcf, dividends, "Dividendi pagati"),
    }
