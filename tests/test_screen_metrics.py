import numpy as np
import pandas as pd
import pytest
from soldoni.core import screen_metrics as sm


def _series(values, start="2024-01-01"):
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series([float(v) for v in values], index=idx)


def test_trailing_return_basic():
    s = _series([100, 110], start="2024-01-01")
    # ~1 giorno di distanza: base 100 -> 110 = +10%
    assert sm.trailing_return(s, days=1) == pytest.approx(0.10)


def test_trailing_return_insufficient_history_returns_none():
    s = _series([100, 101, 102])
    assert sm.trailing_return(s, days=365) is None


def test_vs_moving_average():
    s = _series([10] * 199 + [12])  # MA200 = (199*10 + 12)/200 = 10.01
    out = sm.vs_moving_average(s, window=200)
    assert out == pytest.approx(12 / 10.01 - 1.0)


def test_vs_moving_average_too_few_points_none():
    s = _series([10, 11, 12])
    assert sm.vs_moving_average(s, window=200) is None


def test_distance_from_high():
    s = _series([100, 120, 90])  # max 120, ultimo 90 -> (120-90)/120 = 0.25
    assert sm.distance_from_high(s, days=365) == pytest.approx(0.25)


def test_max_drawdown_negative_or_zero():
    s = _series(list(np.linspace(100, 80, 60)))
    dd = sm.max_drawdown(s, days=365)
    assert dd is not None and dd < 0


def test_price_metrics_returns_dataclass():
    s = _series(list(np.linspace(100, 130, 400)))
    pm = sm.price_metrics(s)
    assert pm.return_12m is not None
    assert pm.volatility is not None
    assert pm.max_drawdown_1y is not None
