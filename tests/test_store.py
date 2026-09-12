import sqlite3
from datetime import date, timedelta
import pandas as pd
from soldoni.core.models import OpType, Transaction, Instrument
from soldoni.data import store


def _tx(d, isin, op, qty, amount):
    return Transaction(date(2026, 1, d), date(2026, 1, d), isin, op, qty, amount,
                       0.0, 1.0, 2.95)


def test_transactions_roundtrip_and_dedup(tmp_path):
    db = str(tmp_path / "t.db")
    conn = store.init_db(db)
    txs = [_tx(1, "X", OpType.BUY, 10, 1000.0), _tx(1, "X", OpType.BUY, 10, 1000.0)]
    inserted = store.insert_transactions(conn, txs)
    assert inserted == 1  # duplicato scartato
    loaded = store.get_transactions(conn)
    assert len(loaded) == 1
    assert loaded[0].isin == "X"
    assert loaded[0].op_type is OpType.BUY


def test_instrument_upsert(tmp_path):
    db = str(tmp_path / "t.db")
    conn = store.init_db(db)
    store.upsert_instrument(conn, Instrument("X", "T", "name", "USD", "stock", "Nord America"))
    store.upsert_instrument(conn, Instrument("X", "T2", "name2", "USD", "stock", "Europa",
                                             None, "Finanza", {"Finanza": 1.0}))
    insts = store.get_instruments(conn)
    assert insts["X"].yahoo_ticker == "T2"
    assert insts["X"].macro_area == "Europa"
    assert insts["X"].sector == "Finanza"
    assert insts["X"].sector_weights == {"Finanza": 1.0}


def test_instrument_excluded_roundtrip(tmp_path):
    db = str(tmp_path / "t.db")
    conn = store.init_db(db)
    store.upsert_instrument(conn, Instrument("X", "T", "n", "EUR", "stock", "Europa",
                                             excluded=True))
    store.upsert_instrument(conn, Instrument("Y", "T", "n", "EUR", "stock", "Europa"))
    insts = store.get_instruments(conn)
    assert insts["X"].excluded is True
    assert insts["Y"].excluded is False


def test_init_db_migrates_missing_excluded_column(tmp_path):
    db = str(tmp_path / "t.db")
    raw = sqlite3.connect(db)
    raw.execute(
        """CREATE TABLE instruments (
            isin TEXT PRIMARY KEY, yahoo_ticker TEXT, name TEXT,
            native_currency TEXT, asset_class TEXT, macro_area TEXT, geo_weights TEXT,
            sector TEXT, sector_weights TEXT)"""
    )
    raw.execute(
        """INSERT INTO instruments (isin, yahoo_ticker, name, native_currency,
                                    asset_class, macro_area)
           VALUES ('Z','T','n','EUR','stock','Europa')"""
    )
    raw.commit()
    raw.close()
    conn = store.init_db(db)
    assert store.get_instruments(conn)["Z"].excluded is False


def test_prices_cache_roundtrip(tmp_path):
    conn = store.init_db(str(tmp_path / "c.db"))
    idx = pd.to_datetime(["2026-01-01", "2026-01-02"])
    df = pd.DataFrame({"close": [10.0, 11.0], "adj_close": [9.5, 10.5]}, index=idx)
    store.write_prices_cache(conn, "X", df)
    back = store.read_prices_cache(conn, "X")
    assert list(back["close"]) == [10.0, 11.0]
    assert list(back["adj_close"]) == [9.5, 10.5]
    assert list(back.index.date) == [date(2026, 1, 1), date(2026, 1, 2)]


def test_read_prices_cache_empty():
    conn = store.init_db(":memory:")
    back = store.read_prices_cache(conn, "NOPE")
    assert back.empty
    assert list(back.columns) == ["close", "adj_close"]


def test_fx_cache_roundtrip(tmp_path):
    conn = store.init_db(str(tmp_path / "c.db"))
    s = pd.Series([1.1, 1.2], index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
    store.write_fx_cache(conn, "EURUSD=X", s)
    back = store.read_fx_cache(conn, "EURUSD=X")
    assert list(back.values) == [1.1, 1.2]
    assert list(back.index.date) == [date(2026, 1, 1), date(2026, 1, 2)]


def test_clear_recent_cache_keeps_old(tmp_path):
    conn = store.init_db(str(tmp_path / "c.db"))
    old = date.today() - timedelta(days=30)
    recent = date.today() - timedelta(days=2)
    df = pd.DataFrame({"close": [1.0, 2.0], "adj_close": [1.0, 2.0]},
                      index=pd.to_datetime([old.isoformat(), recent.isoformat()]))
    store.write_prices_cache(conn, "X", df)
    store.clear_recent_cache(conn, days=10)
    back = store.read_prices_cache(conn, "X")
    assert list(back.index.date) == [old]
