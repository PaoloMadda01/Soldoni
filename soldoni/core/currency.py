from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from soldoni.core.models import Instrument, OpType, Transaction


def currency_exposure(current_value_eur: dict[str, float],
                      instruments: dict[str, Instrument]) -> dict[str, float]:
    """Somma del valore EUR per valuta di quotazione (Instrument.native_currency)."""
    out: dict[str, float] = {}
    for isin, value in current_value_eur.items():
        inst = instruments.get(isin)
        if inst is None:
            raise ValueError(f"Anagrafica mancante per {isin}")
        out[inst.native_currency] = out.get(inst.native_currency, 0.0) + value
    return out


def weighted_entry_fx(transactions: list[Transaction],
                      entry_rate: Callable[[Transaction], float]) -> dict[str, float]:
    """Cambio medio d'ingresso r₀ per ISIN dai soli acquisti, pesato per amount_eur:
       r₀ = Σ(amount_eur × entry_rate(t)) / Σ(amount_eur). Native per 1 EUR.
    `entry_rate(t)` fornisce il cambio (native per EUR) alla data dell'acquisto `t`
    (l'export Fineco registra in EUR con cambio 1.0, quindi va recuperato dallo storico)."""
    num: dict[str, float] = {}
    den: dict[str, float] = {}
    for t in transactions:
        if t.op_type is not OpType.BUY:
            continue
        num[t.isin] = num.get(t.isin, 0.0) + t.amount_eur * entry_rate(t)
        den[t.isin] = den.get(t.isin, 0.0) + t.amount_eur
    return {isin: num[isin] / den[isin] for isin in num if den[isin] != 0}


@dataclass
class FxSplit:
    isin: str
    price_eur: float
    fx_eur: float

    @property
    def total_eur(self) -> float:
        return self.price_eur + self.fx_eur


def fx_price_decomposition(
    cost_eur: dict[str, float],
    current_value_eur: dict[str, float],
    entry_fx: dict[str, float],
    current_fx: dict[str, float],
) -> list[FxSplit]:
    """Scompone il P/L latente lordo (V_eur − C_eur) in prezzo + cambio per posizione.

    price_eur = V_eur·(r₁/r₀) − C_eur ; fx_eur = V_eur·(1 − r₁/r₀).
    Somma = V_eur − C_eur. EUR (r₀=r₁=1): fx_eur=0. r₀≈0 -> ISIN saltato.
    Ordinata per total_eur decrescente.
    """
    splits: list[FxSplit] = []
    for isin in cost_eur:
        if isin not in current_value_eur or isin not in entry_fx or isin not in current_fx:
            continue
        r0 = entry_fx[isin]
        if abs(r0) < 1e-9:
            continue
        r1 = current_fx[isin]
        v = current_value_eur[isin]
        c = cost_eur[isin]
        price_eur = v * (r1 / r0) - c
        fx_eur = v * (1.0 - r1 / r0)
        splits.append(FxSplit(isin=isin, price_eur=price_eur, fx_eur=fx_eur))
    splits.sort(key=lambda s: s.total_eur, reverse=True)
    return splits


@dataclass(frozen=True)
class CurrencyScenario:
    constant_fx_value_eur: float
    final_value_eur: float
    market_gain_eur: float
    fx_impact_eur: float
    total_gain_eur: float
    total_return: float
    break_even_eur_usd: float | None


def simulate_currency(initial_eur: float, usd_return: float,
                      initial_eur_usd: float, final_eur_usd: float) -> CurrencyScenario:
    """Convert a total USD return to EUR. Both rates are USD per 1 EUR.

    The scenario has no currency hedge, fees, taxes or intermediate cash flows.
    A total loss has no positive break-even exchange rate.
    """
    for value, label in ((initial_eur, "Il capitale iniziale"),
                         (initial_eur_usd, "Il cambio iniziale"),
                         (final_eur_usd, "Il cambio finale")):
        if not isfinite(value) or value <= 0.0:
            raise ValueError(f"{label} deve essere un numero finito maggiore di zero.")
    if not isfinite(usd_return) or usd_return < -1.0:
        raise ValueError("Il rendimento in dollari deve essere finito e almeno -100%.")

    constant_fx_value = initial_eur * (1.0 + usd_return)
    final_value = constant_fx_value * (initial_eur_usd / final_eur_usd)
    market_gain = constant_fx_value - initial_eur
    fx_impact = final_value - constant_fx_value
    total_gain = final_value - initial_eur
    total_return = total_gain / initial_eur
    break_even = initial_eur_usd * (1.0 + usd_return)
    if not all(isfinite(value) for value in (
            constant_fx_value, final_value, market_gain, fx_impact,
            total_gain, total_return, break_even)):
        raise ValueError("I valori inseriti sono troppo grandi per calcolare lo scenario.")
    return CurrencyScenario(
        constant_fx_value_eur=constant_fx_value,
        final_value_eur=final_value,
        market_gain_eur=market_gain,
        fx_impact_eur=fx_impact,
        total_gain_eur=total_gain,
        total_return=total_return,
        break_even_eur_usd=break_even if break_even > 0.0 else None,
    )
