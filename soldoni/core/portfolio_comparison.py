from datetime import timedelta

import numpy as np
import pandas as pd

from soldoni.core.models import Instrument, OpType, Transaction
from soldoni.core.valuation import quantity_timeline


def group_portfolio_transactions(
    transactions: list[Transaction], instruments: dict[str, Instrument],
) -> dict[str, list[Transaction]]:
    """Raggruppa tutto lo storico, incluse le posizioni chiuse, rispettando le esclusioni."""
    groups = {"I miei ETF": [], "Le mie azioni": []}
    for transaction in transactions:
        instrument = instruments.get(transaction.isin)
        if instrument is None:
            raise ValueError(f"Completa l'anagrafica per: {transaction.isin}.")
        if instrument.excluded:
            continue
        kind = instrument.asset_class
        if kind == "etf":
            groups["I miei ETF"].append(transaction)
        elif kind in ("azione", "stock"):
            groups["Le mie azioni"].append(transaction)
    return groups


def _validate_dates(index: pd.Index) -> None:
    if (not isinstance(index, pd.DatetimeIndex) or index.empty or index.hasnans
            or not index.is_unique or index.tz is not None
            or not index.equals(index.normalize())):
        raise ValueError("Lo storico deve avere date giornaliere uniche e valide.")


def portfolio_prices_eur(close_native: pd.Series, native_per_eur: pd.Series | None) -> pd.Series:
    """Converte i prezzi con cambi storici, senza anticiparli o superarne la copertura."""
    def daily(series, label):
        if not isinstance(series.index, pd.DatetimeIndex):
            raise ValueError(f"Date non valide per {label}.")
        values = series.dropna().astype(float).copy()
        values.index = values.index.tz_localize(None).normalize()
        _validate_dates(values.index)
        if not np.isfinite(values).all() or (values <= 0.0).any():
            raise ValueError(f"{label} non validi: devono essere finiti e positivi.")
        return values.sort_index()

    close = daily(close_native, "Prezzi")
    if native_per_eur is None:
        return close
    rates = daily(native_per_eur, "Cambi")
    first = max(close.index.min(), rates.index.min())
    last = min(close.index.max(), rates.index.max())
    if first > last:
        raise ValueError("Prezzi e cambi non hanno un periodo comune.")
    dates = pd.date_range(min(close.index.min(), rates.index.min()), last)
    close = close.reindex(dates).ffill(limit=7).loc[first:]
    rates = rates.reindex(dates).ffill(limit=7).loc[first:]
    if close.isna().any() or rates.isna().any():
        raise ValueError("Prezzi o cambi mancanti per oltre sette giorni nel periodo.")
    return daily(close / rates, "Prezzi EUR")


def portfolio_group_index(transactions: list[Transaction], close_eur: pd.DataFrame) -> pd.Series:
    """TWR in EUR dai Close e dai flussi reali; base 100 prima della prima operazione.

    Flussi a fine giornata. Alla prima entrata e dopo un disinvestimento totale,
    il capitale apportato finanzia il periodo; i giorni senza capitale restano invariati.
    """
    if not transactions:
        raise ValueError("Nessuna operazione nel gruppo.")
    _validate_dates(close_eur.index)
    if not close_eur.columns.is_unique:
        raise ValueError("Prezzi duplicati per lo stesso ISIN.")
    first = min(transaction.trade_date for transaction in transactions)
    end = close_eur.index.max()
    if max(transaction.trade_date for transaction in transactions) > end.date():
        raise ValueError("Prezzi mancanti per le operazioni più recenti.")
    dates = pd.date_range(first - timedelta(days=1), end, freq="D")
    quantities = quantity_timeline(transactions, dates)
    if (quantities < -1e-6).any().any():
        raise ValueError("Storico acquisti incompleto: una posizione risulta negativa.")
    missing = set(quantities.columns) - set(close_eur.columns)
    if missing:
        raise ValueError("Prezzi mancanti per: " + ", ".join(sorted(missing)))
    # Weekend e festività possono usare l'ultima quotazione, fino a sette giorni.
    prices = close_eur.reindex(close_eur.index.union(dates)).sort_index().ffill(limit=7)
    prices = prices.reindex(index=dates, columns=quantities.columns).astype(float)
    held = quantities.abs() >= 1e-6
    invalid = held & (~np.isfinite(prices) | (prices <= 0.0))
    if invalid.any().any():
        isins = invalid.columns[invalid.any()]
        raise ValueError("Prezzi mancanti o non validi durante il possesso: " + ", ".join(isins))
    values = (quantities * prices).where(held, 0.0).sum(axis=1)
    flows = pd.Series(0.0, index=dates)
    purchases = pd.Series(0.0, index=dates)
    for transaction in transactions:
        amounts = (transaction.quantity, transaction.amount_eur, transaction.commission_eur)
        if not all(np.isfinite(value) and value >= 0.0 for value in amounts):
            raise ValueError(f"Quantità o importi non validi per {transaction.isin}.")
        if transaction.op_type is OpType.BUY:
            flow = transaction.amount_eur + transaction.commission_eur
            purchases.loc[pd.Timestamp(transaction.trade_date)] += flow
        elif transaction.op_type in (OpType.SELL, OpType.DIVIDEND):
            flow = -transaction.amount_eur + transaction.commission_eur
        else:
            raise ValueError(f"Operazione non supportata per {transaction.isin}.")
        flows.loc[pd.Timestamp(transaction.trade_date)] += flow

    result = []
    current, previous = 100.0, 0.0
    for value, flow, purchase in zip(values, flows, purchases):
        if previous > 1e-9:
            factor = (value - flow) / previous
        elif purchase > 1e-9:
            factor = (value + purchase - flow) / purchase
        elif abs(flow) <= 1e-9 and abs(value) <= 1e-9:
            factor = 1.0
        else:
            raise ValueError("Flussi senza capitale investito: rendimento non determinabile.")
        current *= factor
        if factor < 0.0 or not np.isfinite(current):
            raise ValueError("Rendimento non valido: verifica prezzi, quantità e movimenti.")
        result.append(current)
        previous = value
    return pd.Series(result, index=dates, dtype=float)


def compare_portfolio_histories(
    histories: dict[str, pd.Series],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Confronta rendimento e drawdown sullo stesso periodo, senza estendere gli storici."""
    if len(histories) < 2:
        raise ValueError("Servono almeno due storici disponibili per il confronto.")
    cleaned = {}
    for name, history in histories.items():
        _validate_dates(history.index)
        series = history.dropna().astype(float).sort_index()
        if series.empty or not np.isfinite(series).all() or (series < 0.0).any():
            raise ValueError(f"Storico non valido per {name}.")
        cleaned[name] = series
    common = pd.concat(cleaned, axis=1, join="inner").sort_index()
    if len(common) < 2:
        raise ValueError("Meno di due date comuni: confronto non determinabile.")
    if (common.iloc[0] <= 0.0).any():
        raise ValueError("Capitale azzerato all'inizio del periodo comune.")
    common = common.div(common.iloc[0]).mul(100.0)
    if not np.isfinite(common.to_numpy()).all():
        raise ValueError("Rendimenti non validi nel periodo comune.")
    returns = common.iloc[-1] - 100.0
    summary = pd.DataFrame({
        "Rendimento %": returns,
        "Calo massimo %": (common.div(common.cummax()) - 1.0).min() * 100.0,
        "Vantaggio S&P 500 (p.p.)": returns - returns.get("S&P 500", np.nan),
    })
    return common, summary
