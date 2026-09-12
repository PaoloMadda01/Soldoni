import io
from datetime import date
import pandas as pd
from soldoni.core.holdings import RealizedSale
from soldoni.core.models import Instrument, Transaction
from soldoni.core.net_gain import dividend_net, country_from_isin
from soldoni.core.tax import compute_zainetto

REALIZED_COLS = ["Data", "ISIN", "Nome", "Tipo", "Quantità",
                 "Proventi €", "Costo €", "Plus/Minus €"]
DIVIDEND_COLS = ["Data", "ISIN", "Nome", "Paese", "Lordo €", "Netto €"]
ZAINETTO_COLS = ["Voce", "Valore €"]


def realized_rows(realized_sales: list[RealizedSale],
                  instruments: dict[str, Instrument], year: int | None = None) -> list[dict]:
    rows = []
    for s in sorted(realized_sales, key=lambda x: x.date):
        if year is not None and s.date.year != year:
            continue
        inst = instruments.get(s.isin)
        rows.append({
            "Data": s.date.isoformat(), "ISIN": s.isin,
            "Nome": inst.name if inst else s.isin,
            "Tipo": inst.asset_class if inst else "",
            "Quantità": s.quantity, "Proventi €": round(s.proceeds_eur, 2),
            "Costo €": round(s.cost_basis_eur, 2), "Plus/Minus €": round(s.gain_eur, 2),
        })
    return rows


def dividend_rows(dividends: list[Transaction],
                  instruments: dict[str, Instrument], year: int | None = None) -> list[dict]:
    rows = []
    for d in sorted(dividends, key=lambda x: x.trade_date):
        if year is not None and d.trade_date.year != year:
            continue
        inst = instruments.get(d.isin)
        country = country_from_isin(d.isin)
        rows.append({
            "Data": d.trade_date.isoformat(), "ISIN": d.isin,
            "Nome": inst.name if inst else d.isin, "Paese": country,
            "Lordo €": round(d.amount_eur, 2),
            "Netto €": round(dividend_net(d.amount_eur, country), 2),
        })
    return rows


def zainetto_rows(zai) -> list[dict]:
    rows = [
        {"Voce": "Plus/minus lordo realizzato", "Valore €": round(zai.gross_realized_eur, 2)},
        {"Voce": "Plus tassabili dopo compensazione", "Valore €": round(zai.taxable_gains_eur, 2)},
        {"Voce": "Imposta capital gain", "Valore €": round(zai.capital_tax_eur, 2)},
        {"Voce": "Minus generate", "Valore €": round(zai.minus_generated_eur, 2)},
        {"Voce": "Minus usate", "Valore €": round(zai.minus_used_eur, 2)},
    ]
    for expiry, amt in sorted(zai.residual_by_expiry.items()):
        rows.append({"Voce": f"Minus residue (scad. {expiry})", "Valore €": round(amt, 2)})
    return rows


def build_tax_report_xlsx(realized_sales, dividends, instruments, year: int | None = None) -> bytes:
    rl = pd.DataFrame(realized_rows(realized_sales, instruments, year), columns=REALIZED_COLS)
    dv = pd.DataFrame(dividend_rows(dividends, instruments, year), columns=DIVIDEND_COLS)
    sales_upto = [s for s in realized_sales if year is None or s.date.year <= year]
    today_year = year if year is not None else date.today().year
    zai = compute_zainetto(sales_upto, instruments, today_year=today_year)
    zn = pd.DataFrame(zainetto_rows(zai), columns=ZAINETTO_COLS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        rl.to_excel(writer, sheet_name="Plus-Minus", index=False)
        dv.to_excel(writer, sheet_name="Dividendi", index=False)
        zn.to_excel(writer, sheet_name="Zainetto", index=False)
    return buf.getvalue()
