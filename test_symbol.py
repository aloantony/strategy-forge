"""
Script para probar si un símbolo funciona correctamente.
"""

import MetaTrader5 as mt5

def test_symbol(symbol_name):
    """Prueba si un símbolo está disponible y funciona."""
    if not mt5.initialize():
        print("Error al inicializar MT5")
        return False
    
    print(f"Probando simbolo: {symbol_name}")
    print("-"*60)
    
    # Intentar obtener información del símbolo
    symbol_info = mt5.symbol_info(symbol_name)
    
    if symbol_info is None:
        print(f"[ERROR] Simbolo '{symbol_name}' no encontrado")
        
        # Intentar con prefijo #
        alt_name = f"#{symbol_name}"
        print(f"\nIntentando con prefijo: {alt_name}")
        symbol_info = mt5.symbol_info(alt_name)
        
        if symbol_info is None:
            print(f"[ERROR] Tampoco funciona con prefijo")
            mt5.shutdown()
            return False
        else:
            symbol_name = alt_name
            print(f"[OK] Funciona con prefijo!")
    
    print(f"[OK] Simbolo encontrado: {symbol_name}")
    print(f"   Descripcion: {symbol_info.description}")
    print(f"   Trading permitido: {'SI' if symbol_info.trade_mode else 'NO'}")
    print(f"   Spread: {symbol_info.spread}")
    
    # Intentar obtener datos
    rates = mt5.copy_rates_from_pos(symbol_name, mt5.TIMEFRAME_M1, 0, 10)
    if rates is None or len(rates) == 0:
        print(f"[ERROR] No se pudieron obtener datos")
        mt5.shutdown()
        return False
    
    print(f"[OK] Datos obtenidos: {len(rates)} velas")
    print(f"   Ultimo precio: {rates[-1]['close']:.2f}")
    
    mt5.shutdown()
    return True

if __name__ == "__main__":
    # Probar ambos nombres posibles
    test_symbol("Germany40")
    print("\n" + "="*60 + "\n")
    test_symbol("#Germany40")






