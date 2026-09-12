import openpyxl
import pytest
from datetime import date
from soldoni.core.models import OpType
from soldoni.data.fineco_import import parse_fineco_export

HEADER = ["Operazione", "Data valuta", "Descrizione", "Titolo", "Isin", "Segno",
          "Quantita", "Divisa", "Prezzo", "Cambio", "Controvalore",
          "Commissioni Fondi Sw/Ingr/Uscita", "Commissioni Fondi Banca Corrispondente",
          "Spese Fondi Sgr", "Commissioni amministrato"]


def _make_file(tmp_path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Movimenti Dossier Titoli"
    for _ in range(5):
        ws.append(["Dossier"] + [""] * 14)  # righe 0..4 intestazione
    ws.append(HEADER)                         # riga 5 header
    ws.append([""] * 15)                      # riga 6 vuota
    for r in rows:                            # dati da riga 7
        ws.append(r)
    path = tmp_path / "export.xlsx"
    wb.save(path)
    return str(path)


def test_parse_buy_sell_dividend(tmp_path):
    rows = [
        ["14/04/2026", "16/04/2026", "Compravendita titoli", "MICROSOFT",
         "US5949181045", "A", 2, "EUR", 331.725, 1, 663.45, "", "", "", 2.95],
        ["30/01/2026", "30/01/2026", "Compravendita titoli", "STELLANTIS",
         "NL00150001Q9", "V", 67, "EUR", 8.19, 1, 548.73, "", "", "", 2.95],
        ["22/04/2026", "22/04/2026", "Dividendo", "BCA MEDIOLANUM",
         "IT0004776628", " ", 69, "EUR", 0, 1, 33.19, "", "", "", ""],
    ]
    path = _make_file(tmp_path, rows)
    txs = parse_fineco_export(path)

    assert len(txs) == 3
    buy = txs[0]
    assert buy.op_type is OpType.BUY
    assert buy.trade_date == date(2026, 4, 14)
    assert buy.isin == "US5949181045"
    assert buy.amount_eur == 663.45
    assert buy.commission_eur == 2.95

    assert txs[1].op_type is OpType.SELL
    div = txs[2]
    assert div.op_type is OpType.DIVIDEND
    assert div.commission_eur == 0.0


def test_unknown_description_raises(tmp_path):
    rows = [["01/01/2026", "01/01/2026", "Frazionamento", "FOO",
             "US0000000000", " ", 1, "EUR", 0, 1, 0, "", "", "", ""]]
    path = _make_file(tmp_path, rows)
    with pytest.raises(ValueError, match="Frazionamento"):
        parse_fineco_export(path)
