"""
Interfaz gráfica para el bot de trading.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import queue
from datetime import datetime
import MetaTrader5 as mt5
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.collections import LineCollection
import pandas as pd
import numpy as np
import config
import mt5_connection
import data_feed
import strategy_baseline
import trading


class TradingBotGUI:
    """
    Interfaz gráfica principal del bot de trading.
    """
    
    def __init__(self, root):
        self.root = root
        self.root.title("Bot de Trading MT5 - Panel de Control")
        self.root.geometry("1800x1200")  # Ventana más grande
        self.root.configure(bg='#1e1e1e')
        
        # Datos para gráficos
        self.price_data = None
        self.equity_history = []
        self.trade_history = []
        self.view_period = "1D"  # Período de visualización por defecto
        self.control_pressed = False  # Estado de la tecla Control
        
        # Estado del bot
        self.bot_running = False
        self.bot_thread = None
        self.stop_event = threading.Event()
        self.message_queue = queue.Queue()
        self.update_queue = queue.Queue()  # Cola para actualizaciones de UI
        self.updating = False  # Flag para evitar actualizaciones simultáneas
        self._update_scheduled = False  # Flag para evitar programar múltiples actualizaciones
        self.last_chart_update = 0  # Timestamp de última actualización del gráfico
        self._last_trades_update = 0  # Timestamp de última actualización de operaciones
        
        # Configurar estilo
        self.setup_style()
        
        # Crear interfaz
        self.create_widgets()
        
        # Inicializar MT5
        self.init_mt5()
        
        # Iniciar actualización de mensajes
        self.root.after(100, self.process_messages)
    
    def setup_style(self):
        """Configura el estilo de la interfaz."""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Colores
        self.bg_color = '#1e1e1e'
        self.fg_color = '#ffffff'
        self.accent_color = '#0078d4'
        self.success_color = '#00ff00'
        self.error_color = '#ff0000'
        self.warning_color = '#ffaa00'
        
        style.configure('Title.TLabel', 
                       background=self.bg_color, 
                       foreground=self.fg_color,
                       font=('Segoe UI', 16, 'bold'))
        
        style.configure('Header.TLabel',
                       background=self.bg_color,
                       foreground=self.fg_color,
                       font=('Segoe UI', 12, 'bold'))
        
        style.configure('Normal.TLabel',
                       background=self.bg_color,
                       foreground=self.fg_color,
                       font=('Segoe UI', 10))
    
    def create_widgets(self):
        """Crea todos los widgets de la interfaz."""
        # Frame principal
        main_frame = tk.Frame(self.root, bg=self.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Panel superior - Control
        self.create_control_panel(main_frame)
        
        # Panel medio - Gráficos (en una fila)
        self.create_charts_panel(main_frame)
        
        # Panel medio - Información en tiempo real (más grande)
        self.create_info_panel(main_frame)
        
        # Los paneles de log y operaciones se moverán a una ventana secundaria
        # Crear log oculto (para mantener funcionalidad)
        self.log_text = scrolledtext.ScrolledText(main_frame, height=1)
        self.log_text.pack_forget()  # Oculto pero funcional
        self.log_text.config(state=tk.DISABLED)
    
    def create_control_panel(self, parent):
        """Crea el panel de control."""
        control_frame = tk.LabelFrame(parent, text="Control del Bot", 
                                      bg=self.bg_color, fg=self.fg_color,
                                      font=('Segoe UI', 10, 'bold'))
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Botones de control
        btn_frame = tk.Frame(control_frame, bg=self.bg_color)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.start_btn = tk.Button(btn_frame, text="▶ Iniciar Bot", 
                                   command=self.start_bot,
                                   bg='#28a745', fg='white',
                                   font=('Segoe UI', 11, 'bold'),
                                   padx=20, pady=10,
                                   cursor='hand2')
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = tk.Button(btn_frame, text="⏹ Detener Bot", 
                                  command=self.stop_bot,
                                  bg='#dc3545', fg='white',
                                  font=('Segoe UI', 11, 'bold'),
                                  padx=20, pady=10,
                                  cursor='hand2',
                                  state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        self.logs_btn = tk.Button(btn_frame, text="📋 Ver Logs y Operaciones", 
                                  command=self.open_logs_window,
                                  bg='#6c757d', fg='white',
                                  font=('Segoe UI', 11, 'bold'),
                                  padx=20, pady=10,
                                  cursor='hand2')
        self.logs_btn.pack(side=tk.LEFT, padx=5)
        
        # Estado del bot y configuración
        status_frame = tk.Frame(control_frame, bg=self.bg_color)
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(status_frame, text="Estado:", 
                bg=self.bg_color, fg=self.fg_color,
                font=('Segoe UI', 10)).pack(side=tk.LEFT)
        
        self.status_label = tk.Label(status_frame, text="⏸ Detenido", 
                                     bg=self.bg_color, fg=self.warning_color,
                                     font=('Segoe UI', 10, 'bold'))
        self.status_label.pack(side=tk.LEFT, padx=10)
        
        # Separador
        tk.Label(status_frame, text="|", 
                bg=self.bg_color, fg=self.fg_color,
                font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=10)
        
        # Selector de Timeframe
        tk.Label(status_frame, text="Timeframe:", 
                bg=self.bg_color, fg=self.fg_color,
                font=('Segoe UI', 10)).pack(side=tk.LEFT)
        
        self.timeframe_var = tk.StringVar(value="M1")
        timeframe_options = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
        self.timeframe_combo = ttk.Combobox(status_frame, textvariable=self.timeframe_var,
                                            values=timeframe_options, state="readonly",
                                            width=8, font=('Segoe UI', 10))
        self.timeframe_combo.pack(side=tk.LEFT, padx=5)
        self.timeframe_combo.bind("<<ComboboxSelected>>", self.on_timeframe_change)
        
        # Botón para aplicar cambios
        self.apply_timeframe_btn = tk.Button(status_frame, text="Aplicar Timeframe", 
                                             command=self.apply_timeframe,
                                             bg='#0078d4', fg='white',
                                             font=('Segoe UI', 9),
                                             padx=10, pady=5,
                                             cursor='hand2')
        self.apply_timeframe_btn.pack(side=tk.LEFT, padx=5)
        
        # Separador
        tk.Label(status_frame, text="|", 
                bg=self.bg_color, fg=self.fg_color,
                font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=10)
        
        # Selector de Período de Visualización
        tk.Label(status_frame, text="Período:", 
                bg=self.bg_color, fg=self.fg_color,
                font=('Segoe UI', 10)).pack(side=tk.LEFT)
        
        self.period_var = tk.StringVar(value="1D")
        period_options = ["1D", "5D", "1M", "6M", "YTD", "1A", "5A", "Todo"]
        self.period_combo = ttk.Combobox(status_frame, textvariable=self.period_var,
                                         values=period_options, state="readonly",
                                         width=8, font=('Segoe UI', 10))
        self.period_combo.pack(side=tk.LEFT, padx=5)
        self.period_combo.bind("<<ComboboxSelected>>", self.on_period_change)
        
        # Botón para aplicar período
        self.apply_period_btn = tk.Button(status_frame, text="Aplicar Período", 
                                          command=self.apply_period,
                                          bg='#6f42c1', fg='white',
                                          font=('Segoe UI', 9),
                                          padx=10, pady=5,
                                          cursor='hand2')
        self.apply_period_btn.pack(side=tk.LEFT, padx=5)
    
    def create_charts_panel(self, parent):
        """Crea el panel de gráficos."""
        charts_frame = tk.Frame(parent, bg=self.bg_color)
        charts_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 10))
        
        # Gráfico de precios
        price_chart_frame = tk.LabelFrame(charts_frame, text="📈 Gráfico de Precios",
                                          bg=self.bg_color, fg=self.fg_color,
                                          font=('Segoe UI', 10, 'bold'))
        price_chart_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        self.price_fig = Figure(figsize=(10, 5), facecolor='#1e1e1e')  # Gráfico más grande
        self.price_ax = self.price_fig.add_subplot(111, facecolor='#1e1e1e')
        self.price_ax.tick_params(colors='white', labelsize=10)  # Fuente más grande
        self.price_fig.tight_layout(pad=2)
        
        self.price_canvas = FigureCanvasTkAgg(self.price_fig, price_chart_frame)
        self.price_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Conectar eventos de mouse para tooltip
        self.price_canvas.mpl_connect('motion_notify_event', self.on_price_chart_hover)
        self.candle_tooltip = None  # Referencia al tooltip actual (ventana flotante)
        
        # Conectar eventos de teclado para detectar Control (globalmente)
        # Usar bind_all para capturar eventos en toda la aplicación
        def set_control_true(e=None):
            self.control_pressed = True
        
        def set_control_false(e=None):
            self.control_pressed = False
        
        # Detectar Control presionado (múltiples formas para mayor compatibilidad)
        self.root.bind_all('<KeyPress-Control_L>', set_control_true)
        self.root.bind_all('<KeyPress-Control_R>', set_control_true)
        self.root.bind_all('<KeyRelease-Control_L>', set_control_false)
        self.root.bind_all('<KeyRelease-Control_R>', set_control_false)
        
        # También detectar cuando se presiona/suelta Control en el canvas
        canvas_widget = self.price_canvas.get_tk_widget()
        canvas_widget.focus_set()  # Permitir que el canvas reciba eventos de teclado
        canvas_widget.bind('<KeyPress-Control_L>', set_control_true)
        canvas_widget.bind('<KeyPress-Control_R>', set_control_true)
        canvas_widget.bind('<KeyRelease-Control_L>', set_control_false)
        canvas_widget.bind('<KeyRelease-Control_R>', set_control_false)
        canvas_widget.bind('<Button-1>', lambda e: canvas_widget.focus_set())  # Enfocar al hacer clic
        
        # Detectar cuando el mouse entra/sale del canvas
        def on_canvas_enter(e):
            canvas_widget.focus_set()  # Enfocar automáticamente al entrar
        
        def on_canvas_leave(e):
            set_control_false()  # Resetear al salir
        
        canvas_widget.bind('<Enter>', on_canvas_enter)  # Enfocar al entrar
        canvas_widget.bind('<Leave>', on_canvas_leave)  # Resetear al salir
        
        # También conectar eventos de movimiento del mouse sobre el canvas
        # para asegurar que tenga el foco
        canvas_widget.bind('<Motion>', lambda e: canvas_widget.focus_set())
        
        # Label para mostrar información de la vela (debajo del gráfico)
        self.candle_info_label = tk.Label(price_chart_frame, 
                                         text="Desplaza el ratón sobre las velas para ver detalles",
                                         bg=self.bg_color, fg='#888888',
                                         font=('Segoe UI', 9))
        self.candle_info_label.pack(pady=(0, 5))
        
        # Gráfico de equity
        equity_chart_frame = tk.LabelFrame(charts_frame, text="💰 Equity Curve",
                                           bg=self.bg_color, fg=self.fg_color,
                                           font=('Segoe UI', 10, 'bold'))
        equity_chart_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        self.equity_fig = Figure(figsize=(10, 5), facecolor='#1e1e1e')  # Gráfico más grande
        self.equity_ax = self.equity_fig.add_subplot(111, facecolor='#1e1e1e')
        self.equity_ax.tick_params(colors='white', labelsize=10)  # Fuente más grande
        self.equity_fig.tight_layout(pad=2)
        
        self.equity_canvas = FigureCanvasTkAgg(self.equity_fig, equity_chart_frame)
        self.equity_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    
    def create_info_panel(self, parent):
        """Crea el panel de información en tiempo real."""
        info_frame = tk.Frame(parent, bg=self.bg_color)
        info_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Panel izquierdo - Datos del mercado (más grande)
        market_frame = tk.LabelFrame(info_frame, text="📊 Datos del Mercado",
                                     bg=self.bg_color, fg=self.fg_color,
                                     font=('Segoe UI', 11, 'bold'))
        market_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        self.market_text = scrolledtext.ScrolledText(market_frame,
                                                     bg='#2d2d2d',
                                                     fg=self.fg_color,
                                                     font=('Consolas', 11),
                                                     wrap=tk.WORD,
                                                     height=12)
        self.market_text.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        self.market_text.config(state=tk.DISABLED)
        
        # Panel derecho - Posición y métricas (más grande)
        metrics_frame = tk.LabelFrame(info_frame, text="💼 Posición y Métricas",
                                      bg=self.bg_color, fg=self.fg_color,
                                      font=('Segoe UI', 11, 'bold'))
        metrics_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        self.metrics_text = scrolledtext.ScrolledText(metrics_frame,
                                                      bg='#2d2d2d',
                                                      fg=self.fg_color,
                                                      font=('Consolas', 11),
                                                      wrap=tk.WORD,
                                                      height=12)
        self.metrics_text.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        self.metrics_text.config(state=tk.DISABLED)
    
    def open_logs_window(self):
        """Abre una ventana secundaria con logs y operaciones."""
        if hasattr(self, 'logs_window') and self.logs_window.winfo_exists():
            self.logs_window.lift()
            return
        
        # Crear ventana secundaria
        self.logs_window = tk.Toplevel(self.root)
        self.logs_window.title("Logs y Operaciones - Bot de Trading")
        self.logs_window.geometry("1200x600")
        self.logs_window.configure(bg='#1e1e1e')
        
        # Crear paneles en la ventana secundaria
        logs_frame = tk.Frame(self.logs_window, bg='#1e1e1e')
        logs_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Panel izquierdo - Log
        log_frame = tk.LabelFrame(logs_frame, text="📝 Log de Eventos",
                                  bg=self.bg_color, fg=self.fg_color,
                                  font=('Segoe UI', 10, 'bold'))
        log_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        # Usar el mismo widget de log (necesitamos crear uno nuevo para la ventana)
        log_text_window = scrolledtext.ScrolledText(log_frame,
                                                   bg='#2d2d2d',
                                                   fg=self.fg_color,
                                                   font=('Consolas', 9),
                                                   wrap=tk.WORD)
        log_text_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        log_text_window.config(state=tk.DISABLED)
        
        # Copiar contenido del log principal
        if hasattr(self, 'log_text'):
            main_log_content = self.log_text.get(1.0, tk.END)
            log_text_window.config(state=tk.NORMAL)
            log_text_window.insert(1.0, main_log_content)
            log_text_window.config(state=tk.DISABLED)
        
        # Guardar referencia para actualizar
        self.log_text_window = log_text_window
        
        # Panel derecho - Historial de operaciones
        trades_frame = tk.LabelFrame(logs_frame, text="📋 Historial de Operaciones",
                                     bg=self.bg_color, fg=self.fg_color,
                                     font=('Segoe UI', 10, 'bold'))
        trades_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        # Treeview para operaciones
        columns = ('Fecha', 'Tipo', 'Precio', 'Volumen', 'Profit', 'Razón')
        trades_tree_window = ttk.Treeview(trades_frame, columns=columns, show='headings')
        
        for col in columns:
            trades_tree_window.heading(col, text=col)
            trades_tree_window.column(col, width=150)
        
        scrollbar_trades = ttk.Scrollbar(trades_frame, orient=tk.VERTICAL, command=trades_tree_window.yview)
        trades_tree_window.configure(yscrollcommand=scrollbar_trades.set)
        
        trades_tree_window.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=10)
        scrollbar_trades.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 10), pady=10)
        
        # Guardar referencia
        self.trades_tree_window = trades_tree_window
        
        # Actualizar operaciones en la nueva ventana
        self.update_trades_history_window()
        
        # Función para actualizar el log cuando se añadan mensajes
        def update_log_window():
            if hasattr(self, 'log_text_window') and self.log_text_window.winfo_exists():
                try:
                    new_content = self.log_text.get(1.0, tk.END)
                    current_content = self.log_text_window.get(1.0, tk.END)
                    if new_content != current_content:
                        self.log_text_window.config(state=tk.NORMAL)
                        self.log_text_window.delete(1.0, tk.END)
                        self.log_text_window.insert(1.0, new_content)
                        self.log_text_window.see(tk.END)
                        self.log_text_window.config(state=tk.DISABLED)
                except:
                    pass
                self.logs_window.after(500, update_log_window)
        
        # Iniciar actualización periódica
        update_log_window()
        
        # Manejar cierre de ventana
        self.logs_window.protocol("WM_DELETE_WINDOW", lambda: self.logs_window.destroy())
    
    def init_mt5(self):
        """Inicializa la conexión con MT5 en un hilo separado."""
        def init_thread():
            try:
                # Si no hay timeframe configurado, usar M1 por defecto
                if config.TIMEFRAME is None:
                    config.TIMEFRAME = mt5.TIMEFRAME_M1
                
                mt5_connection.initialize_mt5()
                mt5_connection.check_symbol(config.SYMBOL)
                
                # Actualizar el selector de timeframe con el valor actual
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
        color_map = {
            "info": self.fg_color,
            "success": self.success_color,
            "error": self.error_color,
            "warning": self.warning_color
        }
        
        # Añadir al log principal (oculto pero funcional)
        if not hasattr(self, 'log_text'):
            # Crear log oculto si no existe
            self.log_text = scrolledtext.ScrolledText(self.root, height=1)
            self.log_text.pack_forget()  # Oculto
        
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        
        # Actualizar ventana de logs si está abierta
        if hasattr(self, 'log_text_window') and self.log_text_window.winfo_exists():
            try:
                self.log_text_window.config(state=tk.NORMAL)
                self.log_text_window.insert(tk.END, f"[{timestamp}] {message}\n")
                self.log_text_window.see(tk.END)
                self.log_text_window.config(state=tk.DISABLED)
            except:
                pass
    
    def update_market_info(self):
        """Actualiza la información del mercado en un hilo separado."""
        if self.updating:
            return
        
        # Evitar actualizaciones simultáneas
        if hasattr(self, '_update_scheduled') and self._update_scheduled:
            return
        
        self.updating = True
        self._update_scheduled = True
        
        def update_thread():
            try:
                # Calcular cuántas velas obtener según el período
                timeframe_minutes = self.get_timeframe_minutes()
                bars_needed = self.get_period_bars(self.view_period, timeframe_minutes)
                
                # Operaciones pesadas en hilo separado
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
                
                # Convertir Series a diccionario para poder serializarlo
                last_closed_dict = last_closed.to_dict()
                
                # Enviar datos a la cola para actualizar UI en hilo principal
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
        """Actualiza la UI con los datos del mercado (ejecutado en hilo principal)."""
        try:
            df = data['df']
            last_closed = data['last_closed']
            signal = data['signal']
            market_open = data['market_open']
            market_status = data['market_status']
            
            # Actualizar panel de mercado
            self.market_text.config(state=tk.NORMAL)
            self.market_text.delete(1.0, tk.END)
            
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
            self.market_text.insert(1.0, market_info)
            self.market_text.config(state=tk.DISABLED)
            
            # Guardar datos para gráficos
            self.price_data = df
            
            # Actualizar panel de métricas
            self.update_metrics()
            
            # Actualizar gráficos
            self.update_charts()
            
            # Actualizar historial de operaciones (si la ventana está abierta)
            if hasattr(self, 'trades_tree_window'):
                self.update_trades_history_window()
            
        except Exception as e:
            self.log_message(f"Error al actualizar UI: {e}", "error")
    
    def update_metrics(self):
        """Actualiza las métricas y posición."""
        try:
            position_info = trading.get_position_info(config.SYMBOL, config.MAGIC_NUMBER)
            position_dir = trading.get_open_position_direction(config.SYMBOL, config.MAGIC_NUMBER)
            
            self.metrics_text.config(state=tk.NORMAL)
            self.metrics_text.delete(1.0, tk.END)
            
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
            
            self.metrics_text.insert(1.0, metrics_info)
            self.metrics_text.config(state=tk.DISABLED)
            
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
            
            # Verificar que config.TIMEFRAME está definido
            if config.TIMEFRAME is None:
                return
            
            # Throttling: actualizar gráfico máximo cada 3 segundos para evitar latencia
            import time
            current_time = time.time()
            if current_time - self.last_chart_update < 3.0:  # Aumentado a 3 segundos
                return
            self.last_chart_update = current_time
            
            # Gráfico de precios
            self.price_ax.clear()
            # Usar todas las velas disponibles pero limitar para renderizado
            # Si hay muchas velas, muestrear para evitar congelamientos
            df = self.price_data.copy()
            
            # Muestrear según timeframe para optimizar renderizado
            # Para M1, limitar a 800 velas para evitar freezes (se pueden ver bien con muestreo inteligente)
            if config.TIMEFRAME == mt5.TIMEFRAME_M1:
                max_candles_to_draw = 800  # Reducido para mejor rendimiento
            else:
                max_candles_to_draw = 500
            
            if len(df) > max_candles_to_draw:
                # Muestrear uniformemente
                step = max(1, len(df) // max_candles_to_draw)
                df = df.iloc[::step].copy()
                # Asegurar que la última vela esté incluida
                if len(df) > 0 and len(self.price_data) > 0:
                    if df.index[-1] != self.price_data.index[-1]:
                        df = pd.concat([df, self.price_data.iloc[[-1]]]).drop_duplicates()
            
            # Asegurar que 'time' es datetime
            if not pd.api.types.is_datetime64_any_dtype(df['time']):
                df['time'] = pd.to_datetime(df['time'])
            
            # Usar fechas en el eje X
            x_dates = df['time']
            
            # Dibujar velas japonesas mejoradas
            # Para M1, SIEMPRE dibujar velas completas (el usuario quiere verlas)
            # Para otros timeframes, usar modo simplificado si hay muchas velas
            use_simple_mode = False
            if config.TIMEFRAME == mt5.TIMEFRAME_M1:
                # Para M1, siempre dibujar velas, sin importar cuántas haya
                use_simple_mode = False
            elif config.TIMEFRAME != mt5.TIMEFRAME_M1 and len(df) > 300:
                use_simple_mode = True
            
            if use_simple_mode:
                # Para muchas velas, dibujar solo líneas de precio (más rápido)
                self.price_ax.plot(df['time'], df['close'], color='#0078d4', linewidth=1, label='Close', alpha=0.8, zorder=1)
                # Dibujar bandas directamente
                if not df['upper'].isna().all():
                    self.price_ax.plot(df['time'], df['upper'], color='#ffaa00', linewidth=1, label='Upper', alpha=0.7, zorder=1)
                if not df['average'].isna().all():
                    self.price_ax.plot(df['time'], df['average'], color='#0078d4', linewidth=1.5, label='Average', zorder=1)
                if not df['lower'].isna().all():
                    self.price_ax.plot(df['time'], df['lower'], color='#ffaa00', linewidth=1, label='Lower', alpha=0.7, zorder=1)
            else:
                # Dibujar velas completas usando método optimizado
                try:
                    # Calcular ancho de vela una sola vez (no en cada iteración)
                    timeframe_minutes = self.get_timeframe_minutes()
                    if timeframe_minutes >= 1440:  # D1 o mayor
                        width = pd.Timedelta(hours=12)
                    elif timeframe_minutes >= 60:  # H1, H4
                        width = pd.Timedelta(minutes=timeframe_minutes * 0.6)
                    elif timeframe_minutes == 1:  # M1
                        # Calcular el espaciado promedio entre velas una sola vez
                        if len(df) > 10:
                            time_diffs = df['time'].diff().dropna()
                            if len(time_diffs) > 0:
                                avg_spacing = time_diffs.median()
                                width = avg_spacing * 0.65
                            else:
                                width = pd.Timedelta(minutes=0.85)
                        else:
                            width = pd.Timedelta(minutes=0.85)
                    else:  # M5, M15, M30
                        width = pd.Timedelta(minutes=timeframe_minutes * 0.8)
                    
                    # Convertir width a días para matplotlib
                    width_days = width.total_seconds() / 86400.0
                    
                    # Preparar datos vectorizados
                    times = df['time'].values
                    opens = df['open'].values
                    highs = df['high'].values
                    lows = df['low'].values
                    closes = df['close'].values
                    
                    # Separar velas alcistas y bajistas
                    bullish = closes >= opens
                    bearish = ~bullish
                    
                    # Calcular cuerpos
                    body_lows = np.minimum(opens, closes)
                    body_highs = np.maximum(opens, closes)
                    body_heights = body_highs - body_lows
                    
                    # Dibujar mechas usando método simple (más confiable)
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
                    
                    # Dibujar cuerpos alcistas (verde) - usar bar con arrays
                    if np.any(bullish):
                        bullish_times = times[bullish]
                        bullish_heights = body_heights[bullish]
                        bullish_bottoms = body_lows[bullish]
                        self.price_ax.bar(bullish_times, bullish_heights, 
                                        bottom=bullish_bottoms, width=width_days,
                                        color='#00ff00', edgecolor='#00ff00', 
                                        alpha=0.9, linewidth=0.7, zorder=4)
                    
                    # Dibujar cuerpos bajistas (rojo) - usar bar con arrays
                    if np.any(bearish):
                        bearish_times = times[bearish]
                        bearish_heights = body_heights[bearish]
                        bearish_bottoms = body_lows[bearish]
                        self.price_ax.bar(bearish_times, bearish_heights, 
                                        bottom=bearish_bottoms, width=width_days,
                                        color='#ff0000', edgecolor='#ff0000', 
                                        alpha=0.9, linewidth=0.7, zorder=4)
                    
                    # Dibujar dojis (open == close) - solo si hay pocos
                    doji = body_heights == 0
                    if np.any(doji) and np.sum(doji) < 50:
                        doji_times = times[doji]
                        doji_prices = opens[doji]
                        for t, p in zip(doji_times, doji_prices):
                            # Determinar color basado en la vela anterior
                            idx = np.where(times == t)[0]
                            if len(idx) > 0 and idx[0] > 0:
                                color = '#00ff00' if closes[idx[0]-1] <= p else '#ff0000'
                            else:
                                color = '#00ff00'
                            self.price_ax.plot([t, t], [p-0.0001, p+0.0001], 
                                             color=color, linewidth=2, zorder=4)
                
                except Exception as e:
                    # Si hay error, usar método simple de respaldo
                    self.log_message(f"Error al dibujar velas: {e}", "error")
                    # Dibujar solo línea de cierre como fallback
                    self.price_ax.plot(df['time'], df['close'], color='#0078d4', linewidth=1, label='Close', alpha=0.8, zorder=1)
                
                # Dibujar bandas y media (después de las velas, con zorder más bajo)
                if not df['upper'].isna().all():
                    self.price_ax.plot(df['time'], df['upper'], color='#ffaa00', linewidth=1, label='Upper', alpha=0.7, zorder=2)
                if not df['average'].isna().all():
                    self.price_ax.plot(df['time'], df['average'], color='#0078d4', linewidth=1.5, label='Average', zorder=2)
                if not df['lower'].isna().all():
                    self.price_ax.plot(df['time'], df['lower'], color='#ffaa00', linewidth=1, label='Lower', alpha=0.7, zorder=2)
            
            # Marcar señales (siempre para M1 si hay menos de 1000 velas, para otros si hay menos de 300)
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
            
            # Formatear eje X con fechas
            self.price_ax.set_facecolor('#1e1e1e')
            self.price_ax.tick_params(colors='white', labelsize=10)  # Fuente más grande
            
            # Obtener información del timeframe
            timeframe_str = self.get_timeframe_string()
            timeframe_minutes = self.get_timeframe_minutes()
            
            # Formatear fechas según el timeframe
            try:
                # Calcular número óptimo de etiquetas (máximo 10-12 para legibilidad)
                num_labels = min(12, max(5, len(df) // 50))
                
                if config.TIMEFRAME == mt5.TIMEFRAME_M1:
                    # Para M1, mostrar hora:minuto
                    date_format = mdates.DateFormatter('%H:%M')
                    # Calcular intervalo para mostrar ~10-12 etiquetas
                    total_minutes = (df['time'].iloc[-1] - df['time'].iloc[0]).total_seconds() / 60
                    interval_minutes = max(5, int(total_minutes / num_labels))
                    locator = mdates.MinuteLocator(interval=interval_minutes)
                elif config.TIMEFRAME in [mt5.TIMEFRAME_M5, mt5.TIMEFRAME_M15, mt5.TIMEFRAME_M30]:
                    # Para timeframes de minutos, mostrar hora:minuto
                    date_format = mdates.DateFormatter('%H:%M')
                    total_minutes = (df['time'].iloc[-1] - df['time'].iloc[0]).total_seconds() / 60
                    interval_minutes = max(15, int(total_minutes / num_labels))
                    locator = mdates.MinuteLocator(interval=interval_minutes)
                elif config.TIMEFRAME == mt5.TIMEFRAME_H1:
                    # Para H1, mostrar fecha y hora
                    date_format = mdates.DateFormatter('%m/%d\n%H:%M')
                    total_hours = (df['time'].iloc[-1] - df['time'].iloc[0]).total_seconds() / 3600
                    interval_hours = max(1, int(total_hours / num_labels))
                    locator = mdates.HourLocator(interval=interval_hours)
                elif config.TIMEFRAME == mt5.TIMEFRAME_H4:
                    # Para H4, mostrar fecha y hora
                    date_format = mdates.DateFormatter('%m/%d\n%H:%M')
                    total_hours = (df['time'].iloc[-1] - df['time'].iloc[0]).total_seconds() / 3600
                    interval_hours = max(4, int(total_hours / num_labels))
                    locator = mdates.HourLocator(interval=interval_hours)
                elif config.TIMEFRAME == mt5.TIMEFRAME_D1:
                    # Para D1, mostrar fecha
                    date_format = mdates.DateFormatter('%m/%d')
                    total_days = (df['time'].iloc[-1] - df['time'].iloc[0]).days
                    interval_days = max(1, int(total_days / num_labels))
                    locator = mdates.DayLocator(interval=interval_days)
                else:
                    # Para otros timeframes, mostrar fecha y hora
                    date_format = mdates.DateFormatter('%m/%d\n%H:%M')
                    total_hours = (df['time'].iloc[-1] - df['time'].iloc[0]).total_seconds() / 3600
                    interval_hours = max(1, int(total_hours / num_labels))
                    locator = mdates.HourLocator(interval=interval_hours)
            except Exception as e:
                # Fallback si hay error
                date_format = mdates.DateFormatter('%H:%M')
                locator = mdates.MinuteLocator(interval=10)
                self.log_message(f"Error al formatear fechas: {e}", "error")
            
            self.price_ax.xaxis.set_major_formatter(date_format)
            self.price_ax.xaxis.set_major_locator(locator)
            # Rotar etiquetas 45 grados y ajustar espaciado
            self.price_fig.autofmt_xdate(rotation=45, ha='right')
            # Ajustar padding para que las etiquetas no se corten
            self.price_fig.subplots_adjust(bottom=0.15)
            
            # Información adicional en el título
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
            
            # Añadir información de precio actual en el gráfico
            if len(df) > 0:
                last_price = df['close'].iloc[-1]
                self.price_ax.axhline(y=last_price, color='yellow', linestyle=':', linewidth=1, 
                                    alpha=0.5, label=f'Último: {last_price:.2f}')
            
            self.price_fig.tight_layout(pad=2)
            self.price_canvas.draw()
            
            # Gráfico de equity
            self.equity_ax.clear()
            
            # Obtener historial de operaciones de MT5
            try:
                # Intentar obtener operaciones del último mes
                start_date = datetime.now().replace(day=1) if datetime.now().day > 1 else (datetime.now() - pd.Timedelta(days=30))
                positions = mt5.history_deals_get(start_date, datetime.now())
                
                if positions:
                    # Filtrar por magic number
                    filtered_positions = [p for p in positions if hasattr(p, 'magic') and p.magic == config.MAGIC_NUMBER]
                    
                    if filtered_positions:
                        equity_data = []
                        balance = 10000.0  # Balance inicial
                        
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
                        # Si no hay operaciones, mostrar línea plana
                        self.equity_ax.axhline(y=10000, color='gray', linewidth=2, label='Initial Balance')
                else:
                    # Si no hay operaciones, mostrar línea plana
                    self.equity_ax.axhline(y=10000, color='gray', linewidth=2, label='Initial Balance')
            except Exception:
                # Si hay error, mostrar línea plana
                self.equity_ax.axhline(y=10000, color='gray', linewidth=2, label='Initial Balance')
            
            self.equity_ax.set_facecolor('#1e1e1e')
            self.equity_ax.tick_params(colors='white', labelsize=10)  # Fuente más grande
            self.equity_ax.set_title('Equity Curve', color='white', fontsize=13)
            self.equity_ax.set_xlabel('Tiempo', color='white', fontsize=12)
            self.equity_ax.set_ylabel('Equity', color='white', fontsize=12)
            self.equity_ax.legend(loc='upper left', fontsize=9, facecolor='#2d2d2d', edgecolor='white')
            self.equity_ax.grid(True, alpha=0.3, color='gray')
            self.equity_fig.tight_layout(pad=2)
            self.equity_canvas.draw()
            
        except Exception as e:
            self.log_message(f"Error al actualizar gráficos: {e}", "error")
    
    def update_trades_history(self):
        """Actualiza el historial de operaciones (método legacy, ahora usa update_trades_history_window)."""
        self.update_trades_history_window()
    
    def update_trades_history_window(self):
        """Actualiza el historial de operaciones en la ventana de logs."""
        try:
            # Determinar qué treeview usar
            tree = None
            if hasattr(self, 'trades_tree_window') and self.trades_tree_window.winfo_exists():
                tree = self.trades_tree_window
            elif hasattr(self, 'trades_tree'):
                tree = self.trades_tree
            
            if tree is None:
                return
            
            # Limpiar treeview
            for item in tree.get_children():
                tree.delete(item)
            
            # Obtener historial de operaciones
            try:
                start_date = datetime.now().replace(day=1) if datetime.now().day > 1 else (datetime.now() - pd.Timedelta(days=30))
                positions = mt5.history_deals_get(start_date, datetime.now())
                
                if positions:
                    # Filtrar por magic number
                    positions = [p for p in positions if hasattr(p, 'magic') and p.magic == config.MAGIC_NUMBER]
            except Exception:
                positions = None
            
            if positions:
                # Agrupar por ticket para obtener operaciones completas
                trades_dict = {}
                for deal in positions:
                    ticket = deal.position_id
                    if ticket not in trades_dict:
                        trades_dict[ticket] = {'entry': None, 'exit': None}
                    
                    if deal.entry == mt5.DEAL_ENTRY_IN:
                        trades_dict[ticket]['entry'] = deal
                    elif deal.entry == mt5.DEAL_ENTRY_OUT:
                        trades_dict[ticket]['exit'] = deal
                
                # Añadir a treeview
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
                
                # Configurar colores
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
            
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.status_label.config(text="▶ Ejecutando", fg=self.success_color)
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
        
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_label.config(text="⏸ Detenido", fg=self.warning_color)
        self.log_message("⏹ Bot detenido", "warning")
    
    def bot_loop(self):
        """Bucle principal del bot (ejecutado en hilo separado)."""
        try:
            while self.bot_running and not self.stop_event.is_set():
                try:
                    # Obtener datos
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
                    
                    # Actualizar UI en el hilo principal
                    self.message_queue.put(('update_market', None))
                    
                    # Aplicar señal si existe y mercado abierto
                    if signal != "none" and market_open:
                        self.message_queue.put(('signal', signal))
                        trading.apply_signal(
                            config.SYMBOL, signal, config.LOT,
                            config.SL_POINTS, config.TP_POINTS, config.MAGIC_NUMBER
                        )
                    
                    # Esperar antes de la siguiente iteración
                    # Usar intervalo mínimo de 10 segundos para reducir latencia
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
        """Procesa mensajes de la cola (ejecutado en hilo principal)."""
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
                    self.start_btn.config(state=tk.NORMAL)
                    self.stop_btn.config(state=tk.DISABLED)
                    self.status_label.config(text="⏸ Detenido", fg=self.warning_color)
                    
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
        
        # Actualizar información periódicamente incluso si el bot está detenido
        # Reducir frecuencia para evitar latencia (cada 10 segundos en lugar de 5)
        if not self.bot_running and not self.updating:
            self.root.after(10000, self.update_market_info)
    
    def on_timeframe_change(self, event=None):
        """Maneja el cambio de timeframe en el combobox."""
        # Este método se llama cuando se selecciona un timeframe
        # pero no aplica el cambio hasta que se presiona el botón
        pass
    
    def on_period_change(self, event=None):
        """Maneja el cambio de período en el combobox."""
        # Este método se llama cuando se selecciona un período
        # pero no aplica el cambio hasta que se presiona el botón
        pass
    
    def get_period_bars(self, period_str, timeframe_minutes):
        """
        Calcula cuántas velas obtener según el período seleccionado.
        
        Args:
            period_str: Período seleccionado ("1D", "5D", "1M", etc.)
            timeframe_minutes: Minutos del timeframe actual
        
        Returns:
            int: Número de velas a obtener
        """
        # Calcular minutos en cada período
        minutes_per_day = 24 * 60
        minutes_per_week = 7 * minutes_per_day
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
            # Año hasta la fecha (desde enero 1 hasta ahora)
            now = datetime.now()
            year_start = datetime(now.year, 1, 1)
            days_passed = (now - year_start).days
            bars = (days_passed * minutes_per_day) // timeframe_minutes
        elif period_str == "1A":
            bars = (1 * minutes_per_year) // timeframe_minutes
        elif period_str == "5A":
            bars = (5 * minutes_per_year) // timeframe_minutes
        elif period_str == "Todo":
            # Máximo razonable: 5,000 velas para evitar congelamientos
            bars = 5000
        else:
            bars = 500  # Por defecto
        
        # Asegurar mínimo y máximo razonables
        # Limitar a 5000 velas máximo para evitar congelamientos
        return max(100, min(bars, 5000))
    
    def apply_period(self):
        """Aplica el período de visualización seleccionado."""
        try:
            period_str = self.period_var.get()
            self.view_period = period_str
            self.log_message(f"✅ Período de visualización cambiado a {period_str}", "success")
            # Actualizar información del mercado con el nuevo período
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
                
                # Verificar que el símbolo soporta este timeframe
                try:
                    symbol_info = mt5.symbol_info(config.SYMBOL)
                    if symbol_info is None:
                        raise Exception(f"Símbolo {config.SYMBOL} no encontrado")
                    
                    # Intentar obtener una vela para verificar que el timeframe funciona
                    rates = mt5.copy_rates_from_pos(config.SYMBOL, config.TIMEFRAME, 0, 1)
                    if rates is None or len(rates) == 0:
                        # Revertir cambio si no hay datos
                        config.TIMEFRAME = old_timeframe
                        self.log_message(f"❌ No hay datos disponibles para {timeframe_str} en {config.SYMBOL}", "error")
                        messagebox.showerror("Error", f"No hay datos disponibles para el timeframe {timeframe_str}.\nEl timeframe se mantiene en el anterior.")
                        return
                    
                    self.log_message(f"✅ Timeframe cambiado a {timeframe_str}", "success")
                    # Limpiar datos anteriores
                    self.price_data = None
                    # Actualizar información del mercado con el nuevo timeframe
                    self.update_market_info()
                except Exception as e:
                    # Revertir cambio si hay error
                    config.TIMEFRAME = old_timeframe
                    self.log_message(f"❌ Error al cambiar timeframe: {e}", "error")
                    messagebox.showerror("Error", f"No se pudo cambiar al timeframe {timeframe_str}:\n{e}")
            else:
                self.log_message(f"❌ Timeframe no válido: {timeframe_str}", "error")
        except Exception as e:
            self.log_message(f"❌ Error inesperado al aplicar timeframe: {e}", "error")
            import traceback
            traceback.print_exc()
    
    def check_control_pressed(self):
        """Verifica si Control está presionado usando múltiples métodos."""
        # Método 1: Estado guardado
        if self.control_pressed:
            return True
        
        # Método 2: Verificar estado del teclado usando tkinter
        try:
            canvas_widget = self.price_canvas.get_tk_widget()
            # En Windows, podemos verificar el estado usando eventos
            # Pero esto requiere que el widget tenga el foco
            if canvas_widget.focus_get() == canvas_widget:
                # El canvas tiene el foco, pero no podemos verificar directamente
                # sin eventos, así que confiamos en self.control_pressed
                pass
        except:
            pass
        
        return False
    
    def show_tooltip(self, x, y, text):
        """Muestra un tooltip flotante en la posición del mouse."""
        # Destruir tooltip anterior si existe
        if self.candle_tooltip is not None:
            try:
                self.candle_tooltip.destroy()
            except:
                pass
        
        # Crear nueva ventana de tooltip
        self.candle_tooltip = tk.Toplevel(self.root)
        self.candle_tooltip.wm_overrideredirect(True)  # Sin bordes
        self.candle_tooltip.wm_geometry(f"+{x+10}+{y+10}")  # Posición cerca del cursor
        self.candle_tooltip.configure(bg='#2d2d2d', padx=10, pady=5)
        
        # Crear label con la información
        label = tk.Label(self.candle_tooltip, 
                        text=text,
                        bg='#2d2d2d', 
                        fg='#00ff00',
                        font=('Consolas', 9, 'bold'),
                        justify=tk.LEFT)
        label.pack()
        
        # Asegurar que el tooltip esté encima de todo
        self.candle_tooltip.attributes('-topmost', True)
    
    def hide_tooltip(self):
        """Oculta el tooltip."""
        if self.candle_tooltip is not None:
            try:
                self.candle_tooltip.destroy()
                self.candle_tooltip = None
            except:
                pass
    
    def on_price_chart_hover(self, event):
        """Maneja el movimiento del mouse sobre el gráfico de precios."""
        if event.inaxes != self.price_ax:
            # Si el mouse está fuera del gráfico, ocultar tooltip
            self.hide_tooltip()
            return
        
        # Si tenemos datos, mostrar información
        if self.price_data is None or len(self.price_data) == 0:
            self.hide_tooltip()
            return
        
        try:
            # Convertir coordenadas del mouse a coordenadas de datos
            x_data = mdates.num2date(event.xdata)
            y_data = event.ydata
            
            # Encontrar la vela más cercana
            df = self.price_data.copy()
            if 'time' not in df.columns:
                return
            
            # Convertir time a datetime si no lo es
            if not pd.api.types.is_datetime64_any_dtype(df['time']):
                df['time'] = pd.to_datetime(df['time'])
            
            # Calcular la diferencia de tiempo entre el cursor y cada vela
            df['time_diff'] = (df['time'] - x_data).abs()
            
            # Encontrar la vela más cercana
            closest_idx = df['time_diff'].idxmin()
            closest_row = df.loc[closest_idx]
            
            # Verificar que la vela esté lo suficientemente cerca (dentro de un rango razonable)
            timeframe_minutes = self.get_timeframe_minutes()
            max_time_diff = pd.Timedelta(minutes=timeframe_minutes * 2)  # 2 veces el timeframe
            
            if df.loc[closest_idx, 'time_diff'] > max_time_diff:
                # Muy lejos, no mostrar información
                self.hide_tooltip()
                return
            
            # Formatear información de la vela
            candle_time = closest_row['time']
            time_str = candle_time.strftime('%Y-%m-%d %H:%M:%S')
            
            # Calcular variación del precio
            price_change = closest_row.get('close', 0) - closest_row.get('open', 0)
            price_change_pct = (price_change / closest_row.get('open', 1)) * 100 if closest_row.get('open', 0) != 0 else 0
            
            # Formatear información para el tooltip (más legible)
            info_lines = [
                f"🕐 {time_str}",
                f"O: {closest_row.get('open', 'N/A'):.5f}  H: {closest_row.get('high', 'N/A'):.5f}",
                f"L: {closest_row.get('low', 'N/A'):.5f}  C: {closest_row.get('close', 'N/A'):.5f}",
                f"Δ: {price_change:+.5f} ({price_change_pct:+.2f}%)",
            ]
            
            # Agregar información adicional si está disponible
            if 'average' in closest_row and pd.notna(closest_row['average']):
                info_lines.append(f"Avg: {closest_row['average']:.5f}")
            if 'upper' in closest_row and pd.notna(closest_row['upper']):
                info_lines.append(f"Upper: {closest_row['upper']:.5f}")
            if 'lower' in closest_row and pd.notna(closest_row['lower']):
                info_lines.append(f"Lower: {closest_row['lower']:.5f}")
            if 'dir_1' in closest_row and pd.notna(closest_row['dir_1']):
                dir_val = "LONG" if closest_row['dir_1'] == 1 else "SHORT" if closest_row['dir_1'] == -1 else "NEUTRAL"
                info_lines.append(f"Dir: {dir_val}")
            if 'up_sig' in closest_row and closest_row.get('up_sig', False):
                info_lines.append("🟢 SEÑAL COMPRA")
            if 'dn_sig' in closest_row and closest_row.get('dn_sig', False):
                info_lines.append("🔴 SEÑAL VENTA")
            
            # Obtener posición del mouse en la pantalla
            # El evento de matplotlib tiene coordenadas en píxeles del canvas
            canvas_widget = self.price_canvas.get_tk_widget()
            
            # Obtener posición del canvas en la ventana
            canvas_x = canvas_widget.winfo_x()
            canvas_y = canvas_widget.winfo_y()
            
            # Obtener posición de la ventana en la pantalla
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            
            # Convertir coordenadas del evento a coordenadas de pantalla
            # event.x y event.y están en píxeles del canvas (coordenadas de pantalla del canvas)
            # Necesitamos las coordenadas en píxeles del canvas, no en coordenadas de datos
            try:
                # Obtener las coordenadas del canvas en píxeles
                canvas_bbox = canvas_widget.bbox()
                if canvas_bbox:
                    # event.x y event.y son las coordenadas del mouse en píxeles del canvas
                    mouse_x = root_x + canvas_x + int(event.x) if hasattr(event, 'x') else root_x + canvas_x
                    mouse_y = root_y + canvas_y + int(event.y) if hasattr(event, 'y') else root_y + canvas_y
                else:
                    # Fallback: usar coordenadas de la ventana
                    mouse_x = root_x + canvas_x + 100
                    mouse_y = root_y + canvas_y + 100
            except:
                # Fallback simple
                mouse_x = root_x + canvas_x + 100
                mouse_y = root_y + canvas_y + 100
            
            # Mostrar tooltip
            info_text = "\n".join(info_lines)
            self.show_tooltip(mouse_x, mouse_y, info_text)
            
        except Exception as e:
            # Si hay error, ocultar tooltip
            self.hide_tooltip()
    
    def on_closing(self):
        """Maneja el cierre de la ventana."""
        if self.bot_running:
            self.stop_bot()
            self.bot_thread.join(timeout=2)
        mt5.shutdown()
        self.root.destroy()


def main():
    """Función principal para iniciar la GUI."""
    root = tk.Tk()
    app = TradingBotGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()

