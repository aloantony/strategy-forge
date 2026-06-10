"""
PlanInterpreter v1.
Valida y normaliza un plan dict, resolviendo specs a valores concretos.
No ejecuta nada — sólo prepara las acciones para el ExecutionEngine.
"""


class PlanValidationError(Exception):
    pass


def _resolve_size_spec(size_spec: dict, context: dict) -> float:
    """Resuelve size_spec a volumen en lots."""
    if not isinstance(size_spec, dict):
        raise PlanValidationError(f"size_spec inválido: {size_spec!r}")

    mode = size_spec.get("mode", "")

    if mode in ("fixed_lots", "fixed_lot"):
        return float(size_spec.get("value", 0.01))

    if mode in ("risk_pct_of_equity", "risk_pct"):
        pct = float(size_spec.get("value", 1.0))
        equity = context.get("account", {}).get("equity", 0.0)
        instrument = context.get("instrument", {})
        tick_value = instrument.get("tick_value", 1.0)
        tick_size = instrument.get("tick_size", 0.1)
        stop_points = size_spec.get("stop_points", 300.0)

        if equity <= 0 or tick_value <= 0 or stop_points <= 0:
            return _get_fallback_volume(context)

        risk_amount = equity * pct / 100.0
        value_per_lot_per_point = tick_value / tick_size if tick_size > 0 else tick_value
        volume = risk_amount / (stop_points * value_per_lot_per_point)
        return _clamp_volume(volume, instrument)

    if mode == "volume":
        return float(size_spec.get("value", 0.01))

    if mode == "formula":
        formula_id = size_spec.get("formula_id", "")
        if formula_id == "volume_ratio_based":
            base_risk = float(size_spec.get("inputs", {}).get("base_risk_pct", 0.5))
            cap_risk = float(size_spec.get("inputs", {}).get("cap_risk_pct", 1.0))
            vol_ratio = float(size_spec.get("inputs", {}).get("volume_ratio", 1.0))
            equity = context.get("account", {}).get("equity", 0.0)
            instrument = context.get("instrument", {})
            stop_points = size_spec.get("stop_points", 300.0)

            if equity <= 0 or stop_points <= 0:
                return _get_fallback_volume(context)

            adjusted_pct = min(base_risk * vol_ratio, cap_risk)
            risk_amount = equity * adjusted_pct / 100.0
            tick_value = instrument.get("tick_value", 1.0)
            tick_size = instrument.get("tick_size", 0.1)
            value_per_lot_per_point = tick_value / tick_size if tick_size > 0 else tick_value
            volume = risk_amount / (stop_points * value_per_lot_per_point) if value_per_lot_per_point > 0 else 0.0
            return _clamp_volume(volume, instrument)
        # Otros formula_id: fallback a lot mínimo
        return _get_fallback_volume(context)

    raise PlanValidationError(f"size_spec.mode desconocido: {mode!r}")


def _resolve_stop_spec(stop_spec: dict, side: str, entry_price: float, context: dict) -> float | None:
    """Resuelve stop_spec a precio absoluto de SL. Devuelve None si no hay SL."""
    if not stop_spec:
        return None
    mode = stop_spec.get("mode", "")

    if mode in ("price", "price_absolute"):
        return float(stop_spec.get("value", 0.0))

    if mode in ("price_offset", "points_from_entry"):
        points = float(stop_spec.get("points", stop_spec.get("value", 300.0)))
        instrument = context.get("instrument", {})
        point = instrument.get("point", 0.0001)
        offset = points * point
        return entry_price - offset if side == "long" else entry_price + offset

    if mode == "atr_multiple":
        multiple = float(stop_spec.get("multiple", stop_spec.get("value", 1.0)))
        atr_period = stop_spec.get("atr_period", 14)
        atr_field = stop_spec.get("atr_field", f"atr_{atr_period}")
        atr_value = _get_last_indicator(context, atr_field)
        if atr_value is None or atr_value <= 0:
            return None
        offset = atr_value * multiple
        return entry_price - offset if side == "long" else entry_price + offset

    if mode == "break_even":
        return entry_price

    if mode == "break_even_plus":
        buffer = float(stop_spec.get("buffer_points", 0.0))
        instrument = context.get("instrument", {})
        point = instrument.get("point", 0.0001)
        offset = buffer * point
        return entry_price + offset if side == "long" else entry_price - offset

    return None


def _resolve_take_profit_spec(
    take_profit_spec: dict, side: str, entry_price: float, sl_price: float | None, context: dict
) -> float | None:
    """Resuelve take_profit_spec a precio de TP. Devuelve None si no hay TP."""
    if not take_profit_spec:
        return None
    mode = take_profit_spec.get("mode", "")

    if mode in ("price", "price_absolute"):
        return float(take_profit_spec.get("value", 0.0))

    if mode in ("price_offset", "points_from_entry"):
        points = float(take_profit_spec.get("points", take_profit_spec.get("value", 500.0)))
        instrument = context.get("instrument", {})
        point = instrument.get("point", 0.0001)
        offset = points * point
        return entry_price + offset if side == "long" else entry_price - offset

    if mode in ("rr_multiple", "risk_multiple"):
        multiple = float(take_profit_spec.get("multiple", take_profit_spec.get("value", 2.0)))
        if sl_price is None:
            return None
        risk = abs(entry_price - sl_price)
        return entry_price + risk * multiple if side == "long" else entry_price - risk * multiple

    if mode == "multi_target":
        # Para multi_target devolvemos el primer target como TP principal
        targets = take_profit_spec.get("targets", [])
        if targets:
            first = targets[0]
            rr = float(first.get("rr", 1.0))
            if sl_price is not None:
                risk = abs(entry_price - sl_price)
                return entry_price + risk * rr if side == "long" else entry_price - risk * rr
        return None

    return None


def _get_last_indicator(context: dict, field: str) -> float | None:
    """Busca el último valor de un indicador en market.frames."""
    frames = context.get("market", {}).get("frames", {})
    for frame_data in frames.values():
        bars = frame_data.get("bars", [])
        if bars:
            last_bar = bars[-2] if len(bars) >= 2 else bars[-1]
            indicators = last_bar.get("indicators", {})
            val = indicators.get(field) or last_bar.get(field)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
    return None


def _get_last_price(context: dict) -> float:
    """Obtiene el precio de mercado actual (ask para long, bid para short)."""
    quote = context.get("market", {}).get("quote", {})
    mid = quote.get("mid", 0.0)
    return float(mid) if mid else 0.0


def _get_fallback_volume(context: dict) -> float:
    instrument = context.get("instrument", {})
    return instrument.get("volume_min", 0.01)


def _clamp_volume(volume: float, instrument: dict) -> float:
    vol_min = instrument.get("volume_min", 0.01)
    vol_max = instrument.get("volume_max", 100.0)
    vol_step = instrument.get("volume_step", 0.01)
    if vol_step > 0:
        volume = round(round(volume / vol_step) * vol_step, 10)
    return max(vol_min, min(vol_max, volume))


class PlanInterpreter:
    """
    Valida y normaliza un plan dict.
    Devuelve lista de normalized_actions listas para el ExecutionEngine.
    """

    SUPPORTED_ACTION_TYPES = {
        "open_position",
        "add_to_position",
        "close_position",
        "reduce_position",
        "move_stop_loss",
        "move_take_profit",
        "place_pending_order",
        "cancel_pending_order",
        "replace_pending_order",
    }

    def validate_and_normalize(self, plan: dict, context: dict) -> list:
        """
        Devuelve lista de normalized_action dicts.
        Lanza PlanValidationError si el plan es estructuralmente inválido.
        """
        if not isinstance(plan, dict):
            raise PlanValidationError("El plan debe ser un dict")

        schema_version = plan.get("schema_version", 1)
        if schema_version != 1:
            raise PlanValidationError(f"schema_version no soportado: {schema_version}")

        actions = plan.get("actions", [])
        if not isinstance(actions, list):
            raise PlanValidationError("plan.actions debe ser una lista")

        normalized = []
        for i, action in enumerate(actions):
            try:
                norm = self._normalize_action(action, context, plan)
                normalized.append(norm)
            except PlanValidationError:
                raise
            except Exception as exc:
                raise PlanValidationError(f"Error normalizando action[{i}]: {exc}") from exc

        return normalized

    def _normalize_action(self, action: dict, context: dict, plan: dict) -> dict:
        if not isinstance(action, dict):
            raise PlanValidationError(f"action debe ser dict, got {type(action)}")

        action_type = action.get("type", "")
        if action_type not in self.SUPPORTED_ACTION_TYPES:
            raise PlanValidationError(f"action.type no soportado: {action_type!r}")

        symbol = action.get("symbol") or plan.get("symbol", "")
        reason = action.get("reason", "")
        action_id = action.get("action_id", "")

        if action_type in ("open_position", "add_to_position"):
            return self._normalize_open(action, context, symbol, reason, action_id)

        if action_type == "close_position":
            return self._normalize_close(action, context, symbol, reason, action_id)

        if action_type == "reduce_position":
            return self._normalize_reduce(action, context, symbol, reason, action_id)

        if action_type == "move_stop_loss":
            return self._normalize_move_sl(action, context, symbol, reason, action_id)

        if action_type == "move_take_profit":
            return self._normalize_move_tp(action, context, symbol, reason, action_id)

        # place/cancel/replace pending orders: pasar como están sin resolución profunda
        return {
            "action_id": action_id,
            "type": action_type,
            "symbol": symbol,
            "reason": reason,
            "original": action,
            "resolved": {},
        }

    def _normalize_open(self, action: dict, context: dict, symbol: str, reason: str, action_id: str) -> dict:
        side = action.get("side", "long")
        size_spec = action.get("size_spec", {"mode": "fixed_lots", "value": 0.01})
        stop_spec = action.get("stop_spec")
        tp_spec = action.get("take_profit_spec")

        entry_price = _get_last_price(context)
        if entry_price <= 0:
            quote = context.get("market", {}).get("quote", {})
            entry_price = float(quote.get("ask", 0) if side == "long" else quote.get("bid", 0))

        volume = _resolve_size_spec(size_spec, context)
        sl_price = _resolve_stop_spec(stop_spec, side, entry_price, context) if stop_spec else None
        tp_price = _resolve_take_profit_spec(tp_spec, side, entry_price, sl_price, context) if tp_spec else None

        return {
            "action_id": action_id,
            "type": action.get("type"),
            "symbol": symbol,
            "side": side,
            "reason": reason,
            "tags": action.get("tags", {}),
            "group_spec": action.get("group_spec"),
            "target": action.get("target"),
            "resolved": {
                "volume": volume,
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp_price": tp_price,
            },
            "original": action,
        }

    def _normalize_close(self, action: dict, context: dict, symbol: str, reason: str, action_id: str) -> dict:
        return {
            "action_id": action_id,
            "type": "close_position",
            "symbol": symbol,
            "reason": reason,
            "tags": action.get("tags", {}),
            "target": action.get("target", {}),
            "close_spec": action.get("close_spec", {"mode": "full"}),
            "resolved": {},
            "original": action,
        }

    def _normalize_reduce(self, action: dict, context: dict, symbol: str, reason: str, action_id: str) -> dict:
        return {
            "action_id": action_id,
            "type": "reduce_position",
            "symbol": symbol,
            "reason": reason,
            "tags": action.get("tags", {}),
            "target": action.get("target", {}),
            "reduction_spec": action.get("reduction_spec", {"mode": "pct", "value": 50}),
            "resolved": {},
            "original": action,
        }

    def _normalize_move_sl(self, action: dict, context: dict, symbol: str, reason: str, action_id: str) -> dict:
        stop_spec = action.get("stop_spec", {})
        target = action.get("target", {})

        # Intentar resolver el nuevo SL
        owned_legs = context.get("execution", {}).get("owned_legs", [])
        entry_price = 0.0
        side = "long"
        if owned_legs:
            first_leg = owned_legs[0]
            entry_price = float(first_leg.get("avg_entry_price", 0) or 0)
            side = first_leg.get("side", "long")

        new_sl = _resolve_stop_spec(stop_spec, side, entry_price, context) if entry_price > 0 else None

        return {
            "action_id": action_id,
            "type": "move_stop_loss",
            "symbol": symbol,
            "reason": reason,
            "tags": action.get("tags", {}),
            "target": target,
            "stop_spec": stop_spec,
            "resolved": {"new_sl_price": new_sl},
            "original": action,
        }

    def _normalize_move_tp(self, action: dict, context: dict, symbol: str, reason: str, action_id: str) -> dict:
        return {
            "action_id": action_id,
            "type": "move_take_profit",
            "symbol": symbol,
            "reason": reason,
            "tags": action.get("tags", {}),
            "target": action.get("target", {}),
            "take_profit_spec": action.get("take_profit_spec", {}),
            "resolved": {},
            "original": action,
        }
