"""
Gestión de órdenes y posiciones en MetaTrader 5.
"""

import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
import math
import re
import config
from src.broker.interface import InstrumentInfo

_FILLING_NAME = {
    getattr(mt5, "ORDER_FILLING_FOK", 0): "FOK",
    getattr(mt5, "ORDER_FILLING_IOC", 1): "IOC",
    getattr(mt5, "ORDER_FILLING_RETURN", 2): "RETURN",
}

_MARKET_FUTURE_TICK_TOLERANCE_SECONDS = 60
_MARKET_STALE_TICK_SECONDS = 300
_MAX_BROKER_TICK_OFFSET_HOURS = 14

# Prefijo para comentarios de órdenes creadas por el bot.
_TRADE_COMMENT_PREFIX = "TA"
_DEFAULT_OPEN_COMMENT = "Bot trading"
_DEFAULT_CLOSE_COMMENT = "Cierre automatico"
_MT5_COMMENT_MAX_LEN = 31
_STRATEGY_TOKEN_MAX_LEN = 10
_REASON_TOKEN_MAX_LEN = 24
_FALLBACK_OPEN_COMMENT = "TAOPEN"
_FALLBACK_CLOSE_COMMENT = "TACLOSE"


def _sanitize_comment_token(value: str, max_len: int) -> str:
    # compacta un texto libre en un token seguro para el comentario de MT5.
    token = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    token = re.sub(r"_+", "_", token).strip("_")
    if not token:
        return ""
    return token[:max_len].strip("_")


def _is_invalid_comment_error(last_error) -> bool:
    # detecta si MT5 rechazo el request por argumento comment invalido.
    if not isinstance(last_error, (tuple, list)) or len(last_error) < 2:
        return False
    try:
        code = int(last_error[0])
    except Exception:
        code = None
    message = str(last_error[1] or "").lower()
    return code == -2 and "comment" in message and "invalid" in message


def _fallback_comment_from_request(request: dict) -> str:
    # retorna un comentario ultraseguro para brokers estrictos.
    if isinstance(request, dict) and request.get("position"):
        return _FALLBACK_CLOSE_COMMENT
    return _FALLBACK_OPEN_COMMENT


def _tick_timestamp_to_utc(raw_timestamp) -> datetime | None:
    # convierte el timestamp MT5 a datetime UTC y filtra valores vacios/invalidos.
    try:
        timestamp_value = float(raw_timestamp)
    except (TypeError, ValueError):
        return None
    if timestamp_value <= 0:
        return None
    return datetime.fromtimestamp(timestamp_value, tz=timezone.utc)


def _resolve_tick_time_alignment(tick_time_utc: datetime, now_utc: datetime):
    # algunos brokers entregan ticks con la hora del servidor en vez de UTC.
    raw_diff = (now_utc - tick_time_utc).total_seconds()
    if raw_diff >= -_MARKET_FUTURE_TICK_TOLERANCE_SECONDS:
        return tick_time_utc, raw_diff, 0

    for offset_hours in range(1, _MAX_BROKER_TICK_OFFSET_HOURS + 1):
        adjusted_tick_time = tick_time_utc - timedelta(hours=offset_hours)
        adjusted_diff = (now_utc - adjusted_tick_time).total_seconds()
        if -_MARKET_FUTURE_TICK_TOLERANCE_SECONDS <= adjusted_diff <= _MARKET_STALE_TICK_SECONDS:
            return adjusted_tick_time, adjusted_diff, offset_hours

    return tick_time_utc, raw_diff, 0


def _humanize_reason_token(token: str) -> str:
    # transforma token tipo "ema_cross_up" en texto legible.
    text = str(token or "").strip().replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_trade_comment(
    strategy_key: str = "",
    signal_reason: str = "",
    action_kind: str = "open"
) -> str:
    # arma comentario compacto para recuperar motivo desde history_deals_get.
    action_code = "o" if str(action_kind or "").strip().lower() == "open" else "c"
    strategy_token = _sanitize_comment_token(strategy_key, _STRATEGY_TOKEN_MAX_LEN)
    reason_token = _sanitize_comment_token(signal_reason, _REASON_TOKEN_MAX_LEN)
    parts = [_TRADE_COMMENT_PREFIX, action_code]
    if strategy_token:
        parts.append(f"s={strategy_token}")
    if reason_token:
        parts.append(f"r={reason_token}")
    comment = "|".join(parts)
    if len(comment) <= _MT5_COMMENT_MAX_LEN:
        return comment

    # Prioriza conservar un motivo legible antes que el token de estrategia.
    if strategy_token and reason_token:
        no_strategy = "|".join([_TRADE_COMMENT_PREFIX, action_code, f"r={reason_token}"])
        if len(no_strategy) <= _MT5_COMMENT_MAX_LEN:
            return no_strategy

    # Ajuste progresivo por si el broker limita el tamaño del comentario.
    if reason_token:
        allowed_reason_len = max(4, _MT5_COMMENT_MAX_LEN - len("|".join(parts[:-1])) - 3)
        reason_token = reason_token[:allowed_reason_len].strip("_")
        parts[-1] = f"r={reason_token}" if reason_token else ""
        parts = [p for p in parts if p]
    comment = "|".join(parts)
    if len(comment) <= _MT5_COMMENT_MAX_LEN:
        return comment

    if strategy_token:
        # Si aún excede, prioriza conservar acción + motivo.
        parts = [_TRADE_COMMENT_PREFIX, action_code]
        if reason_token:
            parts.append(f"r={reason_token}")
    comment = "|".join(parts)
    return comment[:_MT5_COMMENT_MAX_LEN]


def decode_trade_comment(comment: str) -> dict:
    # parsea comentario MT5 generado por build_trade_comment.
    result = {
        "raw": str(comment or ""),
        "is_bot_comment": False,
        "action": "",
        "strategy": "",
        "reason_token": "",
        "reason": "",
    }
    text = str(comment or "").strip()
    if not text:
        return result
    parts = text.split("|")
    if len(parts) < 2 or parts[0] != _TRADE_COMMENT_PREFIX:
        return result

    result["is_bot_comment"] = True
    action_code = (parts[1] or "").strip().lower()
    if action_code == "o":
        result["action"] = "open"
    elif action_code == "c":
        result["action"] = "close"

    for item in parts[2:]:
        if item.startswith("s="):
            token = item[2:].strip()
            result["strategy"] = _humanize_reason_token(token)
            continue
        if item.startswith("r="):
            token = item[2:].strip()
            result["reason_token"] = token
            result["reason"] = _humanize_reason_token(token)
            break

    return result



def get_allowed_filling_modes(symbol_info):
    # pregunta que tipos de ejecucion de orden acepta este broker.
    """
    Devuelve la lista de modos de llenado permitidos según el bitmask trade_fillings.
    """
    fillings_flag = getattr(symbol_info, "trade_fillings", 0) or 0

    mapping = [
        (getattr(mt5, "SYMBOL_FILLING_FOK", 1), mt5.ORDER_FILLING_FOK),
        (getattr(mt5, "SYMBOL_FILLING_IOC", 2), mt5.ORDER_FILLING_IOC),
        (getattr(mt5, "SYMBOL_FILLING_RETURN", 4), mt5.ORDER_FILLING_RETURN),
    ]

    allowed = [order_mode for bit, order_mode in mapping if fillings_flag & bit]

    if not allowed:
        mode = getattr(symbol_info, "filling_mode", None)
        if mode in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN):
            allowed.append(mode)

    return allowed


def describe_fillings(symbol_info, allowed_modes):
    # crea un texto legible con los modos de llenado permitidos.
    """
    Devuelve cadena legible con trade_fillings, filling_mode y modos permitidos.
    """
    fillings_flag = getattr(symbol_info, "trade_fillings", 0) or 0
    filling_mode = getattr(symbol_info, "filling_mode", None)

    allowed_names = [ _FILLING_NAME.get(m, str(m)) for m in allowed_modes ] if allowed_modes else []
    filling_mode_name = _FILLING_NAME.get(filling_mode, filling_mode)

    return (f"trade_fillings={fillings_flag} | filling_mode={filling_mode_name} | "
            f"permitidos={allowed_names if allowed_names else 'N/A'}")


def choose_filling_mode(symbol_info, allowed_modes=None) -> int:
    # elige el mejor modo de llenado para aumentar la probabilidad de exito.
    """
    Elige un modo de llenado permitido por el símbolo.
    - Prioriza el filling_mode expuesto si es válido.
    - Si no, toma el primer modo permitido.
    - Como último recurso, usa IOC para no bloquear el envío.
    """
    allowed_modes = allowed_modes or get_allowed_filling_modes(symbol_info)

    mode = getattr(symbol_info, "filling_mode", None)
    if mode in allowed_modes:
        return mode

    if allowed_modes:
        return allowed_modes[0]

    # Heurística final si no se pudo determinar nada
    trade_exemode = getattr(symbol_info, "trade_exemode", None)
    if trade_exemode == mt5.SYMBOL_TRADE_EXMODE_EXCHANGE:
        return mt5.ORDER_FILLING_FOK

    return mt5.ORDER_FILLING_IOC


def _is_unsupported_filling(result) -> bool:
    # detecta si MT5 rechazo la orden por un modo de llenado no valido.
    """
    Detecta si el retcode/comentario indica filling mode no soportado.
    """
    if result is None:
        return False

    invalid_fill_code = getattr(mt5, "TRADE_RETCODE_INVALID_FILL", None)
    if invalid_fill_code is not None and result.retcode == invalid_fill_code:
        return True

    comment = (getattr(result, "comment", "") or "").lower()
    return "unsupported filling mode" in comment or ("filling" in comment and "unsupported" in comment)


def order_send_with_filling_retry(request: dict, symbol_info):
    # intenta enviar la orden probando varios modos hasta que uno funcione.
    """
    Envía una orden intentando automáticamente los modos de llenado permitidos.
    Devuelve (result, modo_usado, modos_intentados, ultimo_last_error).
    """
    allowed_modes = get_allowed_filling_modes(symbol_info)
    initial_mode = request.get("type_filling")

    modes_to_try = []
    if initial_mode is not None:
        modes_to_try.append(initial_mode)
    for mode in allowed_modes:
        if mode not in modes_to_try:
            modes_to_try.append(mode)

    # Fallback: probar todos los modos estándar por si el broker no reporta correctamente trade_fillings
    fallback_modes = [mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]
    for mode in fallback_modes:
        if mode not in modes_to_try:
            modes_to_try.append(mode)

    result = None
    last_mode = None
    last_error = None
    fallback_comment_applied = False

    for mode in modes_to_try:
        # Probamos uno por uno; si alguno funciona, paramos ahi.
        request["type_filling"] = mode
        last_mode = mode
        result = mt5.order_send(request)
        if result is None:
            try:
                last_error = mt5.last_error()
            except Exception:
                last_error = None
            if _is_invalid_comment_error(last_error):
                safe_comment = _fallback_comment_from_request(request)
                if request.get("comment") != safe_comment:
                    request["comment"] = safe_comment
                    fallback_comment_applied = True
                    result = mt5.order_send(request)
                    if result is None:
                        try:
                            last_error = mt5.last_error()
                        except Exception:
                            last_error = None
                        continue
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        return result, mode, modes_to_try, last_error
                    if not _is_unsupported_filling(result):
                        return result, mode, modes_to_try, last_error
            continue
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return result, mode, modes_to_try, last_error
        if not _is_unsupported_filling(result):
            return result, mode, modes_to_try, last_error

    if fallback_comment_applied:
        request["comment"] = request.get("comment", _fallback_comment_from_request(request))
    return result, last_mode, modes_to_try, last_error


def normalize_volume(requested_volume: float, symbol_info):
    # ajusta el volumen al minimo, maximo y paso permitidos por el simbolo.
    """
    Ajusta el volumen solicitado a los limites del simbolo (min, max, step).
    Devuelve el volumen ajustado y un mensaje si se modifica.
    """
    min_vol = getattr(symbol_info, "volume_min", 0.0) or 0.0
    max_vol = getattr(symbol_info, "volume_max", float("inf")) or float("inf")
    step = getattr(symbol_info, "volume_step", 0.0) or 0.0
    digits = getattr(symbol_info, "volume_digits", 2) or 2

    volume = max(requested_volume, min_vol)
    if max_vol != float("inf"):
        volume = min(volume, max_vol)

    if step > 0:
        # Ajustar al multiplo de step mas cercano sin superar max_vol
        max_steps = math.floor((max_vol - min_vol) / step) if max_vol != float("inf") else None
        steps = math.floor((volume - min_vol) / step + 1e-9)
        if max_steps is not None:
            steps = min(steps, max_steps)
        volume = min_vol + steps * step

    volume = round(volume, digits)
    note = None
    if volume != requested_volume:
        note = (f"Volumen ajustado de {requested_volume} a {volume} "
                f"(min {min_vol}, step {step}, max {max_vol if max_vol != float('inf') else 'sin limite'})")

    if volume <= 0:
        return 0.0, "No se pudo calcular un volumen valido para el simbolo"

    return volume, note


def adjust_stops(direction: int, price: float, sl: float, tp: float, symbol_info, tick):
    # mueve SL/TP si estan demasiado cerca del precio actual.
    """
    Ajusta SL/TP para cumplir con el nivel mínimo de stops del símbolo.
    Devuelve (sl, tp, nota) si hubo ajuste.
    """
    point = getattr(symbol_info, "point", 0.0) or 0.0
    digits = getattr(symbol_info, "digits", 0) or 0
    stops_level = getattr(symbol_info, "trade_stops_level", 0) or 0
    freeze_level = getattr(symbol_info, "trade_freeze_level", 0) or 0

    min_points = max(stops_level, freeze_level)
    if min_points <= 0 or point <= 0:
        return sl, tp, None

    min_dist = min_points * point

    ref_price = None
    if tick is not None:
        ref_price = tick.bid if direction == 1 else tick.ask
    if not ref_price or ref_price <= 0:
        ref_price = price

    adjusted = False
    if direction == 1:  # BUY
        # En compra, el SL va por debajo y el TP por encima del precio.
        if sl > 0 and (ref_price - sl) < min_dist:
            sl = ref_price - min_dist
            adjusted = True
        if tp > 0 and (tp - ref_price) < min_dist:
            tp = ref_price + min_dist
            adjusted = True
    else:  # SELL
        # En venta, se invierte la logica: SL arriba y TP abajo.
        if sl > 0 and (sl - ref_price) < min_dist:
            sl = ref_price + min_dist
            adjusted = True
        if tp > 0 and (ref_price - tp) < min_dist:
            tp = ref_price - min_dist
            adjusted = True

    if adjusted:
        sl = round(sl, digits) if sl > 0 else sl
        tp = round(tp, digits) if tp > 0 else tp
        note = f"Ajuste SL/TP al minimo ({min_points} pts)"
        return sl, tp, note

    return sl, tp, None


def is_market_open(symbol: str):
    # revisa si hay precios recientes y validos para poder operar.
    """
    Verifica si el mercado está abierto para el símbolo dado.
    
    Args:
        symbol: Símbolo a verificar.
    
    Returns:
        tuple: (bool, str) - (True si está abierto, mensaje descriptivo)
    """
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return False, f"Símbolo {symbol} no encontrado"
    
    # Verificar si el símbolo está disponible para trading
    if not symbol_info.trade_mode:
        return False, "Trading no permitido para este símbolo"
    
    # Obtener el último tick
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False, "No se pudo obtener información del tick"
    
    tick_time = _tick_timestamp_to_utc(getattr(tick, "time", None))
    if tick_time is None:
        return False, "Hora de tick inválida"

    now = datetime.now(timezone.utc)
    _, time_diff, broker_offset_hours = _resolve_tick_time_alignment(tick_time, now)

    # Si el tick viene "del futuro", no es seguro asumir que el mercado esté abierto.
    if time_diff < -_MARKET_FUTURE_TICK_TOLERANCE_SECONDS:
        return False, (
            f"Hora de tick adelantada {int(abs(time_diff) / 60)} min "
            "(reloj local/broker desalineado)"
        )

    # Si el tick tiene más de 5 minutos, considerar el mercado cerrado
    if time_diff > _MARKET_STALE_TICK_SECONDS:
        return False, f"Sin tick reciente ({int(time_diff/60)} min)"
    
    # Verificar si hay spread válido (si el spread es 0 o muy grande, puede estar cerrado)
    if tick.ask == 0 or tick.bid == 0:
        return False, "Precios no disponibles"
    
    spread = tick.ask - tick.bid
    if spread <= 0:
        return False, "Spread inválido"

    status = f"Tick reciente ({int(max(time_diff, 0))} s)"
    if broker_offset_hours:
        status = f"{status} | offset broker +{broker_offset_hours}h compensado"
    return True, status


def get_open_position_direction(symbol: str, magic_number: int) -> int:
    # dice si ahora mismo tenemos BUY, SELL o nada en ese simbolo.
    """
    Obtiene la dirección de la posición abierta para el símbolo y magic number.
    
    Args:
        symbol: Símbolo a verificar.
        magic_number: Magic number de las órdenes.
    
    Returns:
        int: 1 si hay posición BUY, -1 si hay SELL, 0 si no hay posición.
    """
    positions = mt5.positions_get(symbol=symbol)
    
    if positions is None or len(positions) == 0:
        return 0
    
    for position in positions:
        if position.magic == magic_number:
            if position.type == mt5.ORDER_TYPE_BUY:
                return 1
            elif position.type == mt5.ORDER_TYPE_SELL:
                return -1
    
    return 0


def get_position_info(symbol: str, magic_number: int) -> dict:
    # devuelve detalles de la posicion abierta (ticket, precio, profit, etc.).
    """
    Obtiene información detallada de la posición abierta.
    
    Returns:
        dict: Información de la posición o None si no hay posición.
    """
    positions = mt5.positions_get(symbol=symbol)
    
    if positions is None or len(positions) == 0:
        return None
    
    for position in positions:
        if position.magic == magic_number:
            return {
                'ticket': position.ticket,
                'type': 'BUY' if position.type == mt5.ORDER_TYPE_BUY else 'SELL',
                'volume': position.volume,
                'price_open': position.price_open,
                'price_current': position.price_current,
                'profit': position.profit,
                'sl': position.sl,
                'tp': position.tp
            }
    
    return None


def get_all_positions(symbol: str, magic_number: int) -> list:
    # devuelve todas las posiciones abiertas del bot para ese simbolo, ordenadas por tiempo de apertura ascendente.
    raw_positions = mt5.positions_get(symbol=symbol)
    if raw_positions is None or len(raw_positions) == 0:
        return []

    result = []
    for position in raw_positions:
        if position.magic != magic_number:
            continue
        result.append({
            "ticket":        position.ticket,
            "type":          "BUY" if position.type == mt5.ORDER_TYPE_BUY else "SELL",
            "volume":        position.volume,
            "price_open":    position.price_open,
            "price_current": position.price_current,
            "profit":        position.profit,
            "sl":            position.sl,
            "tp":            position.tp,
            "time_open":     position.time,
        })

    result.sort(key=lambda p: p["time_open"])
    return result


def _close_position(symbol: str, magic_number: int, order_comment: str = ""):
    # cierra la posicion abierta del bot para ese simbolo.
    """
    Cierra la posición abierta del símbolo con el magic number especificado.
    
    Args:
        symbol: Símbolo de la posición a cerrar.
        magic_number: Magic number de la orden.
    """
    results = []
    positions = mt5.positions_get(symbol=symbol)
    
    if positions is None or len(positions) == 0:
        return results
    
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        for position in positions:
            if position.magic == magic_number:
                results.append({
                    "kind": "close",
                    "symbol": symbol,
                    "direction": "buy" if position.type == mt5.ORDER_TYPE_BUY else "sell",
                    "ticket": position.ticket,
                    "volume": position.volume,
                    "profit": position.profit,
                    "success": False,
                    "error": "No se pudo obtener información del símbolo"
                })
        return results

    allowed_modes = get_allowed_filling_modes(symbol_info)
    filling_mode = choose_filling_mode(symbol_info, allowed_modes)

    request_comment = (order_comment or "").strip() or _DEFAULT_CLOSE_COMMENT

    for position in positions:
        if position.magic == magic_number:
            # Para cerrar, enviamos una orden contraria a la posicion actual.
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": position.volume,
                "type": mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                "position": position.ticket,
                "deviation": 20,
                "magic": magic_number,
                "comment": request_comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }

            result, used_mode, tried_modes, last_error = order_send_with_filling_retry(request, symbol_info)
            success = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
            used_comment = str(request.get("comment") or request_comment)

            result_info = {
                "kind": "close",
                "symbol": symbol,
                "direction": "buy" if position.type == mt5.ORDER_TYPE_BUY else "sell",
                "ticket": position.ticket,
                "volume": position.volume,
                "profit": position.profit,
                "success": success,
                "retcode": getattr(result, "retcode", None),
                "comment": getattr(result, "comment", None),
                "mt5_last_error": last_error,
                "order_comment": request_comment,
                "used_order_comment": used_comment,
                "filling_mode": used_mode,
                "tried_fillings": tried_modes
            }
            results.append(result_info)

    return results


def _send_order(
    symbol: str,
    direction: int,
    lot: float,
    sl_points: float,
    tp_points: float,
    magic_number: int,
    order_comment: str = "",
    sl_price: float = 0.0,
    tp_price: float = 0.0,
):
    # abre una operacion nueva (compra o venta) con SL/TP.
    """
    Envía una orden de compra o venta.
    
    Args:
        symbol: Símbolo a operar.
        direction: 1 para BUY, -1 para SELL.
        lot: Tamaño de la posición en lotes.
        sl_points: Stop Loss en puntos.
        tp_points: Take Profit en puntos.
        magic_number: Magic number de la orden.
    """
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return {
            "kind": "open",
            "symbol": symbol,
            "direction": "buy" if direction == 1 else "sell" if direction == -1 else "unknown",
            "success": False,
            "error": "No se pudo obtener información del símbolo"
        }
    
    if not symbol_info.visible:
        mt5.symbol_select(symbol, True)
    
    point = symbol_info.point
    tick = mt5.symbol_info_tick(symbol)
    ask = tick.ask if tick else 0.0
    bid = tick.bid if tick else 0.0
    
    if direction == 1:  # BUY
        # En compra se entra al ASK.
        price = ask
        if sl_price > 0:
            sl = sl_price
        elif sl_points > 0:
            sl = price - (sl_points * point)
        else:
            sl = 0
        if tp_price > 0:
            tp = tp_price
        elif tp_points > 0:
            tp = price + (tp_points * point)
        else:
            tp = 0
        order_type = mt5.ORDER_TYPE_BUY
    elif direction == -1:  # SELL
        # En venta se entra al BID.
        price = bid
        if sl_price > 0:
            sl = sl_price
        elif sl_points > 0:
            sl = price + (sl_points * point)
        else:
            sl = 0
        if tp_price > 0:
            tp = tp_price
        elif tp_points > 0:
            tp = price - (tp_points * point)
        else:
            tp = 0
        order_type = mt5.ORDER_TYPE_SELL
    else:
        return {
            "kind": "open",
            "symbol": symbol,
            "direction": "unknown",
            "success": False,
            "error": f"Dirección inválida: {direction}"
        }

    # Ajustamos parametros para que cumplan reglas del broker antes de enviar nada.
    lot, volume_note = normalize_volume(lot, symbol_info)
    if lot <= 0:
        return {
            "kind": "open",
            "symbol": symbol,
            "direction": "buy" if direction == 1 else "sell",
            "success": False,
            "error": "Volumen calculado no válido",
            "volume_note": volume_note
        }

    sl, tp, stops_note = adjust_stops(direction, price, sl, tp, symbol_info, tick)

    allowed_modes = get_allowed_filling_modes(symbol_info)
    filling_mode = choose_filling_mode(symbol_info, allowed_modes)
    request_comment = (order_comment or "").strip() or _DEFAULT_OPEN_COMMENT

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": magic_number,
        "comment": request_comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode,
    }
    
    result, used_mode, tried_modes, last_error = order_send_with_filling_retry(request, symbol_info)
    success = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
    used_comment = str(request.get("comment") or request_comment)

    result_info = {
        "kind": "open",
        "symbol": symbol,
        "direction": "buy" if direction == 1 else "sell",
        "price": price,
        "volume": lot,
        "sl": sl,
        "tp": tp,
        "success": success,
        "ticket": getattr(result, "order", None),
        "retcode": getattr(result, "retcode", None),
        "comment": getattr(result, "comment", None),
        "mt5_last_error": last_error,
        "order_comment": request_comment,
        "used_order_comment": used_comment,
        "filling_mode": used_mode,
        "tried_fillings": tried_modes,
        "volume_note": volume_note
    }

    return result_info


def apply_signal(
    symbol: str,
    signal: str,
    lot: float,
    sl_points: float,
    tp_points: float,
    magic_number: int,
    strategy_key: str = "",
    strategy_label: str = "",
    signal_reason: str = "",
):
    # traduce la senal (buy/sell/none) en acciones reales de trading.
    """
    Aplica una señal de trading: abre o cierra posiciones según corresponda.
    
    Args:
        symbol: Símbolo a operar.
        signal: "buy", "sell" o "none".
        lot: Tamaño de la posición en lotes.
        sl_points: Stop Loss en puntos.
        tp_points: Take Profit en puntos.
        magic_number: Magic number de las órdenes.
        strategy_key: Clave de estrategia que originó la señal.
        strategy_label: Etiqueta de estrategia que originó la señal.
        signal_reason: Motivo textual resumido de la señal.
    """
    if signal == "none":
        return None

    current_direction = get_open_position_direction(symbol, magic_number)
    position_info = get_position_info(symbol, magic_number)
    signal_reason = str(signal_reason or "").strip()

    actions = []
    open_comment = build_trade_comment(
        strategy_key=strategy_key, signal_reason=signal_reason, action_kind="open"
    )
    close_comment = build_trade_comment(
        strategy_key=strategy_key, signal_reason=signal_reason, action_kind="close"
    )
    
    if signal == "buy":
        if current_direction == 0:
            actions = [_send_order(symbol, 1, lot, sl_points, tp_points, magic_number, order_comment=open_comment)]
        elif current_direction == -1:
            actions = []
            actions.extend(_close_position(symbol, magic_number, order_comment=close_comment) or [])
            actions.append(_send_order(symbol, 1, lot, sl_points, tp_points, magic_number, order_comment=open_comment))
        else:
            actions = []

    elif signal == "sell":
        if current_direction == 0:
            actions = [_send_order(symbol, -1, lot, sl_points, tp_points, magic_number, order_comment=open_comment)]
        elif current_direction == 1:
            actions = []
            actions.extend(_close_position(symbol, magic_number, order_comment=close_comment) or [])
            actions.append(_send_order(symbol, -1, lot, sl_points, tp_points, magic_number, order_comment=open_comment))
        else:
            actions = []

    actions = [a for a in actions if a] if isinstance(actions, list) else []
    if actions:
        if any(isinstance(a, dict) and a.get("success") is True for a in actions):
            return {
            "timestamp": datetime.now(),
            "symbol": symbol,
            "signal": signal,
            "strategy": strategy_key,
            "strategy_label": strategy_label,
            "signal_reason": signal_reason,
            "actions": actions
        }

    return None


def calculate_dynamic_lot(
    atr_value: float,
    volume_ratio: float,
    instrument_info: InstrumentInfo,
    balance: float,
) -> float:
    # calcula el lot dinamico basado en riesgo fijo fraccional. Retorna lot sin normalizar; el caller debe pasar por normalize_volume().
    if atr_value <= 0 or volume_ratio <= 0 or balance <= 0:
        return 0.0

    tick_size = instrument_info.tick_size
    tick_value = instrument_info.tick_value
    if tick_size <= 0 or tick_value <= 0:
        return 0.0

    target_risk_pct = min(volume_ratio * 0.005, 0.01)
    risk_money = target_risk_pct * balance
    risk_per_lot = atr_value * (tick_value / tick_size)
    if risk_per_lot <= 0:
        return 0.0

    return risk_money / risk_per_lot


def check_aggregate_risk(
    new_lot: float,
    atr_value: float,
    balance: float,
    open_positions: list,
    instrument_info: InstrumentInfo,
) -> tuple:
    # verifica que el riesgo agregado (posiciones actuales + nueva entrada) no supere el 3% del balance.
    AGGREGATE_RISK_LIMIT = 0.03

    if balance <= 0:
        return (False, 0.0)

    tick_size = instrument_info.tick_size
    tick_value = instrument_info.tick_value
    if tick_size <= 0 or tick_value <= 0:
        return (False, 0.0)

    value_per_price_unit_per_lot = tick_value / tick_size

    existing_risk_money = 0.0
    for pos in open_positions:
        if pos["type"] != "BUY":
            continue
        sl = pos["sl"]
        if sl <= 0:
            continue
        price_open = pos["price_open"]
        distance = price_open - sl
        if distance <= 0:
            continue
        existing_risk_money += pos["volume"] * distance * value_per_price_unit_per_lot

    new_entry_risk = new_lot * atr_value * value_per_price_unit_per_lot
    total_risk_money = existing_risk_money + new_entry_risk
    aggregate_risk_pct = total_risk_money / balance

    allowed = aggregate_risk_pct <= AGGREGATE_RISK_LIMIT
    return (allowed, aggregate_risk_pct)


def apply_pyramid_signal(
    symbol: str,
    magic_number: int,
    atr_value: float,
    lot: float,
    strategy_key: str = "",
    strategy_label: str = "",
    signal_reason: str = "",
    balance: float = None,
):
    # abre una entrada inicial o piramiada solo-largo, con SL/TP calculados desde el ATR.
    if atr_value <= 0:
        return None

    if balance is None:
        account = mt5.account_info()
        if account is None:
            return None
        balance = account.balance
    if balance <= 0:
        return None

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    ask = tick.ask
    if ask <= 0:
        return None

    positions = get_all_positions(symbol, magic_number)

    sl_price = ask - (1.0 * atr_value)
    tp_price = ask + (2.0 * atr_value)

    open_comment = build_trade_comment(
        strategy_key=strategy_key,
        signal_reason=signal_reason,
        action_kind="open",
    )

    if len(positions) == 0:
        allowed, aggregate_risk_pct = check_aggregate_risk(
            symbol, lot, atr_value, balance, positions
        )
        if not allowed:
            return None

        result = _send_order(
            symbol, 1, lot, 0, 0, magic_number,
            order_comment=open_comment,
            sl_price=sl_price,
            tp_price=tp_price,
        )
        actions = [result] if result else []
    else:
        most_recent = positions[-1]

        if most_recent["type"] != "BUY":
            return None

        last_entry_price = most_recent["price_open"]
        pyramid_threshold = last_entry_price + (0.5 * atr_value)

        if ask < pyramid_threshold:
            return None

        allowed, aggregate_risk_pct = check_aggregate_risk(
            symbol, lot, atr_value, balance, positions
        )
        if not allowed:
            return None

        result = _send_order(
            symbol, 1, lot, 0, 0, magic_number,
            order_comment=open_comment,
            sl_price=sl_price,
            tp_price=tp_price,
        )
        actions = [result] if result else []

    actions = [a for a in actions if a]
    if not actions:
        return None
    if not any(isinstance(a, dict) and a.get("success") is True for a in actions):
        return None

    return {
        "timestamp":      datetime.now(),
        "symbol":         symbol,
        "signal":         "buy",
        "strategy":       strategy_key,
        "strategy_label": strategy_label,
        "signal_reason":  signal_reason,
        "pyramid":        True,
        "actions":        actions,
    }
