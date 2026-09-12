import numpy as np
import pandas as pd


def _daily_values(series: pd.Series, label: str) -> pd.Series:
    if not isinstance(series.index, pd.DatetimeIndex) or series.index.hasnans:
        raise ValueError(f"Date non valide per {label}.")
    values = series.dropna().astype(float).copy()
    values.index = values.index.tz_localize(None).normalize()
    if values.empty:
        raise ValueError(f"Nessun dato disponibile per {label}.")
    if not values.index.is_unique:
        raise ValueError(f"Date duplicate per {label}.")
    if not np.isfinite(values.to_numpy()).all() or (values <= 0).any():
        raise ValueError(f"Valori non validi per {label}: devono essere finiti e positivi.")
    return values.sort_index()


def adjusted_prices_eur(adjusted_close: pd.Series,
                        eur_fx: pd.Series | None = None) -> pd.Series:
    """Converte i prezzi rettificati in EUR; il cambio indica valuta nativa per 1 EUR."""
    close = _daily_values(adjusted_close, "prezzi rettificati")
    if eur_fx is None:
        return close
    rates = _daily_values(eur_fx, "cambi EUR")
    close = close.loc[rates.index.min():rates.index.max()]
    if close.empty:
        raise ValueError("Prezzi e cambi non hanno un periodo comune.")
    aligned = rates.reindex(rates.index.union(close.index)).sort_index().ffill()
    converted = close / aligned.reindex(close.index)
    return _daily_values(converted, "prezzi rettificati in EUR")


def base100_comparison(series_eur: dict[str, pd.Series]) -> pd.DataFrame:
    """Normalizza da 100 sulle sole date con osservazioni per tutti gli strumenti."""
    if not 2 <= len(series_eur) <= 6:
        raise ValueError("Servono da 2 a 6 strumenti con dati validi per il confronto.")
    cleaned = {ticker: _daily_values(series, ticker) for ticker, series in series_eur.items()}
    common = pd.concat(cleaned, axis=1, join="inner").sort_index()
    if len(common) < 2:
        raise ValueError("Meno di due date di quotazione comuni: cambia periodo o strumenti.")
    normalized = common.div(common.iloc[0]).mul(100.0)
    if not np.isfinite(normalized.to_numpy()).all():
        raise ValueError("Il confronto produce valori non finiti.")
    return normalized
