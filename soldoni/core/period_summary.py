from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from soldoni.core.models import OpType, Transaction
from soldoni.core.twr import twr_index
from soldoni.core.valuation import quantity_timeline


@dataclass(frozen=True)
class PeriodContribution:
    isin: str
    initial_value_eur: float
    final_value_eur: float
    purchases_eur: float
    sales_eur: float
    dividends_eur: float
    commissions_eur: float
    result_eur: float


@dataclass(frozen=True)
class PeriodSummary:
    requested_start: date
    requested_end: date
    effective_start: date
    effective_end: date
    initial_value_eur: float
    final_value_eur: float
    purchases_eur: float
    sales_eur: float
    dividends_eur: float
    commissions_eur: float
    result_eur: float
    twr_return: float | None
    benchmark_return: float | None
    contributions: tuple[PeriodContribution, ...]


def required_price_isins(transactions: list[Transaction],
                         start: date, end: date) -> set[str]:
    if start > end:
        raise ValueError("La data iniziale deve precedere la data finale.")
    quantities: dict[str, float] = {}
    for tx in transactions:
        if tx.trade_date >= start or tx.op_type is OpType.DIVIDEND:
            continue
        sign = 1.0 if tx.op_type is OpType.BUY else -1.0
        quantities[tx.isin] = quantities.get(tx.isin, 0.0) + sign * tx.quantity
    required = {isin for isin, quantity in quantities.items() if abs(quantity) >= 1e-6}
    required.update(
        tx.isin for tx in transactions
        if start <= tx.trade_date <= end and tx.op_type is not OpType.DIVIDEND)
    return required


def _money_flows(transactions: list[Transaction], start: date, end: date,
                 isin: str | None = None) -> tuple[float, float, float, float]:
    selected = [
        tx for tx in transactions
        if start <= tx.trade_date <= end and (isin is None or tx.isin == isin)
    ]
    purchases = sum(tx.amount_eur for tx in selected if tx.op_type is OpType.BUY)
    sales = sum(tx.amount_eur for tx in selected if tx.op_type is OpType.SELL)
    dividends = sum(tx.amount_eur for tx in selected if tx.op_type is OpType.DIVIDEND)
    commissions = sum(tx.commission_eur for tx in selected)
    return purchases, sales, dividends, commissions


def _twr_return(values: pd.Series, cashflows: pd.Series) -> tuple[float | None, pd.Timestamp]:
    positive = values[values > 1e-9]
    if positive.empty:
        return None, values.index[0]
    first = positive.index[0]
    after_first = values.loc[first:]
    zero_dates = after_first.index[after_first <= 1e-9]
    if len(zero_dates):
        first_zero = zero_dates[0]
        if (after_first.loc[first_zero:] > 1e-9).any():
            return None, first
        calculation = after_first.loc[:first_zero]
    else:
        calculation = after_first
    index = twr_index(calculation, cashflows.reindex(calculation.index).fillna(0.0))
    if index.empty:
        return None, first
    return float(index.iloc[-1] / index.iloc[0] - 1.0), first


def _benchmark_return(benchmark_eur: pd.Series | None,
                      effective_start: date, end: date) -> float | None:
    if benchmark_eur is None or benchmark_eur.dropna().empty:
        return None
    benchmark = benchmark_eur.sort_index().ffill()
    base_date = pd.Timestamp(effective_start - timedelta(days=1))
    bases = benchmark.loc[benchmark.index <= base_date].dropna()
    finals = benchmark.loc[benchmark.index <= pd.Timestamp(end)].dropna()
    if bases.empty or finals.empty or bases.iloc[-1] == 0:
        return None
    return float(finals.iloc[-1] / bases.iloc[-1] - 1.0)


def summarize_period(transactions: list[Transaction], prices_eur: pd.DataFrame,
                     start: date, end: date,
                     benchmark_eur: pd.Series | None = None) -> PeriodSummary:
    required = required_price_isins(transactions, start, end)
    missing = sorted(required - set(prices_eur.columns))
    if missing:
        raise ValueError("Prezzi mancanti per: " + ", ".join(missing))
    if len(prices_eur.index) == 0:
        raise ValueError("Nessuna serie prezzi disponibile per il periodo.")

    prices = prices_eur.sort_index()
    prices.index = pd.to_datetime(prices.index)
    period_dates = prices.index[
        (prices.index >= pd.Timestamp(start)) & (prices.index <= pd.Timestamp(end))]
    base_dates = prices.index[prices.index < pd.Timestamp(start)]
    if period_dates.empty:
        raise ValueError("Nessuna data disponibile nell'intervallo selezionato.")
    if base_dates.empty:
        raise ValueError("Manca una data di valutazione precedente all'intervallo.")
    base_date = base_dates[-1]
    effective_end = period_dates[-1]
    calculation_dates = prices.index[
        (prices.index >= base_date) & (prices.index <= effective_end)]

    priced_transactions = [
        tx for tx in transactions
        if tx.isin in required and tx.trade_date <= effective_end.date()
    ]
    quantities = quantity_timeline(priced_transactions, prices.index)
    quantities = quantities.reindex(columns=sorted(required), fill_value=0.0)
    if (quantities < -1e-6).any().any():
        raise ValueError("Storico acquisti incompleto: una posizione risulta negativa nel periodo.")
    period_prices = prices.reindex(columns=sorted(required)).ffill()
    unavailable = []
    for isin in required:
        held = quantities.loc[calculation_dates, isin].abs() >= 1e-6
        if (held & period_prices.loc[calculation_dates, isin].isna()).any():
            unavailable.append(isin)
    if unavailable:
        raise ValueError("Copertura prezzi incompleta per: " + ", ".join(sorted(unavailable)))

    values_by_isin = (quantities * period_prices).where(quantities.abs() >= 1e-6, 0.0)
    portfolio_values = values_by_isin.sum(axis=1).loc[calculation_dates]
    initial_value = float(values_by_isin.loc[base_date].sum())
    final_value = float(values_by_isin.loc[effective_end].sum())
    purchases, sales, dividends, commissions = _money_flows(
        transactions, start, effective_end.date())
    result = final_value - initial_value - purchases + sales + dividends - commissions

    cashflows = pd.Series(0.0, index=calculation_dates)
    for tx in transactions:
        timestamp = pd.Timestamp(tx.trade_date)
        if timestamp not in cashflows.index or not start <= tx.trade_date <= effective_end.date():
            continue
        if tx.op_type is OpType.BUY:
            cashflows.loc[timestamp] += tx.amount_eur + tx.commission_eur
        elif tx.op_type is OpType.SELL:
            cashflows.loc[timestamp] -= tx.amount_eur - tx.commission_eur
        else:
            cashflows.loc[timestamp] -= tx.amount_eur - tx.commission_eur
    twr_return, first_invested = _twr_return(portfolio_values, cashflows)
    effective_start = max(start, first_invested.date())

    all_isins = required | {
        tx.isin for tx in transactions if start <= tx.trade_date <= effective_end.date()
    }
    contributions = []
    for isin in all_isins:
        initial = float(values_by_isin.loc[base_date, isin]) if isin in required else 0.0
        final = float(values_by_isin.loc[effective_end, isin]) if isin in required else 0.0
        buy, sale, dividend, commission = _money_flows(
            transactions, start, effective_end.date(), isin)
        contribution = final - initial - buy + sale + dividend - commission
        contributions.append(PeriodContribution(
            isin, initial, final, buy, sale, dividend, commission, contribution))
    contributions.sort(key=lambda item: item.result_eur, reverse=True)

    return PeriodSummary(
        requested_start=start,
        requested_end=end,
        effective_start=effective_start,
        effective_end=effective_end.date(),
        initial_value_eur=initial_value,
        final_value_eur=final_value,
        purchases_eur=purchases,
        sales_eur=sales,
        dividends_eur=dividends,
        commissions_eur=commissions,
        result_eur=result,
        twr_return=twr_return,
        benchmark_return=_benchmark_return(benchmark_eur, effective_start, effective_end.date()),
        contributions=tuple(contributions),
    )
