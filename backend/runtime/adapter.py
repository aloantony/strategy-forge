"""
LegacyStrategyAdapter v1.
Envuelve una estrategia legacy (get_last_signal / get_last_signal_payload)
y la presenta al runtime como si implementara decide(context, state).

Según doc 17: el adaptador envuelve, marca y traduce. No inventa.
"""

import uuid
from datetime import datetime, timezone


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return str(uuid.uuid4())


def _normalize_signal(value) -> str:
    signal = str(value or "").strip().lower()
    return signal if signal in {"buy", "sell", "none"} else "none"


def _float(value, default=0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _int_or_none(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _extract_signal_payload(raw) -> dict:
    """Normaliza la salida legacy a {signal, reason} + campos avanzados (ATR/riesgo)."""
    signal_raw = raw
    reason_raw = ""
    advanced = {
        "pyramiding": False,
        "atr_value": 0.0,
        "sl_atr_mult": 1.0,
        "tp_atr_mult": 2.0,
        "pyramid_atr_mult": 0.5,
        "risk_pct": 0.0,
        "entry_index": None,
        "max_entries": None,
        "block_id": "",
        "tier_id": "",
    }

    if isinstance(raw, dict):
        signal_raw = (
            raw.get("signal") or raw.get("side") or
            raw.get("action") or raw.get("decision") or "none"
        )
        reason_raw = (
            raw.get("reason") or raw.get("motivo") or
            raw.get("message") or raw.get("detail") or raw.get("why") or ""
        )
        advanced["pyramiding"] = bool(raw.get("pyramiding"))
        advanced["atr_value"] = _float(raw.get("atr_value"))
        advanced["sl_atr_mult"] = _float(raw.get("sl_atr_mult"), 1.0)
        advanced["tp_atr_mult"] = _float(raw.get("tp_atr_mult"), 2.0)
        advanced["pyramid_atr_mult"] = _float(raw.get("pyramid_atr_mult"), 0.5)
        advanced["risk_pct"] = _float(raw.get("risk_pct"))
        advanced["entry_index"] = _int_or_none(raw.get("entry_index"))
        advanced["max_entries"] = _int_or_none(raw.get("max_entries"))
        advanced["block_id"] = str(raw.get("block_id") or "")
        advanced["tier_id"] = str(raw.get("tier_id") or "")
    elif isinstance(raw, (tuple, list)):
        if len(raw) > 0:
            signal_raw = raw[0]
        if len(raw) > 1:
            reason_raw = raw[1]

    reason = str(reason_raw or "").strip()
    if len(reason) > 160:
        reason = reason[:157].rstrip() + "..."

    return {
        "signal": _normalize_signal(signal_raw),
        "reason": reason,
        **advanced,
    }


def _df_from_context(context: dict, timeframe_label: str):
    """Reconstruye un DataFrame pandas desde context.market.frames."""
    try:
        import pandas as pd
        frames = context.get("market", {}).get("frames", {})
        frame_data = frames.get(timeframe_label) or next(iter(frames.values()), {})
        bars = frame_data.get("bars", [])
        if not bars:
            return pd.DataFrame()
        df = pd.DataFrame(bars)
        # Aplanar indicadores si están anidados
        if "indicators" in df.columns:
            indicators_df = pd.json_normalize(df["indicators"])
            df = pd.concat([df.drop(columns=["indicators"]), indicators_df], axis=1)
        return df
    except Exception:
        return None


def _get_owned_side(context: dict) -> str | None:
    """Devuelve 'long', 'short' o None según las legs propias abiertas."""
    owned_legs = context.get("execution", {}).get("owned_legs", [])
    open_legs = [
        leg for leg in owned_legs
        if leg.get("status") in ("open", "pending_open", "reducing")
    ]
    if not open_legs:
        return None
    sides = {leg.get("side") for leg in open_legs}
    if "long" in sides:
        return "long"
    if "short" in sides:
        return "short"
    return None


def _build_open_action(symbol: str, side: str, defaults: dict, reason: str) -> dict:
    lot = defaults.get("lot", 0.01)
    sl_points = defaults.get("sl_points", 300.0)
    tp_points = defaults.get("tp_points", 500.0)
    return {
        "action_id": _new_id(),
        "type": "open_position",
        "symbol": symbol,
        "side": side,
        "size_spec": {"mode": "fixed_lots", "value": lot},
        "entry_spec": {"mode": "market"},
        "stop_spec": {"mode": "price_offset", "points": sl_points},
        "take_profit_spec": {"mode": "price_offset", "points": tp_points},
        "reason": reason,
        "tags": {"entry_kind": "initial"},
    }


def _build_close_action(symbol: str, owned_side: str, reason: str) -> dict:
    return {
        "action_id": _new_id(),
        "type": "close_position",
        "symbol": symbol,
        "target": {
            "resource_type": "owned_side",
            "mode": "by_side",
            "value": owned_side,
        },
        "close_spec": {"mode": "full"},
        "reason": reason,
        "tags": {},
    }


_AGGREGATE_RISK_LIMIT = 0.03  # paridad con trading.check_aggregate_risk


def _open_legs(context: dict, side: str | None = None) -> list:
    legs = [
        leg for leg in context.get("execution", {}).get("owned_legs", [])
        if leg.get("status") in ("open", "pending_open", "reducing")
    ]
    if side is not None:
        legs = [leg for leg in legs if leg.get("side") == side]
    return legs


def _aggregate_risk_ok(context: dict, side: str, new_risk_money: float) -> bool:
    """Riesgo agregado (legs abiertas del lado + nueva entrada) ≤ 3% del equity."""
    equity = _float(context.get("account", {}).get("equity"))
    if equity <= 0:
        return False
    instrument = context.get("instrument", {})
    tick_size = _float(instrument.get("tick_size"))
    tick_value = _float(instrument.get("tick_value"))
    value_per_unit = (tick_value / tick_size) if tick_size > 0 and tick_value > 0 else 0.0

    existing = 0.0
    if value_per_unit > 0:
        for leg in _open_legs(context, side):
            sl = _float(leg.get("stop_loss"))
            entry = _float(leg.get("avg_entry_price"))
            volume = _float(leg.get("remaining_volume"))
            if sl <= 0 or entry <= 0 or volume <= 0:
                continue
            distance = (entry - sl) if side == "long" else (sl - entry)
            if distance > 0:
                existing += volume * distance * value_per_unit

    return (existing + max(new_risk_money, 0.0)) / equity <= _AGGREGATE_RISK_LIMIT


def _build_advanced_actions(symbol: str, side: str, payload: dict, defaults: dict,
                            context: dict, reason: str) -> list:
    """
    Traduce un payload avanzado (ATR + tramos de riesgo + piramidación) a acciones
    del plan, replicando las reglas de la ruta legacy directa (apply_pyramid_signal):
    gating por entry_index/max_entries, umbral de pirámide y límite de riesgo agregado.
    """
    atr_value = payload["atr_value"]
    same = _open_legs(context, side)
    opposite = [leg for leg in _open_legs(context) if leg.get("side") != side]
    if opposite:
        return []  # la vía avanzada no revierte: mantiene la posición contraria

    n_open = len(same)
    max_entries = payload["max_entries"]
    if max_entries is not None and max_entries > 0 and n_open >= max_entries:
        return []
    entry_index = payload["entry_index"]
    if entry_index is not None and entry_index >= 0 and n_open != entry_index:
        return []

    quote = context.get("market", {}).get("quote", {})
    price = _float(quote.get("ask") if side == "long" else quote.get("bid")) or _float(quote.get("mid"))

    if n_open > 0:
        if price <= 0:
            return []
        last = max(same, key=lambda leg: str(leg.get("opened_at") or ""))
        last_price = _float(last.get("avg_entry_price"))
        sign = 1 if side == "long" else -1
        threshold = last_price + sign * (payload["pyramid_atr_mult"] * atr_value)
        if side == "long" and price < threshold:
            return []
        if side == "short" and price > threshold:
            return []

    point = _float(context.get("instrument", {}).get("point"))
    if point > 0:
        sl_points = payload["sl_atr_mult"] * atr_value / point
        tp_points = payload["tp_atr_mult"] * atr_value / point
    else:
        sl_points = _float(defaults.get("sl_points"), 300.0)
        tp_points = _float(defaults.get("tp_points"), 500.0)

    equity = _float(context.get("account", {}).get("equity"))
    risk_pct = payload["risk_pct"]
    if risk_pct > 0 and sl_points > 0:
        size_spec = {"mode": "risk_pct", "value": risk_pct * 100.0, "stop_points": sl_points}
        new_risk_money = equity * risk_pct
    else:
        lot = _float(defaults.get("lot"), 0.01)
        size_spec = {"mode": "fixed_lots", "value": lot}
        instrument = context.get("instrument", {})
        tick_size = _float(instrument.get("tick_size"))
        tick_value = _float(instrument.get("tick_value"))
        value_per_unit = (tick_value / tick_size) if tick_size > 0 and tick_value > 0 else 0.0
        new_risk_money = lot * (payload["sl_atr_mult"] * atr_value) * value_per_unit

    if not _aggregate_risk_ok(context, side, new_risk_money):
        return []

    group_spec = None
    if n_open > 0:
        last = max(same, key=lambda leg: str(leg.get("opened_at") or ""))
        group_id = last.get("entry_group_id")
        if group_id:
            group_spec = {"mode": "existing_group", "target": {"mode": "by_id", "value": group_id}}

    action = {
        "action_id": _new_id(),
        "type": "open_position" if n_open == 0 else "add_to_position",
        "symbol": symbol,
        "side": side,
        "size_spec": size_spec,
        "entry_spec": {"mode": "market"},
        "stop_spec": {"mode": "price_offset", "points": sl_points},
        "take_profit_spec": {"mode": "price_offset", "points": tp_points},
        "reason": reason,
        "tags": {
            "entry_kind": "initial" if n_open == 0 else "pyramid",
            "entry_index": n_open,
            "block_id": payload["block_id"],
            "tier_id": payload["tier_id"],
        },
    }
    if group_spec:
        action["group_spec"] = group_spec
    return [action]


class LegacyStrategyAdapter:
    """
    Adapta un módulo legacy al contrato v1 decide(context, state) -> dict.

    No introduce lógica de negocio nueva: envuelve, marca, traduce.
    """

    def __init__(self, module, timeframe_label: str = "M1", frames: dict | None = None):
        self._module = module
        self._timeframe_label = timeframe_label
        # frames: dict {timeframe: DataFrame} para módulos MTF (REQUIRED_TIMEFRAMES);
        # sin ellos un módulo MTF solo vería su timeframe primario y nunca señalaría.
        self._frames = frames

    def decide(self, context: dict, state: dict) -> dict:
        symbol = context.get("symbol", {}).get("name", "")
        instance_id = context.get("instance", {}).get("id", "")
        defaults = (
            context.get("instance", {})
            .get("runtime", {})
            .get("legacy_execution_defaults", {})
        )

        # 1. Ejecutar pipeline legacy
        raw_payload = None
        error_msg = None
        try:
            if self._frames and hasattr(self._module, "get_last_signal_payload_mtf"):
                raw_payload = self._module.get_last_signal_payload_mtf(self._frames, verbose=False)
            else:
                df = self._run_legacy_pipeline(context)
                raw_payload = self._call_legacy_signal(df)
        except Exception as exc:
            error_msg = str(exc)
            raw_payload = None

        if error_msg:
            plan = {
                "schema_version": 1,
                "plan_id": _new_id(),
                "instance_id": instance_id,
                "symbol": symbol,
                "reason": f"Error en estrategia legacy: {error_msg}",
                "actions": [],
                "meta": {
                    "origin": "legacy_adapter",
                    "legacy_signal": "error",
                    "compat_mode": "signal_translation",
                    "error": error_msg,
                },
            }
            return {"plan": plan, "next_state": state or {}}

        # 2. Normalizar payload
        payload = _extract_signal_payload(raw_payload)
        signal = payload["signal"]
        reason = payload["reason"] or f"Señal legacy: {signal}"

        # 3. Traducir señal a actions según doc 17
        owned_side = _get_owned_side(context)
        actions = []
        advanced = signal in ("buy", "sell") and payload["pyramiding"] and payload["atr_value"] > 0

        if advanced:
            # Vía avanzada: tamaño por % de riesgo, SL/TP desde el ATR y piramidación
            # con gating — fiel a la ruta legacy directa y al backtest.
            side = "long" if signal == "buy" else "short"
            actions = _build_advanced_actions(symbol, side, payload, defaults, context, reason)

        elif signal == "buy":
            if owned_side == "long":
                pass  # ya long → no-op
            elif owned_side == "short":
                actions.append(_build_close_action(symbol, "short", reason))
                actions.append(_build_open_action(symbol, "long", defaults, reason))
            else:
                actions.append(_build_open_action(symbol, "long", defaults, reason))

        elif signal == "sell":
            if owned_side == "short":
                pass  # ya short → no-op
            elif owned_side == "long":
                actions.append(_build_close_action(symbol, "long", reason))
                actions.append(_build_open_action(symbol, "short", defaults, reason))
            else:
                actions.append(_build_open_action(symbol, "short", defaults, reason))

        # signal == "none" → actions vacías

        plan = {
            "schema_version": 1,
            "plan_id": _new_id(),
            "instance_id": instance_id,
            "symbol": symbol,
            "reason": reason,
            "actions": actions,
            "meta": {
                "origin": "legacy_adapter",
                "legacy_signal": signal,
                "legacy_reason": reason,
                "compat_mode": "advanced_translation" if advanced else "signal_translation",
            },
        }

        next_state = dict(state or {})
        next_state.update({
            "last_signal": signal,
            "last_reason": reason,
            "last_decision_at": _now_utc(),
        })

        return {"plan": plan, "next_state": next_state}

    def _run_legacy_pipeline(self, context: dict):
        df = _df_from_context(context, self._timeframe_label)
        module = self._module
        if df is not None and not df.empty:
            if hasattr(module, "prepare_dataframe"):
                result = module.prepare_dataframe(df)
                if result is not None:
                    df = result
            if hasattr(module, "compute_dir1_and_signals"):
                result = module.compute_dir1_and_signals(df, True)
                if result is not None:
                    df = result
            elif hasattr(module, "compute_signals"):
                result = module.compute_signals(df, True)
                if result is not None:
                    df = result
        return df

    def _call_legacy_signal(self, df):
        module = self._module
        if hasattr(module, "get_last_signal_payload"):
            try:
                return module.get_last_signal_payload(df, verbose=False)
            except TypeError:
                return module.get_last_signal_payload(df)
        elif hasattr(module, "get_last_signal"):
            try:
                return module.get_last_signal(df, verbose=False)
            except TypeError:
                return module.get_last_signal(df)
        return "none"
