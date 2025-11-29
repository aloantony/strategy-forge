"""
Interfaz gráfica moderna usando CustomTkinter.
Similar a Obsidian/Cursor con mejor UX, zoom y pan funcionales.
"""

import customtkinter as ctk
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.collections import LineCollection
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
import MetaTrader5 as mt5
import threading
import queue
import time
from datetime import datetime
from tkinter import messagebox, ttk

import config
import mt5_connection
import data_feed
import strategy_baseline
import trading


# Configurar apariencia de CustomTkinter
ctk.set_appearance_mode("dark")  # Modo oscuro
ctk.set_default_color_theme("blue")  # Tema azul


class ModernTradingBotGUI:
    """
    Interfaz gráfica moderna del bot de trading usando CustomTkinter.
    """
    
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("Bot de Trading MT5 - Panel de Control")
        self.root.geometry("1800x1200")
        
        # Datos para gráficos
        self.price_data = None
        self.equity_history = []
        self.trade_history = []
        self.view_period = "1D"
        
        # Estado del bot
        self.bot_running = False
        self.bot_thread = None
        self.stop_event = threading.Event()
        self.message_queue = queue.Queue()
        self.update_queue = queue.Queue()
        self.updating = False
        self._update_scheduled = False
        self.last_chart_update = 0
        self._last_trades_update = 0
        
        # La toolbar de matplotlib maneja zoom y pan automáticamente
        
        # Colores (CustomTkinter maneja esto automáticamente, pero los mantenemos para compatibilidad)
        self.bg_color = '#1e1e1e'
        self.fg_color = '#ffffff'
        self.success_color = '#00ff00'
        self.error_color = '#ff0000'
        self.warning_color = '#ffaa00'
        
        # Crear interfaz
        self.create_widgets()
        
        # Inicializar MT5
        self.init_mt5()
        
        # Iniciar actualización
        self.root.after(100, self.process_messages)
    
    def create_widgets(self):
        """Crea todos los widgets de la interfaz."""
        # Configurar grid principal
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        
        # Panel superior - Control
        self.create_control_panel()
        
        # Panel principal
        main_frame = ctk.CTkFrame(self.root)
        main_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_rowconfigure(1, weight=1)
        
        # Gráficos
        self.create_charts_panel(main_frame)
        
        # Información
        self.create_info_panel(main_frame)
        
        # Log oculto (para mantener funcionalidad)
        self.log_text = ctk.CTkTextbox(self.root, height=1)
        self.log_text.grid_remove()  # Oculto pero funcional
    
    def create_control_panel(self):
        """Crea el panel de control superior."""
        control_frame = ctk.CTkFrame(self.root)
        control_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        
        # Botones de control
        btn_frame = ctk.CTkFrame(control_frame)
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        self.start_btn = ctk.CTkButton(
            btn_frame,
            text="▶ Iniciar Bot",
            command=self.start_bot,
            width=120,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#28a745",
            hover_color="#218838"
        )
        self.start_btn.pack(side="left", padx=5)
        
        self.stop_btn = ctk.CTkButton(
            btn_frame,
            text="⏹ Detener Bot",
            command=self.stop_bot,
            width=120,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#dc3545",
            hover_color="#c82333",
            state="disabled"
        )
        self.stop_btn.pack(side="left", padx=5)
        
        self.logs_btn = ctk.CTkButton(
            btn_frame,
            text="📋 Ver Logs y Operaciones",
            command=self.open_logs_window,
            width=180,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#6c757d",
            hover_color="#5a6268"
        )
        self.logs_btn.pack(side="left", padx=5)
        
        # Estado y configuración
        status_frame = ctk.CTkFrame(control_frame)
        status_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(status_frame, text="Estado:", font=ctk.CTkFont(size=11)).pack(side="left", padx=5)
        
        self.status_label = ctk.CTkLabel(
            status_frame,
            text="⏸ Detenido",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=self.warning_color
        )
        self.status_label.pack(side="left", padx=10)
        
        # Separador
        ctk.CTkLabel(status_frame, text="|", font=ctk.CTkFont(size=11)).pack(side="left", padx=10)
        
        # Timeframe selector
        ctk.CTkLabel(status_frame, text="Timeframe:", font=ctk.CTkFont(size=11)).pack(side="left", padx=5)
        
        self.timeframe_var = ctk.StringVar(value="M1")
        self.timeframe_combo = ctk.CTkComboBox(
            status_frame,
            values=["M1", "M5", "M15", "M30", "H1", "H4", "D1"],
            variable=self.timeframe_var,
            width=80,
            command=self.on_timeframe_change
        )
        self.timeframe_combo.pack(side="left", padx=5)
        
        self.apply_timeframe_btn = ctk.CTkButton(
            status_frame,
            text="Aplicar Timeframe",
            command=self.apply_timeframe,
            width=130,
            height=28,
            font=ctk.CTkFont(size=10)
        )
        self.apply_timeframe_btn.pack(side="left", padx=5)
        
        # Separador
        ctk.CTkLabel(status_frame, text="|", font=ctk.CTkFont(size=11)).pack(side="left", padx=10)
        
        # Período selector
        ctk.CTkLabel(status_frame, text="Período:", font=ctk.CTkFont(size=11)).pack(side="left", padx=5)
        
        self.period_var = ctk.StringVar(value="1D")
        self.period_combo = ctk.CTkComboBox(
            status_frame,
            values=["1D", "5D", "1M", "6M", "YTD", "1A", "5A", "Todo"],
            variable=self.period_var,
            width=80,
            command=self.on_period_change
        )
        self.period_combo.pack(side="left", padx=5)
        
        self.apply_period_btn = ctk.CTkButton(
            status_frame,
            text="Aplicar Período",
            command=self.apply_period,
            width=130,
            height=28,
            font=ctk.CTkFont(size=10),
            fg_color="#6f42c1",
            hover_color="#5a32a3"
        )
        self.apply_period_btn.pack(side="left", padx=5)
    
    def create_charts_panel(self, parent):
        """Crea el panel de gráficos."""
        charts_frame = ctk.CTkFrame(parent)
        charts_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        charts_frame.grid_columnconfigure(0, weight=1)
        charts_frame.grid_columnconfigure(1, weight=1)
        charts_frame.grid_rowconfigure(0, weight=1)
        
        # Gráfico de precios
        price_frame = ctk.CTkFrame(charts_frame)
        price_frame.grid(row=0, column=0, sticky="nsew", padx=5)
        price_frame.grid_columnconfigure(0, weight=1)
        price_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            price_frame,
            text="📈 Gráfico de Precios",
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, pady=5)
        
        # Frame para canvas y toolbar (usar tk.Frame para la toolbar)
        canvas_frame = tk.Frame(price_frame, bg='#1e1e1e')
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        canvas_frame.grid_columnconfigure(0, weight=1)
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_rowconfigure(1, weight=0)  # Toolbar no se expande
        
        self.price_fig = Figure(figsize=(10, 5), facecolor='#1e1e1e')
        self.price_ax = self.price_fig.add_subplot(111, facecolor='#1e1e1e')
        self.price_ax.tick_params(colors='white', labelsize=10)
        self.price_fig.tight_layout(pad=2)
        
        self.price_canvas = FigureCanvasTkAgg(self.price_fig, canvas_frame)
        self.price_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        
        # Agregar barra de herramientas de navegación (zoom y pan)
        # Usar pack para la toolbar ya que NavigationToolbar2Tk lo requiere
        toolbar_frame = tk.Frame(canvas_frame, bg='#1e1e1e')
        toolbar_frame.grid(row=1, column=0, sticky="ew")
        
        self.price_toolbar = NavigationToolbar2Tk(self.price_canvas, toolbar_frame)
        self.price_toolbar.update()
        
        # La toolbar de matplotlib ya maneja zoom y pan, no necesitamos pan manual
        
        # Gráfico de equity
        equity_frame = ctk.CTkFrame(charts_frame)
        equity_frame.grid(row=0, column=1, sticky="nsew", padx=5)
        equity_frame.grid_columnconfigure(0, weight=1)
        equity_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            equity_frame,
            text="💰 Equity Curve",
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, pady=5)
        
        # Frame para canvas y toolbar (usar tk.Frame para la toolbar)
        equity_canvas_frame = tk.Frame(equity_frame, bg='#1e1e1e')
        equity_canvas_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        equity_canvas_frame.grid_columnconfigure(0, weight=1)
        equity_canvas_frame.grid_rowconfigure(0, weight=1)
        equity_canvas_frame.grid_rowconfigure(1, weight=0)  # Toolbar no se expande
        
        self.equity_fig = Figure(figsize=(10, 5), facecolor='#1e1e1e')
        self.equity_ax = self.equity_fig.add_subplot(111, facecolor='#1e1e1e')
        self.equity_ax.tick_params(colors='white', labelsize=10)
        self.equity_fig.tight_layout(pad=2)
        
        self.equity_canvas = FigureCanvasTkAgg(self.equity_fig, equity_canvas_frame)
        self.equity_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        
        # Agregar barra de herramientas de navegación para equity
        equity_toolbar_frame = tk.Frame(equity_canvas_frame, bg='#1e1e1e')
        equity_toolbar_frame.grid(row=1, column=0, sticky="ew")
        
        self.equity_toolbar = NavigationToolbar2Tk(self.equity_canvas, equity_toolbar_frame)
        self.equity_toolbar.update()
    
    def create_info_panel(self, parent):
        """Crea el panel de información."""
        info_frame = ctk.CTkFrame(parent)
        info_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        info_frame.grid_columnconfigure(0, weight=1)
        info_frame.grid_columnconfigure(1, weight=1)
        info_frame.grid_rowconfigure(0, weight=1)
        
        # Datos del mercado
        market_frame = ctk.CTkFrame(info_frame)
        market_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        market_frame.grid_columnconfigure(0, weight=1)
        market_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            market_frame,
            text="📊 Datos del Mercado",
            font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, pady=5)
        
        self.market_text = ctk.CTkTextbox(market_frame, width=400, height=200)
        self.market_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        
        # Métricas
        metrics_frame = ctk.CTkFrame(info_frame)
        metrics_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        metrics_frame.grid_columnconfigure(0, weight=1)
        metrics_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            metrics_frame,
            text="💼 Posición y Métricas",
            font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, pady=5)
        
        self.metrics_text = ctk.CTkTextbox(metrics_frame, width=400, height=200)
        self.metrics_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
    
    # Los métodos de pan manual han sido eliminados
    # La toolbar de matplotlib maneja zoom y pan automáticamente
    
    def init_mt5(self):
        """Inicializa la conexión con MT5 en un hilo separado."""
        def init_thread():
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
                    self.timeframe_var.set(timeframe_map[config.TIMEFRAME])
                
                self.update_queue.put(('log', ("✅ MT5 inicializado correctamente", "success")))
                self.update_queue.put(('update_market', None))
            except Exception as e:
                self.update_queue.put(('log', (f"❌ Error al inicializar MT5: {e}", "error")))
                self.update_queue.put(('error_dialog', f"No se pudo inicializar MT5:\n{e}"))
        
        threading.Thread(target=init_thread, daemon=True).start()
    
    def log_message(self, message, level="info"):
        """Añade un mensaje al log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if not hasattr(self, 'log_text'):
            self.log_text = ctk.CTkTextbox(self.root, height=1)
            self.log_text.grid_remove()
        
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        
        # Actualizar ventana de logs si está abierta
        if hasattr(self, 'log_text_window') and self.log_text_window.winfo_exists():
            try:
                self.log_text_window.insert("end", f"[{timestamp}] {message}\n")
                self.log_text_window.see("end")
            except:
                pass
    
    def update_market_info(self):
        """Actualiza la información del mercado en un hilo separado."""
        if self.updating:
            return
        
        if hasattr(self, '_update_scheduled') and self._update_scheduled:
            return
        
        self.updating = True
        self._update_scheduled = True
        
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
                    self.updating = False
                    return
                
                last_closed = df.iloc[-2]
                signal = strategy_baseline.get_last_signal(df)
                market_open, market_status = trading.is_market_open(config.SYMBOL)
                
                last_closed_dict = last_closed.to_dict()
                
                self.update_queue.put(('market_data', {
                    'df': df,
                    'last_closed': last_closed_dict,
                    'signal': signal,
                    'market_open': market_open,
                    'market_status': market_status
                }))
            except Exception as e:
                self.update_queue.put(('log', (f"Error al actualizar información: {e}", "error")))
            finally:
                self.updating = False
                self._update_scheduled = False
        
        threading.Thread(target=update_thread, daemon=True).start()
    
    def update_market_info_ui(self, data):
        """Actualiza la UI con los datos del mercado."""
        try:
            df = data['df']
            last_closed = data['last_closed']
            signal = data['signal']
            market_open = data['market_open']
            market_status = data['market_status']
            
            # Actualizar panel de mercado
            self.market_text.delete("1.0", "end")
            
            market_info = f"""
═══════════════════════════════════════════════════════
  INFORMACIÓN DEL MERCADO
═══════════════════════════════════════════════════════

📊 Última Vela Cerrada:
   Time: {last_closed['time']}
   OHLC: O={last_closed['open']:.2f} H={last_closed['high']:.2f}
         L={last_closed['low']:.2f} C={last_closed['close']:.2f}

📈 Valores Calculados (Source: {config.SOURCE_MODE}):
   H_Set: {last_closed['h_set']:.2f}
   L_Set: {last_closed['l_set']:.2f}
   Average: {last_closed['average']:.2f}
   Upper: {last_closed['upper']:.2f}
   Lower: {last_closed['lower']:.2f}
   ATR: {last_closed.get('atr', 0):.2f}

🎯 Estado de Dir_1:
   Valor: {last_closed['dir1']} {'🟢 Alcista' if last_closed['dir1'] == 1 else '🔴 Bajista' if last_closed['dir1'] == -1 else '⚪ Neutral'}

🚦 Señales:
   Up_Sig: {'✅' if last_closed['up_sig'] else '❌'}
   Dn_Sig: {'✅' if last_closed['dn_sig'] else '❌'}
   Señal: {signal.upper() if signal != 'none' else 'NINGUNA'}

🟢 Estado del Mercado:
   {market_status}
"""
            self.market_text.insert("1.0", market_info)
            
            # Guardar datos para gráficos
            self.price_data = df
            
            # Actualizar panel de métricas
            self.update_metrics()
            
            # Actualizar gráficos
            self.update_charts()
            
            # Actualizar historial de operaciones
            if hasattr(self, 'trades_tree_window'):
                self.update_trades_history_window()
                
        except Exception as e:
            self.log_message(f"Error al actualizar UI: {e}", "error")
    
    def update_metrics(self):
        """Actualiza las métricas y posición."""
        try:
            position_info = trading.get_position_info(config.SYMBOL, config.MAGIC_NUMBER)
            position_dir = trading.get_open_position_direction(config.SYMBOL, config.MAGIC_NUMBER)
            
            self.metrics_text.delete("1.0", "end")
            
            if position_info:
                position_str = "🟢 BUY" if position_dir == 1 else "🔴 SELL"
                metrics_info = f"""
═══════════════════════════════════════════════════════
  POSICIÓN ACTUAL
═══════════════════════════════════════════════════════

Tipo: {position_str}
Ticket: {position_info['ticket']}
Volumen: {position_info['volume']} lotes

Precios:
   Apertura: {position_info['price_open']:.2f}
   Actual: {position_info['price_current']:.2f}

Profit: {position_info['profit']:.2f} {'🟢' if position_info['profit'] >= 0 else '🔴'}

Stop Loss: {position_info['sl']:.2f if position_info['sl'] > 0 else 'No establecido'}
Take Profit: {position_info['tp']:.2f if position_info['tp'] > 0 else 'No establecido'}

═══════════════════════════════════════════════════════
  CONFIGURACIÓN
═══════════════════════════════════════════════════════

Símbolo: {config.SYMBOL}
Lote: {config.LOT}
SL: {config.SL_POINTS} puntos
TP: {config.TP_POINTS} puntos
Magic Number: {config.MAGIC_NUMBER}

Source Mode: {config.SOURCE_MODE}
MA Length: {config.MA_LENGTH}
ATR Length: {config.ATR_LENGTH}
ATR Mult: {config.ATR_MULT}
"""
            else:
                metrics_info = f"""
═══════════════════════════════════════════════════════
  POSICIÓN ACTUAL
═══════════════════════════════════════════════════════

⚪ Sin posición abierta

═══════════════════════════════════════════════════════
  CONFIGURACIÓN
═══════════════════════════════════════════════════════

Símbolo: {config.SYMBOL}
Lote: {config.LOT}
SL: {config.SL_POINTS} puntos
TP: {config.TP_POINTS} puntos
Magic Number: {config.MAGIC_NUMBER}

Source Mode: {config.SOURCE_MODE}
MA Length: {config.MA_LENGTH}
ATR Length: {config.ATR_LENGTH}
ATR Mult: {config.ATR_MULT}
"""
            
            self.metrics_text.insert("1.0", metrics_info)
            
        except Exception as e:
            self.log_message(f"Error al actualizar métricas: {e}", "error")
    
    def get_timeframe_minutes(self):
        """Obtiene los minutos del timeframe actual."""
        if config.TIMEFRAME == mt5.TIMEFRAME_M1:
            return 1
        elif config.TIMEFRAME == mt5.TIMEFRAME_M5:
            return 5
        elif config.TIMEFRAME == mt5.TIMEFRAME_M15:
            return 15
        elif config.TIMEFRAME == mt5.TIMEFRAME_M30:
            return 30
        elif config.TIMEFRAME == mt5.TIMEFRAME_H1:
            return 60
        elif config.TIMEFRAME == mt5.TIMEFRAME_H4:
            return 240
        elif config.TIMEFRAME == mt5.TIMEFRAME_D1:
            return 1440
        else:
            return 1
    
    def get_timeframe_string(self):
        """Obtiene el string del timeframe actual."""
        if config.TIMEFRAME == mt5.TIMEFRAME_M1:
            return "M1"
        elif config.TIMEFRAME == mt5.TIMEFRAME_M5:
            return "M5"
        elif config.TIMEFRAME == mt5.TIMEFRAME_M15:
            return "M15"
        elif config.TIMEFRAME == mt5.TIMEFRAME_M30:
            return "M30"
        elif config.TIMEFRAME == mt5.TIMEFRAME_H1:
            return "H1"
        elif config.TIMEFRAME == mt5.TIMEFRAME_H4:
            return "H4"
        elif config.TIMEFRAME == mt5.TIMEFRAME_D1:
            return "D1"
        else:
            return "Unknown"
    
    def update_charts(self):
        """Actualiza los gráficos de precios y equity."""
        try:
            if self.price_data is None or len(self.price_data) < 2:
                return
            
            if config.TIMEFRAME is None:
                return
            
            # Throttling
            current_time = time.time()
            if current_time - self.last_chart_update < 3.0:
                return
            self.last_chart_update = current_time
            
            # Gráfico de precios
            self.price_ax.clear()
            df = self.price_data.copy()
            
            # Muestrear según timeframe
            if config.TIMEFRAME == mt5.TIMEFRAME_M1:
                max_candles_to_draw = 800
            else:
                max_candles_to_draw = 500
            
            if len(df) > max_candles_to_draw:
                step = max(1, len(df) // max_candles_to_draw)
                df = df.iloc[::step].copy()
                if len(df) > 0 and len(self.price_data) > 0:
                    if df.index[-1] != self.price_data.index[-1]:
                        df = pd.concat([df, self.price_data.iloc[[-1]]]).drop_duplicates()
            
            if not pd.api.types.is_datetime64_any_dtype(df['time']):
                df['time'] = pd.to_datetime(df['time'])
            
            # Dibujar velas
            use_simple_mode = False
            if config.TIMEFRAME == mt5.TIMEFRAME_M1:
                use_simple_mode = False
            elif config.TIMEFRAME != mt5.TIMEFRAME_M1 and len(df) > 300:
                use_simple_mode = True
            
            if use_simple_mode:
                self.price_ax.plot(df['time'], df['close'], color='#0078d4', linewidth=1, label='Close', alpha=0.8, zorder=1)
                if not df['upper'].isna().all():
                    self.price_ax.plot(df['time'], df['upper'], color='#ffaa00', linewidth=1, label='Upper', alpha=0.7, zorder=1)
                if not df['average'].isna().all():
                    self.price_ax.plot(df['time'], df['average'], color='#0078d4', linewidth=1.5, label='Average', zorder=1)
                if not df['lower'].isna().all():
                    self.price_ax.plot(df['time'], df['lower'], color='#ffaa00', linewidth=1, label='Lower', alpha=0.7, zorder=1)
            else:
                # Dibujar velas completas
                try:
                    timeframe_minutes = self.get_timeframe_minutes()
                    if timeframe_minutes >= 1440:
                        width = pd.Timedelta(hours=12)
                    elif timeframe_minutes >= 60:
                        width = pd.Timedelta(minutes=timeframe_minutes * 0.6)
                    elif timeframe_minutes == 1:
                        if len(df) > 10:
                            time_diffs = df['time'].diff().dropna()
                            if len(time_diffs) > 0:
                                avg_spacing = time_diffs.median()
                                width = avg_spacing * 0.65
                            else:
                                width = pd.Timedelta(minutes=0.85)
                        else:
                            width = pd.Timedelta(minutes=0.85)
                    else:
                        width = pd.Timedelta(minutes=timeframe_minutes * 0.8)
                    
                    width_days = width.total_seconds() / 86400.0
                    
                    times = df['time'].values
                    opens = df['open'].values
                    highs = df['high'].values
                    lows = df['low'].values
                    closes = df['close'].values
                    
                    bullish = closes >= opens
                    bearish = ~bullish
                    
                    body_lows = np.minimum(opens, closes)
                    body_highs = np.maximum(opens, closes)
                    body_heights = body_highs - body_lows
                    
                    wick_color = '#888888'
                    
                    # Mechas superiores
                    upper_wicks = highs > body_highs
                    if np.any(upper_wicks):
                        upper_times = times[upper_wicks]
                        upper_starts = body_highs[upper_wicks]
                        upper_ends = highs[upper_wicks]
                        for t, start, end in zip(upper_times, upper_starts, upper_ends):
                            self.price_ax.plot([t, t], [start, end], 
                                             color=wick_color, linewidth=0.6, alpha=0.7, zorder=3)
                    
                    # Mechas inferiores
                    lower_wicks = lows < body_lows
                    if np.any(lower_wicks):
                        lower_times = times[lower_wicks]
                        lower_starts = lows[lower_wicks]
                        lower_ends = body_lows[lower_wicks]
                        for t, start, end in zip(lower_times, lower_starts, lower_ends):
                            self.price_ax.plot([t, t], [start, end], 
                                             color=wick_color, linewidth=0.6, alpha=0.7, zorder=3)
                    
                    # Cuerpos alcistas
                    if np.any(bullish):
                        bullish_times = times[bullish]
                        bullish_heights = body_heights[bullish]
                        bullish_bottoms = body_lows[bullish]
                        self.price_ax.bar(bullish_times, bullish_heights, 
                                        bottom=bullish_bottoms, width=width_days,
                                        color='#00ff00', edgecolor='#00ff00', 
                                        alpha=0.9, linewidth=0.7, zorder=4)
                    
                    # Cuerpos bajistas
                    if np.any(bearish):
                        bearish_times = times[bearish]
                        bearish_heights = body_heights[bearish]
                        bearish_bottoms = body_lows[bearish]
                        self.price_ax.bar(bearish_times, bearish_heights, 
                                        bottom=bearish_bottoms, width=width_days,
                                        color='#ff0000', edgecolor='#ff0000', 
                                        alpha=0.9, linewidth=0.7, zorder=4)
                    
                    # Dojis
                    doji = body_heights == 0
                    if np.any(doji) and np.sum(doji) < 50:
                        doji_times = times[doji]
                        doji_prices = opens[doji]
                        for t, p in zip(doji_times, doji_prices):
                            idx = np.where(times == t)[0]
                            if len(idx) > 0 and idx[0] > 0:
                                color = '#00ff00' if closes[idx[0]-1] <= p else '#ff0000'
                            else:
                                color = '#00ff00'
                            self.price_ax.plot([t, t], [p-0.0001, p+0.0001], 
                                             color=color, linewidth=2, zorder=4)
                
                except Exception as e:
                    self.log_message(f"Error al dibujar velas: {e}", "error")
                    self.price_ax.plot(df['time'], df['close'], color='#0078d4', linewidth=1, label='Close', alpha=0.8, zorder=1)
                
                # Bandas
                if not df['upper'].isna().all():
                    self.price_ax.plot(df['time'], df['upper'], color='#ffaa00', linewidth=1, label='Upper', alpha=0.7, zorder=2)
                if not df['average'].isna().all():
                    self.price_ax.plot(df['time'], df['average'], color='#0078d4', linewidth=1.5, label='Average', zorder=2)
                if not df['lower'].isna().all():
                    self.price_ax.plot(df['time'], df['lower'], color='#ffaa00', linewidth=1, label='Lower', alpha=0.7, zorder=2)
            
            # Señales
            show_signals = False
            if config.TIMEFRAME == mt5.TIMEFRAME_M1 and len(df) <= 1000:
                show_signals = True
            elif config.TIMEFRAME != mt5.TIMEFRAME_M1 and len(df) <= 300:
                show_signals = True
            
            if show_signals:
                buy_signals = df[df['up_sig'] == True]
                sell_signals = df[df['dn_sig'] == True]
                
                if len(buy_signals) > 0:
                    self.price_ax.scatter(buy_signals['time'], buy_signals['close'], 
                                         color='#00ff00', marker='^', s=100, label='Buy Signal', zorder=5)
                if len(sell_signals) > 0:
                    self.price_ax.scatter(sell_signals['time'], sell_signals['close'], 
                                         color='#ff0000', marker='v', s=100, label='Sell Signal', zorder=5)
            
            # Formatear eje X
            self.price_ax.set_facecolor('#1e1e1e')
            self.price_ax.tick_params(colors='white', labelsize=10)
            
            timeframe_str = self.get_timeframe_string()
            timeframe_minutes = self.get_timeframe_minutes()
            
            # Formatear fechas según timeframe
            try:
                num_labels = min(12, max(5, len(df) // 50))
                
                if config.TIMEFRAME == mt5.TIMEFRAME_M1:
                    date_format = mdates.DateFormatter('%H:%M')
                    total_minutes = (df['time'].iloc[-1] - df['time'].iloc[0]).total_seconds() / 60
                    interval_minutes = max(5, int(total_minutes / num_labels))
                    locator = mdates.MinuteLocator(interval=interval_minutes)
                elif config.TIMEFRAME in [mt5.TIMEFRAME_M5, mt5.TIMEFRAME_M15, mt5.TIMEFRAME_M30]:
                    date_format = mdates.DateFormatter('%H:%M')
                    total_minutes = (df['time'].iloc[-1] - df['time'].iloc[0]).total_seconds() / 60
                    interval_minutes = max(15, int(total_minutes / num_labels))
                    locator = mdates.MinuteLocator(interval=interval_minutes)
                elif config.TIMEFRAME == mt5.TIMEFRAME_H1:
                    date_format = mdates.DateFormatter('%m/%d\n%H:%M')
                    total_hours = (df['time'].iloc[-1] - df['time'].iloc[0]).total_seconds() / 3600
                    interval_hours = max(1, int(total_hours / num_labels))
                    locator = mdates.HourLocator(interval=interval_hours)
                elif config.TIMEFRAME == mt5.TIMEFRAME_H4:
                    date_format = mdates.DateFormatter('%m/%d\n%H:%M')
                    total_hours = (df['time'].iloc[-1] - df['time'].iloc[0]).total_seconds() / 3600
                    interval_hours = max(4, int(total_hours / num_labels))
                    locator = mdates.HourLocator(interval=interval_hours)
                elif config.TIMEFRAME == mt5.TIMEFRAME_D1:
                    date_format = mdates.DateFormatter('%m/%d')
                    total_days = (df['time'].iloc[-1] - df['time'].iloc[0]).days
                    interval_days = max(1, int(total_days / num_labels))
                    locator = mdates.DayLocator(interval=interval_days)
                else:
                    date_format = mdates.DateFormatter('%m/%d\n%H:%M')
                    total_hours = (df['time'].iloc[-1] - df['time'].iloc[0]).total_seconds() / 3600
                    interval_hours = max(1, int(total_hours / num_labels))
                    locator = mdates.HourLocator(interval=interval_hours)
            except Exception as e:
                date_format = mdates.DateFormatter('%H:%M')
                locator = mdates.MinuteLocator(interval=10)
                self.log_message(f"Error al formatear fechas: {e}", "error")
            
            self.price_ax.xaxis.set_major_formatter(date_format)
            self.price_ax.xaxis.set_major_locator(locator)
            self.price_fig.autofmt_xdate(rotation=45, ha='right')
            self.price_fig.subplots_adjust(bottom=0.15)
            
            # Título e información
            first_time = df['time'].iloc[0].strftime('%Y-%m-%d %H:%M:%S')
            last_time = df['time'].iloc[-1].strftime('%Y-%m-%d %H:%M:%S')
            price_range = f"High: {df['high'].max():.2f} | Low: {df['low'].min():.2f}"
            
            self.price_ax.set_xlabel(f'Tiempo | Desde: {first_time} | Hasta: {last_time}', 
                                    color='white', fontsize=10)
            self.price_ax.set_ylabel('Precio', color='white', fontsize=12)
            self.price_ax.set_title(f'{config.SYMBOL} - {timeframe_str} | Período: {self.view_period} | {price_range} | {len(df)} velas', 
                                   color='white', fontsize=13, pad=15)
            self.price_ax.legend(loc='upper left', fontsize=9, facecolor='#2d2d2d', edgecolor='white')
            self.price_ax.grid(True, alpha=0.3, color='gray', linestyle='--')
            
            if len(df) > 0:
                last_price = df['close'].iloc[-1]
                self.price_ax.axhline(y=last_price, color='yellow', linestyle=':', linewidth=1, 
                                    alpha=0.5, label=f'Último: {last_price:.2f}')
            
            self.price_fig.tight_layout(pad=2)
            self.price_canvas.draw()
            
            # Gráfico de equity
            self.equity_ax.clear()
            
            try:
                start_date = datetime.now().replace(day=1) if datetime.now().day > 1 else (datetime.now() - pd.Timedelta(days=30))
                positions = mt5.history_deals_get(start_date, datetime.now())
                
                if positions:
                    filtered_positions = [p for p in positions if hasattr(p, 'magic') and p.magic == config.MAGIC_NUMBER]
                    
                    if filtered_positions:
                        equity_data = []
                        balance = 10000.0
                        
                        for deal in sorted(filtered_positions, key=lambda x: x.time):
                            if deal.entry == mt5.DEAL_ENTRY_OUT:
                                balance += deal.profit
                                equity_data.append({
                                    'time': datetime.fromtimestamp(deal.time),
                                    'equity': balance
                                })
                        
                        if equity_data:
                            equity_df = pd.DataFrame(equity_data)
                            equity_df = equity_df.sort_values('time')
                            self.equity_ax.plot(equity_df['time'], equity_df['equity'], 
                                             color='#00ff00', linewidth=2, label='Equity')
                            self.equity_ax.axhline(y=10000, color='gray', linestyle='--', alpha=0.5, label='Initial Balance')
                            self.equity_ax.fill_between(equity_df['time'], 10000, equity_df['equity'], 
                                                        where=(equity_df['equity'] >= 10000), 
                                                        color='green', alpha=0.2)
                            self.equity_ax.fill_between(equity_df['time'], 10000, equity_df['equity'], 
                                                        where=(equity_df['equity'] < 10000), 
                                                        color='red', alpha=0.2)
                    else:
                        self.equity_ax.axhline(y=10000, color='gray', linewidth=2, label='Initial Balance')
                else:
                    self.equity_ax.axhline(y=10000, color='gray', linewidth=2, label='Initial Balance')
            except Exception:
                self.equity_ax.axhline(y=10000, color='gray', linewidth=2, label='Initial Balance')
            
            self.equity_ax.set_facecolor('#1e1e1e')
            self.equity_ax.tick_params(colors='white', labelsize=10)
            self.equity_ax.set_title('Equity Curve', color='white', fontsize=13)
            self.equity_ax.set_xlabel('Tiempo', color='white', fontsize=12)
            self.equity_ax.set_ylabel('Equity', color='white', fontsize=12)
            self.equity_ax.legend(loc='upper left', fontsize=9, facecolor='#2d2d2d', edgecolor='white')
            self.equity_ax.grid(True, alpha=0.3, color='gray')
            self.equity_fig.tight_layout(pad=2)
            self.equity_canvas.draw()
            
        except Exception as e:
            self.log_message(f"Error al actualizar gráficos: {e}", "error")
    
    def update_trades_history_window(self):
        """Actualiza el historial de operaciones en la ventana de logs."""
        try:
            tree = None
            if hasattr(self, 'trades_tree_window') and self.trades_tree_window.winfo_exists():
                tree = self.trades_tree_window
            
            if tree is None:
                return
            
            # Limpiar treeview
            for item in tree.get_children():
                tree.delete(item)
            
            # Obtener historial
            try:
                start_date = datetime.now().replace(day=1) if datetime.now().day > 1 else (datetime.now() - pd.Timedelta(days=30))
                positions = mt5.history_deals_get(start_date, datetime.now())
                
                if positions:
                    positions = [p for p in positions if hasattr(p, 'magic') and p.magic == config.MAGIC_NUMBER]
            except Exception:
                positions = None
            
            if positions:
                trades_dict = {}
                for deal in positions:
                    ticket = deal.position_id
                    if ticket not in trades_dict:
                        trades_dict[ticket] = {'entry': None, 'exit': None}
                    
                    if deal.entry == mt5.DEAL_ENTRY_IN:
                        trades_dict[ticket]['entry'] = deal
                    elif deal.entry == mt5.DEAL_ENTRY_OUT:
                        trades_dict[ticket]['exit'] = deal
                
                for ticket, trade in trades_dict.items():
                    if trade['entry'] and trade['exit']:
                        entry = trade['entry']
                        exit_deal = trade['exit']
                        
                        trade_type = 'BUY' if entry.type == mt5.DEAL_TYPE_BUY else 'SELL'
                        profit = exit_deal.profit
                        profit_color = 'green' if profit >= 0 else 'red'
                        
                        date_str = datetime.fromtimestamp(exit_deal.time).strftime('%Y-%m-%d %H:%M')
                        
                        tree.insert('', 'end', values=(
                            date_str,
                            trade_type,
                            f"{entry.price:.2f}",
                            f"{entry.volume:.2f}",
                            f"{profit:.2f}",
                            "TP" if profit > 0 else "SL"
                        ), tags=(profit_color,))
                
                tree.tag_configure('green', foreground='#00ff00')
                tree.tag_configure('red', foreground='#ff0000')
                
        except Exception as e:
            self.log_message(f"Error al actualizar historial: {e}", "error")
    
    def start_bot(self):
        """Inicia el bot en un hilo separado."""
        if self.bot_running:
            return
        
        try:
            self.bot_running = True
            self.stop_event.clear()
            self.bot_thread = threading.Thread(target=self.bot_loop, daemon=True)
            self.bot_thread.start()
            
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            self.status_label.configure(text="▶ Ejecutando", text_color=self.success_color)
            self.log_message("🚀 Bot iniciado", "success")
            
        except Exception as e:
            self.log_message(f"Error al iniciar bot: {e}", "error")
            self.bot_running = False
    
    def stop_bot(self):
        """Detiene el bot."""
        if not self.bot_running:
            return
        
        self.bot_running = False
        self.stop_event.set()
        
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_label.configure(text="⏸ Detenido", text_color=self.warning_color)
        self.log_message("⏹ Bot detenido", "warning")
    
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
                    market_open, market_status = trading.is_market_open(config.SYMBOL)
                    
                    self.message_queue.put(('update_market', None))
                    
                    if signal != "none" and market_open:
                        self.message_queue.put(('signal', signal))
                        trading.apply_signal(
                            config.SYMBOL, signal, config.LOT,
                            config.SL_POINTS, config.TP_POINTS, config.MAGIC_NUMBER
                        )
                    
                    sleep_time = max(config.SLEEP_SECONDS, 10)
                    if self.stop_event.wait(timeout=sleep_time):
                        break
                        
                except Exception as e:
                    self.message_queue.put(('error', str(e)))
                    sleep_time = max(config.SLEEP_SECONDS, 10)
                    if self.stop_event.wait(timeout=sleep_time):
                        break
                        
        except Exception as e:
            self.message_queue.put(('error', f"Error crítico en el bot: {e}"))
        finally:
            self.bot_running = False
            self.message_queue.put(('stopped', None))
    
    def process_messages(self):
        """Procesa mensajes de la cola."""
        try:
            while True:
                msg_type, data = self.message_queue.get_nowait()
                
                if msg_type == 'update_market':
                    self.update_market_info()
                elif msg_type == 'signal':
                    self.log_message(f"⚡ Señal detectada: {data.upper()}", "success")
                elif msg_type == 'error':
                    self.log_message(f"❌ Error: {data}", "error")
                elif msg_type == 'stopped':
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.status_label.configure(text="⏸ Detenido", text_color=self.warning_color)
                    
        except queue.Empty:
            pass
        
        # Procesar actualizaciones de UI
        try:
            while True:
                msg_type, data = self.update_queue.get_nowait()
                
                if msg_type == 'log':
                    if isinstance(data, tuple):
                        self.log_message(data[0], data[1] if len(data) > 1 else "info")
                    else:
                        self.log_message(data, "info")
                elif msg_type == 'market_data':
                    self.update_market_info_ui(data)
                elif msg_type == 'error_dialog':
                    messagebox.showerror("Error", data)
                elif msg_type == 'update_market':
                    self.update_market_info()
                    
        except queue.Empty:
            pass
        
        # Programar próxima actualización
        self.root.after(100, self.process_messages)
        
        # Actualizar información periódicamente
        if not self.bot_running and not self.updating:
            self.root.after(10000, self.update_market_info)
    
    def on_timeframe_change(self, value):
        """Maneja el cambio de timeframe."""
        pass
    
    def on_period_change(self, value):
        """Maneja el cambio de período."""
        pass
    
    def get_period_bars(self, period_str, timeframe_minutes):
        """Calcula cuántas velas obtener según el período."""
        minutes_per_day = 24 * 60
        minutes_per_month = 30 * minutes_per_day
        minutes_per_year = 365 * minutes_per_day
        
        if period_str == "1D":
            bars = (1 * minutes_per_day) // timeframe_minutes
        elif period_str == "5D":
            bars = (5 * minutes_per_day) // timeframe_minutes
        elif period_str == "1M":
            bars = (1 * minutes_per_month) // timeframe_minutes
        elif period_str == "6M":
            bars = (6 * minutes_per_month) // timeframe_minutes
        elif period_str == "YTD":
            now = datetime.now()
            year_start = datetime(now.year, 1, 1)
            days_passed = (now - year_start).days
            bars = (days_passed * minutes_per_day) // timeframe_minutes
        elif period_str == "1A":
            bars = (1 * minutes_per_year) // timeframe_minutes
        elif period_str == "5A":
            bars = (5 * minutes_per_year) // timeframe_minutes
        elif period_str == "Todo":
            bars = 5000
        else:
            bars = 500
        
        return max(100, min(bars, 5000))
    
    def apply_period(self):
        """Aplica el período de visualización seleccionado."""
        try:
            period_str = self.period_var.get()
            self.view_period = period_str
            self.log_message(f"✅ Período de visualización cambiado a {period_str}", "success")
            self.update_market_info()
        except Exception as e:
            self.log_message(f"❌ Error al cambiar período: {e}", "error")
    
    def apply_timeframe(self):
        """Aplica el timeframe seleccionado."""
        if self.bot_running:
            messagebox.showwarning("Bot en ejecución", 
                                 "Debes detener el bot antes de cambiar el timeframe.")
            return
        
        try:
            timeframe_str = self.timeframe_var.get()
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
                old_timeframe = config.TIMEFRAME
                config.TIMEFRAME = timeframe_map[timeframe_str]
                
                try:
                    symbol_info = mt5.symbol_info(config.SYMBOL)
                    if symbol_info is None:
                        raise Exception(f"Símbolo {config.SYMBOL} no encontrado")
                    
                    rates = mt5.copy_rates_from_pos(config.SYMBOL, config.TIMEFRAME, 0, 1)
                    if rates is None or len(rates) == 0:
                        config.TIMEFRAME = old_timeframe
                        self.log_message(f"❌ No hay datos disponibles para {timeframe_str} en {config.SYMBOL}", "error")
                        messagebox.showerror("Error", f"No hay datos disponibles para el timeframe {timeframe_str}.\nEl timeframe se mantiene en el anterior.")
                        return
                    
                    self.log_message(f"✅ Timeframe cambiado a {timeframe_str}", "success")
                    self.price_data = None
                    self.update_market_info()
                except Exception as e:
                    config.TIMEFRAME = old_timeframe
                    self.log_message(f"❌ Error al cambiar timeframe: {e}", "error")
                    messagebox.showerror("Error", f"No se pudo cambiar al timeframe {timeframe_str}:\n{e}")
            else:
                self.log_message(f"❌ Timeframe no válido: {timeframe_str}", "error")
        except Exception as e:
            self.log_message(f"❌ Error inesperado al aplicar timeframe: {e}", "error")
    
    def open_logs_window(self):
        """Abre una ventana secundaria con logs y operaciones."""
        if hasattr(self, 'logs_window') and self.logs_window.winfo_exists():
            self.logs_window.lift()
            return
        
        # Crear ventana secundaria con CustomTkinter
        self.logs_window = ctk.CTkToplevel(self.root)
        self.logs_window.title("Logs y Operaciones - Bot de Trading")
        self.logs_window.geometry("1200x600")
        
        logs_frame = ctk.CTkFrame(self.logs_window)
        logs_frame.pack(fill="both", expand=True, padx=10, pady=10)
        logs_frame.grid_columnconfigure(0, weight=1)
        logs_frame.grid_columnconfigure(1, weight=1)
        logs_frame.grid_rowconfigure(0, weight=1)
        
        # Panel izquierdo - Log
        log_frame = ctk.CTkFrame(logs_frame)
        log_frame.grid(row=0, column=0, sticky="nsew", padx=5)
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            log_frame,
            text="📝 Log de Eventos",
            font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, pady=5)
        
        self.log_text_window = ctk.CTkTextbox(log_frame)
        self.log_text_window.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        
        # Copiar contenido del log principal
        if hasattr(self, 'log_text'):
            main_log_content = self.log_text.get("1.0", "end")
            self.log_text_window.insert("1.0", main_log_content)
        
        # Panel derecho - Historial de operaciones
        trades_frame = ctk.CTkFrame(logs_frame)
        trades_frame.grid(row=0, column=1, sticky="nsew", padx=5)
        trades_frame.grid_columnconfigure(0, weight=1)
        trades_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            trades_frame,
            text="📋 Historial de Operaciones",
            font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, pady=5)
        
        # Treeview para operaciones (usar ttk.Treeview ya que CustomTkinter no tiene equivalente)
        columns = ('Fecha', 'Tipo', 'Precio', 'Volumen', 'Profit', 'Razón')
        self.trades_tree_window = ttk.Treeview(trades_frame, columns=columns, show='headings')
        
        for col in columns:
            self.trades_tree_window.heading(col, text=col)
            self.trades_tree_window.column(col, width=150)
        
        scrollbar_trades = ttk.Scrollbar(trades_frame, orient="vertical", command=self.trades_tree_window.yview)
        self.trades_tree_window.configure(yscrollcommand=scrollbar_trades.set)
        
        self.trades_tree_window.grid(row=1, column=0, sticky="nsew", padx=(10, 0), pady=10)
        scrollbar_trades.grid(row=1, column=1, sticky="ns", padx=(0, 10), pady=10)
        
        # Actualizar operaciones
        self.update_trades_history_window()
        
        # Función para actualizar el log
        def update_log_window():
            if hasattr(self, 'log_text_window') and self.log_text_window.winfo_exists():
                try:
                    new_content = self.log_text.get("1.0", "end")
                    current_content = self.log_text_window.get("1.0", "end")
                    if new_content != current_content:
                        self.log_text_window.delete("1.0", "end")
                        self.log_text_window.insert("1.0", new_content)
                        self.log_text_window.see("end")
                except:
                    pass
                self.logs_window.after(500, update_log_window)
        
        update_log_window()
        
        # Manejar cierre
        self.logs_window.protocol("WM_DELETE_WINDOW", lambda: self.logs_window.destroy())
    
    def on_closing(self):
        """Maneja el cierre de la ventana."""
        if self.bot_running:
            self.stop_bot()
            if self.bot_thread:
                self.bot_thread.join(timeout=2)
        mt5.shutdown()
        self.root.destroy()
    
    def run(self):
        """Ejecuta la aplicación."""
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()


def main():
    """Función principal."""
    app = ModernTradingBotGUI()
    app.run()


if __name__ == "__main__":
    main()

