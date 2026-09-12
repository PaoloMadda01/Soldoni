from datetime import date

import pandas as pd
from soldoni.core.models import OpType, Transaction


def quantity_timeline(transactions: list[Transaction], dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Quantità nette cumulate per ISIN su ogni data (forward-fill). Dividendi ignorati."""
    deltas: dict[str, pd.Series] = {}
    for tx in transactions:
        if tx.op_type is OpType.DIVIDEND:
            continue
        sign = 1 if tx.op_type is OpType.BUY else -1
        ts = pd.Timestamp(tx.trade_date)
        s = deltas.setdefault(tx.isin, pd.Series(0.0, index=dates))
        if ts in s.index:
            s.loc[ts] += sign * tx.quantity
        else:
            future = s.index[s.index >= ts]
            if len(future):
                s.loc[future[0]] += sign * tx.quantity
    if not deltas:
        return pd.DataFrame(index=dates)
    df = pd.DataFrame(deltas).reindex(dates).fillna(0.0)
    return df.cumsum()


def portfolio_value_eur(quantity: pd.DataFrame, prices_eur: pd.DataFrame) -> pd.Series:
    """Valore EUR per data = somma(quantità * prezzo EUR) sugli ISIN comuni."""
    common = [c for c in quantity.columns if c in prices_eur.columns]
    q = quantity[common]
    p = prices_eur[common].reindex(q.index).ffill()
    return (q * p).sum(axis=1)


def invested_timeline(cashflows: pd.Series) -> pd.Series:
    """Capitale netto versato cumulato nel tempo = cumsum dei cashflow giornalieri."""
    return cashflows.cumsum()


def drawdown(series: pd.Series) -> pd.Series:
    """Caduta percentuale dal massimo precedente: series / series.cummax() - 1 (≤ 0).
    Serie vuota -> serie vuota."""
    if series.empty:
        return series
    return series / series.cummax() - 1.0


def monthly_net_invested(transactions: list[Transaction]) -> pd.Series:
    """Netto investito per mese = Σ(acquisti) − Σ(vendite) in amount_eur, indicizzato al
    primo giorno del mese. Dividendi esclusi. Nessun movimento di capitale -> serie vuota."""
    by_month: dict[pd.Timestamp, float] = {}
    for t in transactions:
        if t.op_type is OpType.DIVIDEND:
            continue
        key = pd.Timestamp(t.trade_date.year, t.trade_date.month, 1)
        sign = 1.0 if t.op_type is OpType.BUY else -1.0
        by_month[key] = by_month.get(key, 0.0) + sign * t.amount_eur
    if not by_month:
        return pd.Series(dtype=float)
    return pd.Series(by_month).sort_index()


def average_monthly_purchases(transactions: list[Transaction],
                              as_of: date,
                              months: int = 12) -> float:
    """Media degli acquisti nei mesi completi precedenti ``as_of``."""
    if not isinstance(months, int) or months <= 0:
        raise ValueError("Il numero di mesi deve essere un intero positivo.")
    current_month = as_of.year * 12 + as_of.month - 1
    first_month = current_month - months
    total = sum(
        tx.amount_eur + tx.commission_eur
        for tx in transactions
        if (tx.op_type is OpType.BUY
            and first_month <= tx.trade_date.year * 12 + tx.trade_date.month - 1
            < current_month)
    )
    return total / months
