import pytest


def test_monthly_payment_zero_interest_splits_principal_evenly():
    from soldoni.core.financing import monthly_payment

    assert monthly_payment(12_000.0, 0.0, 12) == pytest.approx(1_000.0)


def test_monthly_payment_rejects_zero_duration():
    from soldoni.core.financing import monthly_payment

    with pytest.raises(ValueError, match="durata"):
        monthly_payment(12_000.0, 0.05, 0)


def test_monthly_payment_rejects_negative_interest_rate():
    from soldoni.core.financing import monthly_payment

    with pytest.raises(ValueError, match="TAN"):
        monthly_payment(12_000.0, -0.01, 12)


def test_proportional_sale_grosses_up_tax_to_deliver_requested_cash():
    from soldoni.core.financing import estimate_proportional_sale

    result = estimate_proportional_sale(
        current_values_eur={"A": 10_000.0},
        cost_basis_eur={"A": 5_000.0},
        net_needed_eur=5_000.0,
        tax_rate=0.26,
        commission_eur=0.0,
    )

    assert result.gross_sale_eur == pytest.approx(5_000.0 / 0.87)
    assert result.estimated_tax_eur == pytest.approx(result.gross_sale_eur * 0.13)
    assert result.net_proceeds_eur == pytest.approx(5_000.0)


def test_proportional_sale_rejects_cash_above_portfolio_capacity():
    from soldoni.core.financing import estimate_proportional_sale

    with pytest.raises(ValueError, match="portafoglio"):
        estimate_proportional_sale(
            current_values_eur={"A": 10_000.0},
            cost_basis_eur={"A": 10_000.0},
            net_needed_eur=10_001.0,
        )


def test_zero_cost_financing_matches_sale_with_the_same_monthly_budget():
    from soldoni.core.financing import FinancingOption, simulate_financing_decision

    result = simulate_financing_decision(
        current_values_eur={"A": 10_000.0},
        cost_basis_eur={"A": 10_000.0},
        net_needed_eur=6_000.0,
        monthly_budget_eur=1_000.0,
        horizon_years=1,
        expected_annual_return=0.0,
        annual_volatility=0.0,
        annual_inflation=0.0,
        financing_options=(
            FinancingOption("Prestito", 6_000.0, 0.0, 6),
        ),
        simulations=20,
        seed=7,
    )

    sale = result.strategies["Vendita titoli"]
    loan = result.strategies["Prestito"]
    assert loan.monthly_payment_eur == pytest.approx(1_000.0)
    assert loan.median_net_worth_eur == pytest.approx(sale.median_net_worth_eur)
    assert loan.median_path_eur == pytest.approx(sale.median_path_eur)
    assert loan.break_even_annual_return == pytest.approx(0.0, abs=1e-8)


def test_partial_financing_sells_only_the_uncovered_amount():
    from soldoni.core.financing import FinancingOption, simulate_financing_decision

    result = simulate_financing_decision(
        current_values_eur={"A": 10_000.0},
        cost_basis_eur={"A": 10_000.0},
        net_needed_eur=6_000.0,
        monthly_budget_eur=1_000.0,
        horizon_years=1,
        expected_annual_return=0.0,
        annual_volatility=0.0,
        annual_inflation=0.0,
        financing_options=(
            FinancingOption("Prestito", 3_000.0, 0.0, 6),
        ),
        simulations=20,
        seed=7,
    )

    sale = result.strategies["Vendita titoli"]
    loan = result.strategies["Prestito"]
    assert loan.gross_sale_eur == pytest.approx(3_000.0)
    assert loan.median_net_worth_eur == pytest.approx(sale.median_net_worth_eur)


def test_residual_debt_is_subtracted_when_horizon_ends_before_loan():
    from soldoni.core.financing import FinancingOption, simulate_financing_decision

    result = simulate_financing_decision(
        current_values_eur={"A": 10_000.0},
        cost_basis_eur={"A": 10_000.0},
        net_needed_eur=2_400.0,
        monthly_budget_eur=200.0,
        horizon_years=1,
        expected_annual_return=0.0,
        annual_volatility=0.0,
        annual_inflation=0.0,
        financing_options=(
            FinancingOption("Prestito", 2_400.0, 0.0, 24),
        ),
        simulations=20,
        seed=7,
    )

    sale = result.strategies["Vendita titoli"]
    loan = result.strategies["Prestito"]
    assert loan.residual_debt_eur == pytest.approx(1_200.0)
    assert loan.median_net_worth_eur == pytest.approx(sale.median_net_worth_eur)


def test_financing_above_needed_amount_is_reported_and_skipped():
    from soldoni.core.financing import FinancingOption, simulate_financing_decision

    result = simulate_financing_decision(
        current_values_eur={"A": 10_000.0},
        cost_basis_eur={"A": 10_000.0},
        net_needed_eur=6_000.0,
        monthly_budget_eur=1_000.0,
        horizon_years=1,
        expected_annual_return=0.0,
        annual_volatility=0.0,
        annual_inflation=0.0,
        financing_options=(
            FinancingOption("Prestito", 7_000.0, 0.0, 12),
        ),
        simulations=20,
        seed=7,
    )

    assert set(result.strategies) == {"Vendita titoli"}
    assert result.errors == (
        "Prestito: l'importo finanziato supera la spesa residua.",)


def test_annual_tax_benefit_reduces_outflow_and_increases_final_net_worth():
    from soldoni.core.financing import FinancingOption, simulate_financing_decision

    result = simulate_financing_decision(
        current_values_eur={"A": 10_000.0},
        cost_basis_eur={"A": 10_000.0},
        net_needed_eur=6_000.0,
        monthly_budget_eur=1_000.0,
        horizon_years=1,
        expected_annual_return=0.0,
        annual_volatility=0.0,
        annual_inflation=0.0,
        financing_options=(
            FinancingOption("Senza beneficio", 6_000.0, 0.12, 12),
            FinancingOption(
                "Con beneficio", 6_000.0, 0.12, 12,
                annual_tax_benefit_eur=120.0),
        ),
        simulations=20,
        seed=7,
    )

    without_benefit = result.strategies["Senza beneficio"]
    with_benefit = result.strategies["Con beneficio"]
    assert with_benefit.monthly_outflow_eur == pytest.approx(
        without_benefit.monthly_outflow_eur - 10.0)
    assert with_benefit.financing_cost_eur == pytest.approx(
        without_benefit.financing_cost_eur - 120.0)
    assert with_benefit.median_net_worth_eur == pytest.approx(
        without_benefit.median_net_worth_eur + 120.0)


def test_full_financing_remains_available_when_sale_cannot_cover_expense():
    from soldoni.core.financing import FinancingOption, simulate_financing_decision

    result = simulate_financing_decision(
        current_values_eur={"A": 10_000.0},
        cost_basis_eur={"A": 10_000.0},
        net_needed_eur=15_000.0,
        monthly_budget_eur=2_000.0,
        horizon_years=1,
        expected_annual_return=0.0,
        annual_volatility=0.0,
        annual_inflation=0.0,
        financing_options=(
            FinancingOption("Prestito", 15_000.0, 0.0, 12),
        ),
        simulations=20,
        seed=7,
    )

    assert set(result.strategies) == {"Prestito"}
    assert result.errors == (
        "Vendita titoli: il portafoglio non basta a produrre il ricavo netto richiesto.",)


def test_tax_benefit_above_monthly_outflow_is_reported_and_skipped():
    from soldoni.core.financing import FinancingOption, simulate_financing_decision

    result = simulate_financing_decision(
        current_values_eur={"A": 10_000.0},
        cost_basis_eur={"A": 10_000.0},
        net_needed_eur=1_200.0,
        monthly_budget_eur=1_000.0,
        horizon_years=1,
        expected_annual_return=0.0,
        annual_volatility=0.0,
        annual_inflation=0.0,
        financing_options=(
            FinancingOption(
                "Mutuo", 1_200.0, 0.0, 12,
                annual_tax_benefit_eur=2_400.0),
        ),
        simulations=20,
        seed=7,
    )

    assert set(result.strategies) == {"Vendita titoli"}
    assert result.errors == (
        "Mutuo: il beneficio fiscale supera rata e costi mensili.",)


def test_simulation_page_exposes_financing_comparison_inputs():
    from streamlit.testing.v1 import AppTest

    script = """
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from soldoni.app import dashboard
from soldoni.core.models import Instrument, OpType, Transaction

previous_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=10)
transaction = Transaction(
    previous_month, previous_month, "A", OpType.BUY,
    1.0, 1200.0, 1200.0, 1.0, 0.0)
planning_portfolio = (
    {"A": Instrument("A", "A.MI", "Titolo A", "EUR", "azione", "Europa")},
    SimpleNamespace(
        warnings=[],
        positions={"A": SimpleNamespace(quantity=1.0, total_cost_eur=1200.0)}),
    {"A": 1200.0},
    [],
)
with (patch.object(dashboard.store, "get_transactions", return_value=[transaction]),
      patch.object(dashboard, "_planning_portfolio", return_value=planning_portfolio)):
    dashboard.page_simulation(None)
"""

    app = AppTest.from_string(script).run(timeout=10)

    assert not app.exception
    assert "Finanziare o vendere" in [item.value for item in app.subheader]
    labels = {item.label for item in app.number_input}
    assert {
        "Importo della spesa EUR",
        "Liquidità già destinata alla spesa EUR",
        "Budget mensile per rate e investimenti EUR",
        "Importo prestito EUR",
        "TAN prestito %",
        "TAEG prestito %",
        "Importo mutuo EUR",
        "TAN mutuo %",
        "TAEG mutuo %",
        "Beneficio fiscale annuo stimato EUR",
    } <= labels


def test_simulation_page_renders_all_financing_strategies_after_submit():
    from streamlit.testing.v1 import AppTest

    script = """
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from soldoni.app import dashboard
from soldoni.core.models import Instrument, OpType, Transaction
from soldoni.core.simulation import HistoricalAssumptions

previous_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=10)
transaction = Transaction(
    previous_month, previous_month, "A", OpType.BUY,
    1.0, 1200.0, 1200.0, 1.0, 0.0)
planning_portfolio = (
    {"A": Instrument("A", "A.MI", "Titolo A", "EUR", "azione", "Europa")},
    SimpleNamespace(
        warnings=[],
        positions={"A": SimpleNamespace(quantity=1.0, total_cost_eur=1200.0)}),
    {"A": 1200.0},
    [],
)
assumptions = HistoricalAssumptions(
    0.0, 0.0, date(2025, 1, 1), date(2026, 1, 2))
historical = {
    "Portafoglio": assumptions,
    "S&P 500": assumptions,
    "MSCI World": assumptions,
}
with (patch.object(dashboard.store, "get_transactions", return_value=[transaction]),
      patch.object(dashboard, "_planning_portfolio", return_value=planning_portfolio),
      patch.object(dashboard, "_goal_historical_assumptions",
                   return_value=(historical, []))):
    dashboard.page_simulation(None)
"""

    app = AppTest.from_string(script).run(timeout=10)
    values = {
        "Importo della spesa EUR": 600.0,
        "Budget mensile per rate e investimenti EUR": 100.0,
        "Importo prestito EUR": 600.0,
        "Durata prestito (mesi)": 12,
        "TAN prestito %": 0.0,
        "Importo mutuo EUR": 600.0,
        "Durata mutuo (anni)": 1,
        "TAN mutuo %": 0.0,
        "Orizzonte del confronto (anni)": 1,
    }
    for item in app.number_input:
        if item.label in values:
            item.set_value(values[item.label])
    submit = next(
        button for button in app.button
        if button.label == "Confronta le alternative")

    app = submit.click().run(timeout=10)

    assert not app.exception
    frames = [item.value for item in app.dataframe]
    summary = next(frame for frame in frames if "Strategia" in frame.columns)
    assert set(summary["Scenario"]) == {"Portafoglio", "S&P 500", "MSCI World"}
    assert set(summary["Strategia"]) == {
        "Vendita titoli", "Prestito personale", "Mutuo"}
