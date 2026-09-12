from dataclasses import dataclass, field
from datetime import date
from soldoni.core.models import OpType, Transaction


@dataclass
class Position:
    isin: str
    quantity: float = 0.0
    total_cost_eur: float = 0.0  # costo residuo delle quote detenute (incl. commissioni di acquisto)

    @property
    def avg_cost_eur(self) -> float:  # costo medio per quota
        return self.total_cost_eur / self.quantity if self.quantity else 0.0


@dataclass
class RealizedSale:
    isin: str
    date: date
    quantity: float
    proceeds_eur: float    # ricavo netto = amount - commissione
    cost_basis_eur: float  # costo medio * quantità venduta
    gain_eur: float        # proceeds - cost_basis (lordo d'imposta)


@dataclass
class PortfolioState:
    positions: dict[str, Position] = field(default_factory=dict)
    realized_sales: list[RealizedSale] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_portfolio_state(transactions: list[Transaction],
                          on_oversell: str = "raise") -> PortfolioState:
    """Ricostruisce posizioni e vendite realizzate in ordine cronologico.

    on_oversell="raise" (default): una vendita che eccede le quote note solleva
    ValueError (storico incompleto). on_oversell="skip": la vendita viene saltata
    e registrata in `warnings` (utile con export parziali)."""
    state = PortfolioState()
    for tx in sorted(transactions, key=lambda t: (t.trade_date, t.isin)):
        if tx.op_type is OpType.DIVIDEND:
            continue
        pos = state.positions.setdefault(tx.isin, Position(isin=tx.isin))
        if tx.op_type is OpType.BUY:
            pos.quantity += tx.quantity
            pos.total_cost_eur += tx.amount_eur + tx.commission_eur
        elif tx.op_type is OpType.SELL:
            if tx.quantity > pos.quantity:
                msg = (
                    f"Vendita di {tx.quantity} quote di {tx.isin} il {tx.trade_date} "
                    f"ma solo {pos.quantity} disponibili: storico acquisti incompleto. "
                    "Importa l'export Fineco completo dalla prima operazione."
                )
                if on_oversell == "raise":
                    raise ValueError(msg)
                state.warnings.append(msg)
                continue
            avg = pos.avg_cost_eur
            cost_basis = avg * tx.quantity
            proceeds = tx.amount_eur - tx.commission_eur
            state.realized_sales.append(RealizedSale(
                isin=tx.isin, date=tx.trade_date, quantity=tx.quantity,
                proceeds_eur=proceeds, cost_basis_eur=cost_basis,
                gain_eur=proceeds - cost_basis,
            ))
            pos.quantity -= tx.quantity
            pos.total_cost_eur -= cost_basis
    state.positions = {k: v for k, v in state.positions.items() if round(v.quantity, 6) != 0}
    return state
