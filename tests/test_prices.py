import pandas as pd
from datetime import date
from soldoni.data import store
from soldoni.data import prices
from soldoni.data.prices import missing_dates, _candidate_symbols, _select_priced, gap_ranges


def test_missing_dates_excludes_cached():
    have = {date(2026, 1, 1), date(2026, 1, 2)}
    needed = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
    assert missing_dates(have, needed) == [date(2026, 1, 3)]


def test_candidate_symbols_filters_to_tradeable_types():
    quotes = [
        {"symbol": "FLXT.MI", "quoteType": "ETF"},
        {"symbol": "IE000CM02H85.SG", "quoteType": "MUTUALFUND"},
        {"symbol": "EURUSD=X", "quoteType": "CURRENCY"},
        {"quoteType": "ETF"},  # senza symbol
    ]
    assert _candidate_symbols(quotes) == ["FLXT.MI", "IE000CM02H85.SG"]


def test_select_priced_prefers_base_currency():
    prices = {"FLXT.L": "USD", "FLXT.MI": "EUR", "FLXT.DE": "EUR"}
    assert _select_priced(["FLXT.L", "FLXT.MI", "FLXT.DE"], "EUR", prices.get) == "FLXT.MI"


def test_select_priced_falls_back_to_first_priced_when_no_base_currency():
    prices = {"FLXT.SW": "USD", "FLXT.L": "USD"}
    assert _select_priced(["FLXT.SW", "FLXT.L"], "EUR", prices.get) == "FLXT.SW"


def test_select_priced_returns_none_when_no_prices():
    assert _select_priced(["IE000CM02H85.SG"], "EUR", lambda s: None) is None


def test_gap_ranges_empty_cache():
    assert gap_ranges(set(), date(2026, 1, 1), date(2026, 1, 5)) == \
        [(date(2026, 1, 1), date(2026, 1, 5))]


def test_gap_ranges_fully_covered():
    have = {date(2026, 1, 1), date(2026, 1, 5)}
    assert gap_ranges(have, date(2026, 1, 2), date(2026, 1, 4)) == []


def test_gap_ranges_tail_not_fetched():
    # i giorni nuovi (coda) NON si scaricano automaticamente
    have = {date(2026, 1, 1), date(2026, 1, 3)}
    assert gap_ranges(have, date(2026, 1, 1), date(2026, 1, 6)) == []


def test_gap_ranges_head():
    have = {date(2026, 1, 5), date(2026, 1, 8)}
    assert gap_ranges(have, date(2026, 1, 1), date(2026, 1, 8)) == \
        [(date(2026, 1, 1), date(2026, 1, 4))]


def test_gap_ranges_only_head_when_both_sides():
    # con testa mancante si scarica solo la testa, mai la coda
    have = {date(2026, 1, 5), date(2026, 1, 8)}
    assert gap_ranges(have, date(2026, 1, 1), date(2026, 1, 12)) == \
        [(date(2026, 1, 1), date(2026, 1, 4))]


def _fake_prices(values):
    idx = pd.to_datetime([d for d, _ in values])
    return pd.DataFrame({"close": [v for _, v in values], "adj_close": [v for _, v in values]},
                        index=idx)


def test_get_price_history_cached_uses_cache(tmp_path):
    conn = store.init_db(str(tmp_path / "c.db"))
    calls = []

    def fake(ticker, s, e):
        calls.append((s, e))
        return _fake_prices([("2026-01-01", 10.0), ("2026-01-02", 11.0), ("2026-01-03", 12.0)])

    out1 = prices.get_price_history_cached(conn, "X", date(2026, 1, 1), date(2026, 1, 3), fetch=fake)
    assert list(out1["close"]) == [10.0, 11.0, 12.0]
    assert len(calls) == 1
    out2 = prices.get_price_history_cached(conn, "X", date(2026, 1, 1), date(2026, 1, 3), fetch=fake)
    assert len(calls) == 1            # cache hit: fetcher non richiamato
    assert list(out2["close"]) == [10.0, 11.0, 12.0]


def test_get_price_history_cached_no_tail_fetch(tmp_path):
    conn = store.init_db(str(tmp_path / "c.db"))

    def fake1(ticker, s, e):
        return _fake_prices([("2026-01-01", 10.0), ("2026-01-02", 11.0), ("2026-01-03", 12.0)])
    prices.get_price_history_cached(conn, "X", date(2026, 1, 1), date(2026, 1, 3), fetch=fake1)

    calls2 = []

    def fake2(ticker, s, e):
        calls2.append((s, e))
        return _fake_prices([("2026-01-04", 13.0), ("2026-01-05", 14.0)])
    out = prices.get_price_history_cached(conn, "X", date(2026, 1, 1), date(2026, 1, 5), fetch=fake2)
    assert calls2 == []                              # la coda non si scarica automaticamente
    assert list(out["close"]) == [10.0, 11.0, 12.0]  # serve la cache esistente


def test_get_price_history_cached_fetches_head_gap(tmp_path):
    conn = store.init_db(str(tmp_path / "c.db"))

    def fake1(ticker, s, e):
        return _fake_prices([("2026-01-03", 12.0), ("2026-01-04", 13.0), ("2026-01-05", 14.0)])
    prices.get_price_history_cached(conn, "X", date(2026, 1, 3), date(2026, 1, 5), fetch=fake1)

    calls = []

    def fake2(ticker, s, e):
        calls.append((s, e))
        return _fake_prices([("2026-01-01", 10.0), ("2026-01-02", 11.0)])
    out = prices.get_price_history_cached(conn, "X", date(2026, 1, 1), date(2026, 1, 5), fetch=fake2)
    assert calls == [(date(2026, 1, 1), date(2026, 1, 2))]   # testa mancante scaricata
    assert list(out["close"]) == [10.0, 11.0, 12.0, 13.0, 14.0]


def test_refresh_recent_updates_cache(tmp_path):
    conn = store.init_db(str(tmp_path / "c.db"))
    pcalls, fxcalls = [], []

    def fp(ticker, s, e):
        pcalls.append(ticker)
        return _fake_prices([(date.today().isoformat(), 99.0)])

    def ff(pair, s, e):
        fxcalls.append(pair)
        return pd.Series([1.23], index=pd.to_datetime([date.today().isoformat()]))

    prices.refresh_recent(conn, ["X"], ["EURUSD=X"], days=10, fetch_price=fp, fetch_fx=ff)
    assert pcalls == ["X"]
    assert fxcalls == ["EURUSD=X"]
    assert store.cached_tickers(conn) == ["X"]
    assert store.cached_pairs(conn) == ["EURUSD=X"]
    assert list(store.read_prices_cache(conn, "X")["close"]) == [99.0]


def test_get_price_history_cached_raises_when_no_data(tmp_path):
    conn = store.init_db(str(tmp_path / "c.db"))

    def fake_empty(ticker, s, e):
        raise ValueError("nessun prezzo")
    try:
        prices.get_price_history_cached(conn, "X", date(2026, 1, 1), date(2026, 1, 3),
                                        fetch=fake_empty)
        assert False, "doveva sollevare ValueError"
    except ValueError:
        pass
