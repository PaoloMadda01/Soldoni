from datetime import date
from soldoni.core.returns import xirr


def test_xirr_one_year_ten_percent():
    # -100 oggi, +110 fra 1 anno -> 10%
    r = xirr([-100.0, 110.0], [date(2026, 1, 1), date(2027, 1, 1)])
    assert round(r, 4) == 0.1


def test_xirr_two_years_ten_percent():
    # -100 oggi, +121 fra 2 anni -> (1+r)^2 = 1.21 -> 10%
    r = xirr([-100.0, 121.0], [date(2026, 1, 1), date(2028, 1, 1)])
    assert round(r, 4) == 0.1


def test_xirr_all_same_sign_returns_none():
    assert xirr([-100.0, -50.0], [date(2026, 1, 1), date(2026, 6, 1)]) is None


def test_xirr_fewer_than_two_flows_returns_none():
    assert xirr([100.0], [date(2026, 1, 1)]) is None
