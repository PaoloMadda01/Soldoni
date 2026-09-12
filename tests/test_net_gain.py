from datetime import date
from soldoni.core.models import OpType, Transaction
from soldoni.core.holdings import Position, RealizedSale, PortfolioState
from soldoni.core.net_gain import (
    capital_gains_tax, dividend_net, country_from_isin,
    realized_net_gain, latent_net_gain,
)


def test_capital_gains_tax_only_on_positive():
    assert round(capital_gains_tax(100.0), 2) == 26.0
    assert capital_gains_tax(-50.0) == 0.0


def test_country_from_isin():
    assert country_from_isin("US5949181045") == "US"
    assert country_from_isin("IT0004776628") == "IT"


def test_dividend_net_italian_and_us():
    assert round(dividend_net(100.0, "IT"), 2) == 74.0
    assert round(dividend_net(100.0, "US", foreign_rates={"US": 0.15}), 2) == 62.90


def test_realized_net_gain_combines_sales_and_dividends():
    state = PortfolioState(
        positions={},
        realized_sales=[RealizedSale("X", date(2026, 1, 3), 5, 697.05, 551.475, 145.575)],
    )
    dividends = [Transaction(
        trade_date=date(2026, 1, 2), value_date=date(2026, 1, 2), isin="IT0004776628",
        op_type=OpType.DIVIDEND, quantity=69, amount_eur=100.0, price_native=0.0,
        fx_rate=1.0, commission_eur=0.0,
    )]
    result = realized_net_gain(state, dividends, foreign_rates={"US": 0.15})
    assert round(result.capital_net_eur, 2) == 107.73
    assert round(result.dividends_net_eur, 2) == 74.0
    assert round(result.total_eur, 2) == 181.73


def test_latent_net_gain_subtracts_hypothetical_tax_and_commission():
    positions = {"X": Position("X", quantity=15, total_cost_eur=1654.425)}
    current_value = {"X": 2000.0}
    result = latent_net_gain(positions, current_value, sell_commission=2.95)
    gross = 2000.0 - 1654.425
    expected = (gross - 2.95) - 0.26 * gross
    assert round(result.total_eur, 3) == round(expected, 3)
