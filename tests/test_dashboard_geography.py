from soldoni.app import dashboard
from soldoni.data import fundamentals, prices, store
from soldoni.data.fineco_import import ImportedInstrument


def test_auto_created_stock_uses_yahoo_country_macro_area(monkeypatch):
    conn = store.init_db(":memory:")
    fund = fundamentals.get_fundamentals(
        "ACME",
        fetch=lambda ticker: {
            "shortName": "Acme",
            "quoteType": "EQUITY",
            "currency": "USD",
            "country": "United States",
        },
    )
    monkeypatch.setattr(prices, "resolve_ticker", lambda *args, **kwargs: "ACME")
    monkeypatch.setattr(fundamentals, "get_fundamentals", lambda ticker: fund)

    dashboard._auto_create_instruments(
        conn,
        {"US0000000001": ImportedInstrument("US0000000001", "Acme", "USD")},
    )

    assert store.get_instruments(conn)["US0000000001"].macro_area == "Nord America"
