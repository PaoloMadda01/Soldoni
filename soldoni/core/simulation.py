from dataclasses import dataclass
from datetime import date
import math

import numpy as np
import pandas as pd

from soldoni.core.risk import business_day_returns, annualized_volatility


@dataclass(frozen=True)
class StressLine:
    isin: str
    current_value_eur: float
    shock: float
    stressed_value_eur: float
    impact_eur: float


@dataclass(frozen=True)
class StressResult:
    lines: tuple[StressLine, ...]
    total_value_eur: float
    covered_value_eur: float
    stressed_covered_value_eur: float
    impact_eur: float
    coverage: float


@dataclass(frozen=True)
class GoalSimulation:
    months: tuple[int, ...]
    p10_values_eur: tuple[float, ...]
    median_values_eur: tuple[float, ...]
    p90_values_eur: tuple[float, ...]
    success_probability: float
    p10_goal_month: int | None
    median_goal_month: int | None
    p90_goal_month: int | None


@dataclass(frozen=True)
class HistoricalAssumptions:
    annual_return: float
    annual_volatility: float
    start_date: date
    end_date: date


def historical_assumptions(index_series: pd.Series) -> HistoricalAssumptions:
    values = index_series.dropna().sort_index()
    if len(values) < 2:
        raise ValueError("Servono almeno due valori storici.")
    start = pd.Timestamp(values.index[0])
    end = pd.Timestamp(values.index[-1])
    if end < start + pd.DateOffset(years=1):
        raise ValueError("Serve almeno un anno di storico.")
    elapsed_years = (end - start).total_seconds() / (365.25 * 24.0 * 60.0 * 60.0)
    first = float(values.iloc[0])
    last = float(values.iloc[-1])
    if first <= 0.0 or last <= 0.0:
        raise ValueError("I valori storici iniziale e finale devono essere positivi.")
    annual_return = (last / first) ** (1.0 / elapsed_years) - 1.0
    volatility = annualized_volatility(business_day_returns(values))
    if pd.isna(volatility):
        raise ValueError("I dati storici non sono sufficienti per calcolare la volatilità.")
    return HistoricalAssumptions(
        annual_return, volatility, start.date(), end.date())


def _validate_amount(value: float, label: str, allow_zero: bool = True) -> None:
    if not math.isfinite(value) or value < 0.0 or (not allow_zero and value == 0.0):
        suffix = "non negativo" if allow_zero else "maggiore di zero"
        raise ValueError(f"{label} deve essere un numero finito e {suffix}.")


def _validate_assumptions(annual_return: float, annual_inflation: float) -> None:
    if not math.isfinite(annual_return) or annual_return <= -1.0:
        raise ValueError("Il rendimento annuo deve essere maggiore di -100%.")
    if not math.isfinite(annual_inflation) or annual_inflation <= -1.0:
        raise ValueError("L'inflazione annua deve essere maggiore di -100%.")


def stress_portfolio(current_values_eur: dict[str, float],
                     shocks: dict[str, float]) -> StressResult:
    for value in current_values_eur.values():
        _validate_amount(value, "Il valore corrente")
    total = sum(current_values_eur.values())
    lines = []
    for isin in sorted(current_values_eur):
        if isin not in shocks:
            continue
        shock = shocks[isin]
        if not math.isfinite(shock) or shock < -1.0:
            raise ValueError("Uno shock non può essere inferiore a -100%.")
        current = current_values_eur[isin]
        stressed = current * (1.0 + shock)
        lines.append(StressLine(isin, current, shock, stressed, stressed - current))
    covered = sum(line.current_value_eur for line in lines)
    stressed_covered = sum(line.stressed_value_eur for line in lines)
    impact = stressed_covered - covered
    return StressResult(
        tuple(lines), total, covered, stressed_covered, impact,
        covered / total if total else 0.0)


def months_to_target(initial_value_eur: float,
                     monthly_contribution_eur: float,
                     target_eur: float,
                     annual_return: float,
                     annual_inflation: float = 0.0,
                     target_in_today_euros: bool = False,
                     max_months: int = 600) -> int | None:
    _validate_amount(initial_value_eur, "Il capitale iniziale")
    _validate_amount(monthly_contribution_eur, "Il versamento mensile")
    _validate_amount(target_eur, "L'obiettivo", allow_zero=False)
    _validate_assumptions(annual_return, annual_inflation)
    if not isinstance(max_months, int) or max_months <= 0:
        raise ValueError("L'orizzonte deve contenere almeno un mese.")
    if initial_value_eur >= target_eur:
        return 0

    monthly_return = (1.0 + annual_return) ** (1.0 / 12.0) - 1.0
    monthly_inflation = (1.0 + annual_inflation) ** (1.0 / 12.0) - 1.0
    value = initial_value_eur
    target = target_eur
    for month in range(1, max_months + 1):
        value = value * (1.0 + monthly_return) + monthly_contribution_eur
        if target_in_today_euros:
            target *= 1.0 + monthly_inflation
        if value >= target:
            return month
    return None


def _goal_percentile(hit_months: np.ndarray, months: int, percentile: float) -> int | None:
    encoded = np.where(hit_months >= 0, hit_months, months + 1)
    ordered = np.sort(encoded)
    index = math.ceil(percentile * (len(ordered) - 1))
    value = int(ordered[index])
    return value if value <= months else None


def simulate_goal(initial_value_eur: float,
                  monthly_contribution_eur: float,
                  target_eur: float,
                  expected_annual_return: float,
                  annual_volatility: float,
                  annual_inflation: float,
                  years: int,
                  simulations: int = 2000,
                  seed: int = 42,
                  target_in_today_euros: bool = False) -> GoalSimulation:
    _validate_amount(initial_value_eur, "Il capitale iniziale")
    _validate_amount(monthly_contribution_eur, "Il versamento mensile")
    _validate_amount(target_eur, "L'obiettivo", allow_zero=False)
    _validate_assumptions(expected_annual_return, annual_inflation)
    _validate_amount(annual_volatility, "La volatilità annua")
    if not isinstance(years, int) or years <= 0:
        raise ValueError("L'orizzonte deve essere di almeno un anno.")
    if not isinstance(simulations, int) or simulations <= 0:
        raise ValueError("Il numero di simulazioni deve essere positivo.")

    months = years * 12
    values = np.empty((simulations, months + 1), dtype=float)
    values[:, 0] = initial_value_eur
    hit_months = np.full(simulations, -1, dtype=int)
    if initial_value_eur >= target_eur:
        hit_months[:] = 0

    monthly_sigma = annual_volatility / math.sqrt(12.0)
    monthly_log_drift = math.log1p(expected_annual_return) / 12.0
    monthly_log_drift -= 0.5 * monthly_sigma ** 2
    monthly_inflation = math.log1p(annual_inflation) / 12.0
    rng = np.random.default_rng(seed)

    for month in range(1, months + 1):
        random_returns = rng.standard_normal(simulations)
        growth = np.exp(monthly_log_drift + monthly_sigma * random_returns)
        values[:, month] = values[:, month - 1] * growth + monthly_contribution_eur
        target = (target_eur * math.exp(monthly_inflation * month)
                  if target_in_today_euros else target_eur)
        reached = (hit_months < 0) & (values[:, month] >= target)
        hit_months[reached] = month

    p10, median, p90 = np.percentile(values, [10, 50, 90], axis=0)
    return GoalSimulation(
        months=tuple(range(months + 1)),
        p10_values_eur=tuple(float(value) for value in p10),
        median_values_eur=tuple(float(value) for value in median),
        p90_values_eur=tuple(float(value) for value in p90),
        success_probability=float(np.mean(hit_months >= 0)),
        p10_goal_month=_goal_percentile(hit_months, months, 0.10),
        median_goal_month=_goal_percentile(hit_months, months, 0.50),
        p90_goal_month=_goal_percentile(hit_months, months, 0.90),
    )
