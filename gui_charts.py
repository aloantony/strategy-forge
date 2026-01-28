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
import json

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
        self.last_action_info = None
        self._action_tooltip_ready = False
        self.action_markers = []
        self.max_action_markers = 1  # mostrar solo la última operación para evitar ruido
        self.quote_thread = None
        self.quote_stop_event = threading.Event()

        # Panel de indicadores
        self.indicator_panel = None
        self.indicator_rows = {}
        self.indicator_state = {}
        self.indicator_series = {}

        # Colores para indicadores de acción
        self.success_color = '#26a69a'
        self.error_color = '#ef5350'
        self.warning_color = '#ffaa00'
        self.accent_color = '#2196f3'
        
        # Crear gráfico principal
        self.chart = Chart(toolbox=True, inner_height=0.7)
        
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
        self.supertrend_up_line = self.chart.create_line(name='Supertrend Up', color='#4caf50', width=2)
        self.supertrend_down_line = self.chart.create_line(name='Supertrend Down', color='#ef5350', width=2)
        
        # Crear subchart para equity (curva de beneficios)
        self.equity_chart = self.chart.create_subchart(height=0.15, sync=True)
        self.equity_chart.layout(background_color='#131722', text_color='#d1d4dc')
        self.equity_line = self.equity_chart.create_line(name='Equity', color='#4caf50', width=2)

        # Subchart para TuTCI
        self.tci_chart = self.chart.create_subchart(height=0.15, sync=True)
        self.tci_chart.layout(background_color='#131722', text_color='#d1d4dc')
        self.tci_hist = self.tci_chart.create_histogram(
            name='TuTCI',
            color='#c0a65b',
            price_line=False,
            price_label=True,
            scale_margin_top=0.2,
            scale_margin_bottom=0.2
        )
        self.tci_signal = self.tci_chart.create_line(name='TuTCI Signal', color='#ffd54f', width=2)

        # Mapa de series para el panel de indicadores
        self.indicator_series = {
            "baseline": [self.average_line],
            "atr_bands": [self.upper_line, self.lower_line],
            "supertrend": [self.supertrend_up_line, self.supertrend_down_line],
            "tci": [self.tci_hist, self.tci_signal],
            "equity": [self.equity_line],
        }
        
        # Estilos y controles
        self._inject_custom_styles()
        self.setup_topbar()
        self.setup_indicator_panel()
        
        # Nota: los hotkeys requieren un modificador (shift, alt, ctrl, meta)
        # Ejemplo: self.chart.hotkey('shift', 'S', self.start_bot)
        # Por ahora usamos los botones de la topbar
        
    def setup_topbar(self):
        """Configura la barra superior con controles."""
        # Cotizaciones rápidas (estilo TradingView)
        self.chart.topbar.textbox('sell_quote', 'SELL --', align='left')
        self.chart.topbar.textbox('buy_quote', 'BUY --', align='left')
        self.chart.topbar.textbox('spread', 'Spread: --', align='left')
        self._style_quote_widgets()

        # Texto de ayuda
        self.chart.topbar.textbox(
            'help',
            'Ojo=Mostrar/Ocultar linea | Scroll=Zoom | Arrastrar=Mover',
            align='left'
        )

        # Switcher de timeframe
        self.chart.topbar.switcher(
            'timeframe',
            ('M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'),
            default='M1',
            func=self.on_timeframe_change,
            align='left'
        )

        # Switcher de período
        self.chart.topbar.switcher(
            'period',
            ('1D', '5D', '1M', '3M', '6M', 'YTD', '1Y', '5Y', 'All'),
            default='1D',
            func=self.on_period_change,
            align='left'
        )

        # Selector de símbolo desde MT5 (solo símbolos con trading habilitado)
        symbols_enabled = self.get_enabled_symbols()
        if config.SYMBOL not in symbols_enabled:
            symbols_enabled.insert(0, config.SYMBOL)
        self.chart.topbar.switcher(
            'symbol_select',
            tuple(symbols_enabled[:50]),  # limitar tamaño de la lista
            default=config.SYMBOL,
            func=self.on_symbol_change,
            align='left'
        )
        self.chart.topbar.button('reload_symbols', 'Recargar símbolos', func=self.reload_symbols, align='left')

        # Filling mode
        self.chart.topbar.textbox('fill_label', 'Filling:', align='left')
        current_fill = getattr(config, "FILLING_MODE_OVERRIDE", "AUTO")
        default_fill = current_fill if current_fill in ("AUTO", "FOK", "IOC", "RETURN") else "AUTO"
        self.chart.topbar.switcher(
            'filling_mode',
            ('AUTO', 'FOK', 'IOC', 'RETURN'),
            default=default_fill,
            func=self.on_filling_change,
            align='left'
        )

        # Estado del bot (derecha)
        self.chart.topbar.textbox('status_label', 'Estado:', align='right')
        self.chart.topbar.textbox('status', 'Detenido', align='right')

        # Balance en tiempo real
        self.chart.topbar.textbox('balance_label', 'Balance:', align='right')
        self.chart.topbar.textbox('balance', '---', align='right')

        # Indicador de última acción
        self.chart.topbar.textbox('action_label', 'Acción:', align='right')
        self.chart.topbar.textbox('action_icon', '⚪', align='right')
        self.chart.topbar.textbox('action_text', 'Sin acciones todavía', align='right')
        self._ensure_action_tooltip()

        # Botones con nombres descriptivos
        self.chart.topbar.button('start', 'Iniciar Bot', func=self.start_bot, align='right')
        self.chart.topbar.button('stop', 'Detener Bot', func=self.stop_bot, align='right')
        self.chart.topbar.button('refresh', 'Actualizar Datos', func=self.refresh_data, align='right')

    def _inject_custom_styles(self):
        """Inyecta estilos CSS para emular la estética TradingView."""
        self.chart.run_script('''
            if (!document.getElementById("trading-ui-style")) {
                const style = document.createElement("style");
                style.id = "trading-ui-style";
                style.innerHTML = `
                    .quote-box {
                        display: flex;
                        flex-direction: column;
                        align-items: flex-start;
                        justify-content: center;
                        padding: 4px 10px;
                        border-radius: 6px;
                        line-height: 1.05;
                        min-width: 78px;
                    }
                    .quote-box .quote-label {
                        font-size: 10px;
                        letter-spacing: 0.06em;
                        text-transform: uppercase;
                        opacity: 0.9;
                    }
                    .quote-box .quote-price {
                        font-size: 13px;
                        font-weight: 600;
                    }
                    .quote-box.sell { background: #b71c1c; color: #ffffff; }
                    .quote-box.buy { background: #1e88e5; color: #ffffff; }
                    .quote-box.neutral { background: #1c2230; color: #d1d4dc; }

                    .indicator-panel {
                        box-shadow: 0 6px 18px rgba(0,0,0,0.35);
                        border-radius: 8px;
                    }
                    .indicator-panel table th {
                        font-size: 11px;
                        letter-spacing: 0.04em;
                    }
                `;
                document.head.appendChild(style);
            }
        ''')

    def _style_quote_widgets(self):
        """Aplica clases a las cajas de cotización."""
        try:
            sell_id = self.chart.topbar['sell_quote'].id
            buy_id = self.chart.topbar['buy_quote'].id
            spread_id = self.chart.topbar['spread'].id
        except Exception:
            return

        self.chart.run_script(f'''
            {sell_id}.classList.add("quote-box", "sell");
            {buy_id}.classList.add("quote-box", "buy");
            {spread_id}.classList.add("quote-box", "neutral");
        ''')

    def _set_quote_box(self, widget_key: str, label: str, price_text: str):
        """Actualiza el HTML de una caja de cotización."""
        widget = self.chart.topbar.get(widget_key)
        if not widget:
            return
        html = f"<div class='quote-label'>{label}</div><div class='quote-price'>{price_text}</div>"
        widget_id = widget.id
        self.chart.run_script(f"{widget_id}.innerHTML = {json.dumps(html)}")

    def update_quotes(self):
        """Actualiza las cotizaciones BUY/SELL y el spread."""
        try:
            tick = mt5.symbol_info_tick(config.SYMBOL)
            info = mt5.symbol_info(config.SYMBOL)
            if tick is None or info is None:
                return

            digits = getattr(info, "digits", 2)
            bid = getattr(tick, "bid", None)
            ask = getattr(tick, "ask", None)

            if bid is None or ask is None:
                return

            price_fmt = f"{{:.{digits}f}}"
            bid_text = price_fmt.format(bid)
            ask_text = price_fmt.format(ask)
            spread_text = price_fmt.format(ask - bid) if ask is not None and bid is not None else "--"

            self._set_quote_box("sell_quote", "SELL", bid_text)
            self._set_quote_box("buy_quote", "BUY", ask_text)
            self._set_quote_box("spread", "SPREAD", spread_text)
        except Exception as e:
            self.log_message(f"Error al actualizar cotizaciones: {e}")

    def start_quote_updater(self):
        """Inicia un hilo para refrescar cotizaciones periódicamente."""
        if self.quote_thread and self.quote_thread.is_alive():
            return
        self.quote_stop_event.clear()
        self.quote_thread = threading.Thread(target=self._quote_loop, daemon=True)
        self.quote_thread.start()

    def stop_quote_updater(self):
        """Detiene el hilo de cotizaciones."""
        self.quote_stop_event.set()

    def _quote_loop(self):
        while not self.quote_stop_event.is_set():
            self.update_quotes()
            if self.quote_stop_event.wait(timeout=2):
                break

    def setup_indicator_panel(self):
        """Crea el panel lateral de indicadores (Object Tree)."""
        try:
            self.indicator_panel = self.chart.create_table(
                width=0.18,
                height=0.55,
                headings=("Indicador", "Vis"),
                widths=(0.78, 0.22),
                alignments=("left", "center"),
                position='right',
                draggable=True,
                background_color='#10141c',
                border_color='#2a2e39',
                border_width=1,
                heading_text_colors=('#d1d4dc', '#d1d4dc'),
                heading_background_colors=('#1c2230', '#1c2230'),
                return_clicked_cells=True,
                func=self.on_indicator_panel_click
            )
            self.indicator_panel.header(1)
            self.indicator_panel.header[0] = "Object Tree"
            self.chart.run_script(f'{self.indicator_panel.id}._div.classList.add("indicator-panel")')

            self._register_indicator("baseline", "Baseline", True)
            self._register_indicator("atr_bands", "ATR Bands", True)
            self._register_indicator("supertrend", "Supertrend w/ HMA", True)
            self._register_indicator("tci", "TuTCI", True)
            self._register_indicator("equity", "Equity", True)
        except Exception as e:
            self.log_message(f"No se pudo crear el panel de indicadores: {e}")

    def _register_indicator(self, key: str, label: str, visible: bool = True):
        self.indicator_state[key] = visible
        row = self.indicator_panel.new_row(label, "👁" if visible else "🚫")
        row.meta["key"] = key
        self.indicator_rows[key] = row
        self._apply_indicator_visibility(key, visible)
        self._update_indicator_row(key)

    def on_indicator_panel_click(self, row, column=None):
        key = row.meta.get("key") if row else None
        if not key:
            return
        self.toggle_indicator(key)

    def toggle_indicator(self, key: str):
        visible = not self.indicator_state.get(key, True)
        self.indicator_state[key] = visible
        self._apply_indicator_visibility(key, visible)
        self._update_indicator_row(key)

    def _apply_indicator_visibility(self, key: str, visible: bool):
        series_list = self.indicator_series.get(key, [])
        for series in series_list:
            if series is None:
                continue
            if visible:
                series.show_data()
            else:
                series.hide_data()

    def _update_indicator_row(self, key: str):
        row = self.indicator_rows.get(key)
        if not row:
            return
        visible = self.indicator_state.get(key, True)
        row['Vis'] = "👁" if visible else "🚫"
        color = "#d1d4dc" if visible else "#6b7280"
        row._style('color', 'Indicador', color)
        row._style('color', 'Vis', color)
        row._style('opacity', 'Indicador', '1' if visible else '0.6')
        row._style('opacity', 'Vis', '1' if visible else '0.6')
    
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
            self.update_balance()
            self.update_quotes()
            return True
            
        except Exception as e:
            self.log_message(f"Error al inicializar MT5: {e}")
            return False

    def update_balance(self):
        """Actualiza el balance en la barra superior."""
        try:
            info = mt5.account_info()
            if info is None:
                return
            balance = f"{info.balance:.2f}"
            self.chart.topbar['balance'].set(balance)
        except Exception as e:
            self.log_message(f"Error al actualizar balance: {e}")
    
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
        now = datetime.now()
        start_year = datetime(now.year, 1, 1)
        ytd_minutes = int((now - start_year).total_seconds() / 60)
        
        period_minutes = {
            "1D": 1 * minutes_per_day,
            "5D": 5 * minutes_per_day,
            "1M": 1 * minutes_per_month,
            "3M": 3 * minutes_per_month,
            "6M": 6 * minutes_per_month,
            "YTD": ytd_minutes,
            "1A": 1 * minutes_per_year,
            "1Y": 1 * minutes_per_year,
            "5Y": 5 * minutes_per_year,
            "All": 10000 * timeframe_minutes,
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
                df = data_feed.add_supertrend(
                    df,
                    atr_length=getattr(config, "SUPERTREND_ATR_LENGTH", config.ATR_LENGTH),
                    atr_mult=getattr(config, "SUPERTREND_MULT", 3.0),
                    source_col=getattr(config, "SUPERTREND_SOURCE", "close"),
                    use_hma=getattr(config, "SUPERTREND_USE_HMA", True),
                    hma_length=getattr(config, "HMA_LENGTH", 55)
                )
                df = data_feed.add_tci(
                    df,
                    fast_length=getattr(config, "TCI_FAST", 9),
                    slow_length=getattr(config, "TCI_SLOW", 21),
                    signal_length=getattr(config, "TCI_SIGNAL", 5)
                )
                df = strategy_baseline.compute_dir1_and_signals(df, config.ENABLE_SIGNALS)
                
                if len(df) < 2:
                    return
                
                self.price_data = df
                self.update_chart(df)
                self.update_equity_chart()
                self.update_tci_chart(df)
                self.update_balance()
                self.update_quotes()
                
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

            # Supertrend
            if 'supertrend_up' in df.columns:
                st_up = df[['time', 'supertrend_up']].dropna().copy()
                st_up = st_up.reset_index(drop=True)
                st_up = st_up.rename(columns={'supertrend_up': 'Supertrend Up'})
                if len(st_up) > 0:
                    self.supertrend_up_line.set(st_up)
                else:
                    self.supertrend_up_line.set(pd.DataFrame())

            if 'supertrend_down' in df.columns:
                st_down = df[['time', 'supertrend_down']].dropna().copy()
                st_down = st_down.reset_index(drop=True)
                st_down = st_down.rename(columns={'supertrend_down': 'Supertrend Down'})
                if len(st_down) > 0:
                    self.supertrend_down_line.set(st_down)
                else:
                    self.supertrend_down_line.set(pd.DataFrame())
            
            # Marcar operaciones reales (deals de entrada con el magic number)
            try:
                start_time = df['time'].iloc[0].to_pydatetime()
                end_time = df['time'].iloc[-1].to_pydatetime()
                deals = mt5.history_deals_get(start_time, end_time)

                markers = []
                action_markers = []

                if deals:
                    # Deduplicar por position_id (evitar múltiples fills por la misma operación)
                    dedup = {}
                    for deal in deals:
                        if deal.symbol != config.SYMBOL:
                            continue
                        if hasattr(deal, "magic") and deal.magic != config.MAGIC_NUMBER:
                            continue
                        if deal.entry != mt5.DEAL_ENTRY_IN:
                            continue
                        position_id = getattr(deal, "position_id", None) or getattr(deal, "ticket", None)
                        prev = dedup.get(position_id)
                        if prev is None or getattr(deal, "time", 0) > getattr(prev, "time", 0):
                            dedup[position_id] = deal

                    # Limitar a las operaciones más recientes
                    dedup_deals = sorted(dedup.values(), key=lambda d: getattr(d, "time", 0))
                    if self.max_action_markers and len(dedup_deals) > self.max_action_markers:
                        dedup_deals = dedup_deals[-self.max_action_markers:]

                    for deal in dedup_deals:
                        is_buy = deal.type == mt5.DEAL_TYPE_BUY
                        direction = "BUY" if is_buy else "SELL"
                        color = '#26a69a' if is_buy else '#ef5350'
                        marker_time = datetime.fromtimestamp(deal.time)

                        markers.append({
                            "time": marker_time,
                            "position": 'below' if is_buy else 'above',
                            "shape": 'arrow_up' if is_buy else 'arrow_down',
                            "color": color,
                            "text": direction
                        })

                        # Coordenadas para tooltip (alineadas al timeframe)
                        try:
                            aligned_time = float(self.chart._single_datetime_format(marker_time))
                        except Exception:
                            aligned_time = float(deal.time)

                        price = getattr(deal, "price", None)
                        if isinstance(price, (int, float)):
                            tooltip_text = self._format_deal_tooltip(deal, direction)
                            action_markers.append({
                                "time": aligned_time,
                                "price": float(price),
                                "tooltip": tooltip_text,
                                "direction": direction
                            })

                # Limpiar y reponer marcadores para evitar duplicados
                self.chart.clear_markers()
                if markers:
                    self.chart.marker_list(markers)

                self._set_action_markers(action_markers)

            except Exception as e:
                self.log_message(f"Error al marcar operaciones: {e}")

        except Exception as e:
            self.log_message(f"Error al actualizar grafico: {e}")
            import traceback
            traceback.print_exc()

    def update_last_action_ui(self, action_info):
        """Actualiza el indicador de última acción en la topbar."""
        if not action_info:
            return
        self.last_action_info = action_info

        icon, color, summary = self._build_action_summary(action_info)
        self.chart.topbar['action_icon'].set(icon)
        self.chart.topbar['action_text'].set(summary)

        icon_id = self.chart.topbar['action_icon'].id
        text_id = self.chart.topbar['action_text'].id
        self.chart.run_script(f'{icon_id}.style.color = "{color}"')
        self.chart.run_script(f'{text_id}.style.color = "{color}"')

        # El tooltip ahora se gestiona desde los marcadores del gráfico

    def _build_action_summary(self, action_info):
        """Genera icono y resumen de la última acción."""
        actions = action_info.get("actions", []) if isinstance(action_info, dict) else []
        if not actions:
            return "⚪", '#888888', "Sin acciones todavía"

        any_failed = any(a.get("success") is False for a in actions if isinstance(a, dict))
        has_open = any(a.get("kind") == "open" for a in actions if isinstance(a, dict))
        has_close = any(a.get("kind") == "close" for a in actions if isinstance(a, dict))

        if any_failed:
            return "⚠️", self.error_color, "Acción con error (ver detalle)"

        if has_open and has_close:
            open_action = next((a for a in actions if a.get("kind") == "open"), None)
            direction = (open_action or {}).get("direction", "").upper()
            summary = f"Reverso a {direction}" if direction else "Reverso de posición"
            return "🔁", self.accent_color, summary

        if has_open:
            open_action = next((a for a in actions if a.get("kind") == "open"), None)
            direction = (open_action or {}).get("direction", "").upper()
            if direction == "BUY":
                return "🟢", self.success_color, "Apertura BUY"
            if direction == "SELL":
                return "🔴", self.error_color, "Apertura SELL"
            return "✅", self.success_color, "Apertura"

        if has_close:
            close_action = next((a for a in actions if a.get("kind") == "close"), None)
            direction = (close_action or {}).get("direction", "").upper()
            summary = f"Cierre {direction}" if direction else "Cierre"
            return "⚪", self.warning_color, summary

        return "✅", self.success_color, "Acción ejecutada"

    def _format_deal_tooltip(self, deal, direction):
        """Construye el tooltip para una operación (deal)."""
        lines = []
        try:
            deal_time = datetime.fromtimestamp(deal.time)
            lines.append(f"🕒 {deal_time.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception:
            pass

        symbol = getattr(deal, "symbol", None)
        if symbol:
            lines.append(f"Símbolo: {symbol}")

        if direction:
            lines.append(f"Señal: {direction}")

        lines.append("")
        lines.append("Detalles:")

        ticket = getattr(deal, "position_id", None) or getattr(deal, "ticket", None)
        if ticket:
            lines.append(f"   Ticket: {ticket}")

        price = getattr(deal, "price", None)
        if isinstance(price, (int, float)):
            lines.append(f"   Precio: {price:.5f}")

        volume = getattr(deal, "volume", None)
        if isinstance(volume, (int, float)):
            lines.append(f"   Volumen: {volume:.2f}")

        profit = getattr(deal, "profit", None)
        if isinstance(profit, (int, float)) and abs(profit) > 0:
            lines.append(f"   Profit: {profit:.2f}")

        comment = getattr(deal, "comment", None)
        if comment:
            lines.append(f"   Comentario: {comment}")

        return "\n".join(lines).strip()

    def _ensure_action_tooltip(self):
        """Crea el tooltip HTML y conecta el hover sobre los marcadores."""
        if self._action_tooltip_ready:
            return
        self.chart.run_script(f'''
            if (!window.actionTooltip) {{
                window.actionTooltip = document.createElement("div");
                window.actionTooltip.style.position = "fixed";
                window.actionTooltip.style.zIndex = "9999";
                window.actionTooltip.style.background = "rgba(45,45,45,0.95)";
                window.actionTooltip.style.color = "#e5e5e5";
                window.actionTooltip.style.fontFamily = "Consolas, monospace";
                window.actionTooltip.style.fontSize = "12px";
                window.actionTooltip.style.padding = "8px 10px";
                window.actionTooltip.style.border = "1px solid #3C434C";
                window.actionTooltip.style.borderRadius = "6px";
                window.actionTooltip.style.whiteSpace = "pre";
                window.actionTooltip.style.display = "none";
                window.actionTooltip.style.pointerEvents = "none";
                document.body.appendChild(window.actionTooltip);
            }}

            if (!window.actionMarkers) {{
                window.actionMarkers = [];
            }}
            if (window.actionHoverRadius === undefined) {{
                window.actionHoverRadius = 18;
            }}
            if (!window.actionHoverInit) {{
                window.actionHoverInit = true;
                const handler = (param) => {{
                    if (!param || !param.point || !window.actionMarkers || window.actionMarkers.length === 0) {{
                        window.actionTooltip.style.display = "none";
                        return;
                    }}
                    const timeScale = {self.chart.id}.chart.timeScale();
                    const series = {self.chart.id}.series;
                    let closest = null;
                    let minDist = Infinity;

                    for (const marker of window.actionMarkers) {{
                        if (marker.time === null || marker.price === null) continue;
                        const x = timeScale.timeToCoordinate(marker.time);
                        const y = series.priceToCoordinate(marker.price);
                        if (x === null || y === null) continue;
                        const dx = param.point.x - x;
                        const dy = param.point.y - y;
                        const dist = Math.sqrt(dx * dx + dy * dy);
                        if (dist < minDist) {{
                            minDist = dist;
                            closest = {{ marker, x, y }};
                        }}
                    }}

                    if (!closest || minDist > window.actionHoverRadius) {{
                        window.actionTooltip.style.display = "none";
                        return;
                    }}

                    window.actionTooltip.innerText = closest.marker.tooltip || "";
                    window.actionTooltip.style.display = "block";

                    const chartRect = {self.chart.id}.div.getBoundingClientRect();
                    const pad = 10;
                    let left = chartRect.left + closest.x + 8;
                    let top = chartRect.top + closest.y - 8;

                    const tipRect = window.actionTooltip.getBoundingClientRect();
                    if (left + tipRect.width > chartRect.right - pad) {{
                        left = chartRect.right - tipRect.width - pad;
                    }}
                    if (top + tipRect.height > chartRect.bottom - pad) {{
                        top = chartRect.bottom - tipRect.height - pad;
                    }}
                    if (left < chartRect.left + pad) {{
                        left = chartRect.left + pad;
                    }}
                    if (top < chartRect.top + pad) {{
                        top = chartRect.top + pad;
                    }}

                    window.actionTooltip.style.left = left + "px";
                    window.actionTooltip.style.top = top + "px";
                }};
                {self.chart.id}.chart.subscribeCrosshairMove(handler);
            }}
        ''')
        self._action_tooltip_ready = True

    def _set_action_markers(self, markers):
        """Actualiza la lista de marcadores para el tooltip."""
        self._ensure_action_tooltip()
        markers_js = json.dumps(markers or [])
        self.chart.run_script(f'window.actionMarkers = {markers_js}')
    
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

    def update_tci_chart(self, df: pd.DataFrame):
        """Actualiza el subchart TuTCI."""
        try:
            if df is None or len(df) < 2:
                return

            if 'tci_hist' not in df.columns or 'tci_signal' not in df.columns:
                return

            hist_df = df[['time', 'tci_hist']].dropna().copy()
            hist_df = hist_df.rename(columns={'tci_hist': 'TuTCI'})
            if len(hist_df) > 0:
                hist_df['color'] = np.where(hist_df['TuTCI'] >= 0, '#8bc34a', '#ef5350')
                self.tci_hist.set(hist_df)
            else:
                self.tci_hist.set(pd.DataFrame())

            signal_df = df[['time', 'tci_signal']].dropna().copy()
            signal_df = signal_df.rename(columns={'tci_signal': 'TuTCI Signal'})
            if len(signal_df) > 0:
                self.tci_signal.set(signal_df)
            else:
                self.tci_signal.set(pd.DataFrame())

        except Exception as e:
            self.log_message(f"Error al actualizar TuTCI: {e}")

    def get_enabled_symbols(self, pattern=None, limit=200):
        """
        Devuelve lista de símbolos con trading habilitado.
        Opcionalmente filtra por patrón MT5 (ej: 'US*').
        """
        try:
            symbols = mt5.symbols_get(pattern) if pattern else mt5.symbols_get()
            if not symbols:
                return [config.SYMBOL]
            enabled = [s.name for s in symbols if s.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED]
            enabled = sorted(enabled)
            if limit:
                enabled = enabled[:limit]
            return enabled or [config.SYMBOL]
        except Exception as e:
            self.log_message(f"No se pudieron obtener símbolos habilitados: {e}")
            return [config.SYMBOL]

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

    def on_symbol_change(self, chart):
        """Cambia el símbolo a operar desde la lista."""
        try:
            symbol = chart.topbar['symbol_select'].value
        except Exception:
            self.log_message("No se pudo leer el símbolo seleccionado")
            return

        try:
            mt5_connection.check_symbol(symbol)
            config.SYMBOL = symbol
            self.chart.watermark(symbol, color='rgba(180, 180, 200, 0.3)')
            self.log_message(f"Símbolo cambiado a {symbol}")
            self.refresh_data()
            self.update_quotes()
        except Exception as e:
            self.log_message(f"Error al cambiar símbolo: {e}")

    def reload_symbols(self, chart=None):
        """Recarga la lista de símbolos habilitados y actualiza el switcher."""
        symbols_enabled = self.get_enabled_symbols()
        if config.SYMBOL not in symbols_enabled:
            symbols_enabled.insert(0, config.SYMBOL)
        self.chart.topbar['symbol_select'].update(tuple(symbols_enabled[:50]))
        self.log_message(f"Lista de símbolos recargada ({len(symbols_enabled)} habilitados)")

    def on_filling_change(self, chart):
        """Actualiza el modo de llenado desde la interfaz."""
        try:
            mode = chart.topbar['filling_mode'].value
        except Exception:
            self.log_message("No se pudo leer el filling mode")
            return
        config.FILLING_MODE_OVERRIDE = mode
        self.log_message(f"Filling mode configurado: {mode}")

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
                    df = data_feed.add_supertrend(
                        df,
                        atr_length=getattr(config, "SUPERTREND_ATR_LENGTH", config.ATR_LENGTH),
                        atr_mult=getattr(config, "SUPERTREND_MULT", 3.0),
                        source_col=getattr(config, "SUPERTREND_SOURCE", "close"),
                        use_hma=getattr(config, "SUPERTREND_USE_HMA", True),
                        hma_length=getattr(config, "HMA_LENGTH", 55)
                    )
                    df = data_feed.add_tci(
                        df,
                        fast_length=getattr(config, "TCI_FAST", 9),
                        slow_length=getattr(config, "TCI_SLOW", 21),
                        signal_length=getattr(config, "TCI_SIGNAL", 5)
                    )
                    df = strategy_baseline.compute_dir1_and_signals(df, config.ENABLE_SIGNALS)
                    
                    test_mode = getattr(config, "TEST_MODE", False)
                    if test_mode:
                        signal = strategy_baseline.get_test_signal()
                        market_open, market_status = True, "TEST_MODE (sin check)"
                    else:
                        signal = strategy_baseline.get_last_signal(df, verbose=False)
                        market_open, market_status = trading.is_market_open(config.SYMBOL)
                    
                    self.price_data = df
                    self.update_chart(df)
                    self.update_tci_chart(df)
                    self.update_balance()
                    self.update_quotes()
                    
                    if signal != "none" and market_open:
                        self.log_message(f"Senal detectada: {signal.upper()}")
                        action_info = trading.apply_signal(
                            config.SYMBOL, signal, config.LOT,
                            config.SL_POINTS, config.TP_POINTS, config.MAGIC_NUMBER
                        )
                        if action_info:
                            self.update_last_action_ui(action_info)
                    elif signal != "none":
                        self.log_message(f"Skip: mercado cerrado ({market_status})")
                    
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
        self.start_quote_updater()
        
        # Mostrar gráfico
        self.log_message("Iniciando interfaz grafica...")
        try:
            self.chart.show(block=True)
        finally:
            self.stop_quote_updater()


def main():
    """Función principal."""
    app = TradingBotGUI()
    app.run()


if __name__ == "__main__":
    main()
