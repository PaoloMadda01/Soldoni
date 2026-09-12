import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
import pandas as pd
import yfinance as yf

from soldoni.data import store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefreshResult:
    updated_tickers: tuple[str, ...]
    updated_pairs: tuple[str, ...]
    price_errors: tuple[tuple[str, str], ...]
    fx_errors: tuple[tuple[str, str], ...]


def missing_dates(have: set[date], needed: list[date]) -> list[date]:
    return [d for d in needed if d not in have]


def get_price_history(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Ritorna DataFrame con colonne 'close' e 'adj_close' (valuta nativa), indice datetime."""
    df = yf.download(ticker, start=start, end=end, auto_adjust=False, progress=False)
    if df.empty:
        raise ValueError(f"Nessun prezzo da yfinance per '{ticker}'")
    out = pd.DataFrame({
        "close": df["Close"].squeeze(),
        "adj_close": df["Adj Close"].squeeze(),
    })
    return out


def get_fx_history(pair: str, start: date, end: date) -> pd.Series:
    """pair es. 'EURUSD=X'. Ritorna la serie dei tassi (1 EUR = x valuta)."""
    df = yf.download(pair, start=start, end=end, auto_adjust=False, progress=False)
    if df.empty:
        raise ValueError(f"Nessun cambio da yfinance per '{pair}'")
    return df["Close"].squeeze()


def get_current_price(ticker: str) -> float:
    df = yf.download(ticker, period="5d", auto_adjust=False, progress=False)
    if df.empty:
        raise ValueError(f"Nessun prezzo corrente per '{ticker}'")
    return float(df["Close"].squeeze().dropna().iloc[-1])


_YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
_SEARCH_HEADERS = {"User-Agent": "Mozilla/5.0"}
_RESOLVABLE_TYPES = {"EQUITY", "ETF", "MUTUALFUND"}


def _yahoo_search(query: str, timeout: float = 20.0) -> list[dict]:
    """Interroga l'endpoint di ricerca Yahoo e ritorna la lista grezza dei 'quotes'."""
    url = _YAHOO_SEARCH_URL + "?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers=_SEARCH_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    return data.get("quotes", [])


def _candidate_symbols(quotes: list[dict]) -> list[str]:
    """Estrae i simboli negoziabili (azioni/ETF/fondi) preservando l'ordine Yahoo."""
    return [
        q["symbol"]
        for q in quotes
        if q.get("symbol") and q.get("quoteType") in _RESOLVABLE_TYPES
    ]


def _has_prices(ticker: str) -> str | None:
    """Ritorna la valuta del ticker se ha prezzi recenti, altrimenti None.

    Stringa vuota se i prezzi esistono ma la valuta non è rilevabile.
    """
    df = yf.download(ticker, period="10d", auto_adjust=False, progress=False)
    if df.empty or df["Close"].squeeze().dropna().empty:
        return None
    try:
        return yf.Ticker(ticker).fast_info.get("currency") or ""
    except Exception:
        return ""


def _select_priced(
    symbols: list[str], base_currency: str, probe: Callable[[str], str | None]
) -> str | None:
    """Sceglie il primo simbolo con prezzi, preferendo quello in `base_currency`.

    `probe(symbol)` ritorna la valuta (eventualmente '') se ci sono prezzi, altrimenti None.
    Ritorna None se nessun simbolo ha prezzi.
    """
    fallback = None
    for sym in symbols:
        currency = probe(sym)
        if currency is None:
            continue
        if currency == base_currency:
            return sym
        if fallback is None:
            fallback = sym
    return fallback


def resolve_ticker(
    isin: str,
    name: str | None = None,
    ticker: str | None = None,
    base_currency: str = "EUR",
) -> str:
    """Risolve un ISIN nel ticker Yahoo con storico prezzi.

    Ordine: (1) se il `ticker` noto ha già prezzi lo usa; (2) ricerca per ISIN;
    (3) se né ticker né ISIN trovano prezzi, fallback sulla ricerca per nome
    (la ricerca per ISIN spesso restituisce solo quotazioni marginali/delistate).
    Tra i candidati di ricerca preferisce la valuta `base_currency` per evitare
    conversioni FX. Solleva ValueError se nessun ticker fornisce prezzi.
    """
    if ticker and _has_prices(ticker) is not None:
        return ticker
    resolved = _select_priced(_candidate_symbols(_yahoo_search(isin)), base_currency, _has_prices)
    if resolved is None and name:
        resolved = _select_priced(_candidate_symbols(_yahoo_search(name)), base_currency, _has_prices)
    if resolved is None:
        detail = f"ISIN '{isin}'" + (f" / nome '{name}'" if name else "")
        raise ValueError(f"Nessun ticker Yahoo con prezzi per {detail}")
    return resolved


def gap_ranges(cached_dates: set[date], start: date, end: date) -> list[tuple[date, date]]:
    """Range da scaricare AUTOMATICAMENTE: cache vuota -> [(start,end)]; altrimenti solo la
    testa mancante (storia più vecchia di quella in cache). I giorni nuovi fino a oggi NON si
    scaricano da soli — si aggiornano col pulsante 'Aggiorna prezzi' (vedi refresh_recent)."""
    if start > end:
        return []
    if not cached_dates:
        return [(start, end)]
    cmin = min(cached_dates)
    if start < cmin:
        return [(start, min(end, cmin - timedelta(days=1)))]
    return []


def get_price_history_cached(conn, ticker: str, start: date, end: date,
                             fetch=get_price_history) -> pd.DataFrame:
    """Serve [start,end] dalla cache, scaricando solo i gap. ValueError se nessun dato."""
    cached = store.read_prices_cache(conn, ticker)
    have = set(cached.index.date) if not cached.empty else set()
    for s, e in gap_ranges(have, start, end):
        try:
            df = fetch(ticker, s, e)
        except ValueError:
            continue
        store.write_prices_cache(conn, ticker, df)
    cached = store.read_prices_cache(conn, ticker)
    if cached.empty:
        raise ValueError(f"Nessun prezzo in cache/Yahoo per '{ticker}'")
    out = cached[(cached.index >= pd.Timestamp(start)) & (cached.index <= pd.Timestamp(end))]
    if out.empty:
        raise ValueError(f"Nessun prezzo in cache/Yahoo per '{ticker}'")
    return out


def get_fx_history_cached(conn, pair: str, start: date, end: date,
                          fetch=get_fx_history) -> pd.Series:
    """Serve [start,end] dalla cache dei cambi, scaricando solo i gap. ValueError se vuoto."""
    cached = store.read_fx_cache(conn, pair)
    have = set(cached.index.date) if not cached.empty else set()
    for s, e in gap_ranges(have, start, end):
        try:
            series = fetch(pair, s, e)
        except ValueError:
            continue
        store.write_fx_cache(conn, pair, series)
    cached = store.read_fx_cache(conn, pair)
    if cached.empty:
        raise ValueError(f"Nessun cambio in cache/Yahoo per '{pair}'")
    out = cached[(cached.index >= pd.Timestamp(start)) & (cached.index <= pd.Timestamp(end))]
    if out.empty:
        raise ValueError(f"Nessun cambio in cache/Yahoo per '{pair}'")
    return out


def refresh_recent(conn, tickers, pairs, days: int = 10,
                   fetch_price=get_price_history, fetch_fx=get_fx_history) -> RefreshResult:
    """Riscarica la finestra recente (ultimi `days` giorni) e aggiorna la cache (per il pulsante
    'Aggiorna prezzi'). Upsert: i valori recenti vengono sovrascritti con i dati nuovi."""
    start = date.today() - timedelta(days=days)
    end = date.today()
    updated_tickers = []
    updated_pairs = []
    price_errors = []
    fx_errors = []
    for ticker in tickers:
        try:
            frame = fetch_price(ticker, start, end)
            if frame.empty:
                raise ValueError("nessun prezzo restituito")
            store.write_prices_cache(conn, ticker, frame)
            updated_tickers.append(ticker)
        except Exception as e:
            logger.exception("Aggiornamento prezzo fallito per %s", ticker)
            price_errors.append((ticker, str(e) or type(e).__name__))
    for pair in pairs:
        try:
            series = fetch_fx(pair, start, end)
            if series.dropna().empty:
                raise ValueError("nessun cambio restituito")
            store.write_fx_cache(conn, pair, series)
            updated_pairs.append(pair)
        except Exception as e:
            logger.exception("Aggiornamento cambio fallito per %s", pair)
            fx_errors.append((pair, str(e) or type(e).__name__))
    return RefreshResult(
        tuple(updated_tickers), tuple(updated_pairs),
        tuple(price_errors), tuple(fx_errors))
