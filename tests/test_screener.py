import pytest
from soldoni.data.screener import screen_candidates, Candidate


def _capture():
    """Fake `screen`: cattura la query costruita e ritorna quotes vuote."""
    box = {}

    def fake(query, **kwargs):
        box["query"] = query
        box["kwargs"] = kwargs
        return {"quotes": []}

    return fake, box


def _leaves(d):
    """(op, field, value) di ogni foglia gt/lt/eq della query (to_dict, ricorsivo)."""
    op, ops = d["operator"], d["operands"]
    if op in {"AND", "OR"}:
        out = []
        for o in ops:
            out += _leaves(o)
        return out
    return [(op, ops[0], ops[1])]


def test_no_filters_single_region_is_plain_eq():
    fake, box = _capture()
    screen_candidates("stock", ["us"], screen=fake)
    assert box["query"].to_dict() == {"operator": "EQ", "operands": ["region", "us"]}


def test_stock_filters_build_expected_clauses():
    fake, box = _capture()
    screen_candidates("stock", ["us"], filters={"pe_max": 15, "roe_min": 0.15}, screen=fake)
    leaves = _leaves(box["query"].to_dict())
    assert ("LT", "peratio.lasttwelvemonths", 15.0) in leaves
    assert ("GT", "returnonequity.lasttwelvemonths", 0.15) in leaves


def test_none_filter_values_are_skipped():
    fake, box = _capture()
    screen_candidates("stock", ["us"], filters={"pe_max": None}, screen=fake)
    fields = [f for _, f, _ in _leaves(box["query"].to_dict())]
    assert "peratio.lasttwelvemonths" not in fields


def test_multiple_clauses_combined_with_and():
    fake, box = _capture()
    screen_candidates("stock", ["us"], min_market_cap=2e9,
                      filters={"pe_max": 25}, screen=fake)
    assert box["query"].to_dict()["operator"] == "AND"


def test_etf_category_and_filters():
    fake, box = _capture()
    screen_candidates("etf", ["it", "de"], category="Large Blend",
                      filters={"expense_ratio_max": 0.2, "aum_min": 1e8}, screen=fake)
    leaves = _leaves(box["query"].to_dict())
    assert ("EQ", "categoryname", "Large Blend") in leaves
    assert ("LT", "annualreportnetexpenseratio", 0.2) in leaves
    assert ("GT", "fundnetassets", 100000000.0) in leaves


def test_unknown_filter_name_raises():
    fake, _ = _capture()
    with pytest.raises(ValueError):
        screen_candidates("stock", ["us"], filters={"bogus": 1}, screen=fake)


def test_quotes_normalized_to_candidates():
    def fake(query, **kwargs):
        return {"quotes": [
            {"symbol": "AAPL", "shortName": "Apple", "quoteType": "EQUITY"},
            {"longName": "No Symbol Co"},  # scartato: niente symbol
        ]}
    out = screen_candidates("stock", ["us"], screen=fake)
    assert out == [Candidate("AAPL", "Apple", "EQUITY")]


def test_endpoint_error_becomes_valueerror():
    def fake(query, **kwargs):
        raise RuntimeError("boom")
    with pytest.raises(ValueError):
        screen_candidates("stock", ["us"], screen=fake)


def test_no_regions_raises():
    with pytest.raises(ValueError):
        screen_candidates("stock", [], screen=lambda *a, **k: {"quotes": []})
