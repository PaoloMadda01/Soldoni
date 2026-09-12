from soldoni.data import store


def _conn():
    return store.init_db(":memory:")


def test_add_and_get_watchlist():
    conn = _conn()
    store.add_to_watchlist(conn, "AAPL", "US0378331005", "Apple", "stock")
    rows = store.get_watchlist(conn)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["isin"] == "US0378331005"
    assert rows[0]["asset_class"] == "stock"


def test_add_is_idempotent_upsert():
    conn = _conn()
    store.add_to_watchlist(conn, "AAPL", "US0378331005", "Apple", "stock")
    store.add_to_watchlist(conn, "AAPL", "US0378331005", "Apple Inc", "stock")
    rows = store.get_watchlist(conn)
    assert len(rows) == 1
    assert rows[0]["name"] == "Apple Inc"


def test_remove_from_watchlist():
    conn = _conn()
    store.add_to_watchlist(conn, "AAPL", "US0378331005", "Apple", "stock")
    store.add_to_watchlist(conn, "VWCE.DE", "IE00BK5BQT80", "Vanguard FTSE All-World", "etf")
    store.remove_from_watchlist(conn, "AAPL")
    rows = store.get_watchlist(conn)
    assert [r["ticker"] for r in rows] == ["VWCE.DE"]
