import csv
from dataclasses import replace
from datetime import date, datetime
from html.parser import HTMLParser
from io import StringIO
import json
import logging
import math
import re
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

import yfinance as yf

from soldoni.core.etf_profile import EtfHolding, EtfHoldings, EtfProfile

logger = logging.getLogger(__name__)
_CATALOG_URL = ("https://www.ishares.com/varnish-api/blk-product-screener-server/"
                "api/v1/product-screener/product-data")
_MARKETS = {"L": ("gb", "en", "ishares-uk"),
            "MI": ("it", "it", "ishares-it"),
            "DE": ("de", "de", "ishares-de")}


class CatalogUnavailable(ValueError):
    """The shared source failed, so other candidates cannot use it in this search."""


def _download(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.ishares.com", "www.blackrock.com"}:
        raise ValueError("Fonte ETF non consentita.")
    with urlopen(url, timeout=25) as response:
        if urlparse(response.url).hostname not in {"www.ishares.com", "www.blackrock.com"}:
            raise ValueError("Il download ETF è stato reindirizzato a una fonte diversa.")
        data = response.read(12_000_001)
    if len(data) > 12_000_000:
        raise ValueError("Download ETF troppo grande.")
    return data.decode("utf-8-sig")


def get_ishares_catalog(market: str = "L", fetch=_download) -> dict:
    """Read the current official catalog for one listing market."""
    country, language, site = _MARKETS.get(market, _MARKETS["L"])
    url = _CATALOG_URL + "?" + urlencode({"country": country, "language": language,
                                         "siteName": site, "userType": "individual"})
    if market == "DE":
        url = ("https://www.ishares.com/de/privatanleger/de/product-screener/"
               "product-screener-v3.jsn?" + urlencode({
                   "dcrPath": "/templatedata/config/product-screener-v3/data/de/germany/"
                              "product-screener/ishares-product-screener-backend-config",
                   "siteEntryPassthrough": "true"}))
    try:
        catalog = json.loads(fetch(url))
        if market == "DE":
            if catalog.get("status") != "success":
                raise ValueError("Il catalogo tedesco non ha restituito i dati.")
            table = catalog["data"]["tableData"]
            columns = [column["name"] for column in table["columns"]]
            catalog = {str(i): dict(zip(columns, row, strict=True))
                       for i, row in enumerate(table["data"])}
        if (not catalog or not isinstance(catalog, dict) or
                not all(isinstance(v, dict) for v in catalog.values())):
            raise ValueError("Formato del catalogo iShares non riconosciuto.")
        return catalog
    except Exception as e:
        logger.exception("Lettura catalogo ETF fallita")
        raise CatalogUnavailable(f"Catalogo iShares non disponibile: {e}") from e


def _isin(value: str) -> str:
    value = value.strip().upper()
    if value and not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value):
        raise ValueError("ISIN ETF non valido.")
    return value


def profile_from_catalog(catalog: dict, ticker: str, isin: str = "") -> EtfProfile | None:
    """Resolve an exact ISIN, or a ticker in the caller's market catalog."""
    isin = _isin(isin)
    symbol = ticker.upper().rsplit(".", 1)[0]
    matches = [row for row in catalog.values() if "etf" in row.get("productView", [])
               and (row.get("isin") == isin if isin else
                    str(row.get("localExchangeTicker", "")).upper() == symbol)]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("Identificazione ETF ambigua: usa l'ISIN della classe.")
    row = matches[0]
    matched_isin = _isin(row.get("isin", ""))
    if not matched_isin:
        raise ValueError("ISIN mancante nel catalogo ETF.")
    name = row.get("fundName", "")
    share_class = row.get("investorClassCode")
    currency_match = re.search(r"\b(EUR|USD|GBP|CHF|JPY|AUD|CAD)\s+(?:Daily\s+)?(?:Hedged|Hdg)\b",
                               name, re.IGNORECASE)
    # The official ETF catalog maps its blank share-class code to Unhedged.
    # Currency hedging can also be a policy of the fund itself (e.g. IUSE).
    hedged = True if currency_match or share_class == "Hedged" else (
        False if share_class == " " else None)
    hedge_currency = (currency_match.group(1).upper() if currency_match else
                      row.get("seriesBaseCurrencyCode", "") if hedged else "")
    path = row.get("productPageUrl", "")
    product = re.search(r"/(?:products|produkte|prodotti)/(\d+)(/[^?#]*)?$", path)
    if not product:
        raise ValueError("Pagina ufficiale ETF mancante nel catalogo.")
    source = ("https://www.ishares.com/uk/individual/en/products/" + product.group(1) +
              (product.group(2) or ""))
    ratio = row.get("ter")
    ratio = ratio.get("r") if isinstance(ratio, dict) else None
    if ratio is not None:
        ratio = float(ratio) / 100.0
        if not math.isfinite(ratio) or not 0 <= ratio <= 1:
            raise ValueError("TER non valido nel catalogo ETF.")
    distribution = {"accumulating": "Accumulo", "distributing": "Distribuzione",
                    "ad accumulazione": "Accumulo", "distribuzione": "Distribuzione",
                    "thesaurierend": "Accumulo", "ausschüttend": "Distribuzione"}.get(
        str(row.get("useOfProfits", "")).casefold(), "")
    return EtfProfile(ticker, matched_isin, name, hedged, hedge_currency,
                      distribution=distribution, expense_ratio=ratio, source_url=source,
                      retrieved_on=date.today())


class _ProductFields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}
        self.current = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "td" and attrs.get("data-id", "").startswith("keyFundFacts-"):
            self.current = attrs["data-id"]
            self.fields[self.current] = ""

    def handle_data(self, data):
        if self.current:
            self.fields[self.current] += data

    def handle_endtag(self, tag):
        if tag == "td":
            self.current = ""


def enrich_profile(profile: EtfProfile, html: str) -> EtfProfile:
    """Read class-specific facts only after checking the product page's ISIN."""
    parser = _ProductFields()
    parser.feed(html)
    fields = {key.removeprefix("keyFundFacts-").removesuffix("-data"): value.strip()
              for key, value in parser.fields.items()}
    if fields.get("isin") != profile.isin:
        raise ValueError("L'ISIN della pagina ufficiale non corrisponde all'ETF richiesto.")
    structure = fields.get("productStructure", "")
    methodology = fields.get("fundMethodologyTypeCode", "")
    replication = {"Physical": "Fisica", "Synthetic": "Sintetica"}.get(structure, structure)
    if structure == "Physical":
        replication += {"Optimised": " (campionamento)", "Replicated": " (completa)",
                        "Replicating": " (completa)"}.get(methodology, "")
    holdings_url = (profile.source_url.replace("/uk/individual/", "/ch/individual/").rstrip("/") +
                    "/1495092304805.ajax?dataType=fund&fileName=holdings&fileType=csv")
    return replace(profile, replication=replication,
                   benchmark=fields.get("indexSeriesName", ""), holdings_url=holdings_url)


def get_etf_profile(ticker: str, isin: str = "", catalog: dict | None = None,
                    fetch=_download, details: bool = True) -> EtfProfile:
    """Load verified iShares characteristics, or explicitly return unknown metadata."""
    ticker, isin = ticker.strip().upper(), _isin(isin)
    if not ticker:
        raise ValueError("Ticker ETF mancante.")
    try:
        market = ticker.rsplit(".", 1)[-1]
        if catalog is None:
            if not isin and market not in _MARKETS:
                return EtfProfile(ticker, note="Mercato non coperto: analizza tramite ISIN.")
            catalog = get_ishares_catalog(market, fetch)
        profile = profile_from_catalog(catalog, ticker, isin)
        if profile is None:
            return EtfProfile(ticker, isin, note="Caratteristiche non verificate: ETF non trovato "
                              "nel catalogo iShares. Per altri emittenti è disponibile il "
                              "tentativo di lettura delle principali posizioni Yahoo.")
        return enrich_profile(profile, fetch(profile.source_url)) if details else profile
    except Exception as e:
        logger.exception("Caratteristiche ETF non disponibili per %s", ticker)
        raise ValueError(f"Caratteristiche ETF non disponibili per {ticker}: {e}") from e


def _weight(value: str, row_number: int) -> float:
    try:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("non finito")
        return result
    except (TypeError, ValueError) as e:
        raise ValueError(f"Composizione ETF: peso non valido alla riga {row_number}.") from e


def parse_ishares_holdings(text: str, source_url: str) -> EtfHoldings:
    """Parse every row of the English issuer CSV, preserving zero and negative weights."""
    rows = list(csv.reader(StringIO(text.lstrip("\ufeff"))))
    header_index = next((i for i, row in enumerate(rows)
                         if "Name" in row and "Weight (%)" in row and "Asset Class" in row), None)
    if header_index is None:
        raise ValueError("Composizione ETF: intestazione CSV iShares non riconosciuta.")
    as_of = None
    for row in rows[:header_index]:
        if len(row) >= 2 and row[0].strip() == "Fund Holdings as of":
            try:
                as_of = datetime.strptime(row[1].strip().replace("Sept", "Sep"), "%d/%b/%Y").date()
            except ValueError as e:
                raise ValueError("Data della composizione ETF non riconosciuta.") from e
    header = rows[header_index]
    holdings = []
    ended = False
    for number, row in enumerate(rows[header_index + 1:], header_index + 2):
        if not any(cell.strip() for cell in row):
            if holdings:
                ended = True
            continue
        if len(row) != len(header):
            # Issuer legal notes follow the blank line after the portfolio table.
            if ended and len(row) == 1:
                continue
            raise ValueError(f"Composizione ETF: riga {number} incompleta o non riconosciuta.")
        values = dict(zip(header, row))
        name = values.get("Name", "").strip()
        if not name:
            raise ValueError(f"Composizione ETF: nome mancante alla riga {number}.")
        holdings.append(EtfHolding(
            name, values.get("Ticker", values.get("Issuer Ticker", "")).strip(),
            _weight(values["Weight (%)"], number),
            isin=values.get("ISIN", "").strip().replace("-", ""),
            sector=values.get("Sector", ""), country=values.get("Location", ""),
            asset_class=values.get("Asset Class", ""), currency=values.get("Market Currency", "")))
    if not holdings:
        raise ValueError("Composizione ETF vuota.")
    return EtfHoldings(tuple(holdings), source_url, as_of, complete=True)


def _yahoo_top_holdings(ticker):
    return yf.Ticker(ticker).funds_data.top_holdings


def yahoo_holdings(ticker: str, fetch=_yahoo_top_holdings) -> EtfHoldings:
    """Read Yahoo's partial top holdings; its observation date is not supplied."""
    frame = fetch(ticker)
    if frame.empty or not {"Name", "Holding Percent"}.issubset(frame.columns):
        raise ValueError("Principali posizioni Yahoo non disponibili.")
    rows = tuple(EtfHolding(str(row["Name"]), str(symbol),
                            100 * _weight(row["Holding Percent"], number))
                 for number, (symbol, row) in enumerate(frame.iterrows(), 1))
    return EtfHoldings(rows, f"https://finance.yahoo.com/quote/{ticker}/holdings/")


def get_etf_holdings(profile: EtfProfile, fetch=_download) -> EtfHoldings:
    """Download the issuer portfolio when supported, otherwise Yahoo's partial list."""
    try:
        if profile.holdings_url:
            return parse_ishares_holdings(fetch(profile.holdings_url), profile.holdings_url)
        return yahoo_holdings(profile.ticker)
    except Exception as e:
        logger.exception("Composizione ETF non disponibile per %s", profile.ticker)
        raise ValueError(f"Composizione ETF non disponibile: {e}") from e
