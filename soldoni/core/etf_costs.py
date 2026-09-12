from dataclasses import dataclass
from datetime import date
from math import isfinite


@dataclass(frozen=True)
class EtfExpenseRatio:
    value: float
    source: str
    saved_on: date


@dataclass(frozen=True)
class EtfCost:
    isin: str
    value_eur: float | None
    expense_ratio: float | None
    annual_cost_eur: float | None


@dataclass(frozen=True)
class EtfCostSummary:
    rows: tuple[EtfCost, ...]
    annual_cost_eur: float | None
    weighted_expense_ratio: float | None
    covered_value_eur: float
    priced_value_eur: float
    covered_count: int

    @property
    def complete(self) -> bool:
        return self.covered_count == len(self.rows)


def validate_expense_ratio(value: float) -> None:
    """Valida il TER espresso come frazione: 0.002 corrisponde allo 0.20%."""
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("Il TER deve essere un valore finito tra 0% e 100%.")


def summarize_etf_costs(values_eur: dict[str, float | None],
                        expense_ratios: dict[str, float]) -> EtfCostSummary:
    """Stima i costi a valori costanti, ponderando solo gli ETF con entrambi i dati."""
    rows = []
    covered_value = priced_value = annual_cost = 0.0
    covered_count = 0
    for isin, value in values_eur.items():
        if value is not None:
            if not isfinite(value) or value < 0.0:
                raise ValueError(f"Valore ETF non valido per {isin}.")
            priced_value += value
        ratio = expense_ratios.get(isin)
        if ratio is not None:
            validate_expense_ratio(ratio)
        cost = None
        if value is not None and ratio is not None:
            cost = value * ratio
            covered_value += value
            annual_cost += cost
            covered_count += 1
        rows.append(EtfCost(isin, value, ratio, cost))
    return EtfCostSummary(
        rows=tuple(rows),
        annual_cost_eur=annual_cost if covered_count else None,
        weighted_expense_ratio=annual_cost / covered_value if covered_value else None,
        covered_value_eur=covered_value,
        priced_value_eur=priced_value,
        covered_count=covered_count,
    )
