from datetime import date
from soldoni.core.models import OpType, Transaction, Instrument


def test_transaction_construction():
    t = Transaction(
        trade_date=date(2026, 4, 14),
        value_date=date(2026, 4, 16),
        isin="US5949181045",
        op_type=OpType.BUY,
        quantity=2,
        amount_eur=663.45,
        price_native=331.725,
        fx_rate=1.0,
        commission_eur=2.95,
    )
    assert t.op_type is OpType.BUY
    assert t.commission_eur == 2.95
    assert t.source == "import"


def test_instrument_defaults_geo_weights_none():
    inst = Instrument(
        isin="US5949181045",
        yahoo_ticker="MSFT",
        name="MICROSOFT",
        native_currency="USD",
        asset_class="stock",
        macro_area="Nord America",
        sector="Tech",
    )
    assert inst.geo_weights is None
    assert inst.sector == "Tech"
    assert inst.sector_weights is None
