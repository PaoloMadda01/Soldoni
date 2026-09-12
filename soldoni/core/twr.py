import pandas as pd


def twr_index(values: pd.Series, cashflows: pd.Series, base: float = 100.0) -> pd.Series:
    """Indice TWR (base 100). Flusso considerato a fine giornata:
    r_t = (V_t - CF_t) / V_{t-1} - 1. Per il benchmark passare cashflows=0."""
    values = values.sort_index()
    cashflows = cashflows.reindex(values.index).fillna(0.0)
    out = pd.Series(index=values.index, dtype=float)
    prev_v = None
    cur = base
    for d in values.index:
        v = float(values.loc[d])
        cf = float(cashflows.loc[d])
        if prev_v is None or prev_v == 0:
            cur = base
        else:
            r = (v - cf) / prev_v - 1.0
            cur = cur * (1.0 + r)
        out.loc[d] = cur
        prev_v = v
    return out
