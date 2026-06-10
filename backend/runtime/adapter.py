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


def _extract_signal_payload(raw) -> dict:
    """Normaliza la salida legacy a {signal, reason}."""
    signal_raw = raw
    reason_raw = ""

    if isinstance(raw, dict):
        signal_raw = (
            raw.get("signal") or raw.get("side") or
            raw.get("action") or raw.get("decision") or "none"
        )
        reason_raw = (
            raw.get("reason") or raw.get("motivo") or
            raw.get("message") or raw.get("detail") or raw.get("why") or ""
        )
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


class LegacyStrategyAdapter:
    """
    Adapta un módulo legacy al contrato v1 decide(context, state) -> dict.

    No introduce lógica de negocio nueva: envuelve, marca, traduce.
    """

    def __init__(self, module, timeframe_label: str = "M1"):
        self._module = module
        self._timeframe_label = timeframe_label

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

        if signal == "buy":
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
                "compat_mode": "signal_translation",
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
