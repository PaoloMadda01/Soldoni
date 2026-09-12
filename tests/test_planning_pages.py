from contextlib import nullcontext

import pytest
from streamlit.testing.v1 import AppTest

from soldoni.app import dashboard


@pytest.mark.parametrize("selected", ["Ribilanciamento", "Simulazione"])
def test_main_routes_each_planning_screen_separately(monkeypatch, selected):
    calls = []
    menu = {}

    def fake_option_menu(_title, options, **_kwargs):
        menu["options"] = options
        return selected

    monkeypatch.setattr(dashboard.st, "set_page_config", lambda **_kwargs: None)
    monkeypatch.setattr(dashboard.st, "sidebar", nullcontext())
    monkeypatch.setattr(dashboard, "get_conn", lambda: "connection")
    monkeypatch.setattr(dashboard, "option_menu", fake_option_menu)
    monkeypatch.setattr(
        dashboard, "page_rebalancing",
        lambda conn: calls.append(("Ribilanciamento", conn)), raising=False)
    monkeypatch.setattr(
        dashboard, "page_simulation",
        lambda conn: calls.append(("Simulazione", conn)), raising=False)
    monkeypatch.setattr(
        dashboard, "page_import",
        lambda conn: calls.append(("Import & Anagrafica", conn)))

    dashboard.main()

    assert selected in menu["options"]
    assert calls == [(selected, "connection")]


def _planning_page_script(page):
    return f"""
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
    {{"A": Instrument("A", "A.MI", "Titolo A", "EUR", "azione", "Europa")}},
    SimpleNamespace(
        warnings=[],
        positions={{"A": SimpleNamespace(quantity=1.0, total_cost_eur=1200.0)}}),
    {{"A": 1200.0}},
    [],
)
with (patch.object(dashboard.store, "get_transactions", return_value=[transaction]),
      patch.object(dashboard.store, "get_allocation_targets", return_value={{}}),
      patch.object(dashboard, "_planning_portfolio", return_value=planning_portfolio)):
    dashboard.page_{page}(None)
"""


@pytest.mark.parametrize(("page", "label"), [
    ("rebalancing", "Nuova liquidità EUR"),
    ("simulation", "Versamento mensile EUR"),
])
def test_planning_pages_use_average_monthly_purchases_as_default(page, label):
    app = AppTest.from_string(_planning_page_script(page)).run()

    assert not app.exception
    values = {number_input.label: number_input.value for number_input in app.number_input}
    assert values[label] == pytest.approx(100.0)
