"""
Script para encontrar símbolos disponibles en MetaTrader 5.
Útil para encontrar el nombre correcto del DAX en diferentes brokers.
"""

import MetaTrader5 as mt5

def find_dax_symbols():
    # esta funcion sirve para find dax symbols.
    """Busca símbolos relacionados con DAX."""
    if not mt5.initialize():
        print("Error al inicializar MT5")
        return
    
    print("="*60)
    print("BUSCANDO SIMBOLOS DEL DAX EN FxPro")
    print("="*60)
    
    # Obtener todos los símbolos
    symbols = mt5.symbols_get()
    
    if symbols is None:
        print("No se pudieron obtener símbolos")
        mt5.shutdown()
        return
    
    # Buscar símbolos relacionados con DAX
    dax_keywords = ['DAX', 'DE40', 'DE30', 'GER', 'GERMANY', 'GERMAN']
    found_symbols = []
    
    print(f"\nTotal de símbolos disponibles: {len(symbols)}\n")
    print("Símbolos relacionados con DAX:")
    print("-"*60)
    
    for symbol in symbols:
        symbol_name = symbol.name.upper()
        for keyword in dax_keywords:
            if keyword in symbol_name:
                found_symbols.append(symbol)
                print(f"  [+] {symbol.name:20} | {symbol.description}")
                break
    
    if not found_symbols:
        print("  No se encontraron símbolos con palabras clave comunes.")
        print("\nMostrando primeros 50 símbolos disponibles:")
        print("-"*60)
        for i, symbol in enumerate(symbols[:50]):
            print(f"  {symbol.name:20} | {symbol.description}")
        print(f"\n... y {len(symbols) - 50} más")
    else:
        print(f"\n[OK] Se encontraron {len(found_symbols)} simbolos relacionados con DAX")
        print("\nRecomendación: Usa el primer símbolo encontrado o verifica en MT5")
    
    mt5.shutdown()

if __name__ == "__main__":
    find_dax_symbols()


