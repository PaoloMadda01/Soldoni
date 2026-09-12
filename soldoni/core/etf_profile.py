from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class EtfProfile:
    ticker: str
    isin: str = ""
    name: str = ""
    hedged: bool | None = None
    hedge_currency: str = ""
    replication: str = ""
    distribution: str = ""
    benchmark: str = ""
    expense_ratio: float | None = None
    source_url: str = ""
    retrieved_on: date | None = None
    holdings_url: str = ""
    note: str = ""


@dataclass(frozen=True)
class EtfHolding:
    name: str
    ticker: str
    weight_pct: float
    isin: str = ""
    sector: str = ""
    country: str = ""
    asset_class: str = ""
    currency: str = ""


@dataclass(frozen=True)
class EtfHoldings:
    rows: tuple[EtfHolding, ...]
    source_url: str
    as_of: date | None = None
    complete: bool = False


def hedge_label(profile: EtfProfile) -> str:
    """Describe verified currency hedging without treating missing data as No."""
    if profile.hedged is None:
        return "Non verificata"
    if profile.hedged:
        return "Sì" + (f" ({profile.hedge_currency})" if profile.hedge_currency else "")
    return "No"


def filter_non_hedged(candidates, profiles: dict[str, EtfProfile]):
    """Return eligible candidates and separate hedged/unknown exclusions."""
    eligible, hedged, unknown = [], [], []
    for candidate in candidates:
        profile = profiles.get(candidate.symbol)
        if profile is not None and profile.hedged is False:
            eligible.append(candidate)
        elif profile is not None and profile.hedged is True:
            hedged.append(candidate.symbol)
        else:
            unknown.append(candidate.symbol)
    return eligible, hedged, unknown
