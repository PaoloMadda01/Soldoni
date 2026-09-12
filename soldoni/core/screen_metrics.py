from dataclasses import dataclass
import pandas as pd
from soldoni.core.risk import business_day_returns, annualized_volatility
from soldoni.core.valuation import drawdown


@dataclass
class PriceMetrics:
    return_6m: float | None
    return_12m: float | None
    vs_ma200: float | None
    dist_from_52w_high: float | None
    volatility: float | None
    max_drawdown_1y: float | None


def _window(close: pd.Series, days: int) -> pd.Series:
    """Ultimi `days` giorni di calendario della serie."""
    if close.empty:
        return close
    cutoff = close.index.max() - pd.Timedelta(days=days)
    return close[close.index >= cutoff]


def trailing_return(close: pd.Series, days: int) -> float | None:
    """Rendimento % sugli ultimi `days` giorni di calendario. None se storia insufficiente."""
    if close.empty:
        return None
    start_ts = close.index.max() - pd.Timedelta(days=days)
    past = close[close.index <= start_ts]
    if past.empty:
        return None
    base = float(past.iloc[-1])
    if base == 0:
        return None
    return float(close.iloc[-1]) / base - 1.0


def vs_moving_average(close: pd.Series, window: int = 200) -> float | None:
    """(prezzo - media a `window` osservazioni) / media. None se meno di `window` dati."""
    if len(close) < window:
        return None
    ma = float(close.iloc[-window:].mean())
    if ma == 0:
        return None
    return float(close.iloc[-1]) / ma - 1.0


def distance_from_high(close: pd.Series, days: int = 365) -> float | None:
    """(max ultimi `days` gg - prezzo) / max, >= 0. None se vuoto."""
    w = _window(close, days)
    if w.empty:
        return None
    hi = float(w.max())
    if hi == 0:
        return None
    return (hi - float(w.iloc[-1])) / hi


def price_volatility(close: pd.Series, days: int = 365) -> float | None:
    """Volatilita' annualizzata sugli ultimi `days` gg. None se non calcolabile."""
    rets = business_day_returns(_window(close, days))
    vol = annualized_volatility(rets)
    return None if pd.isna(vol) else float(vol)


def max_drawdown(close: pd.Series, days: int = 365) -> float | None:
    """Massimo drawdown (<= 0) sugli ultimi `days` gg. None se vuoto."""
    w = _window(close, days)
    if w.empty:
        return None
    dd = drawdown(w).min()
    return None if pd.isna(dd) else float(dd)


def price_metrics(close: pd.Series) -> PriceMetrics:
    """Calcola tutte le metriche da una serie di prezzi giornalieri (indice datetime)."""
    return PriceMetrics(
        return_6m=trailing_return(close, 182),
        return_12m=trailing_return(close, 365),
        vs_ma200=vs_moving_average(close, 200),
        dist_from_52w_high=distance_from_high(close, 365),
        volatility=price_volatility(close, 365),
        max_drawdown_1y=max_drawdown(close, 365),
    )
