import pandas as pd


def ttm(s: pd.Series) -> pd.Series:
    """Trailing-twelve-months: somma mobile a 4 periodi (grandezze di flusso).

    Serie vuota se `s` è vuota o ha meno di 4 punti. Ordina per data.
    """
    if s is None or s.empty:
        return pd.Series(dtype=float)
    return s.sort_index().rolling(4).sum().dropna()


def yoy_growth(s: pd.Series, periods: int = 1) -> pd.Series:
    """Variazione percentuale (frazione) su `periods` periodi.

    `periods=4` → YoY stesso trimestre su dati trimestrali; `periods=1` → annuale.
    Serie vuota se non ci sono abbastanza punti.
    """
    if s is None or s.empty:
        return pd.Series(dtype=float)
    return s.sort_index().pct_change(periods, fill_method=None).dropna()


def cagr(s: pd.Series) -> float | None:
    """Tasso di crescita composto annuo tra primo e ultimo punto.

    None se: meno di 2 punti, valore iniziale ≤ 0, o intervallo temporale ≤ 0.
    """
    if s is None or s.empty:
        return None
    s = s.sort_index().dropna()
    if len(s) < 2:
        return None
    first, last = float(s.iloc[0]), float(s.iloc[-1])
    if first <= 0:
        return None
    years = (s.index[-1] - s.index[0]).days / 365.25
    if years <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def indexed_to_100(s: pd.Series) -> pd.Series:
    """Serie riportata a base 100 sul primo valore. Vuota se `s` vuota o base ≤ 0."""
    if s is None or s.empty:
        return pd.Series(dtype=float)
    s = s.sort_index().dropna()
    if s.empty or float(s.iloc[0]) <= 0:
        return pd.Series(dtype=float)
    return s / float(s.iloc[0]) * 100.0


def margin(num: pd.Series, den: pd.Series) -> pd.Series:
    """Margine = num/den (frazione) sugli index comuni, dove den valido e ≠ 0."""
    if num is None or den is None or num.empty or den.empty:
        return pd.Series(dtype=float)
    idx = num.index.intersection(den.index)
    n = num.reindex(idx).astype(float)
    d = den.reindex(idx).astype(float)
    valid = d.notna() & (d != 0) & n.notna()
    return (n[valid] / d[valid]).sort_index()
