SYMBOL_REGISTRY = {
    "GER40": {
        "point": 1.0,
        "tick_size": 1.0,
        "tick_value": 1.0,
        "providers": {
            "mt5": "#Germany40",
            "dukascopy": "DEU.IDX/EUR",
        },
    },
}


def resolve_instrument_info(symbol_canonical: str) -> dict:
    entry = SYMBOL_REGISTRY.get(symbol_canonical)
    if entry is None:
        raise RuntimeError(
            f"Unknown canonical symbol: {symbol_canonical!r}. "
            f"Add it to backtesting/symbols.py."
        )
    return {
        "point": float(entry["point"]),
        "tick_size": float(entry["tick_size"]),
        "tick_value": float(entry["tick_value"]),
    }
