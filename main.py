"""
Bot de trading principal para MetaTrader 5.
"""

import MetaTrader5 as mt5
import time
import importlib
import pandas as pd
from datetime import datetime
import config
import mt5_connection
import data_feed
from strategies import strategy_baseline
import trading


def print_market_status(df, signal):
    # Para peques: aqui imprimimos un "resumen del partido" para entender que vio el bot.
    """
    Imprime el estado actual del mercado y la estrategia.
    """
    if len(df) < 2:
        return
    
    # La ultima vela puede seguir moviendose; por eso usamos la penultima (cerrada) para decidir.
    last_idx = len(df) - 1
    last_closed_idx = len(df) - 2
    
    last_candle = df.iloc[last_idx]
    last_closed = df.iloc[last_closed_idx]
    
    print("\n" + "="*80)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Análisis del mercado")
    print("="*80)
    
    # Le mostramos al usuario la vela cerrada, que es la que ya no cambia.
    print(f"\n[VELA] ULTIMA VELA CERRADA:")
    print(f"   Time: {last_closed['time']}")
    print(f"   OHLC: O={last_closed['open']:.2f} H={last_closed['high']:.2f} "
          f"L={last_closed['low']:.2f} C={last_closed['close']:.2f}")
    
    # Estos numeros salen de los indicadores y ayudan a decidir BUY/SELL.
    print(f"\n[CALC] VALORES CALCULADOS (Source: {config.SOURCE_MODE}):")
    print(f"   H_Set: {last_closed['h_set']:.2f}")
    print(f"   L_Set: {last_closed['l_set']:.2f}")
    print(f"   Average: {last_closed['average']:.2f}")
    print(f"   Upper: {last_closed['upper']:.2f}")
    print(f"   Lower: {last_closed['lower']:.2f}")
    if not pd.isna(last_closed.get('atr', None)):
        print(f"   ATR: {last_closed['atr']:.2f}")
    
    # Dir_1 dice "direccion" de la estrategia: 1 alcista, -1 bajista, 0 neutral.
    dir1_prev = df.iloc[last_closed_idx - 1]['dir1'] if last_closed_idx > 0 else 0
    dir1_current = last_closed['dir1']
    dir1_str = "[+] ALCISTA" if dir1_current == 1 else "[-] BAJISTA" if dir1_current == -1 else "[0] NEUTRAL"
    print(f"\n[DIR1] ESTADO DE DIR_1:")
    print(f"   Anterior: {dir1_prev}")
    print(f"   Actual: {dir1_current} {dir1_str}")
    
    # Aqui se imprimen comparaciones simples para ver por que la estrategia cambia de direccion.
    print(f"\n[COND] CONDICIONES:")
    print(f"   L_Set > Upper? {last_closed['l_set']:.2f} > {last_closed['upper']:.2f} = {last_closed['l_set'] > last_closed['upper']}")
    print(f"   H_Set < Lower? {last_closed['h_set']:.2f} < {last_closed['lower']:.2f} = {last_closed['h_set'] < last_closed['lower']}")
    
    # Up_Sig y Dn_Sig son "luces" que indican si aparecio una senal nueva.
    print(f"\n[SIG] SENALES:")
    print(f"   Up_Sig: {last_closed['up_sig']}")
    print(f"   Dn_Sig: {last_closed['dn_sig']}")
    print(f"   Senal detectada: {signal.upper() if signal != 'none' else 'NINGUNA'}")
    
    # Tambien mostramos si hay una operacion abierta ahora mismo.
    position_dir = trading.get_open_position_direction(config.SYMBOL, config.MAGIC_NUMBER)
    position_info = trading.get_position_info(config.SYMBOL, config.MAGIC_NUMBER)
    position_str = "[+] BUY" if position_dir == 1 else "[-] SELL" if position_dir == -1 else "[0] SIN POSICION"
    print(f"\n[POS] POSICION ACTUAL: {position_str}")
    if position_info:
        print(f"   Ticket: {position_info['ticket']}")
        print(f"   Precio apertura: {position_info['price_open']:.2f}")
        print(f"   Precio actual: {position_info['price_current']:.2f}")
        print(f"   Volumen: {position_info['volume']} lotes")
        print(f"   Profit: {position_info['profit']:.2f} {'(+)' if position_info['profit'] >= 0 else '(-)'}")
        if position_info['sl'] > 0:
            print(f"   SL: {position_info['sl']:.2f}")
        if position_info['tp'] > 0:
            print(f"   TP: {position_info['tp']:.2f}")
    
    print("="*80)


def run_bot_loop():
    # Para peques: este es el corazon del bot: mirar mercado, decidir, y actuar en bucle.
    """
    Bucle principal del bot de trading.
    """
    print("Iniciando bucle del bot...")
    
    try:
        while True:
            # Este ciclo se repite cada pocos segundos mientras el bot este encendido.
            try:
                # 1) Obtener DataFrame de velas
                df = data_feed.get_rates_df(
                    config.SYMBOL,
                    config.TIMEFRAME,
                    config.BARS_HISTORY
                )
                
                # 2) Añadir columnas de fuente y bandas
                df = data_feed.add_source_columns(df, config.SOURCE_MODE)
                df = data_feed.add_baseline_bands(
                    df,
                    config.MA_LENGTH,
                    config.ATR_LENGTH,
                    config.ATR_MULT
                )
                
                # 3) Calcular Dir_1 y señales
                df = strategy_baseline.compute_dir1_and_signals(
                    df,
                    config.ENABLE_SIGNALS
                )
                
                # 4) Obtener la señal de la estrategia (o forzar una senal en modo prueba)
                test_mode = getattr(config, "TEST_MODE", False)
                if test_mode:
                    signal = strategy_baseline.get_test_signal()
                    market_open, market_status_msg = True, "TEST_MODE (sin check)"
                else:
                    signal = strategy_baseline.get_last_signal(df, verbose=True)  # Logs detallados para demo
                    # 5) Antes de operar, comprobar si el mercado permite abrir/cerrar posiciones.
                    market_open, market_status_msg = trading.is_market_open(config.SYMBOL)
                
                # 6) Mostrar información detallada
                print_market_status(df, signal)
                
                # 7) Explicar en consola si se puede operar o no.
                if market_open:
                    print(f"\n[OK] ESTADO DEL MERCADO: {market_status_msg}")
                else:
                    print(f"\n[!!] ESTADO DEL MERCADO: {market_status_msg}")
                    print(f"   [WARN] El bot continuara analizando pero NO ejecutara operaciones")
                
                # 8) Solo operamos cuando hay senal real y el mercado esta abierto.
                if signal != "none":
                    if market_open:
                        print(f"\n>>> ACCION: Ejecutando senal {signal.upper()}")
                        trading.apply_signal(
                            config.SYMBOL,
                            signal,
                            config.LOT,
                            config.SL_POINTS,
                            config.TP_POINTS,
                            config.MAGIC_NUMBER
                        )
                    else:
                        print(f"\n[WAIT] Senal {signal.upper()} detectada pero MERCADO CERRADO - No se ejecutara")
                else:
                    print(f"\n[WAIT] Sin accion requerida")
                
                # 9) Esperar un rato para no saturar MT5 con consultas continuas.
                print(f"\n[...] Esperando {config.SLEEP_SECONDS} segundos hasta la siguiente iteracion...\n")
                time.sleep(config.SLEEP_SECONDS)
                
            except Exception as e:
                print(f"\n[ERROR] Error en el bucle: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(config.SLEEP_SECONDS)
                continue
                
    except KeyboardInterrupt:
        print("\n\nBot detenido por el usuario")
        mt5.shutdown()


def main():
    # Para peques: esta funcion sirve para arrancar todo el programa.
    """
    Función principal del bot.
    """
    # Primero elegimos el marco de tiempo (M1, M5, H1...) que usara la estrategia.
    config.TIMEFRAME = mt5.TIMEFRAME_M1
    strategy_timeframe = None
    timeframe_map = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1
    }
    try:
        module_ref = getattr(config, "STRATEGY_MODULE", "") or "strategies.strategy_baseline"
        module = importlib.import_module(module_ref)
        module = importlib.reload(module)
        if hasattr(module, "get_timeframe"):
            strategy_timeframe = module.get_timeframe()
        else:
            for key in ("TIMEFRAME", "STRATEGY_TIMEFRAME", "TIMEFRAME_STR"):
                if hasattr(module, key):
                    strategy_timeframe = getattr(module, key)
                    break
    except Exception as e:
        print(f"[WARN] No se pudo cargar timeframe de estrategia: {e}")
        strategy_timeframe = None

    if isinstance(strategy_timeframe, str):
        tf_value = timeframe_map.get(strategy_timeframe.strip().upper())
        if tf_value is not None:
            config.TIMEFRAME = tf_value
    elif isinstance(strategy_timeframe, int) and strategy_timeframe in timeframe_map.values():
        config.TIMEFRAME = strategy_timeframe
    
    # Conectamos con MetaTrader 5.
    try:
        mt5_connection.initialize_mt5()
    except Exception as e:
        print(f"Error al inicializar MT5: {e}")
        return
    
    # Comprobamos que el simbolo exista y este disponible.
    try:
        mt5_connection.check_symbol(config.SYMBOL)
    except Exception as e:
        print(f"Error al verificar símbolo: {e}")
        mt5.shutdown()
        return
    
    # Mostrar la configuracion ayuda a depurar si algo no cuadra.
    config.print_config()
    
    # Arranca el ciclo infinito del bot.
    run_bot_loop()
    
    # Si el bucle termina, cerramos la conexion de forma limpia.
    mt5.shutdown()


if __name__ == "__main__":
    main()
