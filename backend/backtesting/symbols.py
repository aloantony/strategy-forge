# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

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
