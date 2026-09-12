from dataclasses import dataclass
from datetime import date
from soldoni.core.holdings import RealizedSale
from soldoni.core.models import Instrument
from soldoni.core.net_gain import IT_RATE

EXPIRY_YEARS = 4


@dataclass
class ZainettoResult:
    capital_tax_eur: float
    gross_realized_eur: float
    minus_generated_eur: float
    minus_used_eur: float
    taxable_gains_eur: float
    residual_by_expiry: dict[int, float]


def compute_zainetto(realized_sales: list[RealizedSale],
                     instruments: dict[str, Instrument],
                     rate: float = IT_RATE,
                     today_year: int | None = None) -> ZainettoResult:
    """Compensazione cronologica FIFO delle minusvalenze con distinzione ETF/azioni.

    - perdita (qualsiasi strumento) -> minus nel paniere, taggata con l'anno;
    - plus azione/obbligazione -> compensata con minus non scadute (anno_realizzo + EXPIRY_YEARS),
      `rate` sul residuo;
    - plus ETF (asset_class == 'etf') -> `rate` pieno, niente compensazione.
    Approssimazione: compensazione cronologica (il fisco netta per anno solare).
    """
    pool: list[list] = []   # [anno_realizzo, importo_residuo]
    minus_generated = minus_used = capital_tax = taxable_gains = gross_realized = 0.0
    for s in sorted(realized_sales, key=lambda x: x.date):
        gross_realized += s.gain_eur
        inst = instruments.get(s.isin)
        is_etf = inst is not None and inst.asset_class == "etf"
        g = s.gain_eur
        y = s.date.year
        if g < 0:
            pool.append([y, -g])
            minus_generated += -g
        elif g > 0:
            if is_etf:
                capital_tax += rate * g
                taxable_gains += g
            else:
                remaining = g
                for lot in pool:
                    if remaining <= 0:
                        break
                    if lot[1] <= 0 or y - lot[0] > EXPIRY_YEARS:
                        continue
                    use = min(lot[1], remaining)
                    lot[1] -= use
                    remaining -= use
                    minus_used += use
                capital_tax += rate * remaining
                taxable_gains += remaining
    residual: dict[int, float] = {}
    if today_year is not None:
        for ly, amt in pool:
            if amt > 1e-9 and today_year - ly <= EXPIRY_YEARS:
                expiry = ly + EXPIRY_YEARS
                residual[expiry] = residual.get(expiry, 0.0) + amt
    return ZainettoResult(capital_tax_eur=capital_tax, gross_realized_eur=gross_realized,
                          minus_generated_eur=minus_generated, minus_used_eur=minus_used,
                          taxable_gains_eur=taxable_gains, residual_by_expiry=residual)


def compute_zainetto_for_year(realized_sales: list[RealizedSale],
                              instruments: dict[str, Instrument],
                              year: int | None = None,
                              as_of: date | None = None) -> ZainettoResult:
    """Totali dell'anno e saldo minus alla data finale, con riporto degli anni precedenti.

    Con year=None i totali comprendono tutto lo storico fino ad as_of (oggi di default).
    Il saldo per scadenza è cumulativo anche quando i movimenti sono filtrati per anno.
    """
    today = as_of or date.today()
    if year is not None and not 1 <= year <= today.year:
        raise ValueError("L'anno deve essere compreso tra 1 e l'anno di riferimento")
    cutoff = min(today, date(year, 12, 31)) if year is not None else today
    sales = [sale for sale in realized_sales if sale.date <= cutoff]
    current = compute_zainetto(sales, instruments, today_year=cutoff.year)
    if year is None:
        return current
    previous = compute_zainetto(
        [sale for sale in sales if sale.date.year < year], instruments)
    return ZainettoResult(
        capital_tax_eur=current.capital_tax_eur - previous.capital_tax_eur,
        gross_realized_eur=current.gross_realized_eur - previous.gross_realized_eur,
        minus_generated_eur=current.minus_generated_eur - previous.minus_generated_eur,
        minus_used_eur=current.minus_used_eur - previous.minus_used_eur,
        taxable_gains_eur=current.taxable_gains_eur - previous.taxable_gains_eur,
        residual_by_expiry=current.residual_by_expiry,
    )
