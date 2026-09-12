from dataclasses import dataclass
from datetime import date
from enum import Enum


class OpType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"


@dataclass(frozen=True)
class Transaction:
    trade_date: date
    value_date: date
    isin: str
    op_type: OpType
    quantity: float
    amount_eur: float
    price_native: float
    fx_rate: float
    commission_eur: float
    source: str = "import"
    raw_desc: str = ""


@dataclass
class Instrument:
    isin: str
    yahoo_ticker: str
    name: str
    native_currency: str
    asset_class: str
    macro_area: str
    geo_weights: dict[str, float] | None = None
    sector: str = ""
    sector_weights: dict[str, float] | None = None
    excluded: bool = False
