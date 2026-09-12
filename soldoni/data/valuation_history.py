import pandas as pd
import yfinance as yf


def _fetch_quarterly_eps(ticker: str) -> pd.DataFrame:
    """Conto economico trimestrale yfinance (contiene la riga 'Diluted EPS')."""
    return yf.Ticker(ticker).quarterly_income_stmt


def get_eps_quarterly(ticker: str, fetch=_fetch_quarterly_eps) -> pd.Series:
    """EPS diluiti (o basic) trimestrali come Series indicizzata per data, ordinata.

    Serie vuota se yfinance non espone gli EPS. `fetch` iniettabile per i test.
    """
    df = fetch(ticker)
    if df is None or getattr(df, "empty", True):
        return pd.Series(dtype=float)
    for row in ("Diluted EPS", "Basic EPS"):
        if row in df.index:
            s = df.loc[row].dropna()
            s.index = pd.to_datetime(s.index)
            return s.astype(float).sort_index()
    return pd.Series(dtype=float)


def ttm_eps(quarterly_eps: pd.Series) -> pd.Series:
    """EPS trailing-twelve-months = somma mobile a 4 trimestri (ordinata per data)."""
    if quarterly_eps is None or quarterly_eps.empty:
        return pd.Series(dtype=float)
    return quarterly_eps.sort_index().rolling(4).sum().dropna()


def pe_history(close: pd.Series, quarterly_eps: pd.Series) -> pd.Series:
    """Serie storica del P/E: prezzo / EPS TTM (step, forward-fill), solo dove EPS TTM > 0.

    Serie vuota se mancano prezzi o EPS. Approssimato: l'EPS TTM è una funzione a gradini
    aggiornata alla data di ciascun trimestre.
    """
    ttm = ttm_eps(quarterly_eps)
    if ttm.empty or close.empty:
        return pd.Series(dtype=float)
    union = close.index.union(ttm.index)
    ttm_aligned = ttm.reindex(union).sort_index().ffill().reindex(close.index)
    pe = close / ttm_aligned
    return pe[ttm_aligned > 0].dropna()
