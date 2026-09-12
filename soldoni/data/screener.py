from dataclasses import dataclass
from yfinance import EquityQuery, ETFQuery, screen


@dataclass
class Candidate:
    symbol: str
    name: str | None
    quote_type: str | None


def _region_clause(query_cls, regions: list[str]):
    """`eq` per una sola regione, `is-in` per più di una (la libreria valida i codici)."""
    if len(regions) == 1:
        return query_cls("eq", ["region", regions[0]])
    return query_cls("is-in", ["region", *regions])


def _combine(query_cls, clauses: list):
    """Unisce le clausole in AND; la libreria richiede ≥2 operandi per AND."""
    if not clauses:
        raise ValueError("Nessun filtro per lo screener: seleziona almeno una regione.")
    return clauses[0] if len(clauses) == 1 else query_cls("and", clauses)


# Nome logico (usato dalla UI) -> (campo Yahoo, operatore). La UI non conosce i campi Yahoo.
STOCK_FILTERS: dict[str, tuple[str, str]] = {
    "pe_max": ("peratio.lasttwelvemonths", "lt"),
    "pb_max": ("pricebookratio.quarterly", "lt"),
    "peg_max": ("pegratio_5y", "lt"),
    "ev_ebitda_max": ("lastclosetevebitda.lasttwelvemonths", "lt"),
    "roe_min": ("returnonequity.lasttwelvemonths", "gt"),
    "roa_min": ("returnonassets.lasttwelvemonths", "gt"),
    "net_margin_min": ("netincomemargin.lasttwelvemonths", "gt"),
    "gross_margin_min": ("grossprofitmargin.lasttwelvemonths", "gt"),
    "rev_growth_min": ("totalrevenues1yrgrowth.lasttwelvemonths", "gt"),
    "eps_growth_min": ("epsgrowth.lasttwelvemonths", "gt"),
    "div_yield_min": ("forward_dividend_yield", "gt"),
    "div_growth_years_min": ("consecutive_years_of_dividend_growth_count", "gt"),
    "debt_equity_max": ("totaldebtequity.lasttwelvemonths", "lt"),
    "current_ratio_min": ("currentratio.lasttwelvemonths", "gt"),
}

ETF_FILTERS: dict[str, tuple[str, str]] = {
    "expense_ratio_max": ("annualreportnetexpenseratio", "lt"),
    "return_1y_min": ("annualreturnnavy1", "gt"),
    "return_3y_min": ("annualreturnnavy3", "gt"),
    "return_5y_min": ("annualreturnnavy5", "gt"),
    "morningstar_rating_min": ("performanceratingoverall", "gt"),
    "aum_min": ("fundnetassets", "gt"),
}


def _numeric_clause(query_cls, spec: dict, name: str, value):
    """Clausola gt/lt per un filtro numerico, secondo la spec (campo Yahoo + operatore)."""
    field, op = spec[name]
    return query_cls(op, [field, float(value)])


def _apply_filters(query_cls, spec: dict, clauses: list, filters: dict | None) -> None:
    """Appende a `clauses` una clausola per ogni filtro con valore non None.

    Solleva ValueError se un nome logico non è nella spec (errore di programmazione UI).
    """
    if not filters:
        return
    for name, value in filters.items():
        if name not in spec:
            raise ValueError(f"Filtro screener sconosciuto: {name!r}")
        if value is None:
            continue
        clauses.append(_numeric_clause(query_cls, spec, name, value))


def _equity_query(regions: list[str], sector: str | None, min_market_cap: float | None,
                  filters: dict | None = None):
    clauses = [_region_clause(EquityQuery, regions)]
    if sector:
        clauses.append(EquityQuery("eq", ["sector", sector]))
    if min_market_cap:
        clauses.append(EquityQuery("gt", ["intradaymarketcap", float(min_market_cap)]))
    _apply_filters(EquityQuery, STOCK_FILTERS, clauses, filters)
    return _combine(EquityQuery, clauses), "intradaymarketcap"


def _etf_query(regions: list[str], category: str | None, filters: dict | None = None):
    clauses = [_region_clause(ETFQuery, regions)]
    if category:
        clauses.append(ETFQuery("eq", ["categoryname", category]))
    _apply_filters(ETFQuery, ETF_FILTERS, clauses, filters)
    return _combine(ETFQuery, clauses), "fundnetassets"


def screen_candidates(asset_class: str, regions: list[str], sector: str | None = None,
                      min_market_cap: float | None = None, category: str | None = None,
                      filters: dict | None = None,
                      size: int = 100, screen=screen) -> list[Candidate]:
    """Interroga lo screener Yahoo e ritorna i candidati grezzi (nessuno scoring qui).

    `asset_class`: 'etf' o 'stock'. `filters` è un dict di filtri numerici (nomi logici → valori);
    i valori None sono ignorati. `screen` è iniettabile per i test.
    Solleva ValueError se mancano le regioni, se l'endpoint Yahoo fallisce, o se un nome di
    filtro non è riconosciuto.
    """
    if not regions:
        raise ValueError("Seleziona almeno una regione.")
    if asset_class == "etf":
        query, sort_field = _etf_query(regions, category, filters)
    else:
        query, sort_field = _equity_query(regions, sector, min_market_cap, filters)
    try:
        result = screen(query, size=min(size, 250), sortField=sort_field, sortAsc=False)
    except Exception as e:  # confine I/O verso un servizio esterno: rilancio tipizzato
        raise ValueError(f"Screener Yahoo non disponibile: {e}") from e
    quotes = (result or {}).get("quotes", [])
    return [
        Candidate(q["symbol"], q.get("shortName") or q.get("longName"), q.get("quoteType"))
        for q in quotes if q.get("symbol")
    ]
