from soldoni.core.models import Instrument
from soldoni.core.allocation import geo_breakdown, sector_breakdown


def _inst(isin, area="Europa", weights=None, sector="Tech", sector_weights=None):
    return Instrument(isin, "T", "n", "EUR", "stock", area, weights, sector, sector_weights)


def test_geo_breakdown_single_area():
    instruments = {
        "IT1": _inst("IT1", "Europa"),
        "US1": _inst("US1", "Nord America"),
    }
    values = {"IT1": 1000.0, "US1": 2000.0}
    assert geo_breakdown(values, instruments) == {"Europa": 1000.0, "Nord America": 2000.0}


def test_geo_breakdown_with_weights():
    instruments = {"W": _inst("W", "Nord America", {"Nord America": 0.6, "Europa": 0.4})}
    values = {"W": 1000.0}
    result = geo_breakdown(values, instruments)
    assert round(result["Nord America"], 2) == 600.0
    assert round(result["Europa"], 2) == 400.0


def test_sector_breakdown_single_and_weights():
    instruments = {
        "A": _inst("A", sector="Finanza"),
        "B": _inst("B", sector="Tech", sector_weights={"Tech": 0.7, "Salute": 0.3}),
    }
    values = {"A": 1000.0, "B": 1000.0}
    result = sector_breakdown(values, instruments)
    assert round(result["Finanza"], 2) == 1000.0
    assert round(result["Tech"], 2) == 700.0
    assert round(result["Salute"], 2) == 300.0


def test_breakdowns_label_etf_without_weights_as_etf():
    instruments = {
        "ETF1": Instrument("ETF1", "T", "ETF", "EUR", "etf",
                           "Non disponibile", None, "Non disponibile", None)
    }
    values = {"ETF1": 1000.0}

    assert geo_breakdown(values, instruments) == {"ETF": 1000.0}
    assert sector_breakdown(values, instruments) == {"ETF": 1000.0}


def test_breakdowns_use_etf_weights_when_available():
    instruments = {
        "ETF1": Instrument("ETF1", "T", "ETF", "EUR", "etf", "ETF",
                           {"Nord America": 0.6, "Europa": 0.4}, "ETF",
                           {"Tech": 0.7, "Finanza": 0.3})
    }
    values = {"ETF1": 1000.0}

    assert geo_breakdown(values, instruments) == {
        "Nord America": 600.0, "Europa": 400.0}
    assert sector_breakdown(values, instruments) == {
        "Tech": 700.0, "Finanza": 300.0}
