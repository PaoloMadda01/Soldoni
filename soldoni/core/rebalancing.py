from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RebalanceLine:
    isin: str
    current_value_eur: float
    target_weight: float
    target_value_eur: float
    trade_eur: float


@dataclass(frozen=True)
class TradeCostEstimate:
    commissions_eur: float
    estimated_tax_eur: float

    @property
    def total_eur(self) -> float:
        return self.commissions_eur + self.estimated_tax_eur


def validate_target_weights(target_weights: dict[str, float]) -> None:
    if not target_weights:
        raise ValueError("Inserisci almeno un peso obiettivo.")
    for weight in target_weights.values():
        if not math.isfinite(weight):
            raise ValueError("I pesi obiettivo devono essere numeri finiti.")
        if weight < 0.0:
            raise ValueError("Un peso obiettivo non può essere negativo.")
    if not math.isclose(sum(target_weights.values()), 1.0, abs_tol=1e-6):
        raise ValueError("La somma dei pesi obiettivo deve essere 100%.")


def _validate_values(values_eur: dict[str, float]) -> None:
    if any(not math.isfinite(value) or value < 0.0 for value in values_eur.values()):
        raise ValueError("I valori correnti devono essere numeri finiti e non negativi.")


def _validate_cash(new_cash_eur: float) -> None:
    if not math.isfinite(new_cash_eur) or new_cash_eur < 0.0:
        raise ValueError("La nuova liquidità deve essere un numero finito e non negativo.")


def rebalance_trades(current_values_eur: dict[str, float],
                     target_weights: dict[str, float],
                     new_cash_eur: float = 0.0) -> list[RebalanceLine]:
    validate_target_weights(target_weights)
    _validate_values(current_values_eur)
    _validate_cash(new_cash_eur)
    final_value = sum(current_values_eur.values()) + new_cash_eur
    lines = []
    for isin in sorted(set(current_values_eur) | set(target_weights)):
        current = current_values_eur.get(isin, 0.0)
        weight = target_weights.get(isin, 0.0)
        target = final_value * weight
        lines.append(RebalanceLine(isin, current, weight, target, target - current))
    return lines


def allocate_contribution(current_values_eur: dict[str, float],
                          target_weights: dict[str, float],
                          new_cash_eur: float) -> list[RebalanceLine]:
    validate_target_weights(target_weights)
    _validate_values(current_values_eur)
    _validate_cash(new_cash_eur)
    final_value = sum(current_values_eur.values()) + new_cash_eur
    isins = sorted(set(current_values_eur) | set(target_weights))
    gaps = {
        isin: max(final_value * target_weights.get(isin, 0.0)
                  - current_values_eur.get(isin, 0.0), 0.0)
        for isin in isins
    }
    total_gap = sum(gaps.values())
    lines = []
    for isin in isins:
        current = current_values_eur.get(isin, 0.0)
        weight = target_weights.get(isin, 0.0)
        target = final_value * weight
        trade = new_cash_eur * gaps[isin] / total_gap if total_gap else 0.0
        lines.append(RebalanceLine(isin, current, weight, target, trade))
    return lines


def estimate_trade_costs(trades_eur: dict[str, float],
                         current_values_eur: dict[str, float],
                         cost_basis_eur: dict[str, float],
                         commission_per_trade_eur: float = 2.95,
                         tax_rate: float = 0.26) -> TradeCostEstimate:
    _validate_values(current_values_eur)
    _validate_values(cost_basis_eur)
    if (not math.isfinite(commission_per_trade_eur)
            or commission_per_trade_eur < 0.0):
        raise ValueError("La commissione deve essere un numero finito e non negativo.")
    if not math.isfinite(tax_rate) or not 0.0 <= tax_rate <= 1.0:
        raise ValueError("L'aliquota fiscale deve essere compresa tra 0% e 100%.")

    commissions = 0.0
    estimated_tax = 0.0
    for isin, trade in trades_eur.items():
        if not math.isfinite(trade):
            raise ValueError("Gli importi delle operazioni devono essere numeri finiti.")
        if math.isclose(trade, 0.0, abs_tol=1e-9):
            continue
        commissions += commission_per_trade_eur
        if trade >= 0.0:
            continue
        current = current_values_eur.get(isin, 0.0)
        sale = -trade
        if current <= 0.0 or sale > current + 1e-6:
            raise ValueError(f"Vendita superiore al valore corrente per {isin}.")
        if isin not in cost_basis_eur:
            raise ValueError(f"Costo fiscale non disponibile per {isin}.")
        sold_cost = cost_basis_eur[isin] * min(sale / current, 1.0)
        taxable_gain = max(sale - commission_per_trade_eur - sold_cost, 0.0)
        estimated_tax += taxable_gain * tax_rate
    return TradeCostEstimate(commissions, estimated_tax)
