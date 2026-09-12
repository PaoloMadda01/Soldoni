import pandas as pd
from soldoni.core.twr import twr_index


def test_twr_ignores_contributions():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"])
    values = pd.Series([1000.0, 1100.0, 1655.0], index=dates)
    cashflows = pd.Series([1000.0, 0.0, 500.0], index=dates)
    idx = twr_index(values, cashflows)
    assert round(idx.iloc[0], 4) == 100.0
    assert round(idx.iloc[1], 4) == 110.0
    assert round(idx.iloc[2], 4) == 115.5


def test_twr_benchmark_zero_cashflows_is_normalized_return():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    values = pd.Series([200.0, 220.0], index=dates)
    cashflows = pd.Series([0.0, 0.0], index=dates)
    idx = twr_index(values, cashflows)
    assert round(idx.iloc[0], 4) == 100.0
    assert round(idx.iloc[1], 4) == 110.0
