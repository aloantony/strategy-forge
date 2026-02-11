"""
Gestión de órdenes y posiciones en MetaTrader 5.
"""

import MetaTrader5 as mt5
from datetime import datetime, timedelta
import math
import time
import config

_FILLING_NAME = {
    getattr(mt5, "ORDER_FILLING_FOK", 0): "FOK",
    getattr(mt5, "ORDER_FILLING_IOC", 1): "IOC",
    getattr(mt5, "ORDER_FILLING_RETURN", 2): "RETURN",
}

# Recordamos la ultima accion por simbolo para no operar demasiadas veces seguidas.
_last_action_ts = {}


def _get_timeframe_seconds(timeframe_value=None) -> int:
    # Para peques: convierte M1, M5, H1... en segundos para medir esperas.
    """Devuelve el intervalo minimo entre ejecuciones segun el timeframe."""
    timeframe_seconds = {
        mt5.TIMEFRAME_M1: 60,
        mt5.TIMEFRAME_M5: 5 * 60,
        mt5.TIMEFRAME_M15: 15 * 60,
        mt5.TIMEFRAME_M30: 30 * 60,
        mt5.TIMEFRAME_H1: 60 * 60,
        mt5.TIMEFRAME_H4: 4 * 60 * 60,
        mt5.TIMEFRAME_D1: 24 * 60 * 60
    }
    tf = timeframe_value if timeframe_value is not None else config.TIMEFRAME
    return int(timeframe_seconds.get(tf, 60))


def _should_throttle(symbol: str, magic_number: int, now_ts: float, min_interval: int = None):
    # Para peques: revisa si aun toca esperar antes de permitir otra operacion.
    key = (symbol, magic_number)
    last_ts = _last_action_ts.get(key)
    if last_ts is None:
        return False, 0
    if min_interval is None:
        min_interval = _get_timeframe_seconds()
    elapsed = now_ts - last_ts
    if elapsed < min_interval:
        return True, int(min_interval - elapsed)
    return False, 0


def get_allowed_filling_modes(symbol_info):
    # Para peques: pregunta que tipos de ejecucion de orden acepta este broker.
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
    # Para peques: crea un texto legible con los modos de llenado permitidos.
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
    # Para peques: elige el mejor modo de llenado para aumentar la probabilidad de exito.
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
    # Para peques: detecta si MT5 rechazo la orden por un modo de llenado no valido.
    """
    Detecta si el retcode/comentario indica filling mode no soportado.
    """
    invalid_fill_code = getattr(mt5, "TRADE_RETCODE_INVALID_FILL", None)
    if invalid_fill_code is not None and result.retcode == invalid_fill_code:
        return True

    comment = (getattr(result, "comment", "") or "").lower()
    return "unsupported filling mode" in comment or ("filling" in comment and "unsupported" in comment)


def order_send_with_filling_retry(request: dict, symbol_info):
    # Para peques: intenta enviar la orden probando varios modos hasta que uno funcione.
    """
    Envía una orden intentando automáticamente los modos de llenado permitidos.
    Devuelve (result, modo_usado, modos_intentados).
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

    for mode in modes_to_try:
        # Probamos uno por uno; si alguno funciona, paramos ahi.
        request["type_filling"] = mode
        last_mode = mode
        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return result, mode, modes_to_try
        if not _is_unsupported_filling(result):
            return result, mode, modes_to_try

    return result, last_mode, modes_to_try


def normalize_volume(requested_volume: float, symbol_info):
    # Para peques: ajusta el volumen al minimo, maximo y paso permitidos por el simbolo.
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
    # Para peques: mueve SL/TP si estan demasiado cerca del precio actual.
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
    # Para peques: revisa si hay precios recientes y validos para poder operar.
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
    
    # Verificar si el último tick es reciente (menos de 5 minutos)
    # Si el tick es muy antiguo, probablemente el mercado está cerrado
    tick_time = datetime.fromtimestamp(tick.time)
    now = datetime.now()
    time_diff = (now - tick_time).total_seconds()
    
    # Si el tick tiene más de 5 minutos, considerar el mercado cerrado
    if time_diff > 300:  # 5 minutos
        return False, f"Mercado cerrado (último tick hace {int(time_diff/60)} minutos)"
    
    # Verificar si hay spread válido (si el spread es 0 o muy grande, puede estar cerrado)
    if tick.ask == 0 or tick.bid == 0:
        return False, "Precios no disponibles (mercado cerrado)"
    
    spread = tick.ask - tick.bid
    if spread <= 0:
        return False, "Spread inválido (mercado cerrado)"
    
    return True, "Mercado abierto"


def get_open_position_direction(symbol: str, magic_number: int) -> int:
    # Para peques: dice si ahora mismo tenemos BUY, SELL o nada en ese simbolo.
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
    # Para peques: devuelve detalles de la posicion abierta (ticket, precio, profit, etc.).
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


def close_position(symbol: str, magic_number: int):
    # Para peques: cierra la posicion abierta del bot para ese simbolo.
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
        print(f"   [ERROR] No se pudo obtener información del símbolo {symbol}")
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
    print(f"   [FILL] {describe_fillings(symbol_info, allowed_modes)}")
    filling_mode = choose_filling_mode(symbol_info, allowed_modes)

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
                "comment": "Cierre automático",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }

            result, used_mode, tried_modes = order_send_with_filling_retry(request, symbol_info)
            success = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE

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
                "filling_mode": used_mode,
                "tried_fillings": tried_modes
            }
            results.append(result_info)

            if not success:
                print(f"   [ERROR] Error al cerrar posicion: {result.retcode} - {result.comment}")
                if _is_unsupported_filling(result) and len(tried_modes) > 1:
                    print(f"   [INFO] Modos intentados: {tried_modes}")
            else:
                print(f"   [OK] Posicion cerrada exitosamente (filling {used_mode}):")
                print(f"      Ticket: {position.ticket}")
                print(f"      Profit final: {position.profit:.2f}")

    return results


def send_order(symbol: str, direction: int, lot: float, sl_points: float, tp_points: float, magic_number: int):
    # Para peques: abre una operacion nueva (compra o venta) con SL/TP.
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
        print(f"Error: No se pudo obtener información del símbolo {symbol}")
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
        sl = price - (sl_points * point) if sl_points > 0 else 0
        tp = price + (tp_points * point) if tp_points > 0 else 0
        order_type = mt5.ORDER_TYPE_BUY
    elif direction == -1:  # SELL
        # En venta se entra al BID.
        price = bid
        sl = price + (sl_points * point) if sl_points > 0 else 0
        tp = price - (tp_points * point) if tp_points > 0 else 0
        order_type = mt5.ORDER_TYPE_SELL
    else:
        print(f"Error: Dirección inválida: {direction}")
        return {
            "kind": "open",
            "symbol": symbol,
            "direction": "unknown",
            "success": False,
            "error": f"Dirección inválida: {direction}"
        }

    # Ajustamos parametros para que cumplan reglas del broker antes de enviar nada.
    lot, volume_note = normalize_volume(lot, symbol_info)
    if volume_note:
        print(f"   [WARN] {volume_note}")
    if lot <= 0:
        print("   [ERROR] Volumen calculado no valido. Orden cancelada.")
        return {
            "kind": "open",
            "symbol": symbol,
            "direction": "buy" if direction == 1 else "sell",
            "success": False,
            "error": "Volumen calculado no válido",
            "volume_note": volume_note
        }

    sl, tp, stops_note = adjust_stops(direction, price, sl, tp, symbol_info, tick)
    if stops_note:
        print(f"   [WARN] {stops_note}")

    allowed_modes = get_allowed_filling_modes(symbol_info)
    print(f"   [FILL] {describe_fillings(symbol_info, allowed_modes)}")
    filling_mode = choose_filling_mode(symbol_info, allowed_modes)

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
        "comment": "Bot trading",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode,
    }
    
    result, used_mode, tried_modes = order_send_with_filling_retry(request, symbol_info)
    success = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE

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
        "filling_mode": used_mode,
        "tried_fillings": tried_modes,
        "volume_note": volume_note
    }

    if not success:
        print(f"   [ERROR] Error al enviar orden: {result.retcode} - {result.comment}")
        if _is_unsupported_filling(result) and len(tried_modes) > 1:
            print(f"   [INFO] Modos intentados: {tried_modes}")
    else:
        print(f"   [OK] Orden ejecutada exitosamente (filling {used_mode}):")
        print(f"      Ticket: {result.order}")
        print(f"      Precio: {price:.2f}")
        print(f"      Volumen: {lot} lotes")
        print(f"      SL: {sl:.2f}" if sl > 0 else "      SL: No establecido")
        print(f"      TP: {tp:.2f}" if tp > 0 else "      TP: No establecido")

    return result_info


def apply_signal(
    symbol: str,
    signal: str,
    lot: float,
    sl_points: float,
    tp_points: float,
    magic_number: int,
    timeframe_value: int = None
):
    # Para peques: traduce la senal (buy/sell/none) en acciones reales de trading.
    """
    Aplica una señal de trading: abre o cierra posiciones según corresponda.
    
    Args:
        symbol: Símbolo a operar.
        signal: "buy", "sell" o "none".
        lot: Tamaño de la posición en lotes.
        sl_points: Stop Loss en puntos.
        tp_points: Take Profit en puntos.
        magic_number: Magic number de las órdenes.
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    print("\n" + "!"*60)
    print(f"[{timestamp}] >>> EJECUTANDO SENAL: {signal.upper()} <<<")
    print("!"*60)
    
    if signal == "none":
        # "none" significa mirar y esperar, sin tocar posiciones.
        print(f"   [SKIP] Senal 'none' - No se requiere accion")
        return None

    now_ts = time.time()
    min_interval = _get_timeframe_seconds(timeframe_value)
    throttled, remaining = _should_throttle(symbol, magic_number, now_ts, min_interval=min_interval)
    if throttled:
        print(f"   [SKIP] Esperando cooldown ({remaining}s) para nueva ejecucion.")
        return None
    
    # Miramos en que estado estamos antes de decidir (sin posicion, buy o sell).
    current_direction = get_open_position_direction(symbol, magic_number)
    position_info = get_position_info(symbol, magic_number)
    
    print(f"   [SYMBOL] Simbolo: {symbol}")
    print(f"   [SIGNAL] Senal recibida: {signal.upper()}")
    print(f"   [POS] Posicion actual: {'BUY' if current_direction == 1 else 'SELL' if current_direction == -1 else 'NINGUNA'}")
    print(f"   [LOT] Lote: {lot}")
    print(f"   [SL] Stop Loss: {sl_points} puntos")
    print(f"   [TP] Take Profit: {tp_points} puntos")
    print()
    
    actions = []
    
    if signal == "buy":
        if current_direction == 0:
            # No hay posición, abrir largo
            print(f"   >>> ACCION: Abriendo nueva posicion BUY...")
            actions = [send_order(symbol, 1, lot, sl_points, tp_points, magic_number)]
        elif current_direction == -1:
            # Hay corto, cerrar y abrir largo
            print(f"   [CLOSE] Cerrando SELL (Ticket: {position_info['ticket']}, Profit: {position_info['profit']:.2f})")
            print(f"   >>> ACCION: Abriendo nueva posicion BUY...")
            actions = []
            actions.extend(close_position(symbol, magic_number) or [])
            actions.append(send_order(symbol, 1, lot, sl_points, tp_points, magic_number))
        else:
            print(f"   [SKIP] Ya existe posicion BUY (Ticket: {position_info['ticket']}). No se requiere accion.")
            actions = []
    
    elif signal == "sell":
        if current_direction == 0:
            # No hay posición, abrir corto
            print(f"   >>> ACCION: Abriendo nueva posicion SELL...")
            actions = [send_order(symbol, -1, lot, sl_points, tp_points, magic_number)]
        elif current_direction == 1:
            # Hay largo, cerrar y abrir corto
            print(f"   [CLOSE] Cerrando BUY (Ticket: {position_info['ticket']}, Profit: {position_info['profit']:.2f})")
            print(f"   >>> ACCION: Abriendo nueva posicion SELL...")
            actions = []
            actions.extend(close_position(symbol, magic_number) or [])
            actions.append(send_order(symbol, -1, lot, sl_points, tp_points, magic_number))
        else:
            print(f"   [SKIP] Ya existe posicion SELL (Ticket: {position_info['ticket']}). No se requiere accion.")
            actions = []
    
    print("!"*60 + "\n")

    actions = [a for a in actions if a] if isinstance(actions, list) else []
    if actions:
        if any(isinstance(a, dict) and a.get("success") is True for a in actions):
            _last_action_ts[(symbol, magic_number)] = time.time()
        return {
            "timestamp": datetime.now(),
            "symbol": symbol,
            "signal": signal,
            "actions": actions
        }

    return None
