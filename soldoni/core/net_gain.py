from dataclasses import dataclass
from soldoni.core.models import OpType, Transaction
from soldoni.core.holdings import Position, PortfolioState

IT_RATE = 0.26
DEFAULT_FOREIGN_RATES = {"US": 0.15}  # estendibile per paese


def country_from_isin(isin: str) -> str:
    return isin[:2].upper()


def capital_gains_tax(gross_gain_eur: float, rate: float = IT_RATE) -> float:
    return rate * gross_gain_eur if gross_gain_eur > 0 else 0.0


def dividend_net(gross_eur: float, country: str,
                 foreign_rates: dict[str, float] | None = None,
                 it_rate: float = IT_RATE) -> float:
    rates = DEFAULT_FOREIGN_RATES if foreign_rates is None else foreign_rates
    foreign = 0.0 if country == "IT" else rates.get(country, 0.0)
    net_frontier = gross_eur * (1.0 - foreign)
    return net_frontier * (1.0 - it_rate)


@dataclass
class NetGain:
    capital_net_eur: float
    dividends_net_eur: float

    @property
    def total_eur(self) -> float:
        return self.capital_net_eur + self.dividends_net_eur


def realized_net_gain(state: PortfolioState, dividends: list[Transaction],
                      foreign_rates: dict[str, float] | None = None) -> NetGain:
    capital_net = sum(
        s.gain_eur - capital_gains_tax(s.gain_eur) for s in state.realized_sales
    )
    div_net = sum(
        dividend_net(d.amount_eur, country_from_isin(d.isin), foreign_rates)
        for d in dividends if d.op_type is OpType.DIVIDEND
    )
    return NetGain(capital_net_eur=capital_net, dividends_net_eur=div_net)


@dataclass
class LatentGain:
    gross_eur: float
    commission_eur: float
    tax_eur: float

    @property
    def total_eur(self) -> float:
        return self.gross_eur - self.commission_eur - self.tax_eur


def latent_net_gain(positions: dict[str, Position],
                    current_value_eur: dict[str, float],
                    sell_commission: float = 2.95) -> LatentGain:
    gross = 0.0
    tax = 0.0
    commission = 0.0
    for isin, pos in positions.items():
        if isin not in current_value_eur:
            raise ValueError(f"Valore corrente mancante per {isin}")
        latent = current_value_eur[isin] - pos.total_cost_eur
        gross += latent
        tax += capital_gains_tax(latent)
        commission += sell_commission
    return LatentGain(gross_eur=gross, commission_eur=commission, tax_eur=tax)
