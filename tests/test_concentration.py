from soldoni.core.concentration import (
    weights, herfindahl, effective_positions, top_n_weight, concentration_alerts)


def test_weights_sum_to_one():
    w = weights({"A": 300.0, "B": 100.0})
    assert round(w["A"], 4) == 0.75
    assert round(w["B"], 4) == 0.25


def test_weights_zero_total():
    assert weights({"A": 0.0, "B": 0.0}) == {"A": 0.0, "B": 0.0}


def test_herfindahl_single_position():
    assert herfindahl({"A": 1000.0}) == 1.0


def test_herfindahl_equal_positions():
    assert round(herfindahl({"A": 100.0, "B": 100.0, "C": 100.0, "D": 100.0}), 4) == 0.25


def test_herfindahl_zero_total():
    assert herfindahl({"A": 0.0}) == 0.0


def test_effective_positions_equal():
    assert round(effective_positions({"A": 1.0, "B": 1.0, "C": 1.0, "D": 1.0}), 4) == 4.0


def test_effective_positions_empty():
    assert effective_positions({}) == 0.0


def test_top_n_weight():
    cv = {"A": 500.0, "B": 300.0, "C": 200.0}
    assert round(top_n_weight(cv, 2), 4) == 0.8
    assert round(top_n_weight(cv, 5), 4) == 1.0


def test_concentration_alerts_threshold_and_order():
    cv = {"A": 500.0, "B": 300.0, "C": 200.0}   # pesi .5 .3 .2
    alerts = concentration_alerts(cv, threshold=0.20)
    assert [isin for isin, _ in alerts] == ["A", "B"]   # C è esattamente .2, non > .20


def test_concentration_alerts_none_when_diversified():
    cv = {f"P{i}": 100.0 for i in range(10)}     # ognuna 0.1
    assert concentration_alerts(cv, 0.20) == []
