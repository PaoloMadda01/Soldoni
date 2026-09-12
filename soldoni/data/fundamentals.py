from dataclasses import dataclass
import yfinance as yf
from soldoni.core.etf_costs import validate_expense_ratio


@dataclass
class Fundamentals:
    ticker: str
    name: str | None
    quote_type: str | None
    currency: str | None
    price: float | None
    trailing_pe: float | None
    forward_pe: float | None
    price_to_book: float | None
    ev_to_ebitda: float | None
    peg: float | None
    roe: float | None
    net_margin: float | None
    operating_margin: float | None
    debt_to_equity: float | None
    free_cashflow: float | None
    revenue_growth: float | None
    earnings_growth: float | None
    dividend_yield: float | None
    payout_ratio: float | None
    expense_ratio: float | None
    total_assets: float | None
    top10_weight: float | None
    holdings_count: int | None
    country: str | None = None
    sector: str | None = None
    target_mean_price: float | None = None
    target_high_price: float | None = None
    target_low_price: float | None = None
    recommendation_mean: float | None = None
    recommendation_key: str | None = None
    num_analysts: int | None = None
    annual_dividend: float | None = None
    trailing_eps: float | None = None
    book_value: float | None = None
    shares_outstanding: float | None = None
    market_cap: float | None = None
    financial_currency: str | None = None
    implied_shares_outstanding: float | None = None


_COUNTRY_MACRO_AREAS = {
    "United States": "Nord America",
    "Canada": "Nord America",
    "Italy": "Europa",
    "Germany": "Europa",
    "Denmark": "Europa",
    "United Kingdom": "Europa",
    "France": "Europa",
    "Netherlands": "Europa",
    "Switzerland": "Europa",
    "China": "Asia",
    "Japan": "Asia",
    "India": "Asia",
    "Taiwan": "Asia",
    "South Korea": "Asia",
    "Hong Kong": "Asia",
    "Australia": "Oceania",
    "New Zealand": "Oceania",
    "Brazil": "America Latina",
    "Mexico": "America Latina",
}


def macro_area_from_country(country: str | None) -> str:
    return _COUNTRY_MACRO_AREAS.get((country or "").strip(), "Non disponibile")


def _fetch_info(ticker: str) -> dict:
    return yf.Ticker(ticker).info


def _f(info: dict, key: str) -> float | None:
    v = info.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _yield_fraction(v: float | None) -> float | None:
    """yfinance a volte da' il dividend yield in % (1.5) e a volte in frazione (0.015).
    Normalizza sempre a frazione."""
    if v is None:
        return None
    return v / 100.0 if v > 1 else v


def get_fundamentals(ticker: str, fetch=_fetch_info) -> Fundamentals:
    """Normalizza i fondamentali yfinance in un Fundamentals (campi mancanti = None).

    `fetch(ticker)` ritorna il dict `.info`; iniettabile per i test. ValueError se vuoto.
    """
    info = fetch(ticker)
    if not info:
        raise ValueError(f"Nessun fondamentale da yfinance per '{ticker}'")
    de = _f(info, "debtToEquity")
    return Fundamentals(
        ticker=ticker,
        name=info.get("shortName") or info.get("longName"),
        quote_type=info.get("quoteType"),
        currency=info.get("currency"),
        price=_f(info, "currentPrice") if _f(info, "currentPrice") is not None
        else _f(info, "regularMarketPrice"),
        trailing_pe=_f(info, "trailingPE"),
        forward_pe=_f(info, "forwardPE"),
        price_to_book=_f(info, "priceToBook"),
        ev_to_ebitda=_f(info, "enterpriseToEbitda"),
        peg=_f(info, "trailingPegRatio") if _f(info, "trailingPegRatio") is not None
        else _f(info, "pegRatio"),
        roe=_f(info, "returnOnEquity"),
        net_margin=_f(info, "profitMargins"),
        operating_margin=_f(info, "operatingMargins"),
        debt_to_equity=de / 100.0 if de is not None else None,
        free_cashflow=_f(info, "freeCashflow"),
        revenue_growth=_f(info, "revenueGrowth"),
        earnings_growth=_f(info, "earningsGrowth"),
        dividend_yield=_yield_fraction(_f(info, "dividendYield")),
        payout_ratio=_f(info, "payoutRatio"),
        expense_ratio=_f(info, "annualReportExpenseRatio") if _f(info, "annualReportExpenseRatio")
        is not None else _f(info, "netExpenseRatio"),
        total_assets=_f(info, "totalAssets"),
        top10_weight=None,   # v1: non popolato
        holdings_count=None,
        country=info.get("country"),
        sector=info.get("sector"),
        target_mean_price=_f(info, "targetMeanPrice"),
        target_high_price=_f(info, "targetHighPrice"),
        target_low_price=_f(info, "targetLowPrice"),
        recommendation_mean=_f(info, "recommendationMean"),
        recommendation_key=info.get("recommendationKey"),
        num_analysts=int(info["numberOfAnalystOpinions"])
        if info.get("numberOfAnalystOpinions") is not None else None,
        annual_dividend=_f(info, "trailingAnnualDividendRate"),
        trailing_eps=_f(info, "trailingEps"),
        book_value=_f(info, "bookValue"),
        shares_outstanding=_f(info, "sharesOutstanding"),
        market_cap=_f(info, "marketCap"),
        financial_currency=info.get("financialCurrency"),
        implied_shares_outstanding=_f(info, "impliedSharesOutstanding"),
    )


def get_etf_expense_ratio(ticker: str) -> float:
    """Legge il TER in frazione dal profilo fondo Yahoo (0.002 = 0.20%)."""
    if not ticker.strip():
        raise ValueError("Ticker Yahoo mancante.")
    fund = yf.Ticker(ticker.strip())
    operations = fund.funds_data.fund_operations
    label = "Annual Report Expense Ratio"
    if label not in operations.index or fund.ticker not in operations.columns:
        raise ValueError("TER non disponibile nel profilo fondo Yahoo.")
    try:
        ratio = float(operations.at[label, fund.ticker])
    except (TypeError, ValueError) as e:
        raise ValueError("TER non disponibile nel profilo fondo Yahoo.") from e
    validate_expense_ratio(ratio)
    return ratio
