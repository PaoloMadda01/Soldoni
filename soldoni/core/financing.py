from dataclasses import dataclass, replace
import math

import numpy as np


@dataclass(frozen=True)
class SaleEstimate:
    gross_sale_eur: float
    estimated_tax_eur: float
    commission_eur: float
    net_proceeds_eur: float


@dataclass(frozen=True)
class FinancingOption:
    name: str
    financed_amount_eur: float
    annual_interest_rate: float
    months: int
    upfront_cost_eur: float = 0.0
    monthly_cost_eur: float = 0.0
    annual_tax_benefit_eur: float = 0.0


@dataclass(frozen=True)
class FinancingStrategy:
    name: str
    monthly_payment_eur: float
    monthly_outflow_eur: float
    financing_cost_eur: float
    gross_sale_eur: float
    estimated_sale_tax_eur: float
    sale_commission_eur: float
    residual_debt_eur: float
    p10_net_worth_eur: float
    median_net_worth_eur: float
    p90_net_worth_eur: float
    median_real_net_worth_eur: float
    probability_beats_sale: float | None
    break_even_annual_return: float | None
    median_path_eur: tuple[float, ...]


@dataclass(frozen=True)
class FinancingDecision:
    months: tuple[int, ...]
    strategies: dict[str, FinancingStrategy]
    errors: tuple[str, ...]


def monthly_payment(principal_eur: float, annual_interest_rate: float,
                    months: int) -> float:
    if not math.isfinite(principal_eur) or principal_eur < 0.0:
        raise ValueError("L'importo finanziato deve essere un numero non negativo.")
    if not math.isfinite(annual_interest_rate) or annual_interest_rate < 0.0:
        raise ValueError("Il TAN deve essere un numero non negativo.")
    if not isinstance(months, int) or months <= 0:
        raise ValueError("La durata deve contenere almeno un mese.")
    if annual_interest_rate == 0.0:
        return principal_eur / months
    monthly_rate = annual_interest_rate / 12.0
    return principal_eur * monthly_rate / (1.0 - (1.0 + monthly_rate) ** -months)


def estimate_proportional_sale(current_values_eur: dict[str, float],
                               cost_basis_eur: dict[str, float],
                               net_needed_eur: float,
                               tax_rate: float = 0.26,
                               commission_eur: float = 0.0) -> SaleEstimate:
    total_value = sum(current_values_eur.values())
    positive_gain = sum(
        max(value - cost_basis_eur.get(isin, value), 0.0)
        for isin, value in current_values_eur.items())
    tax_per_gross_euro = tax_rate * positive_gain / total_value
    gross_sale = (net_needed_eur + commission_eur) / (1.0 - tax_per_gross_euro)
    if gross_sale > total_value:
        raise ValueError("il portafoglio non basta a produrre il ricavo netto richiesto.")
    estimated_tax = gross_sale * tax_per_gross_euro
    return SaleEstimate(
        gross_sale, estimated_tax, commission_eur,
        gross_sale - estimated_tax - commission_eur)


def _debt_balances(principal_eur: float, annual_interest_rate: float,
                   term_months: int, horizon_months: int) -> tuple[float, tuple[float, ...]]:
    payment = monthly_payment(principal_eur, annual_interest_rate, term_months)
    monthly_rate = annual_interest_rate / 12.0
    balance = principal_eur
    balances = [balance]
    for month in range(1, horizon_months + 1):
        if month <= term_months:
            principal_paid = payment - balance * monthly_rate
            balance = max(balance - principal_paid, 0.0)
        balances.append(balance)
    return payment, tuple(balances)


def _simulate_investment(initial_eur: float, monthly_contributions: tuple[float, ...],
                         growth: np.ndarray, debt_balances: tuple[float, ...]) -> np.ndarray:
    simulations, months = growth.shape
    values = np.empty((simulations, months + 1), dtype=float)
    values[:, 0] = initial_eur
    for month in range(1, months + 1):
        values[:, month] = (
            values[:, month - 1] * growth[:, month - 1]
            + monthly_contributions[month - 1])
    return values - np.asarray(debt_balances)


def _deterministic_final(initial_eur: float, monthly_contributions: tuple[float, ...],
                         residual_debt_eur: float, annual_return: float) -> float:
    monthly_growth = (1.0 + annual_return) ** (1.0 / 12.0)
    value = initial_eur
    for contribution in monthly_contributions:
        value = value * monthly_growth + contribution
    return value - residual_debt_eur


def _break_even_return(sale_initial_eur: float, sale_contributions: tuple[float, ...],
                       option_initial_eur: float,
                       option_contributions: tuple[float, ...],
                       residual_debt_eur: float) -> float | None:
    def difference(annual_return):
        return _deterministic_final(
            option_initial_eur, option_contributions,
            residual_debt_eur, annual_return) - _deterministic_final(
                sale_initial_eur, sale_contributions, 0.0, annual_return)

    if math.isclose(difference(0.0), 0.0, abs_tol=1e-9):
        return 0.0
    low, high = -0.99, 2.0
    low_value, high_value = difference(low), difference(high)
    if low_value * high_value > 0.0:
        return None
    for _ in range(80):
        midpoint = (low + high) / 2.0
        value = difference(midpoint)
        if value == 0.0:
            return midpoint
        if low_value * value <= 0.0:
            high = midpoint
        else:
            low = midpoint
            low_value = value
    return (low + high) / 2.0


def _strategy_result(name: str, net_worth: np.ndarray, payment: float,
                     monthly_outflow: float, financing_cost: float,
                     sale: SaleEstimate, residual_debt: float,
                     annual_inflation: float, horizon_years: int) -> FinancingStrategy:
    p10, median, p90 = np.percentile(net_worth[:, -1], [10, 50, 90])
    median_path = np.median(net_worth, axis=0)
    real_factor = (1.0 + annual_inflation) ** horizon_years
    return FinancingStrategy(
        name=name,
        monthly_payment_eur=payment,
        monthly_outflow_eur=monthly_outflow,
        financing_cost_eur=financing_cost,
        gross_sale_eur=sale.gross_sale_eur,
        estimated_sale_tax_eur=sale.estimated_tax_eur,
        sale_commission_eur=sale.commission_eur,
        residual_debt_eur=residual_debt,
        p10_net_worth_eur=float(p10),
        median_net_worth_eur=float(median),
        p90_net_worth_eur=float(p90),
        median_real_net_worth_eur=float(median / real_factor),
        probability_beats_sale=None,
        break_even_annual_return=None,
        median_path_eur=tuple(float(value) for value in median_path),
    )


def simulate_financing_decision(
        current_values_eur: dict[str, float], cost_basis_eur: dict[str, float],
        net_needed_eur: float, monthly_budget_eur: float, horizon_years: int,
        expected_annual_return: float, annual_volatility: float,
        annual_inflation: float, financing_options: tuple[FinancingOption, ...],
        tax_rate: float = 0.26, sale_commission_eur: float = 0.0,
        simulations: int = 2000, seed: int = 42) -> FinancingDecision:
    horizon_months = horizon_years * 12
    monthly_sigma = annual_volatility / math.sqrt(12.0)
    monthly_log_drift = math.log1p(expected_annual_return) / 12.0
    monthly_log_drift -= 0.5 * monthly_sigma ** 2
    rng = np.random.default_rng(seed)
    growth = np.exp(
        monthly_log_drift
        + monthly_sigma * rng.standard_normal((simulations, horizon_months)))
    total_value = sum(current_values_eur.values())
    errors = []
    strategies = {}
    sale_initial = None
    sale_contributions = tuple(monthly_budget_eur for _ in range(horizon_months))
    final_sale = None
    try:
        full_sale = estimate_proportional_sale(
            current_values_eur, cost_basis_eur, net_needed_eur,
            tax_rate, sale_commission_eur)
    except ValueError as e:
        errors.append(f"Vendita titoli: {e}")
    else:
        no_debt = tuple(0.0 for _ in range(horizon_months + 1))
        sale_initial = total_value - full_sale.gross_sale_eur
        sale_net_worth = _simulate_investment(
            sale_initial, sale_contributions, growth, no_debt)
        strategies["Vendita titoli"] = _strategy_result(
            "Vendita titoli", sale_net_worth, 0.0, 0.0, 0.0,
            full_sale, 0.0, annual_inflation, horizon_years)
        final_sale = sale_net_worth[:, -1]
    for option in financing_options:
        if option.financed_amount_eur > net_needed_eur:
            errors.append(
                f"{option.name}: l'importo finanziato supera la spesa residua.")
            continue
        payment, balances = _debt_balances(
            option.financed_amount_eur, option.annual_interest_rate,
            option.months, horizon_months)
        monthly_tax_benefit = option.annual_tax_benefit_eur / 12.0
        monthly_outflow = payment + option.monthly_cost_eur - monthly_tax_benefit
        if monthly_outflow < 0.0:
            errors.append(
                f"{option.name}: il beneficio fiscale supera rata e costi mensili.")
            continue
        if monthly_outflow > monthly_budget_eur:
            errors.append(
                f"{option.name}: rata e costi mensili superano il budget disponibile.")
            continue
        uncovered = net_needed_eur - option.financed_amount_eur
        partial_sale = estimate_proportional_sale(
            current_values_eur, cost_basis_eur, uncovered,
            tax_rate, sale_commission_eur if uncovered > 0.0 else 0.0)
        contributions = tuple(
            monthly_budget_eur - monthly_outflow if month <= option.months
            else monthly_budget_eur
            for month in range(1, horizon_months + 1))
        initial = total_value - partial_sale.gross_sale_eur - option.upfront_cost_eur
        net_worth = _simulate_investment(initial, contributions, growth, balances)
        financing_cost = (
            payment * option.months - option.financed_amount_eur
            + option.upfront_cost_eur + option.monthly_cost_eur * option.months
            - monthly_tax_benefit * option.months)
        strategy = _strategy_result(
            option.name, net_worth, payment, monthly_outflow, financing_cost,
            partial_sale, balances[-1], annual_inflation, horizon_years)
        probability = None
        break_even = None
        if final_sale is not None and sale_initial is not None:
            differences = net_worth[:, -1] - final_sale
            probability = float(np.mean(np.where(
                np.isclose(differences, 0.0, atol=1e-8),
                0.5, differences > 0.0)))
            break_even = _break_even_return(
                sale_initial, sale_contributions,
                initial, contributions, balances[-1])
        strategies[option.name] = replace(
            strategy, probability_beats_sale=probability,
            break_even_annual_return=break_even)
    return FinancingDecision(tuple(range(horizon_months + 1)), strategies, tuple(errors))
