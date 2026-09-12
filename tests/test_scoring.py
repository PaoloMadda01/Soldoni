import pytest
from soldoni.core.scoring import (
    Threshold, metric_band, band_score, pillar_score, composite_score,
    score_instrument, asset_class_from_quote_type)
from soldoni.core.screen_metrics import PriceMetrics
from soldoni.data.fundamentals import Fundamentals


def test_metric_band_monotone_lower_is_better():
    thr = Threshold("monotone", green=15, yellow=25, higher_is_better=False)
    assert metric_band(10, thr) == "green"
    assert metric_band(20, thr) == "yellow"
    assert metric_band(30, thr) == "red"


def test_metric_band_monotone_higher_is_better():
    thr = Threshold("monotone", green=0.15, yellow=0.08, higher_is_better=True)
    assert metric_band(0.20, thr) == "green"
    assert metric_band(0.10, thr) == "yellow"
    assert metric_band(0.05, thr) == "red"


def test_metric_band_sweet():
    thr = Threshold("sweet", green_low=0.02, green_high=0.06, yellow_low=0.0, yellow_high=0.08)
    assert metric_band(0.04, thr) == "green"
    assert metric_band(0.01, thr) == "yellow"
    assert metric_band(0.07, thr) == "yellow"
    assert metric_band(0.09, thr) == "red"


def test_metric_band_none_is_na():
    thr = Threshold("monotone", green=15, yellow=25, higher_is_better=False)
    assert metric_band(None, thr) == "na"


def test_band_score_mapping():
    assert band_score("green") == 100.0
    assert band_score("yellow") == 60.0
    assert band_score("red") == 20.0
    assert band_score("na") is None


def test_pillar_score_ignores_none():
    assert pillar_score([100.0, None, 20.0]) == pytest.approx(60.0)
    assert pillar_score([None, None]) is None


def test_composite_reweights_on_available_pillars():
    pillars = {"value": 100.0, "quality": None, "momentum": 20.0, "dividend": None}
    weights = {"value": 0.30, "quality": 0.35, "momentum": 0.20, "dividend": 0.15}
    # solo value+momentum disponibili: (0.30*100 + 0.20*20) / (0.30+0.20) = 68
    assert composite_score(pillars, weights) == pytest.approx(68.0)


def test_asset_class_from_quote_type():
    assert asset_class_from_quote_type("ETF") == "etf"
    assert asset_class_from_quote_type("MUTUALFUND") == "etf"
    assert asset_class_from_quote_type("EQUITY") == "stock"
    assert asset_class_from_quote_type(None) == "stock"


def _blank_fundamentals(**kw):
    base = dict(
        ticker="X", name="X", quote_type="EQUITY", currency="USD", price=100.0,
        trailing_pe=None, forward_pe=None, price_to_book=None, ev_to_ebitda=None, peg=None,
        roe=None, net_margin=None, operating_margin=None, debt_to_equity=None,
        free_cashflow=None, revenue_growth=None, earnings_growth=None,
        dividend_yield=None, payout_ratio=None, expense_ratio=None, total_assets=None,
        top10_weight=None, holdings_count=None)
    base.update(kw)
    return Fundamentals(**base)


def _blank_pm(**kw):
    base = dict(return_6m=None, return_12m=None, vs_ma200=None,
                dist_from_52w_high=None, volatility=None, max_drawdown_1y=None)
    base.update(kw)
    return PriceMetrics(**base)


def test_score_instrument_stock_end_to_end():
    fund = _blank_fundamentals(trailing_pe=10, roe=0.25, dividend_yield=0.04, payout_ratio=0.4)
    pm = _blank_pm(return_12m=0.20, volatility=0.10)
    res = score_instrument("stock", fund, pm)
    assert res.asset_class == "stock"
    assert 0 <= res.composite <= 100
    assert res.pillars["value"] is not None
    assert res.pillars["dividend"] is not None


def test_score_instrument_etf_uses_etf_pillars():
    fund = _blank_fundamentals(quote_type="ETF", expense_ratio=0.0015, dividend_yield=0.02)
    pm = _blank_pm(return_12m=0.12, vs_ma200=0.05, volatility=0.10, max_drawdown_1y=-0.10)
    res = score_instrument("etf", fund, pm)
    assert set(res.pillars) == {"cost", "risk", "momentum", "income"}
    assert res.composite is not None


def test_negative_payout_is_red():
    fund = _blank_fundamentals(payout_ratio=-0.2)
    pm = _blank_pm()
    res = score_instrument("stock", fund, pm)
    payout = [m for m in res.metrics["dividend"] if m.name == "payout_ratio"][0]
    assert payout.band == "red"
