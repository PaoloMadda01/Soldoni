import pandas as pd
import pytest

from soldoni.core import financial_trends as ft


def _annual(values):
    idx = pd.to_datetime([f"{2021 + i}-12-31" for i in range(len(values))])
    return pd.Series(values, index=idx, dtype=float)


def test_ttm_sums_four_periods():
    q = pd.Series(range(1, 7), index=pd.to_datetime(
        ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30"]),
        dtype=float)
    out = ft.ttm(q)
    assert out.iloc[0] == 1 + 2 + 3 + 4
    assert out.iloc[-1] == 3 + 4 + 5 + 6
    assert len(out) == 3


def test_ttm_too_few_points_is_empty():
    assert ft.ttm(_annual([1, 2, 3])).empty
    assert ft.ttm(pd.Series(dtype=float)).empty


def test_yoy_growth_annual():
    out = ft.yoy_growth(_annual([100, 110, 121]), periods=1)
    assert out.iloc[0] == pytest.approx(0.10)
    assert out.iloc[1] == pytest.approx(0.10)


def test_yoy_growth_quarterly_same_quarter():
    q = pd.Series([100, 50, 60, 70, 120], index=pd.to_datetime(
        ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31"]), dtype=float)
    out = ft.yoy_growth(q, periods=4)
    assert out.iloc[-1] == pytest.approx(0.20)  # Q1'25 vs Q1'24


def test_cagr_known_case():
    s = _annual([100, 0, 0, 144])  # ~3 anni, 100 -> 144
    assert ft.cagr(s) == pytest.approx(0.1292, abs=1e-2)


def test_cagr_flat_is_zero():
    assert ft.cagr(_annual([100, 100, 100])) == pytest.approx(0.0)


def test_cagr_guards_return_none():
    assert ft.cagr(_annual([100])) is None
    assert ft.cagr(_annual([-10, 50])) is None
    assert ft.cagr(pd.Series(dtype=float)) is None


def test_indexed_to_100():
    out = ft.indexed_to_100(_annual([200, 250, 300]))
    assert out.iloc[0] == pytest.approx(100.0)
    assert out.iloc[-1] == pytest.approx(150.0)


def test_indexed_to_100_nonpositive_base_is_empty():
    assert ft.indexed_to_100(_annual([0, 100])).empty
    assert ft.indexed_to_100(_annual([-5, 100])).empty


def test_margin_basic_and_guards():
    rev = _annual([100, 200, 400])
    ni = _annual([10, 0, 80])
    out = ft.margin(ni, rev)
    assert out.iloc[0] == pytest.approx(0.10)
    assert out.iloc[-1] == pytest.approx(0.20)
    # denominatore 0 escluso
    rev0 = _annual([0, 200])
    ni0 = _annual([5, 20])
    m = ft.margin(ni0, rev0)
    assert len(m) == 1 and m.iloc[0] == pytest.approx(0.10)
