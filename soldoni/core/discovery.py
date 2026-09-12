from dataclasses import dataclass
from typing import Callable
from soldoni.data.fundamentals import Fundamentals
from soldoni.core.scoring import ScoreResult


@dataclass
class RankedCandidate:
    symbol: str
    name: str | None
    result: ScoreResult


def rank_candidates(candidates, exclude: set[str],
                    analyze: Callable[[str], tuple[Fundamentals, ScoreResult]],
                    limit: int) -> tuple[list[RankedCandidate], list[str]]:
    """Valuta e ordina i candidati per punteggio composito (None in coda).

    Esclude (confronto case-insensitive) i ticker in `exclude` e i duplicati.
    `analyze(symbol)` ritorna (Fundamentals, ScoreResult) o solleva ValueError se i
    dati mancano: in tal caso il ticker finisce in `skipped`. Vengono fatti al massimo
    `limit` tentativi di `analyze` per limitare le chiamate di rete.
    Ritorna (ranked ordinati, skipped).
    """
    excluded = {t.upper() for t in exclude}
    ranked: list[RankedCandidate] = []
    skipped: list[str] = []
    seen: set[str] = set()
    attempts = 0
    for c in candidates:
        key = c.symbol.upper()
        if key in excluded or key in seen:
            continue
        seen.add(key)
        if attempts >= limit:
            break
        attempts += 1
        try:
            fund, res = analyze(c.symbol)
        except ValueError:
            skipped.append(c.symbol)
            continue
        ranked.append(RankedCandidate(c.symbol, fund.name or c.name, res))
    ranked.sort(key=lambda r: (r.result.composite is None, -(r.result.composite or 0)))
    return ranked, skipped
