from dataclasses import dataclass
from soldoni.core.holdings import Position, RealizedSale


@dataclass
class Contribution:
    isin: str
    latent_eur: float
    realized_eur: float

    @property
    def total_eur(self) -> float:
        return self.latent_eur + self.realized_eur


def pnl_attribution(
    positions: dict[str, Position],
    current_value_eur: dict[str, float],
    realized_sales: list[RealizedSale],
) -> list[Contribution]:
    """Contributo P/L lordo per ISIN: latente (posizioni prezzate) + realizzato (vendite).

    Universo = posizioni prezzate ∪ ISIN con vendite (così rientrano i titoli già usciti).
    `latent_eur` = current_value - total_cost se l'ISIN è detenuto e prezzato, altrimenti 0.
    Lista ordinata per `total_eur` decrescente.
    """
    realized_by_isin: dict[str, float] = {}
    for s in realized_sales:
        realized_by_isin[s.isin] = realized_by_isin.get(s.isin, 0.0) + s.gain_eur

    priced = {isin for isin in positions if isin in current_value_eur}
    isins = priced | set(realized_by_isin)

    contribs: list[Contribution] = []
    for isin in isins:
        if isin in priced:
            latent = current_value_eur[isin] - positions[isin].total_cost_eur
        else:
            latent = 0.0
        contribs.append(Contribution(
            isin=isin, latent_eur=latent, realized_eur=realized_by_isin.get(isin, 0.0)))

    contribs.sort(key=lambda c: c.total_eur, reverse=True)
    return contribs


def attribution_shares(contribs: list[Contribution]) -> dict[str, float]:
    """Quota di ogni contributo sul risultato lordo totale (Σ total_eur).

    Se il totale è ~0 ritorna 0.0 per tutti (nessuna divisione per zero).
    """
    total = sum(c.total_eur for c in contribs)
    if abs(total) < 1e-9:
        return {c.isin: 0.0 for c in contribs}
    return {c.isin: c.total_eur / total for c in contribs}
