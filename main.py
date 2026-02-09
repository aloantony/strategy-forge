"""
Bot de trading principal para MetaTrader 5.
"""

import MetaTrader5 as mt5
import time
import pandas as pd
from datetime import datetime
import config
import mt5_connection
import data_feed
from strategies import strategy_baseline
import trading


def print_market_status(df, signal):
    """
    Imprime el estado actual del mercado y la estrategia.
    """
    if len(df) < 2:
        return
    
    last_idx = len(df) - 1
    last_closed_idx = len(df) - 2
    
    last_candle = df.iloc[last_idx]
    last_closed = df.iloc[last_closed_idx]
    
    print("\n" + "="*80)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Análisis del mercado")
    print("="*80)
    
    # Información de la última vela cerrada
    print(f"\n[VELA] ULTIMA VELA CERRADA:")
    print(f"   Time: {last_closed['time']}")
    print(f"   OHLC: O={last_closed['open']:.2f} H={last_closed['high']:.2f} "
          f"L={last_closed['low']:.2f} C={last_closed['close']:.2f}")
    
    # Valores calculados
    print(f"\n[CALC] VALORES CALCULADOS (Source: {config.SOURCE_MODE}):")
    print(f"   H_Set: {last_closed['h_set']:.2f}")
    print(f"   L_Set: {last_closed['l_set']:.2f}")
    print(f"   Average: {last_closed['average']:.2f}")
    print(f"   Upper: {last_closed['upper']:.2f}")
    print(f"   Lower: {last_closed['lower']:.2f}")
    if not pd.isna(last_closed.get('atr', None)):
        print(f"   ATR: {last_closed['atr']:.2f}")
    
    # Estado de Dir_1
    dir1_prev = df.iloc[last_closed_idx - 1]['dir1'] if last_closed_idx > 0 else 0
    dir1_current = last_closed['dir1']
    dir1_str = "[+] ALCISTA" if dir1_current == 1 else "[-] BAJISTA" if dir1_current == -1 else "[0] NEUTRAL"
    print(f"\n[DIR1] ESTADO DE DIR_1:")
    print(f"   Anterior: {dir1_prev}")
    print(f"   Actual: {dir1_current} {dir1_str}")
    
    # Condiciones de la estrategia
    print(f"\n[COND] CONDICIONES:")
    print(f"   L_Set > Upper? {last_closed['l_set']:.2f} > {last_closed['upper']:.2f} = {last_closed['l_set'] > last_closed['upper']}")
    print(f"   H_Set < Lower? {last_closed['h_set']:.2f} < {last_closed['lower']:.2f} = {last_closed['h_set'] < last_closed['lower']}")
    
    # Señales
    print(f"\n[SIG] SENALES:")
    print(f"   Up_Sig: {last_closed['up_sig']}")
    print(f"   Dn_Sig: {last_closed['dn_sig']}")
    print(f"   Senal detectada: {signal.upper() if signal != 'none' else 'NINGUNA'}")
    
    # Estado de posiciones
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
    """
    Bucle principal del bot de trading.
    """
    print("Iniciando bucle del bot...")
    
    try:
        while True:
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
                
                # 4) Obtener última señal (o forzar test)
                test_mode = getattr(config, "TEST_MODE", False)
                if test_mode:
                    signal = strategy_baseline.get_test_signal()
                    market_open, market_status_msg = True, "TEST_MODE (sin check)"
                else:
                    signal = strategy_baseline.get_last_signal(df, verbose=True)  # Logs detallados para demo
                    # 5) Verificar si el mercado está abierto
                    market_open, market_status_msg = trading.is_market_open(config.SYMBOL)
                
                # 6) Mostrar información detallada
                print_market_status(df, signal)
                
                # 7) Mostrar estado del mercado
                if market_open:
                    print(f"\n[OK] ESTADO DEL MERCADO: {market_status_msg}")
                else:
                    print(f"\n[!!] ESTADO DEL MERCADO: {market_status_msg}")
                    print(f"   [WARN] El bot continuara analizando pero NO ejecutara operaciones")
                
                # 8) Aplicar señal si existe Y el mercado está abierto
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
                
                # 7) Esperar antes de la siguiente iteración
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
    """
    Función principal del bot.
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
    
    # Imprimir configuración
    config.print_config()
    
    # Ejecutar bucle del bot
    run_bot_loop()
    
    # Cerrar conexión
    mt5.shutdown()


if __name__ == "__main__":
    main()
