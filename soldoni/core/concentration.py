def weights(current_value_eur: dict[str, float]) -> dict[str, float]:
    """Quota di ogni ISIN sul valore totale. Totale 0 -> tutti 0.0."""
    total = sum(current_value_eur.values())
    if total == 0:
        return {isin: 0.0 for isin in current_value_eur}
    return {isin: v / total for isin, v in current_value_eur.items()}


def herfindahl(current_value_eur: dict[str, float]) -> float:
    """Indice HHI = Σ wᵢ². Vuoto/totale 0 -> 0.0."""
    return sum(w * w for w in weights(current_value_eur).values())


def effective_positions(current_value_eur: dict[str, float]) -> float:
    """Numero effettivo di posizioni = 1/HHI. HHI 0 -> 0.0."""
    hhi = herfindahl(current_value_eur)
    return 1.0 / hhi if hhi > 0 else 0.0


def top_n_weight(current_value_eur: dict[str, float], n: int) -> float:
    """Somma dei pesi delle n posizioni maggiori."""
    ordered = sorted(weights(current_value_eur).values(), reverse=True)
    return sum(ordered[:n])


def concentration_alerts(current_value_eur: dict[str, float],
                         threshold: float = 0.20) -> list[tuple[str, float]]:
    """ISIN il cui peso supera `threshold`, come (isin, peso), ordinati per peso desc."""
    over = [(isin, w) for isin, w in weights(current_value_eur).items() if w > threshold]
    over.sort(key=lambda t: t[1], reverse=True)
    return over
