import pandas as pd
import pytest

from soldoni.core.scoring import (
    score_instrument, effective_threshold, STOCK_PILLARS, STOCK_WEIGHTS)
from soldoni.core.screen_metrics import PriceMetrics
from soldoni.data.fundamentals import Fundamentals, get_fundamentals
from soldoni.data.valuation_history import ttm_eps, pe_history


def _fund(**kw):
    base = dict(
        ticker="X", name="X", quote_type="EQUITY", currency="USD", price=100.0,
        trailing_pe=None, forward_pe=None, price_to_book=None, ev_to_ebitda=None, peg=None,
        roe=None, net_margin=None, operating_margin=None, debt_to_equity=None,
        free_cashflow=None, revenue_growth=None, earnings_growth=None,
        dividend_yield=None, payout_ratio=None, expense_ratio=None, total_assets=None,
        top10_weight=None, holdings_count=None, sector=None)
    base.update(kw)
    return Fundamentals(**base)


def _pm(**kw):
    base = dict(return_6m=None, return_12m=None, vs_ma200=None,
                dist_from_52w_high=None, volatility=None, max_drawdown_1y=None)
    base.update(kw)
    return PriceMetrics(**base)


def _band(res, pillar, name):
    return [m.band for m in res.metrics[pillar] if m.name == name][0]


# --- A: Pilastro Crescita ---

def test_growth_pillar_registered_and_weights_sum_to_one():
    assert "growth" in STOCK_PILLARS
    assert "growth" in STOCK_WEIGHTS
    assert sum(STOCK_WEIGHTS.values()) == pytest.approx(1.0)


def test_growth_scored_green():
    res = score_instrument("stock", _fund(revenue_growth=0.20, earnings_growth=0.25), _pm())
    assert res.pillars["growth"] is not None
    assert _band(res, "growth", "revenue_growth") == "green"
    assert _band(res, "growth", "earnings_growth") == "green"


def test_negative_earnings_growth_red():
    res = score_instrument("stock", _fund(earnings_growth=-0.10), _pm())
    assert _band(res, "growth", "earnings_growth") == "red"


# --- effective_threshold (per i gauge) ---

def test_effective_threshold_sector_and_default_and_na():
    assert effective_threshold("trailing_pe", "Technology").green == 25
    assert effective_threshold("trailing_pe", None).green == 15
    assert effective_threshold("ev_to_ebitda", "Financial Services") is None


# --- B: campi analisti ---

def test_get_fundamentals_captures_analysts():
    info = {"quoteType": "EQUITY", "targetMeanPrice": 150.0, "targetHighPrice": 180.0,
            "targetLowPrice": 120.0, "recommendationMean": 1.9,
            "recommendationKey": "buy", "numberOfAnalystOpinions": 20}
    f = get_fundamentals("X", fetch=lambda t: info)
    assert f.target_mean_price == 150.0
    assert f.target_high_price == 180.0
    assert f.recommendation_key == "buy"
    assert f.num_analysts == 20


# --- D: P/E band storico (logica pura) ---

def test_ttm_eps_rolling_4_quarters():
    idx = pd.to_datetime(["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31", "2024-03-31"])
    s = pd.Series([1.0, 1.0, 1.0, 1.0, 2.0], index=idx)
    ttm = ttm_eps(s)
    assert ttm.iloc[0] == pytest.approx(4.0)
    assert ttm.iloc[-1] == pytest.approx(5.0)


def test_pe_history_basic():
    eps = pd.Series([1.0, 1.0, 1.0, 1.0],
                    index=pd.to_datetime(["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31"]))
    price = pd.Series([40.0, 48.0], index=pd.to_datetime(["2024-01-15", "2024-02-15"]))
    pe = pe_history(price, eps)
    assert pe.iloc[0] == pytest.approx(10.0)
    assert pe.iloc[1] == pytest.approx(12.0)


def test_pe_history_empty_without_eps():
    price = pd.Series([40.0], index=pd.to_datetime(["2024-01-15"]))
    assert pe_history(price, pd.Series(dtype=float)).empty
