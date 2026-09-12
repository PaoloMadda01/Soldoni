import math
from datetime import date


def _npv(rate: float, amounts: list[float], years: list[float]) -> float:
    return sum(a / (1.0 + rate) ** y for a, y in zip(amounts, years))


def xirr(amounts: list[float], dates: list[date], guess: float = 0.1) -> float | None:
    """Rendimento annualizzato money-weighted sui flussi (amounts, dates).

    Risolve NPV(r) = Σ amounts[i]/(1+r)^(giorni_i/365) = 0. Newton-Raphson da `guess`,
    fallback a bisezione su [-0.9999, 10.0]. None se <2 flussi, segni tutti uguali, o
    nessuna convergenza."""
    if len(amounts) < 2 or len(amounts) != len(dates):
        return None
    if all(a >= 0 for a in amounts) or all(a <= 0 for a in amounts):
        return None
    d0 = dates[0]
    years = [(d - d0).days / 365.0 for d in dates]

    # Newton-Raphson
    rate = guess
    for _ in range(100):
        if rate <= -1.0:
            break
        f = _npv(rate, amounts, years)
        if abs(f) < 1e-6:
            return rate
        df = sum(-y * a / (1.0 + rate) ** (y + 1.0) for a, y in zip(amounts, years))
        if df == 0:
            break
        new_rate = rate - f / df
        if not math.isfinite(new_rate):
            break
        rate = new_rate

    # Bisezione su [-0.9999, 10.0]
    lo, hi = -0.9999, 10.0
    f_lo = _npv(lo, amounts, years)
    f_hi = _npv(hi, amounts, years)
    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi
    if (f_lo > 0) == (f_hi > 0):
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = _npv(mid, amounts, years)
        if abs(f_mid) < 1e-9:
            return mid
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi, f_hi = mid, f_mid
    return (lo + hi) / 2.0
