import pytest
from soldoni.data import fundamentals
from soldoni.data.fundamentals import get_fundamentals, Fundamentals


def test_normalizes_stock_info():
    info = {
        "shortName": "Acme", "quoteType": "EQUITY", "currency": "USD",
        "country": "United States",
        "currentPrice": 100.0, "trailingPE": 18.0, "forwardPE": 15.0,
        "priceToBook": 3.0, "enterpriseToEbitda": 11.0, "trailingPegRatio": 1.2,
        "returnOnEquity": 0.21, "profitMargins": 0.14, "operatingMargins": 0.2,
        "debtToEquity": 120.0, "freeCashflow": 5_000_000.0,
        "revenueGrowth": 0.08, "earningsGrowth": 0.1,
        "dividendYield": 1.5, "payoutRatio": 0.4,
    }
    f = get_fundamentals("ACME", fetch=lambda t: info)
    assert isinstance(f, Fundamentals)
    assert f.ticker == "ACME"
    assert f.name == "Acme"
    assert f.quote_type == "EQUITY"
    assert f.country == "United States"
    assert f.trailing_pe == 18.0
    assert f.debt_to_equity == pytest.approx(1.2)       # 120 -> ratio 1.2
    assert f.dividend_yield == pytest.approx(0.015)     # 1.5% -> frazione 0.015


def test_missing_fields_become_none():
    f = get_fundamentals("X", fetch=lambda t: {"quoteType": "EQUITY"})
    assert f.trailing_pe is None
    assert f.roe is None
    assert f.dividend_yield is None
    assert f.top10_weight is None


def test_empty_info_raises():
    with pytest.raises(ValueError):
        get_fundamentals("X", fetch=lambda t: {})


def test_country_maps_to_macro_area():
    assert fundamentals.macro_area_from_country("United States") == "Nord America"
    assert fundamentals.macro_area_from_country("Italy") == "Europa"
    assert fundamentals.macro_area_from_country("China") == "Asia"
    assert fundamentals.macro_area_from_country("Unknown") == "Non disponibile"
