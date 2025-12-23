"""
Interfaz gráfica del Bot de Trading usando Lightweight Charts (TradingView).
Gráficos profesionales, fluidos y con el mismo aspecto que TradingView.
"""

from lightweight_charts import Chart
import pandas as pd
import numpy as np
import MetaTrader5 as mt5
import threading
import time
import sys
import io
from datetime import datetime, timedelta

import config
import mt5_connection
import data_feed
import strategy_baseline
import trading

# Configurar stdout para UTF-8
try:
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except:
    pass


class TradingBotGUI:
    """
    Interfaz gráfica del bot de trading usando Lightweight Charts.
    """
    
    def __init__(self):
        # Estado del bot
        self.bot_running = False
        self.bot_thread = None
        self.stop_event = threading.Event()
        
        # Datos
        self.price_data = None
        self.view_period = "1D"
        self.current_timeframe = "M1"
        
        # Crear gráfico principal
        self.chart = Chart(toolbox=True)
        
        # Configurar apariencia
        self.chart.layout(
            background_color='#131722',
            text_color='#d1d4dc',
            font_size=12,
            font_family='Trebuchet MS'
        )
        
        self.chart.candle_style(
            up_color='#26a69a',
            down_color='#ef5350',
            wick_up_color='#26a69a',
            wick_down_color='#ef5350'
        )
        
        self.chart.volume_config(
            up_color='rgba(38, 166, 154, 0.5)',
            down_color='rgba(239, 83, 80, 0.5)'
        )
        
        self.chart.watermark(config.SYMBOL, color='rgba(180, 180, 200, 0.3)')
        
        self.chart.crosshair(
            mode='normal',
            vert_color='#758696',
            vert_style='dotted',
            horz_color='#758696',
            horz_style='dotted'
        )
        
        self.chart.legend(visible=True, font_size=12)
        
        # Crear líneas para indicadores (el ojo permite mostrar/ocultar cada línea)
        self.upper_line = self.chart.create_line(name='Upper', color='#ff9800', width=1)
        self.average_line = self.chart.create_line(name='Average', color='#2196f3', width=2)
        self.lower_line = self.chart.create_line(name='Lower', color='#ff9800', width=1)
        
        # Crear subchart para equity (curva de beneficios)
        self.equity_chart = self.chart.create_subchart(height=0.2, sync=True)
        self.equity_chart.layout(background_color='#131722', text_color='#d1d4dc')
        self.equity_line = self.equity_chart.create_line(name='Equity', color='#4caf50', width=2)
        
        # Configurar controles
        self.setup_topbar()
        
        # Nota: los hotkeys requieren un modificador (shift, alt, ctrl, meta)
        # Ejemplo: self.chart.hotkey('shift', 'S', self.start_bot)
        # Por ahora usamos los botones de la topbar
        
    def setup_topbar(self):
        """Configura la barra superior con controles."""
        # Texto de ayuda
        self.chart.topbar.textbox('help', 'Ojo=Mostrar/Ocultar linea | Scroll=Zoom | Arrastrar=Mover')
        
        # Separador visual
        self.chart.topbar.textbox('sep1', ' | ')
        
        # Switcher de timeframe
        self.chart.topbar.switcher(
            'timeframe',
            ('M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'),
            default='M1',
            func=self.on_timeframe_change
        )
        
        # Switcher de período
        self.chart.topbar.switcher(
            'period',
            ('1D', '5D', '1M', '6M', '1A', 'Todo'),
            default='1D',
            func=self.on_period_change
        )
        
        # Separador
        self.chart.topbar.textbox('sep2', ' | ')
        
        # Estado del bot
        self.chart.topbar.textbox('status_label', 'Estado:')
        self.chart.topbar.textbox('status', 'Detenido')
        
        # Separador
        self.chart.topbar.textbox('sep3', ' | ')
        
        # Botones con nombres descriptivos
        self.chart.topbar.button('start', 'Iniciar Bot', func=self.start_bot)
        self.chart.topbar.button('stop', 'Detener Bot', func=self.stop_bot)
        self.chart.topbar.button('refresh', 'Actualizar Datos', func=self.refresh_data)
    
    def log_message(self, message):
        """Registra un mensaje."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        try:
            print(f"[{timestamp}] {message}")
        except:
            pass
    
    def init_mt5(self):
        """Inicializa la conexión con MT5."""
        try:
            if config.TIMEFRAME is None:
                config.TIMEFRAME = mt5.TIMEFRAME_M1
            
            mt5_connection.initialize_mt5()
            mt5_connection.check_symbol(config.SYMBOL)
            
            timeframe_map = {
                mt5.TIMEFRAME_M1: "M1",
                mt5.TIMEFRAME_M5: "M5",
                mt5.TIMEFRAME_M15: "M15",
                mt5.TIMEFRAME_M30: "M30",
                mt5.TIMEFRAME_H1: "H1",
                mt5.TIMEFRAME_H4: "H4",
                mt5.TIMEFRAME_D1: "D1"
            }
            if config.TIMEFRAME in timeframe_map:
                self.current_timeframe = timeframe_map[config.TIMEFRAME]
            
            self.log_message("MT5 inicializado correctamente")
            return True
            
        except Exception as e:
            self.log_message(f"Error al inicializar MT5: {e}")
            return False
    
    def get_timeframe_minutes(self):
        """Obtiene los minutos del timeframe actual."""
        timeframe_minutes = {
            mt5.TIMEFRAME_M1: 1,
            mt5.TIMEFRAME_M5: 5,
            mt5.TIMEFRAME_M15: 15,
            mt5.TIMEFRAME_M30: 30,
            mt5.TIMEFRAME_H1: 60,
            mt5.TIMEFRAME_H4: 240,
            mt5.TIMEFRAME_D1: 1440
        }
        return timeframe_minutes.get(config.TIMEFRAME, 1)
    
    def get_period_bars(self, period_str, timeframe_minutes):
        """Calcula cuántas velas obtener según el período."""
        minutes_per_day = 24 * 60
        minutes_per_month = 30 * minutes_per_day
        minutes_per_year = 365 * minutes_per_day
        
        period_minutes = {
            "1D": 1 * minutes_per_day,
            "5D": 5 * minutes_per_day,
            "1M": 1 * minutes_per_month,
            "6M": 6 * minutes_per_month,
            "1A": 1 * minutes_per_year,
            "Todo": 10000 * timeframe_minutes
        }
        
        minutes = period_minutes.get(period_str, 1 * minutes_per_day)
        bars = minutes // timeframe_minutes
        return max(100, min(bars, 10000))
    
    def refresh_data(self, chart=None):
        """Actualiza los datos del gráfico."""
        def update_thread():
            try:
                timeframe_minutes = self.get_timeframe_minutes()
                bars_needed = self.get_period_bars(self.view_period, timeframe_minutes)
                
                df = data_feed.get_rates_df(config.SYMBOL, config.TIMEFRAME, bars_needed)
                df = data_feed.add_source_columns(df, config.SOURCE_MODE)
                df = data_feed.add_baseline_bands(
                    df, config.MA_LENGTH, config.ATR_LENGTH, config.ATR_MULT
                )
                df = strategy_baseline.compute_dir1_and_signals(df, config.ENABLE_SIGNALS)
                
                if len(df) < 2:
                    return
                
                self.price_data = df
                self.update_chart(df)
                self.update_equity_chart()
                
                self.log_message(f"Datos actualizados: {len(df)} velas")
                
            except Exception as e:
                self.log_message(f"Error al actualizar datos: {e}")
        
        threading.Thread(target=update_thread, daemon=True).start()
    
    def update_chart(self, df):
        """Actualiza el gráfico de velas."""
        try:
            # Preparar datos para Lightweight Charts
            chart_data = df[['time', 'open', 'high', 'low', 'close', 'tick_volume']].copy()
            chart_data = chart_data.rename(columns={'tick_volume': 'volume'})
            
            if not pd.api.types.is_datetime64_any_dtype(chart_data['time']):
                chart_data['time'] = pd.to_datetime(chart_data['time'])
            
            # Establecer datos de velas
            self.chart.set(chart_data)
            
            # Actualizar bandas - crear DataFrames con columnas 'time' y nombre que coincide con la línea
            if 'upper' in df.columns and not df['upper'].isna().all():
                upper_data = df[['time', 'upper']].dropna().copy()
                upper_data = upper_data.reset_index(drop=True)
                upper_data = upper_data.rename(columns={'upper': 'Upper'})
                if len(upper_data) > 0:
                    self.upper_line.set(upper_data)
            
            if 'average' in df.columns and not df['average'].isna().all():
                avg_data = df[['time', 'average']].dropna().copy()
                avg_data = avg_data.reset_index(drop=True)
                avg_data = avg_data.rename(columns={'average': 'Average'})
                if len(avg_data) > 0:
                    self.average_line.set(avg_data)
            
            if 'lower' in df.columns and not df['lower'].isna().all():
                lower_data = df[['time', 'lower']].dropna().copy()
                lower_data = lower_data.reset_index(drop=True)
                lower_data = lower_data.rename(columns={'lower': 'Lower'})
                if len(lower_data) > 0:
                    self.lower_line.set(lower_data)
            
            # Marcar señales (limitado para no sobrecargar)
            if 'up_sig' in df.columns and 'dn_sig' in df.columns:
                buy_signals = df[df['up_sig'] == True].tail(50)
                sell_signals = df[df['dn_sig'] == True].tail(50)
                
                for _, row in buy_signals.iterrows():
                    self.chart.marker(
                        time=row['time'],
                        position='below',
                        shape='arrow_up',
                        color='#26a69a',
                        text='BUY'
                    )
                
                for _, row in sell_signals.iterrows():
                    self.chart.marker(
                        time=row['time'],
                        position='above',
                        shape='arrow_down',
                        color='#ef5350',
                        text='SELL'
                    )
            
        except Exception as e:
            self.log_message(f"Error al actualizar grafico: {e}")
            import traceback
            traceback.print_exc()
    
    def update_equity_chart(self):
        """Actualiza el gráfico de equity."""
        try:
            start_date = datetime.now() - timedelta(days=30)
            positions = mt5.history_deals_get(start_date, datetime.now())
            
            if positions:
                filtered = [p for p in positions if hasattr(p, 'magic') and p.magic == config.MAGIC_NUMBER]
                
                if filtered:
                    equity_data = []
                    balance = 10000.0
                    
                    for deal in sorted(filtered, key=lambda x: x.time):
                        if deal.entry == mt5.DEAL_ENTRY_OUT:
                            balance += deal.profit
                            equity_data.append({
                                'time': datetime.fromtimestamp(deal.time),
                                'Equity': float(balance)
                            })
                    
                    if equity_data:
                        equity_df = pd.DataFrame(equity_data)
                        equity_df['time'] = pd.to_datetime(equity_df['time'])
                        equity_df = equity_df.reset_index(drop=True)
                        self.equity_line.set(equity_df)
                        return
            
            # Si no hay datos, mostrar línea base con el precio actual
            if self.price_data is not None and len(self.price_data) > 1:
                # Usar tiempo del precio de datos para la línea base
                first_time = self.price_data['time'].iloc[0]
                last_time = self.price_data['time'].iloc[-1]
                base_data = pd.DataFrame({
                    'time': [first_time, last_time],
                    'Equity': [10000.0, 10000.0]
                })
            else:
                now = datetime.now()
                base_data = pd.DataFrame({
                    'time': pd.to_datetime([now - timedelta(days=7), now]),
                    'Equity': [10000.0, 10000.0]
                })
            
            base_data = base_data.reset_index(drop=True)
            self.equity_line.set(base_data)
            
        except Exception as e:
            self.log_message(f"Error al actualizar equity: {e}")
            import traceback
            traceback.print_exc()
    
    def on_timeframe_change(self, chart):
        """Maneja el cambio de timeframe."""
        try:
            timeframe_str = chart.topbar['timeframe'].value
            self.current_timeframe = timeframe_str
            
            timeframe_map = {
                "M1": mt5.TIMEFRAME_M1,
                "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15,
                "M30": mt5.TIMEFRAME_M30,
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1
            }
            
            if timeframe_str in timeframe_map:
                config.TIMEFRAME = timeframe_map[timeframe_str]
                self.log_message(f"Timeframe cambiado a {timeframe_str}")
                self.refresh_data()
                
        except Exception as e:
            self.log_message(f"Error al cambiar timeframe: {e}")
    
    def on_period_change(self, chart):
        """Maneja el cambio de período."""
        try:
            period_str = chart.topbar['period'].value
            self.view_period = period_str
            self.log_message(f"Periodo cambiado a {period_str}")
            self.refresh_data()
            
        except Exception as e:
            self.log_message(f"Error al cambiar periodo: {e}")
    
    def start_bot(self, chart=None):
        """Inicia el bot."""
        if self.bot_running:
            return
        
        try:
            self.bot_running = True
            self.stop_event.clear()
            self.bot_thread = threading.Thread(target=self.bot_loop, daemon=True)
            self.bot_thread.start()
            
            self.chart.topbar['status'].set('Ejecutando')
            self.log_message("Bot iniciado")
            
        except Exception as e:
            self.log_message(f"Error al iniciar bot: {e}")
            self.bot_running = False
    
    def stop_bot(self, chart=None):
        """Detiene el bot."""
        if not self.bot_running:
            return
        
        self.bot_running = False
        self.stop_event.set()
        
        self.chart.topbar['status'].set('Detenido')
        self.log_message("Bot detenido")
    
    def bot_loop(self):
        """Bucle principal del bot."""
        try:
            while self.bot_running and not self.stop_event.is_set():
                try:
                    df = data_feed.get_rates_df(
                        config.SYMBOL, config.TIMEFRAME, config.BARS_HISTORY
                    )
                    df = data_feed.add_source_columns(df, config.SOURCE_MODE)
                    df = data_feed.add_baseline_bands(
                        df, config.MA_LENGTH, config.ATR_LENGTH, config.ATR_MULT
                    )
                    df = strategy_baseline.compute_dir1_and_signals(df, config.ENABLE_SIGNALS)
                    
                    signal = strategy_baseline.get_last_signal(df)
                    market_open, _ = trading.is_market_open(config.SYMBOL)
                    
                    self.price_data = df
                    self.update_chart(df)
                    
                    if signal != "none" and market_open:
                        self.log_message(f"Senal detectada: {signal.upper()}")
                        trading.apply_signal(
                            config.SYMBOL, signal, config.LOT,
                            config.SL_POINTS, config.TP_POINTS, config.MAGIC_NUMBER
                        )
                    
                    sleep_time = max(config.SLEEP_SECONDS, 10)
                    if self.stop_event.wait(timeout=sleep_time):
                        break
                    
                except Exception as e:
                    self.log_message(f"Error en bot loop: {e}")
                    if self.stop_event.wait(timeout=10):
                        break
                    
        except Exception as e:
            self.log_message(f"Error critico: {e}")
        finally:
            self.bot_running = False
    
    def run(self):
        """Ejecuta la aplicación."""
        # Inicializar MT5
        if not self.init_mt5():
            self.log_message("No se pudo inicializar MT5. Ejecutando sin datos.")
        
        # Cargar datos iniciales
        self.refresh_data()
        
        # Mostrar gráfico
        self.log_message("Iniciando interfaz grafica...")
        self.chart.show(block=True)


def main():
    """Función principal."""
    app = TradingBotGUI()
    app.run()


if __name__ == "__main__":
    main()
