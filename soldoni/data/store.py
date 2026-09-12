import json
import sqlite3
from datetime import date, timedelta
import pandas as pd
from soldoni.core.models import OpType, Transaction, Instrument
from soldoni.core.rebalancing import validate_target_weights
from soldoni.core.etf_costs import EtfExpenseRatio, validate_expense_ratio


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    initialize_schema(conn)
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Crea e aggiorna lo schema anche dopo il ripristino di un vecchio backup."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS instruments (
            isin TEXT PRIMARY KEY, yahoo_ticker TEXT, name TEXT,
            native_currency TEXT, asset_class TEXT, macro_area TEXT, geo_weights TEXT,
            sector TEXT, sector_weights TEXT, excluded INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT, value_date TEXT, isin TEXT, op_type TEXT,
            quantity REAL, amount_eur REAL, price_native REAL, fx_rate REAL,
            commission_eur REAL, source TEXT, raw_desc TEXT,
            UNIQUE(trade_date, isin, op_type, quantity, amount_eur)
        );
        CREATE TABLE IF NOT EXISTS prices_cache (
            ticker TEXT, date TEXT, close_native REAL, adj_close_native REAL,
            PRIMARY KEY (ticker, date)
        );
        CREATE TABLE IF NOT EXISTS fx_cache (
            pair TEXT, date TEXT, rate REAL, PRIMARY KEY (pair, date)
        );
        CREATE TABLE IF NOT EXISTS watchlist (
            ticker TEXT PRIMARY KEY,
            isin TEXT,
            name TEXT,
            asset_class TEXT,
            added_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS allocation_targets (
            isin TEXT PRIMARY KEY,
            target_weight REAL NOT NULL CHECK(target_weight >= 0 AND target_weight <= 1)
        );
        CREATE TABLE IF NOT EXISTS etf_expense_ratios (
            isin TEXT PRIMARY KEY,
            expense_ratio REAL NOT NULL CHECK(expense_ratio >= 0 AND expense_ratio <= 1),
            source TEXT NOT NULL CHECK(source IN ('Yahoo', 'Manuale')),
            saved_on TEXT NOT NULL
        );
        """
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(instruments)")}
    if "excluded" not in cols:
        conn.execute("ALTER TABLE instruments ADD COLUMN excluded INTEGER DEFAULT 0")
    conn.commit()


def insert_transactions(conn: sqlite3.Connection, txs: list[Transaction]) -> int:
    inserted = 0
    for t in txs:
        cur = conn.execute(
            """INSERT OR IGNORE INTO transactions
               (trade_date, value_date, isin, op_type, quantity, amount_eur,
                price_native, fx_rate, commission_eur, source, raw_desc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (t.trade_date.isoformat(), t.value_date.isoformat(), t.isin, t.op_type.value,
             t.quantity, t.amount_eur, t.price_native, t.fx_rate, t.commission_eur,
             t.source, t.raw_desc),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


def get_transactions(conn: sqlite3.Connection) -> list[Transaction]:
    rows = conn.execute(
        """SELECT trade_date, value_date, isin, op_type, quantity, amount_eur,
                  price_native, fx_rate, commission_eur, source, raw_desc
           FROM transactions ORDER BY trade_date, isin"""
    ).fetchall()
    return [
        Transaction(
            trade_date=date.fromisoformat(r[0]), value_date=date.fromisoformat(r[1]),
            isin=r[2], op_type=OpType(r[3]), quantity=r[4], amount_eur=r[5],
            price_native=r[6], fx_rate=r[7], commission_eur=r[8], source=r[9], raw_desc=r[10],
        )
        for r in rows
    ]


def upsert_instrument(conn: sqlite3.Connection, inst: Instrument) -> None:
    conn.execute(
        """INSERT INTO instruments
           (isin, yahoo_ticker, name, native_currency, asset_class, macro_area, geo_weights,
            sector, sector_weights, excluded)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(isin) DO UPDATE SET
             yahoo_ticker=excluded.yahoo_ticker, name=excluded.name,
             native_currency=excluded.native_currency, asset_class=excluded.asset_class,
             macro_area=excluded.macro_area, geo_weights=excluded.geo_weights,
             sector=excluded.sector, sector_weights=excluded.sector_weights,
             excluded=excluded.excluded""",
        (inst.isin, inst.yahoo_ticker, inst.name, inst.native_currency,
         inst.asset_class, inst.macro_area,
         json.dumps(inst.geo_weights) if inst.geo_weights else None,
         inst.sector,
         json.dumps(inst.sector_weights) if inst.sector_weights else None,
         int(inst.excluded)),
    )
    conn.commit()


def get_instruments(conn: sqlite3.Connection) -> dict[str, Instrument]:
    rows = conn.execute(
        """SELECT isin, yahoo_ticker, name, native_currency, asset_class,
                  macro_area, geo_weights, sector, sector_weights, excluded FROM instruments"""
    ).fetchall()
    out: dict[str, Instrument] = {}
    for r in rows:
        out[r[0]] = Instrument(
            isin=r[0], yahoo_ticker=r[1], name=r[2], native_currency=r[3],
            asset_class=r[4], macro_area=r[5],
            geo_weights=json.loads(r[6]) if r[6] else None,
            sector=r[7] or "",
            sector_weights=json.loads(r[8]) if r[8] else None,
            excluded=bool(r[9]),
        )
    return out


def read_prices_cache(conn: sqlite3.Connection, ticker: str) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT date, close_native, adj_close_native FROM prices_cache "
        "WHERE ticker=? ORDER BY date", (ticker,)).fetchall()
    if not rows:
        return pd.DataFrame(columns=["close", "adj_close"])
    return pd.DataFrame(
        {"close": [r[1] for r in rows], "adj_close": [r[2] for r in rows]},
        index=pd.to_datetime([r[0] for r in rows]))


def write_prices_cache(conn: sqlite3.Connection, ticker: str, df: pd.DataFrame) -> None:
    params = [(ticker, ts.date().isoformat(), float(c), float(a))
              for ts, c, a in zip(df.index, df["close"], df["adj_close"])]
    conn.executemany(
        "INSERT OR REPLACE INTO prices_cache (ticker, date, close_native, adj_close_native) "
        "VALUES (?,?,?,?)", params)
    conn.commit()


def read_fx_cache(conn: sqlite3.Connection, pair: str) -> pd.Series:
    rows = conn.execute(
        "SELECT date, rate FROM fx_cache WHERE pair=? ORDER BY date", (pair,)).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series([r[1] for r in rows], index=pd.to_datetime([r[0] for r in rows]))


def write_fx_cache(conn: sqlite3.Connection, pair: str, series: pd.Series) -> None:
    params = [(pair, ts.date().isoformat(), float(v)) for ts, v in zip(series.index, series.values)]
    conn.executemany(
        "INSERT OR REPLACE INTO fx_cache (pair, date, rate) VALUES (?,?,?)", params)
    conn.commit()


def clear_recent_cache(conn: sqlite3.Connection, days: int = 10) -> None:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn.execute("DELETE FROM prices_cache WHERE date >= ?", (cutoff,))
    conn.execute("DELETE FROM fx_cache WHERE date >= ?", (cutoff,))
    conn.commit()


def cached_tickers(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM prices_cache").fetchall()]


def cached_pairs(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT pair FROM fx_cache").fetchall()]


def add_to_watchlist(conn: sqlite3.Connection, ticker: str, isin: str | None,
                     name: str | None, asset_class: str) -> None:
    """Inserisce o aggiorna una voce della watchlist (chiave: ticker)."""
    conn.execute(
        """INSERT INTO watchlist (ticker, isin, name, asset_class, added_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(ticker) DO UPDATE SET
             isin=excluded.isin, name=excluded.name, asset_class=excluded.asset_class""",
        (ticker, isin, name, asset_class, date.today().isoformat()),
    )
    conn.commit()


def get_watchlist(conn: sqlite3.Connection) -> list[dict]:
    """Voci della watchlist, ordinate per data di inserimento."""
    rows = conn.execute(
        "SELECT ticker, isin, name, asset_class, added_at FROM watchlist "
        "ORDER BY added_at, ticker").fetchall()
    return [
        {"ticker": r[0], "isin": r[1], "name": r[2], "asset_class": r[3], "added_at": r[4]}
        for r in rows
    ]


def remove_from_watchlist(conn: sqlite3.Connection, ticker: str) -> None:
    conn.execute("DELETE FROM watchlist WHERE ticker=?", (ticker,))
    conn.commit()


def replace_allocation_targets(conn: sqlite3.Connection,
                               targets: dict[str, float]) -> None:
    validate_target_weights(targets)
    with conn:
        conn.execute("DELETE FROM allocation_targets")
        conn.executemany(
            "INSERT INTO allocation_targets (isin, target_weight) VALUES (?,?)",
            sorted(targets.items()),
        )


def get_allocation_targets(conn: sqlite3.Connection) -> dict[str, float]:
    rows = conn.execute(
        "SELECT isin, target_weight FROM allocation_targets ORDER BY isin").fetchall()
    return {isin: weight for isin, weight in rows}


def get_etf_expense_ratios(conn: sqlite3.Connection) -> dict[str, EtfExpenseRatio]:
    """Legge i TER salvati, con fonte e data di acquisizione."""
    rows = conn.execute(
        "SELECT isin, expense_ratio, source, saved_on FROM etf_expense_ratios").fetchall()
    return {isin: EtfExpenseRatio(ratio, source, date.fromisoformat(saved_on))
            for isin, ratio, source, saved_on in rows}


def upsert_etf_expense_ratio(conn: sqlite3.Connection, isin: str,
                             expense_ratio: float, source: str) -> bool:
    """Salva un TER; un aggiornamento Yahoo non sovrascrive un valore manuale."""
    validate_expense_ratio(expense_ratio)
    if not isin.strip() or source not in ("Yahoo", "Manuale"):
        raise ValueError("ISIN o fonte del TER non validi.")
    with conn:
        cursor = conn.execute(
            """INSERT INTO etf_expense_ratios (isin, expense_ratio, source, saved_on)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(isin) DO UPDATE SET
                 expense_ratio=excluded.expense_ratio, source=excluded.source,
                 saved_on=excluded.saved_on
               WHERE etf_expense_ratios.source != 'Manuale' OR excluded.source = 'Manuale'""",
            (isin, expense_ratio, source, date.today().isoformat()),
        )
    return cursor.rowcount > 0


def delete_etf_expense_ratio(conn: sqlite3.Connection, isin: str) -> None:
    """Rimuove il TER salvato, permettendo un successivo recupero automatico."""
    with conn:
        conn.execute("DELETE FROM etf_expense_ratios WHERE isin=?", (isin,))
