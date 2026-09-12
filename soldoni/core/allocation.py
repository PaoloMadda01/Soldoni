from soldoni.core.models import Instrument


def _breakdown(values_eur: dict[str, float], instruments: dict[str, Instrument],
               key_attr: str, weights_attr: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for isin, value in values_eur.items():
        inst = instruments.get(isin)
        if inst is None:
            raise ValueError(f"Anagrafica mancante per {isin}")
        weights = getattr(inst, weights_attr)
        if not weights:
            key = "ETF" if inst.asset_class == "etf" else getattr(inst, key_attr)
            weights = {key: 1.0}
        for key, w in weights.items():
            out[key] = out.get(key, 0.0) + value * w
    return out


def geo_breakdown(values_eur: dict[str, float],
                  instruments: dict[str, Instrument]) -> dict[str, float]:
    return _breakdown(values_eur, instruments, "macro_area", "geo_weights")


def sector_breakdown(values_eur: dict[str, float],
                     instruments: dict[str, Instrument]) -> dict[str, float]:
    return _breakdown(values_eur, instruments, "sector", "sector_weights")
