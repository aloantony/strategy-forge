# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
backend/analytics/trade_history.py — Empareja deals de MetaTrader5 en operaciones
round-trip (entrada↔salida) y clasifica el motivo de cierre nativo (deal.reason).

Lógica pura reutilizable por la GUI, el server y los tests. No importa de
gui_charts, config ni mt5; recibe el tamaño de punto y resolutores opcionales de
estrategia/motivo. Las constantes DEAL_* son los valores numéricos oficiales del
API de MetaTrader5 (estables), hardcodeados para mantener esta capa pura.
"""

_DEAL_TYPE_BUY = 0       # mt5.DEAL_TYPE_BUY
_DEAL_TYPE_SELL = 1      # mt5.DEAL_TYPE_SELL
_DEAL_ENTRY_IN = 0       # mt5.DEAL_ENTRY_IN
_DEAL_ENTRY_OUT = 1      # mt5.DEAL_ENTRY_OUT
_DEAL_ENTRY_INOUT = 2    # mt5.DEAL_ENTRY_INOUT

_EXIT_CAUSE_BY_REASON = {
    4: "SL",             # mt5.DEAL_REASON_SL
    5: "TP",             # mt5.DEAL_REASON_TP
    6: "Stop Out",       # mt5.DEAL_REASON_SO
    3: "Reversión/Bot",  # mt5.DEAL_REASON_EXPERT
    0: "Manual",         # mt5.DEAL_REASON_CLIENT
    1: "Manual",         # mt5.DEAL_REASON_MOBILE
    2: "Manual",         # mt5.DEAL_REASON_WEB
}


def resolve_exit_cause(deal) -> str:
    """Traduce deal.reason (nativo MT5) en una causa de cierre legible."""
    reason = getattr(deal, "reason", None)
    if reason is None:
        return ""
    try:
        reason = int(reason)
    except (TypeError, ValueError):
        return ""
    return _EXIT_CAUSE_BY_REASON.get(reason, "Otro")


def points_from_price_delta(entry_price, exit_price, direction, point) -> float:
    """Convierte una diferencia de precio en puntos con signo según dirección."""
    try:
        point = float(point)
        if point <= 0:
            return 0.0
        raw = (float(exit_price) - float(entry_price)) / point
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
    return raw if str(direction).upper() == "BUY" else -raw


def build_round_trips(deals, point, strategy_resolver=None, reason_resolver=None) -> list:
    """
    Empareja deals IN/OUT por position_id en operaciones cerradas (round-trips).

    Soporta entradas/salidas parciales (acumula volumen y usa precio ponderado por
    volumen). Devuelve solo operaciones con al menos un IN y un OUT, ordenadas por
    hora de salida. Cada elemento incluye precios/horas de entrada y salida, volumen,
    profit (€), retorno %, puntos, duración, dirección, estrategia, motivo y causa.
    """
    if not deals:
        return []

    by_position = {}
    for deal in deals:
        if getattr(deal, "type", None) not in (_DEAL_TYPE_BUY, _DEAL_TYPE_SELL):
            continue
        pid = getattr(deal, "position_id", None) or getattr(deal, "ticket", None)
        if pid is None:
            continue
        by_position.setdefault(pid, []).append(deal)

    in_entries = (_DEAL_ENTRY_IN, _DEAL_ENTRY_INOUT)
    out_entries = (_DEAL_ENTRY_OUT, _DEAL_ENTRY_INOUT)

    round_trips = []
    for pid, pdeals in by_position.items():
        pdeals = sorted(pdeals, key=lambda d: getattr(d, "time", 0))
        ins = [d for d in pdeals if getattr(d, "entry", None) in in_entries]
        outs = [d for d in pdeals if getattr(d, "entry", None) in out_entries]
        if not ins or not outs:
            continue  # operación aún abierta o incompleta

        in_vol = sum(float(getattr(d, "volume", 0) or 0) for d in ins)
        out_vol = sum(float(getattr(d, "volume", 0) or 0) for d in outs)
        entry_price = _weighted_price(ins, in_vol)
        exit_price = _weighted_price(outs, out_vol)

        first_in = ins[0]
        last_out = outs[-1]
        direction = "BUY" if getattr(first_in, "type", None) == _DEAL_TYPE_BUY else "SELL"
        profit = sum(float(getattr(d, "profit", 0) or 0) for d in outs)
        entry_time = int(getattr(first_in, "time", 0) or 0)
        exit_time = int(getattr(last_out, "time", 0) or 0)

        return_pct = 0.0
        if entry_price:
            return_pct = ((exit_price - entry_price) / entry_price) * 100.0
            if direction == "SELL":
                return_pct = -return_pct

        round_trips.append({
            "position_id": pid,
            "direction": direction,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "volume": in_vol,
            "profit": profit,
            "return_pct": return_pct,
            "points": points_from_price_delta(entry_price, exit_price, direction, point),
            "duration_s": max(0, exit_time - entry_time),
            "strategy": strategy_resolver(first_in) if strategy_resolver else "",
            "reason": reason_resolver(first_in) if reason_resolver else "",
            "exit_cause": resolve_exit_cause(last_out),
        })

    round_trips.sort(key=lambda r: r["exit_time"])
    return round_trips


def _weighted_price(group, total_vol) -> float:
    if total_vol and total_vol > 0:
        return sum(
            float(getattr(d, "price", 0) or 0) * float(getattr(d, "volume", 0) or 0)
            for d in group
        ) / total_vol
    prices = [
        float(getattr(d, "price", 0) or 0)
        for d in group
        if isinstance(getattr(d, "price", None), (int, float))
    ]
    return sum(prices) / len(prices) if prices else 0.0
