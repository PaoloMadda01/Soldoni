from datetime import date

import pandas as pd
import pytest

from soldoni.app import dashboard
from soldoni.core.models import Instrument, OpType, Transaction


def test_dashboard_requests_prices_from_each_instruments_first_trade(monkeypatch):
    calls = []

    def fake_prices(conn, ticker, start, end):
        calls.append((ticker, start))
        index = pd.to_datetime([start, end])
        return pd.DataFrame(
            {"close": [100.0, 100.0], "adj_close": [100.0, 100.0]}, index=index)

    class StopAfterPrices(Exception):
        pass

    def stop_after_prices(*args, **kwargs):
        raise StopAfterPrices

    monkeypatch.setattr(dashboard.prices, "get_price_history_cached", fake_prices)
    monkeypatch.setattr(dashboard, "quantity_timeline", stop_after_prices)
    txs = [
        Transaction(date(2024, 1, 2), date(2024, 1, 2), "EARLY", OpType.BUY,
                    1.0, 100.0, 100.0, 1.0, 0.0),
        Transaction(date(2024, 6, 3), date(2024, 6, 3), "LATE", OpType.BUY,
                    1.0, 100.0, 100.0, 1.0, 0.0),
    ]
    instruments = {
        isin: Instrument(isin, ticker, ticker, "EUR", "azione", "Europa")
        for isin, ticker in (("EARLY", "EARLY.MI"), ("LATE", "LATE.MI"))
    }

    with pytest.raises(StopAfterPrices):
        dashboard._render_dashboard(None, txs, instruments)

    assert calls == [
        ("EARLY.MI", date(2024, 1, 2)),
        ("LATE.MI", date(2024, 6, 3)),
    ]
