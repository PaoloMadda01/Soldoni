from soldoni.core.scoring import score_instrument
from soldoni.core.screen_metrics import PriceMetrics
from soldoni.data.fundamentals import Fundamentals, get_fundamentals


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


def test_get_fundamentals_captures_sector():
    f = get_fundamentals("X", fetch=lambda t: {"quoteType": "EQUITY", "sector": "Technology"})
    assert f.sector == "Technology"


def test_tech_high_pe_not_red_with_sector():
    res = score_instrument("stock", _fund(sector="Technology", trailing_pe=35), _pm())
    assert _band(res, "value", "trailing_pe") == "yellow"


def test_same_high_pe_red_without_sector():
    res = score_instrument("stock", _fund(sector=None, trailing_pe=35), _pm())
    assert _band(res, "value", "trailing_pe") == "red"


def test_unknown_sector_uses_default_thresholds():
    res = score_instrument("stock", _fund(sector="Nonexistent", trailing_pe=35), _pm())
    assert _band(res, "value", "trailing_pe") == "red"


def test_financials_meaningless_metrics_are_na():
    res = score_instrument("stock", _fund(
        sector="Financial Services", ev_to_ebitda=12, debt_to_equity=5.0,
        free_cashflow=-1000.0), _pm())
    assert _band(res, "value", "ev_to_ebitda") == "na"
    assert _band(res, "quality", "debt_to_equity") == "na"
    assert _band(res, "quality", "free_cashflow") == "na"


def test_financials_low_pb_is_green():
    res = score_instrument("stock", _fund(sector="Financial Services", price_to_book=0.8), _pm())
    assert _band(res, "value", "price_to_book") == "green"


def test_reit_high_payout_not_penalized():
    res = score_instrument("stock", _fund(sector="Real Estate", payout_ratio=0.95), _pm())
    assert _band(res, "dividend", "payout_ratio") == "na"
