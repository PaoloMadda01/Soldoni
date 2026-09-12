import math
from dataclasses import dataclass, field
from soldoni.data.fundamentals import Fundamentals
from soldoni.core.screen_metrics import PriceMetrics


@dataclass(frozen=True)
class Threshold:
    kind: str                      # "monotone" | "sweet"
    green: float = 0.0             # monotone: cutoff verde
    yellow: float = 0.0            # monotone: cutoff giallo
    higher_is_better: bool = True  # monotone
    green_low: float = 0.0         # sweet
    green_high: float = 0.0
    yellow_low: float = 0.0
    yellow_high: float = 0.0


@dataclass
class MetricScore:
    name: str
    value: float | None
    band: str
    score: float | None


@dataclass
class ScoreResult:
    asset_class: str
    composite: float | None
    pillars: dict[str, float | None]
    metrics: dict[str, list[MetricScore]] = field(default_factory=dict)


_BAND_SCORE = {"green": 100.0, "yellow": 60.0, "red": 20.0}


def metric_band(value: float | None, thr: Threshold) -> str:
    """Banda 'green'|'yellow'|'red' confrontando `value` con le soglie; 'na' se mancante."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "na"
    if thr.kind == "monotone":
        if thr.higher_is_better:
            if value >= thr.green:
                return "green"
            return "yellow" if value >= thr.yellow else "red"
        if value <= thr.green:
            return "green"
        return "yellow" if value <= thr.yellow else "red"
    if thr.kind == "sweet":
        if thr.green_low <= value <= thr.green_high:
            return "green"
        if thr.yellow_low <= value <= thr.yellow_high:
            return "yellow"
        return "red"
    raise ValueError(f"Threshold.kind sconosciuto: {thr.kind}")


def band_score(band: str) -> float | None:
    """Punteggio numerico da 0 a 100 per una banda; None per 'na'."""
    return _BAND_SCORE.get(band)


def pillar_score(metric_scores: list[float | None]) -> float | None:
    """Media dei punteggi metrica disponibili (None esclusi). None se tutti mancanti."""
    vals = [s for s in metric_scores if s is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def composite_score(pillars: dict[str, float | None], weights: dict[str, float]) -> float | None:
    """Media pesata dei pillar disponibili, con pesi rinormalizzati sui soli pillar presenti."""
    num = den = 0.0
    for name, score in pillars.items():
        if score is None:
            continue
        w = weights.get(name, 0.0)
        num += w * score
        den += w
    if not den:
        return None
    return max(0.0, min(100.0, num / den))


def asset_class_from_quote_type(quote_type: str | None) -> str:
    """Restituisce 'etf' per ETF/MUTUALFUND, 'stock' per tutto il resto."""
    if quote_type and quote_type.upper() in {"ETF", "MUTUALFUND"}:
        return "etf"
    return "stock"


STOCK_THRESHOLDS = {
    "trailing_pe": Threshold("monotone", green=15, yellow=25, higher_is_better=False),
    "price_to_book": Threshold("monotone", green=2, yellow=4, higher_is_better=False),
    "ev_to_ebitda": Threshold("monotone", green=10, yellow=16, higher_is_better=False),
    "peg": Threshold("monotone", green=1, yellow=2, higher_is_better=False),
    "roe": Threshold("monotone", green=0.15, yellow=0.08, higher_is_better=True),
    "net_margin": Threshold("monotone", green=0.12, yellow=0.05, higher_is_better=True),
    "debt_to_equity": Threshold("monotone", green=0.5, yellow=1.5, higher_is_better=False),
    "free_cashflow": Threshold("monotone", green=0.0, yellow=0.0, higher_is_better=True),
    "return_12m": Threshold("monotone", green=0.10, yellow=-0.10, higher_is_better=True),
    "vs_ma200": Threshold("monotone", green=0.0, yellow=-0.05, higher_is_better=True),
    "dist_from_52w_high": Threshold("monotone", green=0.10, yellow=0.25, higher_is_better=False),
    "volatility": Threshold("monotone", green=0.20, yellow=0.35, higher_is_better=False),
    "dividend_yield": Threshold("sweet", green_low=0.02, green_high=0.06,
                                yellow_low=0.0, yellow_high=0.08),
    "payout_ratio": Threshold("monotone", green=0.60, yellow=0.80, higher_is_better=False),
    "revenue_growth": Threshold("monotone", green=0.15, yellow=0.05, higher_is_better=True),
    "earnings_growth": Threshold("monotone", green=0.15, yellow=0.0, higher_is_better=True),
}

ETF_THRESHOLDS = {
    "expense_ratio": Threshold("monotone", green=0.0020, yellow=0.0050, higher_is_better=False),
    "volatility": Threshold("monotone", green=0.15, yellow=0.25, higher_is_better=False),
    "max_drawdown_1y": Threshold("monotone", green=-0.15, yellow=-0.30, higher_is_better=True),
    "return_12m": Threshold("monotone", green=0.10, yellow=-0.10, higher_is_better=True),
    "vs_ma200": Threshold("monotone", green=0.0, yellow=-0.05, higher_is_better=True),
    "dividend_yield": Threshold("sweet", green_low=0.01, green_high=0.04,
                                yellow_low=0.0, yellow_high=0.06),
    "top10_weight": Threshold("monotone", green=0.30, yellow=0.50, higher_is_better=False),
    "holdings_count": Threshold("monotone", green=100, yellow=30, higher_is_better=True),
}

STOCK_PILLARS = {
    "value": ["trailing_pe", "price_to_book", "ev_to_ebitda", "peg"],
    "quality": ["roe", "net_margin", "debt_to_equity", "free_cashflow"],
    "growth": ["revenue_growth", "earnings_growth"],
    "momentum": ["return_12m", "vs_ma200", "dist_from_52w_high", "volatility"],
    "dividend": ["dividend_yield", "payout_ratio"],
}
STOCK_WEIGHTS = {"value": 0.25, "quality": 0.30, "growth": 0.15,
                 "momentum": 0.15, "dividend": 0.15}

ETF_PILLARS = {
    "cost": ["expense_ratio"],
    "risk": ["volatility", "max_drawdown_1y"],
    "momentum": ["return_12m", "vs_ma200"],
    "income": ["dividend_yield", "top10_weight", "holdings_count"],
}
ETF_WEIGHTS = {"cost": 0.30, "risk": 0.25, "momentum": 0.25, "income": 0.20}


# Override per settore (etichette yfinance) dei multipli di valore e di alcune metriche di
# qualita'/dividendo che dipendono dal settore. Una metrica mappata a None e' "n/d" per quel
# settore (non significativa -> esclusa dal punteggio). Settore assente o non in tabella ->
# fallback alle soglie assolute STOCK_THRESHOLDS. Valori di default approssimativi e tunabili.
SECTOR_THRESHOLDS: dict[str, dict[str, Threshold | None]] = {
    "Technology": {
        "trailing_pe": Threshold("monotone", green=25, yellow=40, higher_is_better=False),
        "price_to_book": Threshold("monotone", green=6, yellow=12, higher_is_better=False),
        "ev_to_ebitda": Threshold("monotone", green=18, yellow=28, higher_is_better=False),
        "net_margin": Threshold("monotone", green=0.18, yellow=0.10, higher_is_better=True),
        "roe": Threshold("monotone", green=0.18, yellow=0.10, higher_is_better=True),
    },
    "Communication Services": {
        "trailing_pe": Threshold("monotone", green=18, yellow=30, higher_is_better=False),
        "price_to_book": Threshold("monotone", green=3, yellow=6, higher_is_better=False),
        "net_margin": Threshold("monotone", green=0.15, yellow=0.08, higher_is_better=True),
    },
    "Consumer Cyclical": {
        "trailing_pe": Threshold("monotone", green=18, yellow=28, higher_is_better=False),
        "price_to_book": Threshold("monotone", green=3, yellow=6, higher_is_better=False),
        "net_margin": Threshold("monotone", green=0.08, yellow=0.04, higher_is_better=True),
    },
    "Consumer Defensive": {
        "trailing_pe": Threshold("monotone", green=18, yellow=26, higher_is_better=False),
        "price_to_book": Threshold("monotone", green=3, yellow=6, higher_is_better=False),
        "net_margin": Threshold("monotone", green=0.06, yellow=0.03, higher_is_better=True),
        "debt_to_equity": Threshold("monotone", green=0.8, yellow=1.8, higher_is_better=False),
        "payout_ratio": Threshold("monotone", green=0.70, yellow=0.85, higher_is_better=False),
    },
    "Healthcare": {
        "trailing_pe": Threshold("monotone", green=18, yellow=30, higher_is_better=False),
        "price_to_book": Threshold("monotone", green=4, yellow=8, higher_is_better=False),
        "net_margin": Threshold("monotone", green=0.12, yellow=0.06, higher_is_better=True),
    },
    "Industrials": {
        "trailing_pe": Threshold("monotone", green=17, yellow=26, higher_is_better=False),
        "price_to_book": Threshold("monotone", green=3, yellow=6, higher_is_better=False),
        "net_margin": Threshold("monotone", green=0.08, yellow=0.04, higher_is_better=True),
        "debt_to_equity": Threshold("monotone", green=0.8, yellow=1.8, higher_is_better=False),
    },
    "Energy": {
        "trailing_pe": Threshold("monotone", green=10, yellow=15, higher_is_better=False),
        "price_to_book": Threshold("monotone", green=1.5, yellow=3, higher_is_better=False),
        "net_margin": Threshold("monotone", green=0.08, yellow=0.03, higher_is_better=True),
        "debt_to_equity": Threshold("monotone", green=0.6, yellow=1.5, higher_is_better=False),
        "payout_ratio": Threshold("monotone", green=0.70, yellow=0.90, higher_is_better=False),
    },
    "Utilities": {
        "trailing_pe": Threshold("monotone", green=16, yellow=22, higher_is_better=False),
        "price_to_book": Threshold("monotone", green=1.5, yellow=2.5, higher_is_better=False),
        "net_margin": Threshold("monotone", green=0.10, yellow=0.05, higher_is_better=True),
        "debt_to_equity": Threshold("monotone", green=1.5, yellow=2.5, higher_is_better=False),
        "roe": Threshold("monotone", green=0.10, yellow=0.06, higher_is_better=True),
        "payout_ratio": Threshold("monotone", green=0.75, yellow=0.90, higher_is_better=False),
    },
    "Basic Materials": {
        "trailing_pe": Threshold("monotone", green=12, yellow=20, higher_is_better=False),
        "price_to_book": Threshold("monotone", green=2, yellow=4, higher_is_better=False),
        "net_margin": Threshold("monotone", green=0.08, yellow=0.04, higher_is_better=True),
        "debt_to_equity": Threshold("monotone", green=0.7, yellow=1.6, higher_is_better=False),
    },
    "Financial Services": {
        "trailing_pe": Threshold("monotone", green=11, yellow=16, higher_is_better=False),
        "price_to_book": Threshold("monotone", green=1.0, yellow=1.8, higher_is_better=False),
        "ev_to_ebitda": None,        # non significativo per le banche
        "net_margin": Threshold("monotone", green=0.22, yellow=0.12, higher_is_better=True),
        "debt_to_equity": None,      # la leva e' il modello di business, non un segnale di solvibilita'
        "free_cashflow": None,       # FCF non significativo per il settore finanziario
        "roe": Threshold("monotone", green=0.12, yellow=0.08, higher_is_better=True),
        "payout_ratio": Threshold("monotone", green=0.60, yellow=0.85, higher_is_better=False),
    },
    "Real Estate": {
        "trailing_pe": Threshold("monotone", green=18, yellow=30, higher_is_better=False),
        "price_to_book": Threshold("monotone", green=1.2, yellow=2.0, higher_is_better=False),
        "ev_to_ebitda": None,        # i REIT si valutano su FFO, non EV/EBITDA
        "net_margin": Threshold("monotone", green=0.20, yellow=0.10, higher_is_better=True),
        "debt_to_equity": Threshold("monotone", green=1.0, yellow=2.0, higher_is_better=False),
        "free_cashflow": None,       # i REIT usano FFO, non FCF
        "payout_ratio": None,        # i REIT devono distribuire ~90%: payout alto e' obbligatorio
    },
}


def _band_for(name: str, value: float | None, default_thresholds: dict[str, Threshold],
              sector_overrides: dict[str, Threshold | None]) -> str:
    """Banda della metrica usando l'override di settore se presente; None nell'override = 'na'."""
    if name in sector_overrides:
        thr = sector_overrides[name]
        return "na" if thr is None else metric_band(value, thr)
    return metric_band(value, default_thresholds[name])


def effective_threshold(name: str, sector: str | None,
                        asset_class: str = "stock") -> Threshold | None:
    """Soglia effettivamente applicata a una metrica (override di settore o default).

    Ritorna None se la metrica è 'n/d' per quel settore o se non esiste per l'asset class.
    Utile alla UI per disegnare le bande dei gauge coerenti col punteggio.
    """
    if asset_class == "etf":
        return ETF_THRESHOLDS.get(name)
    overrides = SECTOR_THRESHOLDS.get(sector or "", {})
    if name in overrides:
        return overrides[name]
    return STOCK_THRESHOLDS.get(name)


def _stock_values(fund: Fundamentals, pm: PriceMetrics) -> dict[str, float | None]:
    return {
        "trailing_pe": fund.trailing_pe, "price_to_book": fund.price_to_book,
        "ev_to_ebitda": fund.ev_to_ebitda, "peg": fund.peg,
        "roe": fund.roe, "net_margin": fund.net_margin,
        "debt_to_equity": fund.debt_to_equity, "free_cashflow": fund.free_cashflow,
        "return_12m": pm.return_12m, "vs_ma200": pm.vs_ma200,
        "dist_from_52w_high": pm.dist_from_52w_high, "volatility": pm.volatility,
        "dividend_yield": fund.dividend_yield, "payout_ratio": fund.payout_ratio,
        "revenue_growth": fund.revenue_growth, "earnings_growth": fund.earnings_growth,
    }


def _etf_values(fund: Fundamentals, pm: PriceMetrics) -> dict[str, float | None]:
    return {
        "expense_ratio": fund.expense_ratio,
        "volatility": pm.volatility, "max_drawdown_1y": pm.max_drawdown_1y,
        "return_12m": pm.return_12m, "vs_ma200": pm.vs_ma200,
        "dividend_yield": fund.dividend_yield,
        "top10_weight": fund.top10_weight, "holdings_count": fund.holdings_count,
    }


def score_instrument(asset_class: str, fund: Fundamentals, pm: PriceMetrics) -> ScoreResult:
    """Calcola pillar e composito per uno strumento. asset_class: 'etf' o 'stock'."""
    if asset_class == "etf":
        thresholds, pillars_map, weights = ETF_THRESHOLDS, ETF_PILLARS, ETF_WEIGHTS
        values = _etf_values(fund, pm)
        sector_overrides: dict[str, Threshold | None] = {}
    else:
        thresholds, pillars_map, weights = STOCK_THRESHOLDS, STOCK_PILLARS, STOCK_WEIGHTS
        values = _stock_values(fund, pm)
        sector_overrides = SECTOR_THRESHOLDS.get(fund.sector or "", {})

    metrics: dict[str, list[MetricScore]] = {}
    pillar_scores: dict[str, float | None] = {}
    for pillar, names in pillars_map.items():
        row: list[MetricScore] = []
        for name in names:
            value = values.get(name)
            band = _band_for(name, value, thresholds, sector_overrides)
            if name == "payout_ratio" and band != "na" and value is not None and value < 0:
                band = "red"
            row.append(MetricScore(name, value, band, band_score(band)))
        metrics[pillar] = row
        pillar_scores[pillar] = pillar_score([m.score for m in row])
    composite = composite_score(pillar_scores, weights)
    return ScoreResult(asset_class, composite, pillar_scores, metrics)
