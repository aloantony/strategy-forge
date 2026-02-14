"""
Gestión de conexión con MetaTrader 5.
"""

import MetaTrader5 as mt5
import config


def initialize_mt5():
    # esta funcion sirve para initialize mt5.
    """
    Inicializa la conexión con MetaTrader 5.
    
    Returns:
        bool: True si la inicialización fue exitosa, False en caso contrario.
    
    Raises:
        Exception: Si hay un error crítico durante la inicialización.
    """
    if not mt5.initialize():
        error = mt5.last_error()
        raise Exception(f"Error al inicializar MT5: {error}")
    
    account_info = mt5.account_info()
    if account_info is None:
        mt5.shutdown()
        raise Exception("No se pudo obtener información de la cuenta")
    
    print(f"MT5 inicializado correctamente")
    print(f"Login: {account_info.login}")
    print(f"Servidor: {account_info.server}")
    print(f"Balance: {account_info.balance}")
    
    return True


def check_symbol(symbol: str):
    # esta funcion sirve para comprobar simbolo.
    """
    Verifica que el símbolo existe y está disponible.
    
    Args:
        symbol: Símbolo a verificar.
    
    Returns:
        bool: True si el símbolo es válido, False en caso contrario.
    
    Raises:
        Exception: Si el símbolo no existe o no está disponible.
    """
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        raise Exception(f"Símbolo {symbol} no encontrado")
    
    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            raise Exception(f"No se pudo seleccionar el símbolo {symbol}")
    
    print(f"Símbolo {symbol} verificado correctamente")
    return True


