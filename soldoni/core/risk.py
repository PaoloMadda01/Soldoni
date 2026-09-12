import pandas as pd


def business_day_returns(index_series: pd.Series) -> pd.Series:
    """Rendimenti semplici sui soli giorni di borsa (toglie i weekend ffill)."""
    if index_series.empty:
        return index_series
    bdays = pd.bdate_range(index_series.index.min(), index_series.index.max())
    return index_series.reindex(bdays).ffill().pct_change().dropna()


def annualized_volatility(returns: pd.Series, periods: int = 252) -> float:
    """Deviazione standard campionaria (ddof=1) annualizzata. <2 dati -> nan."""
    if len(returns) < 2:
        return float("nan")
    return float(returns.std(ddof=1) * (periods ** 0.5))


def sharpe(returns: pd.Series, rf: float = 0.03, periods: int = 252) -> float:
    """(media·periods − rf) / volatilità_annua. Vol 0 o <2 dati -> nan."""
    vol = annualized_volatility(returns, periods)
    if pd.isna(vol) or vol == 0:
        return float("nan")
    ann_return = returns.mean() * periods
    return float((ann_return - rf) / vol)


def sortino(returns: pd.Series, rf: float = 0.03, periods: int = 252) -> float:
    """(media·periods − rf) / downside_deviation_annua, target = rf/periods.
    Downside deviation 0 o <2 dati -> nan."""
    if len(returns) < 2:
        return float("nan")
    target = rf / periods
    downside = returns.apply(lambda x: min(0.0, x - target))
    dd = float((downside.pow(2).mean()) ** 0.5 * (periods ** 0.5))
    if dd == 0:
        return float("nan")
    ann_return = returns.mean() * periods
    return float((ann_return - rf) / dd)


def beta(returns: pd.Series, bench_returns: pd.Series) -> float:
    """cov(returns, bench)/var(bench) sui rendimenti allineati. <2 punti o var 0 -> nan."""
    aligned = pd.concat([returns, bench_returns], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        return float("nan")
    rp = aligned.iloc[:, 0]
    rb = aligned.iloc[:, 1]
    var_b = rb.var(ddof=1)
    if var_b == 0:
        return float("nan")
    return float(rp.cov(rb) / var_b)


def rolling_volatility(returns: pd.Series, window: int, periods: int = 252) -> pd.Series:
    """Volatilità annualizzata su finestra mobile: std(ddof=1) rolling · √periods."""
    return returns.rolling(window).std(ddof=1) * (periods ** 0.5)


def rolling_beta(returns: pd.Series, bench_returns: pd.Series, window: int) -> pd.Series:
    """Beta su finestra mobile = cov(returns,bench)/var(bench) rolling, sui rendimenti allineati."""
    aligned = pd.concat([returns, bench_returns], axis=1, join="inner").dropna()
    rp, rb = aligned.iloc[:, 0], aligned.iloc[:, 1]
    return rp.rolling(window).cov(rb) / rb.rolling(window).var()


def correlation_matrix(price_eur: pd.DataFrame) -> pd.DataFrame:
    """Matrice di correlazione dei rendimenti giornalieri feriali per colonna (ISIN).
    DataFrame vuoto -> DataFrame vuoto."""
    if price_eur.empty:
        return pd.DataFrame()
    bdays = pd.bdate_range(price_eur.index.min(), price_eur.index.max())
    rets = price_eur.reindex(bdays).ffill().pct_change().dropna()
    return rets.corr()


def monthly_returns_table(index_series: pd.Series) -> pd.DataFrame:
    """Tabella anno×mese dei rendimenti mensili (%) da una serie indice (es. TWR).
    Serie vuota o meno di 2 fine-mese -> DataFrame vuoto."""
    if index_series.empty:
        return pd.DataFrame()
    m = index_series.resample("ME").last().pct_change().dropna() * 100.0
    if m.empty:
        return pd.DataFrame()
    df = pd.DataFrame({"year": m.index.year, "month": m.index.month, "ret": m.values})
    return df.pivot(index="year", columns="month", values="ret")
