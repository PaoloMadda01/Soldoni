from dataclasses import dataclass
from datetime import date

from soldoni.core.models import OpType, Transaction


TransactionKey = tuple[date, str, OpType, float, float]


@dataclass(frozen=True)
class ImportConflict:
    existing: Transaction
    incoming: Transaction


@dataclass(frozen=True)
class ImportPreview:
    new_transactions: tuple[Transaction, ...]
    duplicates: tuple[Transaction, ...]
    conflicts: tuple[ImportConflict, ...]


def transaction_key(tx: Transaction) -> TransactionKey:
    return tx.trade_date, tx.isin, tx.op_type, tx.quantity, tx.amount_eur


def _accounting_values(tx: Transaction) -> tuple[date, float, float, float]:
    return tx.value_date, tx.price_native, tx.fx_rate, tx.commission_eur


def classify_import(incoming: list[Transaction],
                    existing: list[Transaction]) -> ImportPreview:
    known = {transaction_key(tx): tx for tx in existing}
    new_transactions = []
    duplicates = []
    conflicts = []
    for tx in incoming:
        key = transaction_key(tx)
        previous = known.get(key)
        if previous is None:
            new_transactions.append(tx)
            known[key] = tx
        elif _accounting_values(previous) == _accounting_values(tx):
            duplicates.append(tx)
        else:
            conflicts.append(ImportConflict(previous, tx))
    return ImportPreview(
        tuple(new_transactions), tuple(duplicates), tuple(conflicts))
