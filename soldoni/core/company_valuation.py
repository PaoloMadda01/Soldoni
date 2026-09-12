"""Modelli per azione: tassi in frazione e importi nella stessa valuta."""

import math
import logging
from dataclasses import dataclass, replace
from numbers import Real

from soldoni.core.cash_flow import CashFlowPeriod
from soldoni.data.fundamentals import Fundamentals

logger = logging.getLogger(__name__)


def _number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{name}: dato assente o non finito.")
    return float(value)


def _positive(value: float, name: str) -> float:
    value = _number(value, name)
    if value <= 0:
        raise ValueError(f"{name}: deve essere positivo per questo modello.")
    return value


def _growth(value: float) -> float:
    value = _number(value, "Crescita")
    if value <= -1:
        raise ValueError("La crescita deve essere maggiore di -100%.")
    return value


def _spread(required_return: float, growth: float) -> float:
    required_return = _positive(required_return, "Rendimento richiesto")
    growth = _growth(growth)
    if required_return <= growth:
        raise ValueError("Il rendimento richiesto deve superare la crescita perpetua.")
    return required_return - growth


def gordon_value(dividend: float, required_return: float, growth: float) -> float:
    """Valore D0*(1+g)/(r-g), per dividendi positivi a crescita costante."""
    spread = _spread(required_return, growth)
    value = _positive(dividend, "Dividendo annuo") * (1 + growth) / spread
    return _positive(value, "Valore Gordon")


def graham_number(eps: float, book_value: float) -> float:
    """Riferimento sqrt(22.5*EPS*BVPS); entrambi i fattori devono essere positivi."""
    value = math.sqrt(22.5 * _positive(eps, "EPS") * _positive(book_value, "BVPS"))
    return _positive(value, "Numero di Graham")


def earnings_multiple_value(eps: float, multiple: float) -> float:
    """Valore per azione = EPS trailing * P/E obiettivo."""
    value = _positive(eps, "EPS") * _positive(multiple, "P/E obiettivo")
    return _positive(value, "Valore con P/E")


def implied_dividend_growth(dividend: float, price: float, required_return: float) -> float:
    """Crescita implicita in Gordon usando D0, prezzo e rendimento richiesto."""
    dividend = _positive(dividend, "Dividendo annuo")
    price = _positive(price, "Prezzo")
    required_return = _positive(required_return, "Rendimento richiesto")
    return _number((price * required_return - dividend) / (price + dividend),
                   "Crescita implicita")


def _two_stage_value(base: float, growth: float, terminal_growth: float,
                     required_return: float, years: int) -> float:
    growth = _growth(growth)
    spread = _spread(required_return, terminal_growth)
    if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 100:
        raise ValueError("L'orizzonte deve essere un intero tra 1 e 100 anni.")
    value = 0.0
    flow = base
    discount = 1.0
    for _ in range(years):
        flow *= 1 + growth
        discount *= 1 + required_return
        value += flow / discount
    value += flow * (1 + terminal_growth) / spread / discount
    return _positive(value, "Valore attualizzato")


def two_stage_dividend_value(dividend: float, growth: float, terminal_growth: float,
                             required_return: float, years: int) -> float:
    """Dividendi iniziali espliciti più terminale Gordon, entrambi attualizzati."""
    return _two_stage_value(_positive(dividend, "Dividendo annuo"), growth,
                            terminal_growth, required_return, years)


def dcf_equity_value(fcfe: float, shares: float, growth: float, terminal_growth: float,
                     required_return: float, years: int) -> float:
    """DCF del FCFE per azione, a numero di azioni costante; nessun ulteriore debito."""
    per_share = _positive(fcfe, "FCFE") / _positive(shares, "Numero di azioni")
    return _two_stage_value(per_share, growth, terminal_growth, required_return, years)


def fcfe_from_cashflow(operating_cashflow: float, capex: float, net_borrowing: float) -> float:
    """FCFE = CFO - CapEx (uscita) + debito emesso meno debito rimborsato."""
    value = (_number(operating_cashflow, "Cash flow operativo")
             - abs(_number(capex, "CapEx")) + _number(net_borrowing, "Indebitamento netto"))
    return _number(value, "FCFE")


def margin_of_safety_price(value: float, margin: float) -> float:
    """Prezzo soglia ottenuto applicando uno sconto al valore stimato."""
    value = _positive(value, "Valore stimato")
    margin = _number(margin, "Margine di sicurezza")
    if not 0 <= margin < 1:
        raise ValueError("Il margine di sicurezza deve essere tra 0% incluso e 100% escluso.")
    return value * (1 - margin)


@dataclass(frozen=True)
class ValuationAssumptions:
    required_return: float = 0.10
    terminal_growth: float = 0.02
    dividend_growth: float = 0.05
    fcfe_growth: float = 0.05
    years: int = 5
    multiple: float = 15.0
    margin: float = 0.20


@dataclass(frozen=True)
class ValuationEstimate:
    value: float | None
    reason: str = ""
    upside: float | None = None
    safety_price: float | None = None


@dataclass(frozen=True)
class CompanyValuation:
    models: dict[str, ValuationEstimate]
    fcfe: ValuationEstimate
    implied_growth: ValuationEstimate
    currency_issue: str


def _estimate(name, calculation, unavailable=""):
    if unavailable:
        return ValuationEstimate(None, unavailable)
    try:
        return ValuationEstimate(calculation())
    except ValueError as e:
        logger.warning("%s non disponibile: %s", name, e)
        return ValuationEstimate(None, str(e))


def _financial_currency_issue(fund):
    currency = fund.currency or ""
    if len(currency) != 3 or not currency.isalpha() or not currency.isupper():
        return "Valuta di quotazione assente o in subunità: confronto automatico non disponibile."
    if not fund.financial_currency:
        return "Valuta del bilancio non disponibile: confronto monetario non verificabile."
    if fund.financial_currency != currency:
        return (f"Valute diverse: bilancio {fund.financial_currency}, quotazione {currency}. "
                "Serve una conversione verificata dei dati per azione.")
    return ""


def _is_positive(value):
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def _share_count_issue(fund):
    if not _is_positive(fund.shares_outstanding):
        return "Numero di azioni non disponibile o non positivo."
    checks = []
    if _is_positive(fund.implied_shares_outstanding):
        checks.append(math.isclose(fund.shares_outstanding, fund.implied_shares_outstanding,
                                    rel_tol=0.01))
    if _is_positive(fund.price) and _is_positive(fund.market_cap):
        checks.append(math.isclose(fund.shares_outstanding * fund.price, fund.market_cap,
                                    rel_tol=0.01))
    if not checks:
        return "Dati insufficienti per verificare il numero di azioni equivalente del DCF."
    if not all(checks):
        return ("Numero di azioni, azioni equivalenti e capitalizzazione non coerenti entro 1%: "
                "possibili classi diverse o dati non allineati. DCF non confrontabile.")
    return ""


def evaluate_company(fund: Fundamentals, period: CashFlowPeriod,
                     assumptions: ValuationAssumptions) -> CompanyValuation:
    """Calcola tutti i modelli con le stesse ipotesi e verifiche di applicabilità."""
    a = assumptions
    currency_issue = _financial_currency_issue(fund)
    row = period.values
    fcfe = _estimate("FCFE", lambda: fcfe_from_cashflow(
        row.get("operating_cashflow"), row.get("capex"), row.get("net_borrowing")))
    dcf_issue = currency_issue or fcfe.reason or _share_count_issue(fund)
    if fund.sector in {"Financial Services", "Real Estate"}:
        dcf_issue = "Il DCF generico sui flussi non è applicato al settore finanziario/immobiliare."
    models = {}
    for name, calculate, issue in [
        ("Gordon", lambda: gordon_value(fund.annual_dividend, a.required_return,
                                       a.terminal_growth), currency_issue),
        ("DDM a due fasi", lambda: two_stage_dividend_value(
            fund.annual_dividend, a.dividend_growth, a.terminal_growth, a.required_return,
            a.years), currency_issue),
        ("Graham", lambda: graham_number(fund.trailing_eps, fund.book_value), currency_issue),
        ("P/E obiettivo", lambda: earnings_multiple_value(fund.trailing_eps, a.multiple),
         currency_issue),
        ("DCF (FCFE)", lambda: dcf_equity_value(fcfe.value, fund.shares_outstanding,
            a.fcfe_growth, a.terminal_growth, a.required_return, a.years), dcf_issue),
    ]:
        estimate = _estimate(name, calculate, issue)
        if estimate.value is not None:
            estimate = replace(estimate,
                upside=(estimate.value / fund.price - 1) * 100 if _is_positive(fund.price) else None,
                safety_price=margin_of_safety_price(estimate.value, a.margin))
        models[name] = estimate
    implied = _estimate("Gordon inverso", lambda: implied_dividend_growth(
        fund.annual_dividend, fund.price, a.required_return), currency_issue)
    return CompanyValuation(models, fcfe, implied, currency_issue)


def scenario_assumptions(base: ValuationAssumptions, scenario: str) -> ValuationAssumptions:
    """Variazioni comuni alle aziende: rendimento ±2 punti, crescita ±1/2 punti."""
    if scenario not in {"Prudente", "Base", "Ottimista"}:
        raise ValueError(f"Scenario non valido: {scenario}")
    direction = {"Prudente": -1, "Base": 0, "Ottimista": 1}[scenario]
    return replace(base, required_return=base.required_return - direction * 0.02,
                   terminal_growth=base.terminal_growth + direction * 0.01,
                   dividend_growth=base.dividend_growth + direction * 0.02,
                   fcfe_growth=base.fcfe_growth + direction * 0.02)
