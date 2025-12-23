"""
Gestión de órdenes y posiciones en MetaTrader 5.
"""

import MetaTrader5 as mt5
from datetime import datetime, timedelta
import config


def is_market_open(symbol: str):
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
    """
    Cierra la posición abierta del símbolo con el magic number especificado.
    
    Args:
        symbol: Símbolo de la posición a cerrar.
        magic_number: Magic number de la orden.
    """
    positions = mt5.positions_get(symbol=symbol)
    
    if positions is None or len(positions) == 0:
        return
    
    for position in positions:
        if position.magic == magic_number:
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
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"   [ERROR] Error al cerrar posicion: {result.retcode} - {result.comment}")
            else:
                print(f"   [OK] Posicion cerrada exitosamente:")
                print(f"      Ticket: {position.ticket}")
                print(f"      Profit final: {position.profit:.2f}")


def send_order(symbol: str, direction: int, lot: float, sl_points: float, tp_points: float, magic_number: int):
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
        return
    
    if not symbol_info.visible:
        mt5.symbol_select(symbol, True)
    
    point = symbol_info.point
    ask = mt5.symbol_info_tick(symbol).ask
    bid = mt5.symbol_info_tick(symbol).bid
    
    if direction == 1:  # BUY
        price = ask
        sl = price - (sl_points * point) if sl_points > 0 else 0
        tp = price + (tp_points * point) if tp_points > 0 else 0
        order_type = mt5.ORDER_TYPE_BUY
    elif direction == -1:  # SELL
        price = bid
        sl = price + (sl_points * point) if sl_points > 0 else 0
        tp = price - (tp_points * point) if tp_points > 0 else 0
        order_type = mt5.ORDER_TYPE_SELL
    else:
        print(f"Error: Dirección inválida: {direction}")
        return
    
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
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"   [ERROR] Error al enviar orden: {result.retcode} - {result.comment}")
    else:
        print(f"   [OK] Orden ejecutada exitosamente:")
        print(f"      Ticket: {result.order}")
        print(f"      Precio: {price:.2f}")
        print(f"      Volumen: {lot} lotes")
        print(f"      SL: {sl:.2f}" if sl > 0 else "      SL: No establecido")
        print(f"      TP: {tp:.2f}" if tp > 0 else "      TP: No establecido")


def apply_signal(symbol: str, signal: str, lot: float, sl_points: float, tp_points: float, magic_number: int):
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
        print(f"   [SKIP] Senal 'none' - No se requiere accion")
        return
    
    current_direction = get_open_position_direction(symbol, magic_number)
    position_info = get_position_info(symbol, magic_number)
    
    print(f"   [SYMBOL] Simbolo: {symbol}")
    print(f"   [SIGNAL] Senal recibida: {signal.upper()}")
    print(f"   [POS] Posicion actual: {'BUY' if current_direction == 1 else 'SELL' if current_direction == -1 else 'NINGUNA'}")
    print(f"   [LOT] Lote: {lot}")
    print(f"   [SL] Stop Loss: {sl_points} puntos")
    print(f"   [TP] Take Profit: {tp_points} puntos")
    print()
    
    if signal == "buy":
        if current_direction == 0:
            # No hay posición, abrir largo
            print(f"   >>> ACCION: Abriendo nueva posicion BUY...")
            send_order(symbol, 1, lot, sl_points, tp_points, magic_number)
        elif current_direction == -1:
            # Hay corto, cerrar y abrir largo
            print(f"   [CLOSE] Cerrando SELL (Ticket: {position_info['ticket']}, Profit: {position_info['profit']:.2f})")
            print(f"   >>> ACCION: Abriendo nueva posicion BUY...")
            close_position(symbol, magic_number)
            send_order(symbol, 1, lot, sl_points, tp_points, magic_number)
        else:
            print(f"   [SKIP] Ya existe posicion BUY (Ticket: {position_info['ticket']}). No se requiere accion.")
    
    elif signal == "sell":
        if current_direction == 0:
            # No hay posición, abrir corto
            print(f"   >>> ACCION: Abriendo nueva posicion SELL...")
            send_order(symbol, -1, lot, sl_points, tp_points, magic_number)
        elif current_direction == 1:
            # Hay largo, cerrar y abrir corto
            print(f"   [CLOSE] Cerrando BUY (Ticket: {position_info['ticket']}, Profit: {position_info['profit']:.2f})")
            print(f"   >>> ACCION: Abriendo nueva posicion SELL...")
            close_position(symbol, magic_number)
            send_order(symbol, -1, lot, sl_points, tp_points, magic_number)
        else:
            print(f"   [SKIP] Ya existe posicion SELL (Ticket: {position_info['ticket']}). No se requiere accion.")
    
    print("!"*60 + "\n")

