"""
Script para ejecutar backtesting de la estrategia.
"""

import MetaTrader5 as mt5
from datetime import datetime, timedelta
import config
import mt5_connection
import backtest


def main():
    """
    Función principal para ejecutar el backtesting.
    """
    # Establecer timeframe
    config.TIMEFRAME = mt5.TIMEFRAME_M1
    
    # Inicializar MT5
    try:
        mt5_connection.initialize_mt5()
    except Exception as e:
        print(f"Error al inicializar MT5: {e}")
        return
    
    # Verificar símbolo
    try:
        mt5_connection.check_symbol(config.SYMBOL)
    except Exception as e:
        print(f"Error al verificar símbolo: {e}")
        mt5.shutdown()
        return
    
    # Configurar período de backtesting
    # Por defecto: últimos 30 días
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    # Puedes modificar estas fechas según necesites:
    # start_date = datetime(2024, 1, 1)
    # end_date = datetime(2024, 1, 31)
    
    print("\n" + "="*80)
    print("CONFIGURACIÓN DEL BACKTEST")
    print("="*80)
    config.print_config()
    print(f"\nPeríodo de backtesting:")
    print(f"   Desde: {start_date.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Hasta: {end_date.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    # Ejecutar backtest
    try:
        engine = backtest.run_backtest(
            config.SYMBOL,
            config.TIMEFRAME,
            start_date,
            end_date
        )
        
        # Opcional: mostrar algunas operaciones
        results = engine.get_results()
        if 'positions' in results and len(results['positions']) > 0:
            print("\n📋 PRIMERAS 10 OPERACIONES:")
            print("-" * 80)
            for i, pos in enumerate(results['positions'][:10], 1):
                direction_str = "BUY" if pos['direction'] == 1 else "SELL"
                profit_str = f"+{pos['profit']:.2f}" if pos['profit'] >= 0 else f"{pos['profit']:.2f}"
                print(f"{i}. {direction_str} | Entrada: {pos['entry_price']:.2f} | "
                      f"Salida: {pos['exit_price']:.2f} | Profit: {profit_str} | "
                      f"Razón: {pos['reason']}")
            if len(results['positions']) > 10:
                print(f"... y {len(results['positions']) - 10} operaciones más")
            print("-" * 80)
        
    except Exception as e:
        print(f"\n❌ Error durante el backtesting: {e}")
        import traceback
        traceback.print_exc()
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()

