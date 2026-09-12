from datetime import date
from soldoni.core.holdings import Position, RealizedSale
from soldoni.core.attribution import Contribution, pnl_attribution, attribution_shares


def _sale(isin, gain):
    return RealizedSale(isin=isin, date=date(2026, 1, 1), quantity=1.0,
                        proceeds_eur=0.0, cost_basis_eur=0.0, gain_eur=gain)


def test_pnl_attribution_latent_only():
    positions = {"A": Position("A", 10, 1000.0)}
    current = {"A": 1200.0}
    contribs = pnl_attribution(positions, current, [])
    assert len(contribs) == 1
    assert contribs[0].isin == "A"
    assert contribs[0].latent_eur == 200.0
    assert contribs[0].realized_eur == 0.0
    assert contribs[0].total_eur == 200.0


def test_pnl_attribution_realized_only_for_exited_position():
    contribs = pnl_attribution({}, {}, [_sale("B", 50.0)])
    assert len(contribs) == 1
    assert contribs[0].isin == "B"
    assert contribs[0].latent_eur == 0.0
    assert contribs[0].realized_eur == 50.0


def test_pnl_attribution_combines_and_sorts_desc():
    positions = {"A": Position("A", 10, 1000.0), "C": Position("C", 5, 500.0)}
    current = {"A": 1200.0, "C": 450.0}            # A latent +200, C latent -50
    sales = [_sale("A", 30.0), _sale("B", 80.0)]   # A realized +30, B uscito +80
    contribs = pnl_attribution(positions, current, sales)
    assert [c.isin for c in contribs] == ["A", "B", "C"]   # totali 230, 80, -50
    a = next(c for c in contribs if c.isin == "A")
    assert a.total_eur == 230.0


def test_pnl_attribution_unpriced_held_excluded_when_no_realized():
    positions = {"D": Position("D", 3, 300.0)}     # detenuto, non prezzato, niente vendite
    contribs = pnl_attribution(positions, {}, [])
    assert contribs == []


def test_attribution_shares_normal():
    contribs = [Contribution("A", 75.0, 0.0), Contribution("B", 25.0, 0.0)]
    shares = attribution_shares(contribs)
    assert round(shares["A"], 4) == 0.75
    assert round(shares["B"], 4) == 0.25


def test_attribution_shares_mixed_signs():
    contribs = [Contribution("A", 120.0, 0.0), Contribution("B", -20.0, 0.0)]
    shares = attribution_shares(contribs)          # totale 100
    assert round(shares["A"], 4) == 1.2
    assert round(shares["B"], 4) == -0.2


def test_attribution_shares_zero_total():
    contribs = [Contribution("A", 50.0, 0.0), Contribution("B", -50.0, 0.0)]
    assert attribution_shares(contribs) == {"A": 0.0, "B": 0.0}
