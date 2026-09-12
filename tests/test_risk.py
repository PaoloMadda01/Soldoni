import pandas as pd
import pytest
from soldoni.core.risk import (
    business_day_returns, annualized_volatility, sharpe, sortino, beta,
    rolling_volatility, rolling_beta, correlation_matrix, monthly_returns_table)


def test_business_day_returns_excludes_weekend():
    # 2026-01-05 è lunedì; 10-11 gen sono sab/dom
    idx = pd.date_range("2026-01-05", "2026-01-12", freq="D")
    s = pd.Series([100, 110, 120, 130, 140, 140, 140, 150], index=idx, dtype=float)
    r = business_day_returns(s)
    assert len(r) == 5                       # Lun..Ven + Lun successivo, meno il primo
    assert (r.index.weekday < 5).all()       # nessun weekend
    assert round(r.iloc[0], 4) == 0.1        # 110/100 - 1


def test_annualized_volatility_constant_is_zero():
    assert annualized_volatility(pd.Series([0.0, 0.0, 0.0])) == 0.0


def test_annualized_volatility_known():
    r = pd.Series([0.01, -0.01, 0.01, -0.01])   # std(ddof=1)=0.0115470, *sqrt(252)=0.1833030
    assert round(annualized_volatility(r), 4) == 0.1833


def test_annualized_volatility_too_few_is_nan():
    assert pd.isna(annualized_volatility(pd.Series([0.01])))


def test_sharpe_known():
    r = pd.Series([0.01, -0.01, 0.01, -0.01])   # media 0 -> (0-0.03)/0.1833030
    assert round(sharpe(r), 4) == -0.1637


def test_sortino_known():
    r = pd.Series([0.01, -0.01, 0.01, -0.01])   # downside_dev_annua=0.113597 -> (0-0.03)/...
    assert round(sortino(r), 4) == -0.2641


def test_beta_self_and_scaled():
    r = pd.Series([0.02, -0.01, 0.03, -0.02])
    assert beta(r, r) == pytest.approx(1.0)
    assert beta(r, -r) == pytest.approx(-1.0)
    assert beta(2 * r, r) == pytest.approx(2.0)


def test_beta_too_few_is_nan():
    r = pd.Series([0.02], index=[0])
    assert pd.isna(beta(r, r))


def test_rolling_volatility_constant_is_zero():
    out = rolling_volatility(pd.Series([0.0, 0.0, 0.0, 0.0, 0.0]), 3).dropna()
    assert (out == 0.0).all()


def test_rolling_volatility_known_last():
    r = pd.Series([0.01, -0.01, 0.01, -0.01])      # finestra piena solo all'ultimo punto
    assert round(rolling_volatility(r, 4).dropna().iloc[-1], 4) == 0.1833


def test_rolling_beta_self_is_one():
    r = pd.Series([0.02, -0.01, 0.03, -0.02, 0.01])
    assert rolling_beta(r, r, 4).dropna().iloc[-1] == pytest.approx(1.0)


def test_correlation_matrix_opposite_and_diagonal():
    idx = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"])
    price = pd.DataFrame({"A": [100.0, 110.0, 104.5, 114.95],
                          "B": [100.0, 90.0, 94.5, 85.05]}, index=idx)
    corr = correlation_matrix(price)
    assert round(corr.loc["A", "A"], 4) == 1.0
    assert round(corr.loc["A", "B"], 4) == -1.0


def test_correlation_matrix_empty():
    assert correlation_matrix(pd.DataFrame()).empty


def test_monthly_returns_table_cells():
    idx = pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31"])
    s = pd.Series([100.0, 110.0, 99.0], index=idx)
    tab = monthly_returns_table(s)
    assert tab.loc[2026, 2] == pytest.approx(10.0)     # feb: 110/100-1
    assert tab.loc[2026, 3] == pytest.approx(-10.0)    # mar: 99/110-1


def test_monthly_returns_table_too_short_is_empty():
    one = pd.Series([100.0], index=pd.to_datetime(["2026-01-31"]))
    assert monthly_returns_table(one).empty
    assert monthly_returns_table(pd.Series(dtype=float)).empty
