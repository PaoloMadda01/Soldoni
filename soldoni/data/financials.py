import pandas as pd
import yfinance as yf


_ROWS = {
    "revenue": ("Total Revenue", "Operating Revenue"),
    "net_income": ("Net Income", "Net Income Common Stockholders"),
    "operating_income": ("Operating Income", "EBIT"),
    "eps": ("Diluted EPS", "Basic EPS"),
    "free_cashflow": ("Free Cash Flow",),
    "operating_cashflow": ("Operating Cash Flow", "Total Cash From Operating Activities"),
    "capex": ("Capital Expenditure",),
    "net_borrowing": ("Net Issuance Payments Of Debt",),
    "dividends_paid": ("Cash Dividends Paid", "Common Stock Dividend Paid"),
}
_INCOME = ("revenue", "net_income", "operating_income", "eps")
_CASHFLOW = ("free_cashflow", "operating_cashflow", "capex", "net_borrowing", "dividends_paid")


def _fetch_statements(ticker: str, freq: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Income statement + cash flow grezzi da yfinance. `freq` in {"annual","quarterly"}."""
    t = yf.Ticker(ticker)
    if freq == "annual":
        return t.income_stmt, t.cashflow
    return t.quarterly_income_stmt, t.quarterly_cashflow


def _row(df: pd.DataFrame, labels: tuple[str, ...]) -> pd.Series | None:
    """Prima riga presente tra `labels`, come Series float indicizzata per data asc. None se assente."""
    if df is None or getattr(df, "empty", True):
        return None
    for label in labels:
        if label in df.index:
            s = df.loc[label].dropna()
            if s.empty:
                continue
            s.index = pd.to_datetime(s.index)
            return s.astype(float).sort_index()
    return None


def get_financials(ticker: str, freq: str = "quarterly", fetch=_fetch_statements) -> pd.DataFrame:
    """Income statement + cash flow yfinance normalizzati.

    Index = date di fine periodo (ascendente); colonne = nomi canonici con dati disponibili.
    `freq` in {"quarterly","annual"}. `fetch` iniettabile per i test.
    ValueError se entrambi i frame sono vuoti.
    """
    income_df, cashflow_df = fetch(ticker, freq)
    income_empty = income_df is None or getattr(income_df, "empty", True)
    cashflow_empty = cashflow_df is None or getattr(cashflow_df, "empty", True)
    if income_empty and cashflow_empty:
        raise ValueError(f"Nessun dato di bilancio da yfinance per '{ticker}'")
    cols: dict[str, pd.Series] = {}
    for name in _INCOME:
        s = _row(income_df, _ROWS[name])
        if s is not None:
            cols[name] = s
    for name in _CASHFLOW:
        s = _row(cashflow_df, _ROWS[name])
        if s is not None:
            cols[name] = s
    return pd.DataFrame(cols).sort_index()
