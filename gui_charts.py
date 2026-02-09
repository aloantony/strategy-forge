"""
Interfaz gráfica del Bot de Trading usando Lightweight Charts (TradingView).
Gráficos profesionales, fluidos y con el mismo aspecto que TradingView.
"""

from lightweight_charts import Chart
from lightweight_charts.util import parse_event_message
import pandas as pd
import numpy as np
import MetaTrader5 as mt5
import threading
import time
import asyncio
import queue
import sys
import io
import importlib
import importlib.util
import os
import re
import base64
from datetime import datetime, timedelta, timezone
import json
import urllib.request
from urllib.parse import unquote

import config
import mt5_connection
import data_feed
from strategies import strategy_baseline
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
        self.callback_thread = None
        self.callback_stop_event = threading.Event()
        self._latest_deals_cache = []
        self._latest_deals_range = None

        # Panel de indicadores
        self.indicator_panel = None
        self.indicator_rows = {}
        self.indicator_state = {}
        self.indicator_series = {}
        self.object_tree_items = []
        self.equity_chart = None
        self.equity_line = None

        # Colores para indicadores de acción
        self.success_color = '#26a69a'
        self.error_color = '#ef5350'
        self.warning_color = '#ffaa00'
        self.accent_color = '#2196f3'

        # Estrategias
        self.strategy_registry = {}
        self.current_strategy_key = None
        self.strategy_module = None
        self._init_strategy_registry()
        
        # Crear gráfico principal
        self.chart = Chart(toolbox=False, inner_width=0.78, inner_height=0.7)
        
        # Configurar apariencia (estilo TradingView oscuro)
        self.chart.layout(
            background_color='#1e1e1e',
            text_color='#bfbfbf',
            font_size=12,
            font_family='Roboto, Segoe UI, sans-serif'
        )

        self.chart.candle_style(
            up_color='#2ecc71',
            down_color='#e74c3c',
            wick_up_color='#2ecc71',
            wick_down_color='#e74c3c'
        )

        self.chart.volume_config(
            up_color='rgba(46, 204, 113, 0.4)',
            down_color='rgba(231, 76, 60, 0.4)'
        )

        self.chart.watermark(config.SYMBOL, color='rgba(180, 180, 200, 0.18)')
        self.chart.grid(color='#3a3a3a', style='solid')
        self.chart.time_scale(border_visible=True, border_color='#3a3a3a')
        self.chart.price_scale(
            text_color='#bfbfbf',
            border_visible=False,
            ticks_visible=True,
            scale_margin_top=0.15,
            scale_margin_bottom=0.1
        )
        self.chart.price_line(label_visible=True, line_visible=True)
        self.chart.run_script(f'''
            {self.chart.id}.series.applyOptions({{
                priceLineColor: "#00c853",
                priceLineWidth: 1,
                priceLineStyle: 2
            }})
        ''')

        self.chart.crosshair(
            mode='normal',
            vert_color='#5a5a5a',
            vert_style='dotted',
            horz_color='#5a5a5a',
            horz_style='dotted'
        )

        self.chart.legend(
            visible=True,
            ohlc=True,
            percent=False,
            lines=False,
            color='#bfbfbf',
            font_size=11,
            font_family='Roboto, Segoe UI, sans-serif'
        )
        
        # Crear líneas para indicadores (el ojo permite mostrar/ocultar cada línea)
        self.upper_line = self.chart.create_line(name='Upper', color='#ff9800', width=1)
        self.average_line = self.chart.create_line(name='Average', color='#2ecc71', width=1)
        self.lower_line = self.chart.create_line(name='Lower', color='#ff9800', width=1)
        self.supertrend_up_line = self.chart.create_line(
            name='Supertrend Up', color='#2ecc71', width=2, style='dotted'
        )
        self.supertrend_down_line = self.chart.create_line(
            name='Supertrend Down', color='#e74c3c', width=2, style='dotted'
        )

        # Subchart para TuTCI
        self.tci_chart = self.chart.create_subchart(width=0.78, height=0.22, sync=True)
        self.tci_chart.layout(background_color='#1e1e1e', text_color='#bfbfbf')
        self.tci_chart.grid(color='#3a3a3a', style='solid')
        self.tci_chart.price_scale(
            text_color='#bfbfbf',
            border_visible=False,
            ticks_visible=True,
            scale_margin_top=0.1,
            scale_margin_bottom=0.1
        )
        self.tci_hist = self.tci_chart.create_histogram(
            name='TuTCI',
            color='#e0e0e0',
            price_line=False,
            price_label=True,
            scale_margin_top=0.2,
            scale_margin_bottom=0.2
        )
        self.tci_fill = self.tci_chart.create_histogram(
            name='TuTCI Fill',
            color='rgba(160, 120, 60, 0.35)',
            price_line=False,
            price_label=False,
            scale_margin_top=0.2,
            scale_margin_bottom=0.2
        )
        self.tci_signal = self.tci_chart.create_line(name='TuTCI Signal', color='#d9a441', width=1)
        self.tci_sync_line = self.tci_chart.create_line(
            name='TuTCI Sync',
            color='rgba(0, 0, 0, 0)',
            width=1,
            price_line=False,
            price_label=False
        )

        # Mapa de series para el panel de indicadores
        self.indicator_series = {
            "baseline": [self.average_line],
            "atr_bands": [self.upper_line, self.lower_line],
            "supertrend": [self.supertrend_up_line, self.supertrend_down_line],
            "tci": [self.tci_hist, self.tci_fill, self.tci_signal],
        }
        
        # Estilos y controles
        self._inject_custom_styles()
        self.setup_topbar()
        self.setup_side_panel()
        self.setup_bottom_bar()
        
        # Nota: los hotkeys requieren un modificador (shift, alt, ctrl, meta)
        # Ejemplo: self.chart.hotkey('shift', 'S', self.start_bot)
        # Por ahora usamos los botones de la topbar

    def _init_strategy_registry(self):
        """Inicializa el registro de estrategias disponibles."""
        self.strategy_registry = {}
        baseline_module = "strategies.strategy_baseline"
        legacy_baseline_module = "strategy_baseline"
        self._register_strategy(
            key="baseline",
            label="Baseline (Dir_1)",
            module_ref=baseline_module
        )
        cfg_key = getattr(config, "STRATEGY_KEY", "baseline")
        cfg_module = getattr(config, "STRATEGY_MODULE", baseline_module)
        if cfg_module == legacy_baseline_module:
            cfg_module = baseline_module
        if cfg_module and cfg_module != baseline_module:
            custom_key = self._slugify(cfg_key or cfg_module)
            if custom_key not in self.strategy_registry:
                self._register_strategy(custom_key, cfg_key or custom_key, cfg_module)
            cfg_key = custom_key
        default_key = cfg_key
        if default_key not in self.strategy_registry:
            default_key = "baseline"
        self._set_strategy_by_key(default_key, refresh=False, sync_ui=False)

    def _register_strategy(self, key: str, label: str, module_ref: str):
        self.strategy_registry[key] = {
            "key": key,
            "label": label,
            "module": module_ref
        }

    def _get_strategy_dir(self) -> str:
        base_dir = getattr(config, "STRATEGY_DIR", "strategies")
        if not os.path.isabs(base_dir):
            base_dir = os.path.join(os.path.dirname(__file__), base_dir)
        os.makedirs(base_dir, exist_ok=True)
        return base_dir

    def _sanitize_strategy_filename(self, filename: str) -> str:
        name = os.path.basename(filename or "").strip()
        name = name.replace(" ", "_")
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
        if not name:
            name = "strategy.py"
        if not name.lower().endswith(".py"):
            name = f"{name}.py"
        return name

    def _save_strategy_file(self, filename: str, content: bytes):
        try:
            base_dir = self._get_strategy_dir()
            safe_name = self._sanitize_strategy_filename(filename)
            base, ext = os.path.splitext(safe_name)
            candidate = os.path.join(base_dir, safe_name)
            counter = 1
            while os.path.exists(candidate):
                candidate = os.path.join(base_dir, f"{base}_{counter}{ext}")
                counter += 1
            with open(candidate, "wb") as f:
                f.write(content)
            return candidate
        except Exception as e:
            self.log_message(f"No se pudo guardar la estrategia: {e}")
            return None

    def _slugify(self, text: str) -> str:
        text = (text or "").strip().lower()
        text = re.sub(r"[^a-z0-9_]+", "_", text)
        text = text.strip("_")
        return text or "strategy"

    def _get_strategy_payload(self):
        return [
            {
                "key": entry["key"],
                "label": entry["label"],
                "module": entry["module"]
            }
            for entry in self.strategy_registry.values()
        ]

    def _get_side_panel_icons(self):
        return {
            "chart": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><rect x='2' y='3' width='12' height='10' rx='1.5'/><path d='M4 10 L7 7 L9 9 L12 6'/></svg>",
            "line": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><path d='M2 11 L6 7 L9 9 L14 4'/></svg>",
            "bands": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><path d='M2 4 H14'/><path d='M2 8 H14'/><path d='M2 12 H14'/></svg>",
            "trend": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><path d='M2 12 L6 8 L10 10 L14 6'/><circle cx='6' cy='8' r='1.2'/><circle cx='10' cy='10' r='1.2'/></svg>",
            "hist": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><path d='M3 12 V7'/><path d='M7 12 V5'/><path d='M11 12 V9'/><path d='M14 12 H2'/></svg>",
            "long": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><path d='M8 12 V4'/><path d='M8 4 L5 7'/><path d='M8 4 L11 7'/></svg>",
            "short": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><path d='M8 4 V12'/><path d='M8 12 L5 9'/><path d='M8 12 L11 9'/></svg>",
        }

    def _get_object_tree_catalog(self):
        return {
            "baseline": {"label": "Baseline", "icon": "line", "toggle": True, "visible": True},
            "atr_bands": {"label": "ATR Bands", "icon": "bands", "toggle": True, "visible": True},
            "supertrend": {"label": "Supertrend w/ HMA", "icon": "trend", "toggle": True, "visible": True},
            "tci": {"label": "TuTCI", "icon": "hist", "toggle": True, "visible": True},
        }

    def _get_default_object_tree_items(self):
        defaults = getattr(config, "OBJECT_TREE_DEFAULT_ITEMS", None)
        if isinstance(defaults, (list, tuple)) and defaults:
            return list(defaults)
        return ["baseline", "atr_bands", "supertrend", "tci"]

    def _merge_object_tree_items(self, primary, fallback):
        combined = []
        for items in (primary, fallback):
            if not items:
                continue
            if isinstance(items, (list, tuple, set)):
                combined.extend(list(items))
            else:
                combined.append(items)
        return combined

    def _normalize_object_tree_items(self, items):
        catalog = self._get_object_tree_catalog()
        normalized = []
        seen = set()
        if not items:
            return normalized

        for entry in items:
            if isinstance(entry, str):
                key = entry
                overrides = {}
            elif isinstance(entry, dict):
                key = entry.get("key") or entry.get("id") or entry.get("name")
                overrides = dict(entry)
            else:
                continue

            key = (key or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)

            base = catalog.get(key, {})
            item = {**base, **overrides}
            item["key"] = key

            if not item.get("label"):
                item["label"] = key.replace("_", " ").title()
            if not item.get("icon"):
                item["icon"] = "line"

            if "toggle" not in item:
                item["toggle"] = key in self.indicator_series
            if item.get("toggle") and key not in self.indicator_series:
                item["toggle"] = False

            if "visible" in item:
                item["visible"] = bool(item["visible"])
            elif key in self.indicator_state:
                item["visible"] = bool(self.indicator_state.get(key, True))
            else:
                item["visible"] = bool(base.get("visible", True))

            normalized.append(item)

        return normalized

    def _get_strategy_object_tree_items(self):
        module = self.strategy_module or strategy_baseline
        candidates = (
            "OBJECT_TREE_ITEMS",
            "OBJECT_TREE_KEYS",
            "MEASURES",
            "MEASURE_KEYS",
            "INDICATORS",
            "INDICATOR_KEYS",
        )

        strategy_items = None
        for name in candidates:
            if hasattr(module, name):
                try:
                    items = getattr(module, name)
                except Exception:
                    items = None
                if items:
                    strategy_items = items
                    break

        combined = self._merge_object_tree_items(strategy_items, self._get_default_object_tree_items())
        if not combined:
            combined = list(self._get_object_tree_catalog().keys())
        return self._normalize_object_tree_items(combined)

    def _build_object_tree_items(self):
        items = [
            {"key": "symbol", "label": f"{config.SYMBOL} · MT5", "icon": "chart", "toggle": False, "visible": True},
        ]
        items.extend(self._get_strategy_object_tree_items())
        items.extend([
            {"key": "long_pos", "label": "Long Position", "icon": "long", "toggle": False, "visible": True},
            {"key": "short_pos", "label": "Short Position", "icon": "short", "toggle": False, "visible": True},
        ])

        combined = []
        seen = set()
        for item in items:
            key = item.get("key")
            if not key or key in seen:
                continue
            seen.add(key)
            combined.append(item)
        return combined

    def _apply_indicator_visibility_for_items(self, items):
        active_keys = {item["key"] for item in items if item.get("toggle")}
        for item in items:
            if not item.get("toggle"):
                continue
            key = item["key"]
            visible = bool(item.get("visible", True))
            self.indicator_state[key] = visible
            self._apply_indicator_visibility(key, visible)
        for key in self.indicator_series.keys():
            if key not in active_keys:
                self._apply_indicator_visibility(key, False)

    def _render_object_tree(self, items=None):
        handler = getattr(self, "side_panel_handler", None)
        if not handler:
            return
        if items is None:
            items = self.object_tree_items
        payload = json.dumps({
            "items": items or [],
            "icons": self._get_side_panel_icons(),
            "handler": handler
        })
        self.chart.run_script(f'''
            ;(function() {{
                const payload = {payload};
                if (window.renderObjectTreeList) {{
                    window.renderObjectTreeList(payload);
                }}
            }})();
        ''')

    def _refresh_object_tree_items(self, render: bool = True):
        items = self._build_object_tree_items()
        self.object_tree_items = items
        if self.indicator_series:
            self._apply_indicator_visibility_for_items(items)
        if render:
            self._render_object_tree(items)

    def _load_strategy_module(self, module_ref: str):
        """Carga dinámicamente un módulo de estrategia."""
        if not module_ref:
            return None

        module_ref = module_ref.strip()
        if not module_ref:
            return None

        path_like = module_ref.endswith(".py") or any(
            sep in module_ref for sep in (os.sep, os.altsep) if sep
        )
        if path_like:
            path = module_ref
            if not path.endswith(".py") and os.path.isfile(path + ".py"):
                path = path + ".py"
            if not os.path.isfile(path):
                self.log_message(f"Estrategia no encontrada: {path}")
                return None
            module_name = f"user_strategy_{self._slugify(os.path.splitext(os.path.basename(path))[0])}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                self.log_message(f"No se pudo cargar la estrategia: {path}")
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        module = importlib.import_module(module_ref)
        return importlib.reload(module)

    def _set_strategy_by_key(self, key: str, refresh: bool = True, sync_ui: bool = True):
        entry = self.strategy_registry.get(key)
        if not entry:
            self.log_message(f"Estrategia desconocida: {key}")
            return
        try:
            module = self._load_strategy_module(entry["module"])
        except Exception as e:
            self.log_message(f"Error al cargar estrategia {entry['label']}: {e}")
            module = None

        if module is None:
            if key != "baseline":
                self.log_message("Volviendo a estrategia baseline.")
                self._set_strategy_by_key("baseline", refresh=refresh, sync_ui=sync_ui)
            return

        if not hasattr(module, "get_last_signal"):
            self.log_message("La estrategia no define get_last_signal().")
            return

        self.strategy_module = module
        self.current_strategy_key = key
        config.STRATEGY_KEY = key
        config.STRATEGY_MODULE = entry["module"]
        self.log_message(f"Estrategia activa: {entry['label']} ({entry['module']})")

        self._refresh_object_tree_items()

        if sync_ui:
            self._render_strategy_panel()
        if refresh:
            self.refresh_data()

    def _add_strategy_from_input(self, label: str, module_ref: str):
        label = (label or "").strip()
        module_ref = (module_ref or "").strip()
        if not module_ref:
            self.log_message("Debe indicar el módulo o ruta de la estrategia.")
            return

        key_source = label or module_ref
        key = self._slugify(key_source)
        if key in self.strategy_registry:
            self.log_message(f"La estrategia '{key}' ya existe.")
            return

        try:
            module = self._load_strategy_module(module_ref)
        except Exception as e:
            self.log_message(f"No se pudo cargar la nueva estrategia: {e}")
            return

        if module is None:
            return
        if not hasattr(module, "get_last_signal"):
            self.log_message("La estrategia no define get_last_signal().")
            return

        self._register_strategy(key, label or key, module_ref)
        self._set_strategy_by_key(key, refresh=True, sync_ui=True)

    def _add_strategy_from_drop(self, filename: str, data_uri: str):
        filename = (filename or "").strip()
        data_uri = (data_uri or "").strip()
        if not filename or not data_uri:
            self.log_message("Archivo de estrategia inválido.")
            return
        if not filename.lower().endswith(".py"):
            self.log_message("Solo se aceptan archivos .py.")
            return

        data = data_uri
        if data.startswith("data:"):
            try:
                header, b64data = data.split(",", 1)
            except ValueError:
                self.log_message("No se pudo leer el archivo de estrategia.")
                return
            data = b64data

        try:
            content = base64.b64decode(data)
        except Exception as e:
            self.log_message(f"Error al decodificar estrategia: {e}")
            return

        saved_path = self._save_strategy_file(filename, content)
        if not saved_path:
            return

        label = os.path.splitext(os.path.basename(saved_path))[0]
        module_ref = saved_path
        key = self._slugify(label)
        if key in self.strategy_registry:
            key = self._slugify(f"{label}_{len(self.strategy_registry)}")

        self._register_strategy(key, label, module_ref)
        self._set_strategy_by_key(key, refresh=True, sync_ui=True)

    def _render_strategy_panel(self):
        payload = json.dumps({
            "strategies": self._get_strategy_payload(),
            "selected": self.current_strategy_key or "",
            "handler": self.side_panel_handler
        })
        self.chart.run_script(f'''
            ;(function() {{
                const payload = {payload};
                if (window.renderStrategyList) {{
                    window.renderStrategyList(payload);
                }}
            }})();
        ''')
        self._sync_strategy_status_ui()

    def _sync_strategy_status_ui(self):
        running = "true" if self.bot_running else "false"
        self.chart.run_script(f'''
            ;(function() {{
                if (window.setStrategyStatus) {{
                    window.setStrategyStatus({running});
                }}
            }})();
        ''')

    def _apply_strategy_processing(self, df: pd.DataFrame) -> pd.DataFrame:
        module = self.strategy_module or strategy_baseline
        try:
            if hasattr(module, "prepare_dataframe"):
                result = module.prepare_dataframe(df)
                if isinstance(result, pd.DataFrame):
                    df = result
            if hasattr(module, "compute_dir1_and_signals"):
                result = module.compute_dir1_and_signals(df, config.ENABLE_SIGNALS)
                if isinstance(result, pd.DataFrame):
                    df = result
            elif hasattr(module, "compute_signals"):
                result = module.compute_signals(df, config.ENABLE_SIGNALS)
                if isinstance(result, pd.DataFrame):
                    df = result
        except Exception as e:
            self.log_message(f"Error en estrategia '{self.current_strategy_key}': {e}")
        return df

    def _get_strategy_signal(self, df: pd.DataFrame, verbose: bool = False) -> str:
        module = self.strategy_module or strategy_baseline
        if getattr(config, "TEST_MODE", False):
            if hasattr(module, "get_test_signal"):
                return module.get_test_signal()
            return strategy_baseline.get_test_signal()

        if hasattr(module, "get_last_signal"):
            try:
                return module.get_last_signal(df, verbose=verbose)
            except TypeError:
                return module.get_last_signal(df)
            except Exception as e:
                self.log_message(f"Error al obtener señal ({self.current_strategy_key}): {e}")
        return "none"
        
    def setup_topbar(self):
        """Configura la barra superior con controles."""
        # Cotizaciones rápidas (estilo TradingView)
        self.chart.topbar.textbox('sell_quote', 'SELL --', align='left')
        self.chart.topbar.textbox('spread', '4.00', align='left')
        self.chart.topbar.textbox('buy_quote', 'BUY --', align='left')
        self.chart.topbar.textbox('symbol_label', config.SYMBOL, align='left')

        # Widgets internos (mantener para lógica del bot, pero ocultos)
        self.chart.topbar.textbox('status', 'Detenido', align='right')
        self.chart.topbar.textbox('balance', '---', align='right')
        self.chart.topbar.textbox('action_icon', '⚪', align='right')
        self.chart.topbar.textbox('action_text', 'Sin acciones todavía', align='right')
        self.chart.topbar.button('start', 'Iniciar Bot', func=self.start_bot, align='right')
        self.chart.topbar.button('stop', 'Detener Bot', func=self.stop_bot, align='right')
        self.chart.topbar.button('refresh', 'Actualizar Datos', func=self.refresh_data, align='right')

        self._style_quote_widgets()
        self._bind_quote_actions()
        self._hide_non_visual_widgets()
        self._ensure_action_tooltip()

    def _inject_custom_styles(self):
        """Inyecta estilos CSS para emular la estética TradingView."""
        self.chart.run_script('''
            if (!document.getElementById("trading-ui-style")) {
                const style = document.createElement("style");
                style.id = "trading-ui-style";
                style.innerHTML = `
                    :root {
                        --tv-bg-main: #1e1e1e;
                        --tv-bg-panel: #252525;
                        --tv-grid: #3a3a3a;
                        --tv-text-primary: #ffffff;
                        --tv-text-secondary: #b0b0b0;
                        --tv-buy: #1e88e5;
                        --tv-sell: #c62828;
                        --tv-highlight: #00c853;
                        --tv-indicator-fill: rgba(160, 120, 60, 0.35);
                        --tv-topbar-height: 34px;
                        --tv-bottom-height: 32px;
                    }
                    body, html {
                        background: var(--tv-bg-main);
                        font-family: Roboto, "Segoe UI", sans-serif;
                    }
                    .topbar {
                        background: var(--tv-bg-main);
                        border-bottom: 1px solid var(--tv-grid);
                        height: var(--tv-topbar-height);
                    }
                    .topbar-container {
                        gap: 6px;
                        align-items: center;
                    }
                    .topbar-textbox {
                        color: var(--tv-text-secondary);
                    }
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
                    .quote-box.sell { background: var(--tv-sell); color: #ffffff; }
                    .quote-box.buy { background: var(--tv-buy); color: #ffffff; }
                    .quote-box.spread {
                        background: transparent;
                        color: var(--tv-text-secondary);
                        min-width: 40px;
                        padding: 4px 6px;
                        text-align: center;
                    }
                    .quote-box.symbol {
                        background: #2a2a2a;
                        color: var(--tv-text-secondary);
                        padding: 4px 8px;
                        min-width: 90px;
                    }
                    .toolbox {
                        display: none !important;
                    }
                    .legend-toggle-switch {
                        display: none !important;
                    }

                    #tv-side-panel {
                        position: fixed;
                        top: var(--tv-topbar-height);
                        right: 0;
                        width: 22%;
                        height: calc(100% - var(--tv-topbar-height) - var(--tv-bottom-height));
                        background: var(--tv-bg-panel);
                        border-left: 1px solid var(--tv-grid);
                        padding-right: 40px;
                        box-sizing: border-box;
                        display: flex;
                        flex-direction: column;
                        z-index: 1200;
                    }
                    .tv-side-tabs {
                        display: flex;
                        border-bottom: 1px solid var(--tv-grid);
                        background: #1b1b1b;
                    }
                    .tv-side-tab {
                        flex: 1;
                        text-align: center;
                        padding: 6px 8px;
                        font-size: 12px;
                        color: var(--tv-text-secondary);
                        cursor: pointer;
                        user-select: none;
                    }
                    .tv-side-tab.active {
                        color: var(--tv-text-primary);
                        background: #222222;
                    }
                    .tv-side-list {
                        flex: 1;
                        overflow-y: auto;
                        padding: 8px 6px;
                        display: flex;
                        flex-direction: column;
                        gap: 6px;
                    }
                    .tv-side-item {
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        gap: 8px;
                        padding: 6px 8px;
                        border-radius: 6px;
                        color: var(--tv-text-primary);
                        font-size: 12px;
                        cursor: pointer;
                    }
                    .tv-side-item.dim {
                        color: #8c8c8c;
                    }
                    .tv-side-item.selected {
                        background: #2c2c2c;
                    }
                    .tv-side-left {
                        display: flex;
                        align-items: center;
                        gap: 8px;
                        overflow: hidden;
                    }
                    .tv-side-icon {
                        width: 16px;
                        height: 16px;
                        display: inline-flex;
                        align-items: center;
                        justify-content: center;
                        color: #cfcfcf;
                    }
                    .tv-side-label {
                        white-space: nowrap;
                        overflow: hidden;
                        text-overflow: ellipsis;
                    }
                    .tv-eye {
                        width: 18px;
                        height: 18px;
                        display: inline-flex;
                        align-items: center;
                        justify-content: center;
                        color: #cfcfcf;
                        opacity: 0.8;
                    }
                    .tv-eye.hidden {
                        opacity: 0.35;
                    }
                    .tv-side-content {
                        flex: 1;
                        overflow-y: auto;
                        padding: 12px;
                        display: flex;
                        flex-direction: column;
                        gap: 10px;
                        color: var(--tv-text-secondary);
                        font-size: 12px;
                    }
                    .tv-section-title {
                        font-size: 13px;
                        font-weight: 600;
                        color: var(--tv-text-primary);
                    }
                    .tv-section-desc {
                        font-size: 11px;
                        line-height: 1.4;
                        color: #9a9a9a;
                    }
                    .tv-feedback-form {
                        display: flex;
                        flex-direction: column;
                        gap: 8px;
                    }
                    .tv-feedback-form input,
                    .tv-feedback-form textarea {
                        background: #1a1a1a;
                        border: 1px solid #333333;
                        color: var(--tv-text-primary);
                        padding: 8px;
                        border-radius: 6px;
                        font-size: 12px;
                    }
                    .tv-feedback-form textarea {
                        resize: vertical;
                        min-height: 90px;
                    }
                    .tv-feedback-form button {
                        background: #2b2b2b;
                        color: var(--tv-text-primary);
                        border: 1px solid #3a3a3a;
                        padding: 8px;
                        border-radius: 6px;
                        font-size: 12px;
                        cursor: pointer;
                    }
                    .tv-feedback-form button:hover {
                        background: #3a3a3a;
                    }
                    .tv-feedback-hint {
                        font-size: 11px;
                        color: #7a7a7a;
                    }
                    .tv-feedback-status {
                        font-size: 11px;
                        color: #9aa0a6;
                        min-height: 14px;
                    }
                    .tv-feedback-status.success {
                        color: #5fd6a3;
                    }
                    .tv-feedback-status.error {
                        color: #ff8a80;
                    }
                    .tv-legacy-panel {
                        flex: 1;
                        display: flex;
                        flex-direction: column;
                        overflow: hidden;
                    }
                    #tv-data-window {
                        flex: 1;
                        overflow: hidden;
                        padding: 10px 12px;
                        color: var(--tv-text-secondary);
                        display: flex;
                        flex-direction: column;
                        gap: 10px;
                    }
                    .tv-data-header {
                        display: flex;
                        flex-direction: column;
                        gap: 6px;
                    }
                    .tv-data-title {
                        font-size: 13px;
                        font-weight: 600;
                        color: var(--tv-text-primary);
                    }
                    .tv-data-meta {
                        display: flex;
                        flex-direction: column;
                        gap: 4px;
                    }
                    .tv-data-body {
                        display: flex;
                        flex-direction: column;
                        gap: 6px;
                    }
                    .tv-data-section {
                        margin-top: 6px;
                        padding-bottom: 4px;
                        border-bottom: 1px solid #333333;
                        font-size: 12px;
                        font-weight: 600;
                        color: #cfcfcf;
                    }
                    .tv-data-row {
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        gap: 8px;
                        font-size: 12px;
                    }
                    .tv-data-label {
                        color: #9a9a9a;
                    }
                    .tv-data-value {
                        color: #e0e0e0;
                        font-variant-numeric: tabular-nums;
                    }
                    .tv-data-empty {
                        font-size: 11px;
                        color: #7a7a7a;
                        padding-top: 4px;
                    }
                    .tv-data-trades {
                        flex: 1;
                        min-height: 120px;
                        display: flex;
                        flex-direction: column;
                        gap: 6px;
                        overflow: hidden;
                    }
                    .tv-data-trades-list {
                        flex: 1;
                        overflow-y: auto;
                        display: flex;
                        flex-direction: column;
                        gap: 6px;
                        padding-right: 4px;
                    }
                    .tv-trade-item {
                        background: #1f1f1f;
                        border: 1px solid #2f2f2f;
                        border-radius: 6px;
                        padding: 8px;
                        display: flex;
                        flex-direction: column;
                        gap: 6px;
                    }
                    .tv-trade-main {
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        gap: 8px;
                        font-size: 12px;
                    }
                    .tv-trade-side {
                        font-weight: 600;
                        letter-spacing: 0.04em;
                    }
                    .tv-trade-side.buy { color: #5fd6a3; }
                    .tv-trade-side.sell { color: #ff8a80; }
                    .tv-trade-entry {
                        font-size: 10px;
                        color: #9a9a9a;
                        text-transform: uppercase;
                    }
                    .tv-trade-price {
                        font-variant-numeric: tabular-nums;
                        color: #e0e0e0;
                    }
                    .tv-trade-meta {
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        gap: 8px;
                        font-size: 11px;
                        color: #9a9a9a;
                    }
                    .tv-trade-profit.pos { color: #5fd6a3; }
                    .tv-trade-profit.neg { color: #ff8a80; }
                    .tv-trade-comment {
                        font-size: 10px;
                        color: #7a7a7a;
                        line-height: 1.3;
                    }
                    .tv-strategy-list {
                        display: flex;
                        flex-direction: column;
                        gap: 6px;
                        margin-bottom: 8px;
                    }
                    .tv-strategy-item {
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        gap: 8px;
                        padding: 8px;
                        border-radius: 6px;
                        background: #1f1f1f;
                        color: var(--tv-text-primary);
                        font-size: 12px;
                        cursor: pointer;
                    }
                    .tv-strategy-item.selected {
                        background: #2c2c2c;
                    }
                    .tv-strategy-left {
                        display: flex;
                        flex-direction: column;
                        gap: 2px;
                        overflow: hidden;
                    }
                    .tv-strategy-title {
                        font-weight: 600;
                        color: var(--tv-text-primary);
                        white-space: nowrap;
                        overflow: hidden;
                        text-overflow: ellipsis;
                    }
                    .tv-strategy-module {
                        font-size: 10px;
                        color: #8c8c8c;
                        white-space: nowrap;
                        overflow: hidden;
                        text-overflow: ellipsis;
                    }
                    .tv-strategy-empty {
                        font-size: 11px;
                        color: #7a7a7a;
                        margin: 6px 2px 10px 2px;
                    }
                    .tv-strategy-add {
                        display: flex;
                        flex-direction: column;
                        gap: 6px;
                    }
                    .tv-strategy-add.hidden {
                        display: none;
                    }
                    .tv-strategy-toggle {
                        background: #222222;
                        color: var(--tv-text-primary);
                        border: 1px solid #333333;
                        padding: 6px 8px;
                        border-radius: 4px;
                        font-size: 12px;
                        cursor: pointer;
                        margin: 6px 0;
                    }
                    .tv-strategy-toggle:hover {
                        background: #2f2f2f;
                    }
                    .tv-strategy-runbox {
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        gap: 8px;
                        margin: 6px 0;
                    }
                    .tv-strategy-run {
                        background: #1f2a1f;
                        color: #cfe8cf;
                        border: 1px solid #2f4a2f;
                        padding: 6px 10px;
                        border-radius: 4px;
                        font-size: 12px;
                        cursor: pointer;
                    }
                    .tv-strategy-run.running {
                        background: #3a1f1f;
                        color: #f3cfcf;
                        border-color: #5a2f2f;
                    }
                    .tv-strategy-status {
                        font-size: 11px;
                        color: #8c8c8c;
                    }
                    .tv-strategy-drop {
                        border: 1px dashed #3a3a3a;
                        border-radius: 6px;
                        padding: 14px 10px;
                        text-align: center;
                        font-size: 11px;
                        color: #9a9a9a;
                        background: #1a1a1a;
                        cursor: pointer;
                        min-height: 70px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                    }
                    .tv-strategy-drop.drag {
                        border-color: var(--tv-highlight);
                        color: var(--tv-text-primary);
                        background: #202020;
                    }
                    .tv-strategy-add input {
                        background: #1a1a1a;
                        border: 1px solid #333333;
                        color: var(--tv-text-primary);
                        padding: 6px 8px;
                        border-radius: 4px;
                        font-size: 12px;
                    }
                    .tv-strategy-add button {
                        background: #2b2b2b;
                        color: var(--tv-text-primary);
                        border: 1px solid #3a3a3a;
                        padding: 6px 8px;
                        border-radius: 4px;
                        font-size: 12px;
                        cursor: pointer;
                    }
                    .tv-strategy-add button:hover {
                        background: #3a3a3a;
                    }

                    #tv-side-toolbar {
                        position: fixed;
                        top: var(--tv-topbar-height);
                        right: 0;
                        width: 40px;
                        height: calc(100% - var(--tv-topbar-height) - var(--tv-bottom-height));
                        background: #161616;
                        border-left: 1px solid var(--tv-grid);
                        display: flex;
                        flex-direction: column;
                        align-items: center;
                        padding: 8px 0;
                        gap: 10px;
                        z-index: 1201;
                    }
                    .tv-tool-btn {
                        width: 28px;
                        height: 28px;
                        border-radius: 6px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        color: #bfbfbf;
                        cursor: pointer;
                    }
                    .tv-tool-btn:hover {
                        background: #2b2b2b;
                        color: #ffffff;
                    }
                    .tv-tool-btn.active {
                        background: #2c2c2c;
                        color: #ffffff;
                    }

                    #tv-bottom-bar {
                        position: fixed;
                        left: 0;
                        right: 0;
                        bottom: 0;
                        height: var(--tv-bottom-height);
                        background: #1b1b1b;
                        border-top: 1px solid var(--tv-grid);
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        padding: 0 12px;
                        z-index: 1200;
                        font-size: 12px;
                        color: var(--tv-text-secondary);
                    }
                    #tv-bottom-bar .tv-periods {
                        display: flex;
                        gap: 10px;
                        align-items: center;
                    }
                    .tv-period-btn {
                        color: var(--tv-text-secondary);
                        cursor: pointer;
                        padding: 4px 2px;
                        border-bottom: 2px solid transparent;
                    }
                    .tv-period-btn.active {
                        color: var(--tv-text-primary);
                        border-bottom-color: var(--tv-highlight);
                    }
                    #tv-bottom-bar .tv-left {
                        display: flex;
                        gap: 14px;
                        align-items: center;
                    }
                    #tv-bottom-bar .tv-right {
                        display: flex;
                        gap: 8px;
                        align-items: center;
                        color: var(--tv-text-secondary);
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
            symbol_id = self.chart.topbar['symbol_label'].id
        except Exception:
            return

        self.chart.run_script(f'''
            {sell_id}.classList.add("quote-box", "sell");
            {buy_id}.classList.add("quote-box", "buy");
            {spread_id}.classList.add("quote-box", "spread");
            {symbol_id}.classList.add("quote-box", "symbol");
        ''')

    def _bind_quote_actions(self):
        """Permite abrir operaciones desde los botones BUY/SELL."""
        self.quick_trade_handler = 'quick_trade_evt'
        self.chart.win.handlers[self.quick_trade_handler] = self.on_quick_trade
        try:
            sell_id = self.chart.topbar['sell_quote'].id
            buy_id = self.chart.topbar['buy_quote'].id
        except Exception:
            return
        self.chart.run_script(f'''
            {sell_id}.style.cursor = "pointer";
            {buy_id}.style.cursor = "pointer";
            {sell_id}.onclick = () => window.callbackFunction("{self.quick_trade_handler}_~_sell");
            {buy_id}.onclick = () => window.callbackFunction("{self.quick_trade_handler}_~_buy");
        ''')

    def on_quick_trade(self, side):
        side = (side or "").lower()
        if side not in ("buy", "sell"):
            return
        try:
            market_open, market_status = trading.is_market_open(config.SYMBOL)
            if not market_open:
                self.log_message(f"Mercado cerrado ({market_status})")
                return
            action_info = trading.apply_signal(
                config.SYMBOL,
                side,
                config.LOT,
                config.SL_POINTS,
                config.TP_POINTS,
                config.MAGIC_NUMBER
            )
            if action_info:
                self.update_last_action_ui(action_info)
        except Exception as e:
            self.log_message(f"Error al ejecutar {side.upper()}: {e}")

    def _hide_non_visual_widgets(self):
        """Oculta widgets de control para no alterar el layout visual."""
        keys = ['status', 'balance', 'action_icon', 'action_text', 'start', 'stop', 'refresh']
        for key in keys:
            widget = self.chart.topbar.get(key)
            if not widget:
                continue
            widget_id = widget.id
            self.chart.run_script(f'''
                if ({widget_id}.elem) {{
                    {widget_id}.elem.style.display = "none";
                }} else {{
                    {widget_id}.style.display = "none";
                }}
            ''')

    def _set_quote_box(self, widget_key: str, label: str, price_text: str):
        """Actualiza el HTML de una caja de cotización."""
        widget = self.chart.topbar.get(widget_key)
        if not widget:
            return
        if widget_key == "spread":
            html = f"<div class='quote-price'>{price_text}</div>"
        elif widget_key == "symbol_label":
            html = f"<div class='quote-label'>SYMBOL</div><div class='quote-price'>{price_text}</div>"
        else:
            html = f"<div class='quote-label'>{label}</div><div class='quote-price'>{price_text}</div>"
        widget_id = widget.id
        self.chart.run_script(f"{widget_id}.innerHTML = {json.dumps(html)};")

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

            price_fmt = f"{{:,.{digits}f}}"
            bid_text = price_fmt.format(bid)
            ask_text = price_fmt.format(ask)
            spread_text = price_fmt.format(ask - bid) if ask is not None and bid is not None else "--"

            self._set_quote_box("sell_quote", "SELL", bid_text)
            self._set_quote_box("buy_quote", "BUY", ask_text)
            self._set_quote_box("spread", "SPREAD", spread_text)
            self._set_quote_box("symbol_label", "SYMBOL", config.SYMBOL)
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

    def start_callback_pump(self):
        """Inicia el loop que procesa callbacks JS (botones, selectores, etc.)."""
        if self.callback_thread and self.callback_thread.is_alive():
            return
        self.callback_stop_event.clear()
        self.callback_thread = threading.Thread(target=self._callback_loop, daemon=True)
        self.callback_thread.start()

    def stop_callback_pump(self):
        """Detiene el loop de callbacks JS."""
        self.callback_stop_event.set()

    def _callback_loop(self):
        while not self.callback_stop_event.is_set():
            try:
                response = Chart.WV.emit_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            except Exception:
                break

            if response == 'exit':
                try:
                    Chart.WV.exit()
                except Exception:
                    pass
                self.chart.is_alive = False
                break

            try:
                func, args = parse_event_message(self.chart.win, response)
                if asyncio.iscoroutinefunction(func):
                    asyncio.run(func(*args))
                else:
                    func(*args)
            except Exception as e:
                self.log_message(f"Error en callback: {e}")

    def _quote_loop(self):
        while not self.quote_stop_event.is_set():
            self.update_quotes()
            self.update_bottom_clock()
            if self.quote_stop_event.wait(timeout=2):
                break

    def setup_side_panel(self):
        """Crea el panel lateral con noticias, sugerencias y panel clásico."""
        self.side_panel_handler = 'side_panel_evt'
        self.chart.win.handlers[self.side_panel_handler] = self.on_side_panel_event

        self._refresh_object_tree_items(render=False)
        items = self.object_tree_items
        save_dir = getattr(config, "FEEDBACK_SAVE_DIR", "feedback") or "feedback"
        webhook_url = (getattr(config, "FEEDBACK_WEBHOOK_URL", "") or "").strip()
        if webhook_url:
            feedback_target = "Webhook"
        else:
            feedback_target = f"Archivo local ({save_dir})"
        self._build_side_panel(items, feedback_target)
        self._render_strategy_panel()

    def _build_side_panel(self, items, feedback_target: str):
        icons = self._get_side_panel_icons()

        payload = json.dumps({
            "items": items,
            "icons": icons,
            "handler": self.side_panel_handler,
            "strategies": self._get_strategy_payload(),
            "selected_strategy": self.current_strategy_key or "",
            "feedback_target": feedback_target or "Archivo local",
        })

        self.chart.run_script(f'''            ;(function() {{
            const payload = {payload};
            const container = window.containerDiv;
            if (!container) return;

            let panel = document.getElementById("tv-side-panel");
            if (!panel) {{
                panel = document.createElement("div");
                panel.id = "tv-side-panel";
            }}
            panel.innerHTML = "";

            const oldToolbar = document.getElementById("tv-side-toolbar");
            if (oldToolbar) {{
                oldToolbar.remove();
            }}

            const newsPanel = document.createElement("div");
            newsPanel.id = "tv-news-panel";
            newsPanel.className = "tv-side-content";
            newsPanel.innerHTML = `
                <div class="tv-section-title">Noticias del mercado</div>
                <div class="tv-section-desc">Aquí aparecerán noticias relevantes del mercado actual (próximamente).</div>
            `;

            const feedbackPanel = document.createElement("div");
            feedbackPanel.id = "tv-feedback-panel";
            feedbackPanel.className = "tv-side-content";
            feedbackPanel.style.display = "none";

            const feedbackTitle = document.createElement("div");
            feedbackTitle.className = "tv-section-title";
            feedbackTitle.innerText = "Envíanos sugerencias";

            const feedbackDesc = document.createElement("div");
            feedbackDesc.className = "tv-section-desc";
            feedbackDesc.innerText = "Escribe tu sugerencia o petición. Se enviará desde la app.";

            const form = document.createElement("div");
            form.className = "tv-feedback-form";

            const subjectInput = document.createElement("input");
            subjectInput.id = "tv-feedback-subject";
            subjectInput.type = "text";
            subjectInput.placeholder = "Asunto (opcional)";

            const messageInput = document.createElement("textarea");
            messageInput.id = "tv-feedback-message";
            messageInput.placeholder = "Describe tu sugerencia o mejora...";
            messageInput.rows = 6;

            const sendBtn = document.createElement("button");
            sendBtn.type = "button";
            sendBtn.innerText = "Enviar";

            const statusLine = document.createElement("div");
            statusLine.id = "tv-feedback-status";
            statusLine.className = "tv-feedback-status";

            const feedbackHint = document.createElement("div");
            feedbackHint.className = "tv-feedback-hint";
            feedbackHint.innerText = "Destino: " + (payload.feedback_target || "Archivo local");

            const setStatus = (text, kind) => {{
                statusLine.innerText = text || "";
                statusLine.classList.remove("success", "error");
                if (kind === "success") {{
                    statusLine.classList.add("success");
                }}
                if (kind === "error") {{
                    statusLine.classList.add("error");
                }}
            }};

            const sendFeedback = () => {{
                const subjectRaw = (subjectInput.value || "Sugerencia Trading Agent").trim();
                const bodyRaw = (messageInput.value || "").trim();
                if (!bodyRaw) {{
                    setStatus("Escribe un mensaje antes de enviar.", "error");
                    return;
                }}
                setStatus("Enviando...", "");
                const subject = encodeURIComponent(subjectRaw);
                const body = encodeURIComponent(bodyRaw);
                window.callbackFunction(payload.handler + "_~_feedback_send;;;" + subject + ";;;" + body);
            }};

            sendBtn.addEventListener("click", sendFeedback);
            messageInput.addEventListener("keydown", (e) => {{
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {{
                    sendFeedback();
                }}
            }});

            form.appendChild(subjectInput);
            form.appendChild(messageInput);
            form.appendChild(sendBtn);
            form.appendChild(statusLine);
            form.appendChild(feedbackHint);

            feedbackPanel.appendChild(feedbackTitle);
            feedbackPanel.appendChild(feedbackDesc);
            feedbackPanel.appendChild(form);

            const legacyPanel = document.createElement("div");
            legacyPanel.id = "tv-legacy-panel";
            legacyPanel.className = "tv-legacy-panel";
            legacyPanel.style.display = "none";

            const legacyTabs = document.createElement("div");
            legacyTabs.className = "tv-side-tabs";
            const tabObjects = document.createElement("div");
            tabObjects.className = "tv-side-tab active";
            tabObjects.innerText = "Object Tree";
            const tabData = document.createElement("div");
            tabData.className = "tv-side-tab";
            tabData.innerText = "Data Window";
            const tabStrategies = document.createElement("div");
            tabStrategies.className = "tv-side-tab";
            tabStrategies.innerText = "Estrategias";
            legacyTabs.appendChild(tabObjects);
            legacyTabs.appendChild(tabData);
            legacyTabs.appendChild(tabStrategies);

            const list = document.createElement("div");
            list.className = "tv-side-list";
            list.id = "tv-side-list";

            const dataWindow = document.createElement("div");
            dataWindow.id = "tv-data-window";
            dataWindow.className = "tv-data-window";
            dataWindow.style.display = "none";
            dataWindow.innerHTML = `
                <div class="tv-data-header">
                    <div class="tv-data-title">Data Window</div>
                    <div class="tv-data-meta">
                        <div class="tv-data-row">
                            <span class="tv-data-label">Símbolo</span>
                            <span class="tv-data-value" id="tv-data-symbol">--</span>
                        </div>
                        <div class="tv-data-row">
                            <span class="tv-data-label">Timeframe</span>
                            <span class="tv-data-value" id="tv-data-timeframe">--</span>
                        </div>
                        <div class="tv-data-row">
                            <span class="tv-data-label">Hora</span>
                            <span class="tv-data-value" id="tv-data-time">--</span>
                        </div>
                    </div>
                </div>
                <div class="tv-data-body" id="tv-data-body"></div>
                <div class="tv-data-empty" id="tv-data-empty">Sin datos todavía.</div>
                <div class="tv-data-trades" id="tv-data-trades">
                    <div class="tv-data-section">Movimientos</div>
                    <div class="tv-data-trades-list" id="tv-data-trades-list"></div>
                    <div class="tv-data-empty" id="tv-data-trades-empty">No hay movimientos todavía.</div>
                </div>
            `;

            const strategyPanel = document.createElement("div");
            strategyPanel.id = "tv-strategy-panel";
            strategyPanel.style.display = "none";
            strategyPanel.style.padding = "10px";
            strategyPanel.style.color = "#b0b0b0";

            const strategyList = document.createElement("div");
            strategyList.id = "tv-strategy-list";
            strategyList.className = "tv-strategy-list";

            const strategyEmpty = document.createElement("div");
            strategyEmpty.id = "tv-strategy-empty";
            strategyEmpty.className = "tv-strategy-empty";
            strategyEmpty.innerText = "No hay estrategias registradas.";

            const toggleBtn = document.createElement("button");
            toggleBtn.type = "button";
            toggleBtn.className = "tv-strategy-toggle";
            toggleBtn.innerText = "Añadir estrategia";

            const runBox = document.createElement("div");
            runBox.className = "tv-strategy-runbox";
            const runBtn = document.createElement("button");
            runBtn.type = "button";
            runBtn.id = "tv-strategy-run";
            runBtn.className = "tv-strategy-run";
            runBtn.innerText = "Iniciar estrategia";
            const runStatus = document.createElement("div");
            runStatus.id = "tv-strategy-status";
            runStatus.className = "tv-strategy-status";
            runStatus.innerText = "Estado: detenido";
            runBox.appendChild(runBtn);
            runBox.appendChild(runStatus);

            const addBox = document.createElement("div");
            addBox.className = "tv-strategy-add hidden";
            const nameInput = document.createElement("input");
            nameInput.id = "tv-strategy-name";
            nameInput.placeholder = "Nombre (opcional)";
            const moduleInput = document.createElement("input");
            moduleInput.id = "tv-strategy-module";
            moduleInput.placeholder = "Módulo o ruta .py";

            const dropZone = document.createElement("div");
            dropZone.className = "tv-strategy-drop";
            dropZone.innerText = "Arrastra aquí tu .py (o haz click)";

            const fileInput = document.createElement("input");
            fileInput.type = "file";
            fileInput.accept = ".py";
            fileInput.style.display = "none";

            const addBtn = document.createElement("button");
            addBtn.type = "button";
            addBtn.innerText = "Añadir";

            const fireAdd = () => {{
                const name = encodeURIComponent((nameInput.value || "").trim());
                const moduleRef = encodeURIComponent((moduleInput.value || "").trim());
                if (!moduleRef) {{
                    return;
                }}
                window.callbackFunction(payload.handler + "_~_strategy_add;;;" + name + ";;;" + moduleRef);
            }};

            const handleFiles = (files) => {{
                if (!files || !files.length) return;
                const file = files[0];
                if (!file || !file.name || !file.name.toLowerCase().endsWith(".py")) {{
                    return;
                }}
                const reader = new FileReader();
                reader.onload = () => {{
                    const dataUrl = reader.result;
                    const name = encodeURIComponent(file.name);
                    const data = encodeURIComponent(dataUrl);
                    window.callbackFunction(payload.handler + "_~_strategy_drop;;;" + name + ";;;" + data);
                }};
                reader.readAsDataURL(file);
            }};

            addBtn.addEventListener("click", fireAdd);
            moduleInput.addEventListener("keydown", (e) => {{
                if (e.key === "Enter") fireAdd();
            }});
            nameInput.addEventListener("keydown", (e) => {{
                if (e.key === "Enter") fireAdd();
            }});

            toggleBtn.addEventListener("click", () => {{
                const isHidden = addBox.classList.contains("hidden");
                if (isHidden) {{
                    addBox.classList.remove("hidden");
                    toggleBtn.innerText = "Cerrar";
                }} else {{
                    addBox.classList.add("hidden");
                    toggleBtn.innerText = "Añadir estrategia";
                }}
            }});

            runBtn.addEventListener("click", () => {{
                window.callbackFunction(payload.handler + "_~_strategy_toggle");
            }});

            dropZone.addEventListener("click", () => {{
                fileInput.click();
            }});
            dropZone.addEventListener("dragover", (e) => {{
                e.preventDefault();
                dropZone.classList.add("drag");
            }});
            dropZone.addEventListener("dragleave", () => {{
                dropZone.classList.remove("drag");
            }});
            dropZone.addEventListener("drop", (e) => {{
                e.preventDefault();
                dropZone.classList.remove("drag");
                handleFiles(e.dataTransfer.files);
            }});
            fileInput.addEventListener("change", () => {{
                handleFiles(fileInput.files);
                fileInput.value = "";
            }});

            addBox.appendChild(nameInput);
            addBox.appendChild(moduleInput);
            addBox.appendChild(dropZone);
            addBox.appendChild(fileInput);
            addBox.appendChild(addBtn);

            strategyPanel.appendChild(strategyList);
            strategyPanel.appendChild(strategyEmpty);
            strategyPanel.appendChild(runBox);
            strategyPanel.appendChild(toggleBtn);
            strategyPanel.appendChild(addBox);

            legacyPanel.appendChild(legacyTabs);
            legacyPanel.appendChild(list);
            legacyPanel.appendChild(dataWindow);
            legacyPanel.appendChild(strategyPanel);

            tabObjects.addEventListener("click", () => {{
                tabObjects.classList.add("active");
                tabData.classList.remove("active");
                tabStrategies.classList.remove("active");
                list.style.display = "flex";
                dataWindow.style.display = "none";
                strategyPanel.style.display = "none";
            }});
            tabData.addEventListener("click", () => {{
                tabData.classList.add("active");
                tabObjects.classList.remove("active");
                tabStrategies.classList.remove("active");
                list.style.display = "none";
                dataWindow.style.display = "flex";
                strategyPanel.style.display = "none";
            }});
            tabStrategies.addEventListener("click", () => {{
                tabStrategies.classList.add("active");
                tabObjects.classList.remove("active");
                tabData.classList.remove("active");
                list.style.display = "none";
                dataWindow.style.display = "none";
                strategyPanel.style.display = "block";
            }});

            panel.appendChild(newsPanel);
            panel.appendChild(feedbackPanel);
            panel.appendChild(legacyPanel);
            if (!panel.parentElement) {{
                container.appendChild(panel);
            }}

            window.renderObjectTreeList = (data) => {{
                const list = document.getElementById("tv-side-list");
                if (!list) return;
                const tree = data || {{}};
                list.innerHTML = "";
                (tree.items || []).forEach((item, index) => {{
                    const row = document.createElement("div");
                    row.className = "tv-side-item" + (index === 0 ? " selected" : "");
                    row.dataset.key = item.key;
                    row.dataset.toggle = item.toggle ? "1" : "0";
                    row.dataset.visible = item.visible ? "1" : "0";

                    const left = document.createElement("div");
                    left.className = "tv-side-left";
                    const icon = document.createElement("span");
                    icon.className = "tv-side-icon";
                    icon.innerHTML = (tree.icons && tree.icons[item.icon]) || (tree.icons ? tree.icons.line : "");
                    const label = document.createElement("span");
                    label.className = "tv-side-label";
                    label.innerText = item.label;
                    left.appendChild(icon);
                    left.appendChild(label);

                    const eye = document.createElement("span");
                    eye.className = "tv-eye" + (item.visible ? "" : " hidden");
                    eye.innerHTML = item.toggle ? "👁" : "";

                    row.appendChild(left);
                    row.appendChild(eye);

                    row.addEventListener("click", (e) => {{
                        document.querySelectorAll(".tv-side-item").forEach((el) => el.classList.remove("selected"));
                        row.classList.add("selected");
                    }});

                    if (item.toggle) {{
                        eye.addEventListener("click", (e) => {{
                            e.stopPropagation();
                            window.callbackFunction(tree.handler + "_~_toggle;;;" + item.key);
                        }});
                    }} else {{
                        row.classList.add("dim");
                    }}

                    list.appendChild(row);
                }});
            }};

            if (window.renderObjectTreeList) {{
                window.renderObjectTreeList(payload);
            }}

            window.renderStrategyList = (data) => {{
                const list = document.getElementById("tv-strategy-list");
                const empty = document.getElementById("tv-strategy-empty");
                if (!list) return;
                list.innerHTML = "";
                (data.strategies || []).forEach((strategy) => {{
                    const row = document.createElement("div");
                    row.className = "tv-strategy-item" + (strategy.key === data.selected ? " selected" : "");
                    row.dataset.key = strategy.key;

                    const left = document.createElement("div");
                    left.className = "tv-strategy-left";

                    const title = document.createElement("div");
                    title.className = "tv-strategy-title";
                    title.innerText = strategy.label || strategy.key;

                    const module = document.createElement("div");
                    module.className = "tv-strategy-module";
                    module.innerText = strategy.module || "";

                    left.appendChild(title);
                    left.appendChild(module);
                    row.appendChild(left);

                    row.addEventListener("click", () => {{
                        window.callbackFunction(data.handler + "_~_strategy_select;;;" + strategy.key);
                    }});

                    list.appendChild(row);
                }});
                if (empty) {{
                    empty.style.display = (data.strategies && data.strategies.length) ? "none" : "block";
                }}
            }};

            window.setStrategyStatus = (running) => {{
                const btn = document.getElementById("tv-strategy-run");
                const status = document.getElementById("tv-strategy-status");
                if (btn) {{
                    btn.innerText = running ? "Detener estrategia" : "Iniciar estrategia";
                    btn.classList.toggle("running", !!running);
                }}
                if (status) {{
                    status.innerText = running ? "Estado: ejecutando" : "Estado: detenido";
                }}
            }};

            if (window.renderStrategyList) {{
                window.renderStrategyList({{
                    strategies: payload.strategies,
                    selected: payload.selected_strategy,
                    handler: payload.handler
                }});
            }}

            window.tvDataWindow = window.tvDataWindow || {{}};
            window.tvDataWindow._state = window.tvDataWindow._state || {{
                fields: [],
                dataMap: {{}},
                times: [],
                trades: [],
                latestTime: null,
                currentTime: null,
                meta: {{}},
                valueEls: {{}},
                tradeListEl: null,
                tradeEmptyEl: null
            }};

            window.tvDataWindow._ensureDom = () => {{
                const state = window.tvDataWindow._state;
                state.container = document.getElementById("tv-data-window");
                if (!state.container) return false;
                state.symbolEl = document.getElementById("tv-data-symbol");
                state.timeframeEl = document.getElementById("tv-data-timeframe");
                state.timeEl = document.getElementById("tv-data-time");
                state.bodyEl = document.getElementById("tv-data-body");
                state.emptyEl = document.getElementById("tv-data-empty");
                state.tradeListEl = document.getElementById("tv-data-trades-list");
                state.tradeEmptyEl = document.getElementById("tv-data-trades-empty");
                return true;
            }};

            window.tvDataWindow._formatTime = (time) => {{
                if (time === null || time === undefined) return "--";
                const dt = new Date(time * 1000);
                if (isNaN(dt.getTime())) return "--";
                const pad = (val) => String(val).padStart(2, "0");
                const y = dt.getFullYear();
                const m = pad(dt.getMonth() + 1);
                const d = pad(dt.getDate());
                const hh = pad(dt.getHours());
                const mm = pad(dt.getMinutes());
                const ss = pad(dt.getSeconds());
                return `${{y}}-${{m}}-${{d}} ${{hh}}:${{mm}}:${{ss}}`;
            }};

            window.tvDataWindow._formatValue = (value, format, digits) => {{
                if (value === null || value === undefined) return "--";
                const num = Number(value);
                if (Number.isNaN(num)) return String(value);
                if (format === "price") {{
                    return num.toLocaleString(undefined, {{
                        minimumFractionDigits: digits,
                        maximumFractionDigits: digits
                    }});
                }}
                if (format === "volume" || format === "int") {{
                    return Math.round(num).toLocaleString();
                }}
                if (format === "percent") {{
                    return (num * 100).toFixed(2) + "%";
                }}
                return num.toLocaleString(undefined, {{
                    minimumFractionDigits: 0,
                    maximumFractionDigits: 4
                }});
            }};

            window.tvDataWindow._findNearestTime = (target) => {{
                const state = window.tvDataWindow._state;
                const times = state.times || [];
                if (!times.length || typeof target !== "number") return state.latestTime;
                let lo = 0;
                let hi = times.length - 1;
                while (lo <= hi) {{
                    const mid = (lo + hi) >> 1;
                    const v = times[mid];
                    if (v === target) return v;
                    if (v < target) {{
                        lo = mid + 1;
                    }} else {{
                        hi = mid - 1;
                    }}
                }}
                if (hi < 0) return times[0];
                if (lo >= times.length) return times[times.length - 1];
                return (target - times[hi] <= times[lo] - target) ? times[hi] : times[lo];
            }};

            window.tvDataWindow._renderFields = () => {{
                const state = window.tvDataWindow._state;
                if (!window.tvDataWindow._ensureDom()) return;
                const body = state.bodyEl;
                if (!body) return;
                body.innerHTML = "";
                state.valueEls = {{}};
                let currentSection = "";
                (state.fields || []).forEach((field) => {{
                    if (!field || field.visible === false) return;
                    const section = field.section || "";
                    if (section && section !== currentSection) {{
                        currentSection = section;
                        const sectionEl = document.createElement("div");
                        sectionEl.className = "tv-data-section";
                        sectionEl.innerText = section;
                        body.appendChild(sectionEl);
                    }}
                    const row = document.createElement("div");
                    row.className = "tv-data-row";
                    const label = document.createElement("span");
                    label.className = "tv-data-label";
                    label.innerText = field.label || field.key || "";
                    const value = document.createElement("span");
                    value.className = "tv-data-value";
                    value.innerText = "--";
                    row.appendChild(label);
                    row.appendChild(value);
                    body.appendChild(row);
                    if (field.key) {{
                        state.valueEls[field.key] = value;
                    }}
                }});
            }};

            window.tvDataWindow._renderTrades = () => {{
                const state = window.tvDataWindow._state;
                if (!window.tvDataWindow._ensureDom()) return;
                const list = state.tradeListEl;
                const empty = state.tradeEmptyEl;
                if (!list) return;
                list.innerHTML = "";
                const trades = state.trades || [];
                if (!trades.length) {{
                    if (empty) empty.style.display = "block";
                    return;
                }}
                if (empty) empty.style.display = "none";
                const digits = (state.meta && typeof state.meta.digits === "number") ? state.meta.digits : 2;
                trades.forEach((trade) => {{
                    if (!trade) return;
                    const item = document.createElement("div");
                    item.className = "tv-trade-item";

                    const main = document.createElement("div");
                    main.className = "tv-trade-main";

                    const side = document.createElement("div");
                    const direction = (trade.direction || "").toUpperCase();
                    side.className = "tv-trade-side" + (direction === "BUY" ? " buy" : direction === "SELL" ? " sell" : "");
                    side.innerText = direction || "--";

                    const entry = document.createElement("div");
                    entry.className = "tv-trade-entry";
                    entry.innerText = trade.entry || "";

                    const price = document.createElement("div");
                    price.className = "tv-trade-price";
                    price.innerText = window.tvDataWindow._formatValue(trade.price, "price", digits);

                    main.appendChild(side);
                    main.appendChild(entry);
                    main.appendChild(price);

                    const meta = document.createElement("div");
                    meta.className = "tv-trade-meta";

                    const vol = document.createElement("span");
                    vol.innerText = trade.volume !== null && trade.volume !== undefined
                        ? "Vol " + window.tvDataWindow._formatValue(trade.volume, "number", digits)
                        : "Vol --";

                    const profit = document.createElement("span");
                    profit.className = "tv-trade-profit";
                    if (typeof trade.profit === "number") {{
                        const sign = trade.profit >= 0 ? "+" : "";
                        profit.innerText = "P/L " + sign + trade.profit.toFixed(2);
                        if (trade.profit > 0) profit.classList.add("pos");
                        if (trade.profit < 0) profit.classList.add("neg");
                    }} else {{
                        profit.innerText = "P/L --";
                    }}

                    const time = document.createElement("span");
                    time.innerText = window.tvDataWindow._formatTime(trade.time);

                    meta.appendChild(vol);
                    meta.appendChild(profit);
                    meta.appendChild(time);

                    item.appendChild(main);
                    item.appendChild(meta);

                    if (trade.comment) {{
                        const comment = document.createElement("div");
                        comment.className = "tv-trade-comment";
                        comment.innerText = trade.comment;
                        item.appendChild(comment);
                    }}

                    list.appendChild(item);
                }});
            }};

            window.tvDataWindow.setData = (payload) => {{
                const state = window.tvDataWindow._state;
                payload = payload || {{}};
                state.meta = payload.meta || state.meta || {{}};
                state.fields = payload.fields || state.fields || [];
                state.trades = payload.trades || [];
                state.dataMap = {{}};
                state.times = [];
                (payload.data || []).forEach((row) => {{
                    if (!row || row.time === null || row.time === undefined) return;
                    const key = String(row.time);
                    state.dataMap[key] = row;
                    state.times.push(row.time);
                }});
                if (state.times.length) {{
                    state.latestTime = payload.latest || state.times[state.times.length - 1];
                }} else {{
                    state.latestTime = payload.latest || null;
                }}
                window.tvDataWindow._renderFields();
                window.tvDataWindow._renderTrades();
                window.tvDataWindow.updateTime(state.latestTime);
            }};

            window.tvDataWindow.updateTime = (time) => {{
                const state = window.tvDataWindow._state;
                if (!window.tvDataWindow._ensureDom()) return;
                const digits = (state.meta && typeof state.meta.digits === "number") ? state.meta.digits : 2;
                if (state.symbolEl) state.symbolEl.innerText = state.meta.symbol || "--";
                if (state.timeframeEl) state.timeframeEl.innerText = state.meta.timeframe || "--";
                let keyTime = time;
                if (keyTime === null || keyTime === undefined) {{
                    keyTime = state.latestTime;
                }}
                if (typeof keyTime === "number" && !state.dataMap[String(keyTime)]) {{
                    const nearest = window.tvDataWindow._findNearestTime(keyTime);
                    if (nearest !== null && nearest !== undefined) {{
                        keyTime = nearest;
                    }}
                }}
                state.currentTime = keyTime;
                const row = (keyTime !== null && keyTime !== undefined) ? state.dataMap[String(keyTime)] : null;
                if (state.timeEl) state.timeEl.innerText = window.tvDataWindow._formatTime(keyTime);
                if (state.emptyEl) state.emptyEl.style.display = row ? "none" : "block";
                (state.fields || []).forEach((field) => {{
                    if (!field || field.visible === false) return;
                    const el = field.key ? state.valueEls[field.key] : null;
                    if (!el) return;
                    const val = row ? row[field.key] : null;
                    el.innerText = window.tvDataWindow._formatValue(val, field.format, digits);
                }});
            }};

            window.tvDataWindow._normalizeTime = (time) => {{
                if (time === null || time === undefined) return null;
                if (typeof time === "number") return time;
                if (typeof time === "string") {{
                    const parsed = Date.parse(time);
                    return isNaN(parsed) ? null : Math.floor(parsed / 1000);
                }}
                if (typeof time === "object") {{
                    if (time.timestamp) return time.timestamp;
                    if ("year" in time && "month" in time && "day" in time) {{
                        const utc = Date.UTC(time.year, time.month - 1, time.day);
                        return Math.floor(utc / 1000);
                    }}
                }}
                return null;
            }};

            window.tvDataWindow.updateFromParam = (param) => {{
                if (!param || param.time === undefined || param.time === null) {{
                    window.tvDataWindow.updateTime(null);
                    return;
                }}
                const normalized = window.tvDataWindow._normalizeTime(param.time);
                window.tvDataWindow.updateTime(normalized);
            }};

            if (window.tvDataWindow && window.tvDataWindow._ensureDom) {{
                window.tvDataWindow._ensureDom();
                window.tvDataWindow._renderFields();
                window.tvDataWindow.updateTime(window.tvDataWindow._state.latestTime);
            }}

            if (!window.dataWindowCrosshairBound) {{
                window.dataWindowCrosshairBound = true;
                window.dataWindowCrosshairHandler = (param) => {{
                    if (window.tvDataWindow && window.tvDataWindow.updateFromParam) {{
                        window.tvDataWindow.updateFromParam(param);
                    }}
                }};
                {self.chart.id}.chart.subscribeCrosshairMove(window.dataWindowCrosshairHandler);
                {self.tci_chart.id}.chart.subscribeCrosshairMove(window.dataWindowCrosshairHandler);
            }}

            const toolbar = document.createElement("div");
            toolbar.id = "tv-side-toolbar";
            const tools = [
                {{
                    key: "legacy",
                    label: "Panel clásico",
                    icon: "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.3'><path d='M2 8 L8 3 L14 8'/><path d='M4 7.5 V13 H12 V7.5'/><path d='M6 13 V10 H10 V13'/></svg>"
                }},
                {{
                    key: "news",
                    label: "Noticias",
                    icon: "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.3'><rect x='2' y='3' width='12' height='10' rx='1.5'/><path d='M5 6 H11'/><path d='M5 8 H11'/><path d='M5 10 H9'/></svg>"
                }},
                {{
                    key: "feedback",
                    label: "Sugerencias",
                    icon: "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.3'><path d='M2 4 H14 V12 H2 Z'/><path d='M2 4 L8 9 L14 4'/></svg>"
                }}
            ];
            const buttons = {{}};

            const activate = (key) => {{
                newsPanel.style.display = key === "news" ? "flex" : "none";
                feedbackPanel.style.display = key === "feedback" ? "flex" : "none";
                legacyPanel.style.display = key === "legacy" ? "flex" : "none";
                Object.keys(buttons).forEach((btnKey) => {{
                    buttons[btnKey].classList.toggle("active", btnKey === key);
                }});
            }};

            tools.forEach((tool) => {{
                const btn = document.createElement("div");
                btn.className = "tv-tool-btn";
                btn.innerHTML = tool.icon;
                btn.title = tool.label;
                btn.addEventListener("click", () => activate(tool.key));
                toolbar.appendChild(btn);
                buttons[tool.key] = btn;
            }});
            container.appendChild(toolbar);

            activate("legacy");
            }})();

        ''')
    def on_side_panel_event(self, action, *args):
        action = (action or "").strip()
        if action == "feedback_send":
            subject = unquote(args[0]) if len(args) > 0 else ""
            message = unquote(args[1]) if len(args) > 1 else ""
            self._handle_feedback_send(subject, message)
            return
        if action == "toggle" and args:
            self.toggle_indicator(args[0])
            return
        if action == "strategy_select" and args:
            self._set_strategy_by_key(args[0])
            return
        if action == "strategy_add":
            label = unquote(args[0]) if len(args) > 0 else ""
            module_ref = unquote(args[1]) if len(args) > 1 else ""
            self._add_strategy_from_input(label, module_ref)
            return
        if action == "strategy_drop":
            filename = unquote(args[0]) if len(args) > 0 else ""
            data_uri = unquote(args[1]) if len(args) > 1 else ""
            self._add_strategy_from_drop(filename, data_uri)
            return
        if action == "strategy_toggle":
            self._toggle_strategy_run()
            return

    def _handle_feedback_send(self, subject: str, message: str):
        subject = (subject or "").strip() or "Sugerencia Trading Agent"
        message = (message or "").strip()
        if not message:
            self._set_feedback_status("Escribe un mensaje antes de enviar.", "error")
            return

        payload = {
            "subject": subject,
            "message": message,
            "symbol": getattr(config, "SYMBOL", ""),
            "strategy": self.current_strategy_key or "",
            "timeframe": self.current_timeframe or "",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        saved_ok = self._save_feedback_local(payload)
        webhook_url = (getattr(config, "FEEDBACK_WEBHOOK_URL", "") or "").strip()
        if webhook_url:
            sent_ok, error = self._post_feedback_webhook(webhook_url, payload)
            if sent_ok:
                self._set_feedback_status("Enviado correctamente.", "success")
            else:
                if saved_ok:
                    self._set_feedback_status("No se pudo enviar, pero quedó guardado localmente.", "error")
                else:
                    self._set_feedback_status("No se pudo enviar.", "error")
                if error:
                    self.log_message(f"Error enviando feedback: {error}")
            return

        if saved_ok:
            self._set_feedback_status("Guardado localmente.", "success")
        else:
            self._set_feedback_status("No se pudo guardar localmente.", "error")

    def _save_feedback_local(self, payload: dict) -> bool:
        save_dir = getattr(config, "FEEDBACK_SAVE_DIR", "feedback") or "feedback"
        try:
            os.makedirs(save_dir, exist_ok=True)
            filename = f"feedback_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
            path = os.path.join(save_dir, filename)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
            return True
        except Exception as e:
            self.log_message(f"Error al guardar feedback: {e}")
            return False

    def _post_feedback_webhook(self, url: str, payload: dict):
        try:
            data = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"}
            )
            timeout = getattr(config, "FEEDBACK_TIMEOUT_SECONDS", 4) or 4
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.getcode()
            if 200 <= status < 300:
                return True, ""
            return False, f"HTTP {status}"
        except Exception as e:
            return False, str(e)

    def _set_feedback_status(self, text: str, kind: str = ""):
        text_js = json.dumps(text or "")
        kind_js = json.dumps(kind or "")
        clear_inputs = "true" if kind == "success" else "false"
        self.chart.run_script(f'''
            ;(function() {{
                var status = document.getElementById("tv-feedback-status");
                if (status) {{
                    status.textContent = {text_js};
                    status.classList.remove("success", "error");
                    var kind = {kind_js};
                    if (kind === "success") status.classList.add("success");
                    if (kind === "error") status.classList.add("error");
                }}
                if ({clear_inputs}) {{
                    var subject = document.getElementById("tv-feedback-subject");
                    var message = document.getElementById("tv-feedback-message");
                    if (subject) subject.value = "";
                    if (message) message.value = "";
                }}
            }})();
        ''')

    def _toggle_strategy_run(self):
        """Inicia o detiene el bot desde el panel de estrategias."""
        thread_alive = self.bot_thread is not None and self.bot_thread.is_alive()
        if self.bot_running and thread_alive:
            self.stop_bot()
            return
        if self.bot_running and not thread_alive:
            # Estado inconsistente: el hilo no está vivo pero el flag sigue activo.
            self.bot_running = False
        self.start_bot()

    def toggle_indicator(self, key: str):
        visible = not self.indicator_state.get(key, True)
        self.indicator_state[key] = visible
        self._apply_indicator_visibility(key, visible)
        self._sync_indicator_ui(key, visible)
        if self.price_data is not None:
            try:
                self._update_data_window(self.price_data)
            except Exception:
                pass

    def _apply_indicator_visibility(self, key: str, visible: bool):
        series_list = self.indicator_series.get(key, [])
        for series in series_list:
            if series is None:
                continue
            if visible:
                series.show_data()
            else:
                series.hide_data()

    def _sync_indicator_ui(self, key: str, visible: bool):
        visible_flag = "1" if visible else "0"
        eye = "👁" if visible else "👁"
        hidden_class = "" if visible else "hidden"
        self.chart.run_script(f'''
            ;(function() {{
                var row = document.querySelector(`.tv-side-item[data-key="{key}"]`);
                if (row) {{
                    row.dataset.visible = "{visible_flag}";
                    var eye = row.querySelector(".tv-eye");
                    if (eye) {{
                        eye.classList.remove("hidden");
                        if ("{hidden_class}" === "hidden") {{
                            eye.classList.add("hidden");
                        }}
                        eye.innerHTML = "{eye}";
                    }}
                    row.classList.toggle("dim", !{str(visible).lower()});
                }}
            }})();
        ''')

    def setup_bottom_bar(self):
        """Crea la barra inferior con periodos y estado de mercado."""
        self.bottom_bar_handler = 'bottom_bar_evt'
        self.chart.win.handlers[self.bottom_bar_handler] = self.on_bottom_bar_event

        periods = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "All"]
        payload = json.dumps({
            "periods": periods,
            "handler": self.bottom_bar_handler,
        })

        self.chart.run_script(f'''
            ;(function() {{
            const payload = {payload};
            const container = window.containerDiv;
            if (!container) return;

            if (!document.getElementById("tv-bottom-bar")) {{
                const bar = document.createElement("div");
                bar.id = "tv-bottom-bar";

                const left = document.createElement("div");
                left.className = "tv-left";
                const trading = document.createElement("div");
                trading.id = "tv-trading-panel";
                trading.innerText = "Trading Panel";
                left.appendChild(trading);

                const periods = document.createElement("div");
                periods.className = "tv-periods";
                payload.periods.forEach((label) => {{
                    const btn = document.createElement("div");
                    btn.className = "tv-period-btn";
                    btn.dataset.period = label;
                    btn.innerText = label;
                    btn.addEventListener("click", () => {{
                        window.callbackFunction(payload.handler + "_~_" + label);
                    }});
                    periods.appendChild(btn);
                }});
                left.appendChild(periods);

                const right = document.createElement("div");
                right.className = "tv-right";
                const clock = document.createElement("div");
                clock.id = "tv-clock";
                clock.innerText = "--:--:-- UTC";
                const session = document.createElement("div");
                session.id = "tv-session";
                session.innerText = "RTH";
                right.appendChild(clock);
                right.appendChild(session);

                bar.appendChild(left);
                bar.appendChild(right);
                container.appendChild(bar);

                container.style.paddingBottom = "var(--tv-bottom-height)";
            }}
            }})();
        ''')

        self.set_bottom_period_active(self.view_period)

    def set_bottom_period_active(self, period: str):
        self.chart.run_script(f'''
            ;(function() {{
                document.querySelectorAll(".tv-period-btn").forEach((btn) => {{
                    btn.classList.toggle("active", btn.dataset.period === "{period}");
                }});
            }})();
        ''')

    def on_bottom_bar_event(self, period):
        if period:
            self.view_period = period
            self.set_bottom_period_active(period)
            self.refresh_data()

    def update_bottom_clock(self):
        """Actualiza reloj y sesión en la barra inferior."""
        try:
            now = datetime.now()
            offset = now.astimezone().utcoffset()
            offset_fmt = "UTC"
            if offset is not None:
                total_minutes = int(offset.total_seconds() / 60)
                sign = "+" if total_minutes >= 0 else "-"
                total_minutes = abs(total_minutes)
                hours = total_minutes // 60
                minutes = total_minutes % 60
                if minutes == 0:
                    offset_fmt = f"UTC{sign}{hours}"
                else:
                    offset_fmt = f"UTC{sign}{hours}:{minutes:02d}"
            clock_text = now.strftime("%H:%M:%S") + f" {offset_fmt}"
            self.chart.run_script(f'''
                ;(function() {{
                    var clock = document.getElementById("tv-clock");
                    if (clock) clock.innerText = "{clock_text}";
                }})();
            ''')
        except Exception:
            pass
    
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
            self.update_bottom_clock()
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
            widget = self.chart.topbar.get('balance')
            if widget:
                widget.set(balance)
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
                df = self._apply_strategy_processing(df)
                
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
            self.chart.run_script(f'{self.chart.id}.series.applyOptions({{visible: true}})')
            try:
                self.chart.show_data()
                self.chart.run_script(f'{self.chart.id}.volumeSeries.applyOptions({{visible: true}})')
            except Exception:
                pass
            # Asegurar que los datos queden dentro del viewport
            try:
                self.chart.time_scale(
                    right_offset=5,
                    min_bar_spacing=2.0,
                    time_visible=True,
                    seconds_visible=False,
                    border_visible=True,
                    border_color='#3a3a3a'
                )
                self.chart.fit()
            except Exception:
                pass
            
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
                filtered_deals = []

                if deals:
                    # Deduplicar por position_id (evitar múltiples fills por la misma operación)
                    for deal in deals:
                        if deal.symbol != config.SYMBOL:
                            continue
                        if hasattr(deal, "magic") and deal.magic != config.MAGIC_NUMBER:
                            continue
                        filtered_deals.append(deal)

                self._latest_deals_cache = filtered_deals
                self._latest_deals_range = (start_time, end_time)

                if filtered_deals:
                    dedup = {}
                    for deal in filtered_deals:
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

            try:
                self._update_data_window(df)
            except Exception as e:
                self.log_message(f"Error al actualizar data window: {e}")

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

    def _get_symbol_digits(self) -> int:
        """Devuelve los dígitos de precio del símbolo actual."""
        try:
            info = mt5.symbol_info(config.SYMBOL)
            if info and hasattr(info, "digits"):
                return int(info.digits)
        except Exception:
            pass
        return 2

    def _format_deals_for_data_window(self, deals, limit: int = 40):
        """Convierte deals de MT5 en una lista amigable para el Data Window."""
        if not deals:
            return []
        trades = []
        try:
            ordered = sorted(deals, key=lambda d: getattr(d, "time", 0), reverse=True)
        except Exception:
            ordered = list(deals)

        for deal in ordered:
            try:
                deal_time = getattr(deal, "time", None)
                if not isinstance(deal_time, (int, float)):
                    continue
                deal_type = getattr(deal, "type", None)
                if deal_type == mt5.DEAL_TYPE_BUY:
                    direction = "BUY"
                elif deal_type == mt5.DEAL_TYPE_SELL:
                    direction = "SELL"
                else:
                    direction = "OTHER"

                entry = getattr(deal, "entry", None)
                if entry == mt5.DEAL_ENTRY_IN:
                    entry_label = "IN"
                elif entry == mt5.DEAL_ENTRY_OUT:
                    entry_label = "OUT"
                elif entry == mt5.DEAL_ENTRY_INOUT:
                    entry_label = "IN/OUT"
                else:
                    entry_label = ""

                price = getattr(deal, "price", None)
                volume = getattr(deal, "volume", None)
                profit = getattr(deal, "profit", None)
                ticket = getattr(deal, "position_id", None) or getattr(deal, "ticket", None)
                comment = getattr(deal, "comment", None)

                trade = {
                    "time": int(deal_time),
                    "direction": direction,
                    "entry": entry_label,
                    "price": float(price) if isinstance(price, (int, float)) else None,
                    "volume": float(volume) if isinstance(volume, (int, float)) else None,
                    "profit": float(profit) if isinstance(profit, (int, float)) else None,
                    "ticket": str(ticket) if ticket is not None else "",
                    "comment": str(comment) if comment else "",
                }
                trades.append(trade)
            except Exception:
                continue
            if limit and len(trades) >= limit:
                break

        return trades

    def _build_data_window_payload(self, df: pd.DataFrame):
        """Construye el payload con datos para el Data Window."""
        if df is None or len(df) == 0:
            return None

        time_values = None
        try:
            candle_data = getattr(self.chart, "candle_data", None)
            if isinstance(candle_data, pd.DataFrame) and "time" in candle_data.columns:
                if len(candle_data) == len(df):
                    time_values = candle_data["time"].tolist()
        except Exception:
            time_values = None

        if time_values is None:
            try:
                time_values = (
                    pd.to_datetime(df["time"]).astype("int64") // 10 ** 9
                ).tolist()
            except Exception:
                time_values = list(range(len(df)))

        data_df = pd.DataFrame({"time": time_values})

        for col in ("open", "high", "low", "close"):
            if col in df.columns:
                data_df[col] = df[col]

        if "tick_volume" in df.columns:
            data_df["volume"] = df["tick_volume"]
        elif "volume" in df.columns:
            data_df["volume"] = df["volume"]

        if "average" in df.columns:
            data_df["average"] = df["average"]
        if "upper" in df.columns:
            data_df["upper"] = df["upper"]
        if "lower" in df.columns:
            data_df["lower"] = df["lower"]

        if "supertrend_up" in df.columns:
            data_df["supertrend_up"] = df["supertrend_up"]
        if "supertrend_down" in df.columns:
            data_df["supertrend_down"] = df["supertrend_down"]

        if "tci_hist" in df.columns:
            data_df["tci_hist"] = df["tci_hist"].shift(1)
        if "tci_signal" in df.columns:
            data_df["tci_signal"] = df["tci_signal"].shift(1)

        fields = []

        def add_field(key, label, fmt, section, group=None):
            if key not in data_df.columns:
                return
            visible = True
            if group:
                visible = bool(self.indicator_state.get(group, True))
            fields.append({
                "key": key,
                "label": label,
                "format": fmt,
                "section": section,
                "visible": visible
            })

        add_field("open", "Apertura", "price", "Precio")
        add_field("high", "Máximo", "price", "Precio")
        add_field("low", "Mínimo", "price", "Precio")
        add_field("close", "Cierre", "price", "Precio")
        add_field("volume", "Volumen", "volume", "Volumen")

        add_field("average", "Average", "price", "Baseline", "baseline")
        add_field("upper", "Upper", "price", "ATR Bands", "atr_bands")
        add_field("lower", "Lower", "price", "ATR Bands", "atr_bands")
        add_field("supertrend_up", "Supertrend Up", "price", "Supertrend", "supertrend")
        add_field("supertrend_down", "Supertrend Down", "price", "Supertrend", "supertrend")
        add_field("tci_hist", "TuTCI", "number", "TuTCI", "tci")
        add_field("tci_signal", "TuTCI Signal", "number", "TuTCI", "tci")

        data_df = data_df.astype(object).where(pd.notnull(data_df), None)
        records = data_df.to_dict(orient="records")
        latest_time = time_values[-1] if time_values else None
        trades = self._format_deals_for_data_window(getattr(self, "_latest_deals_cache", None))

        return {
            "meta": {
                "symbol": getattr(config, "SYMBOL", ""),
                "timeframe": getattr(self, "current_timeframe", ""),
                "digits": self._get_symbol_digits(),
            },
            "fields": fields,
            "data": records,
            "latest": latest_time,
            "trades": trades
        }

    def _update_data_window(self, df: pd.DataFrame):
        """Envía los datos del Data Window al frontend."""
        payload = self._build_data_window_payload(df)
        if not payload:
            return
        payload_json = json.dumps(payload, ensure_ascii=False)
        self.chart.run_script(f'''
            ;(function() {{
                if (window.tvDataWindow && window.tvDataWindow.setData) {{
                    window.tvDataWindow.setData({payload_json});
                }}
            }})();
        ''')
    
    def update_equity_chart(self):
        """Actualiza el gráfico de equity."""
        try:
            if self.equity_chart is None or self.equity_line is None:
                return
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

            if self.tci_sync_line is not None:
                sync_df = df[['time']].copy()
                sync_df['TuTCI Sync'] = 0.0
                self.tci_sync_line.set(sync_df)

            tci_view = df[['time', 'tci_hist', 'tci_signal']].copy()
            tci_view[['tci_hist', 'tci_signal']] = tci_view[['tci_hist', 'tci_signal']].shift(1)

            hist_df = tci_view[['time', 'tci_hist']].dropna().copy()
            hist_df = hist_df.rename(columns={'tci_hist': 'TuTCI'})
            if len(hist_df) > 0:
                hist_df['color'] = np.where(hist_df['TuTCI'] >= 0, '#e6e6e6', '#9e9e9e')
                self.tci_hist.set(hist_df)
            else:
                self.tci_hist.set(pd.DataFrame())

            fill_df = tci_view[['time', 'tci_signal']].dropna().copy()
            fill_df = fill_df.rename(columns={'tci_signal': 'TuTCI Fill'})
            if len(fill_df) > 0:
                self.tci_fill.set(fill_df)
            else:
                self.tci_fill.set(pd.DataFrame())

            signal_df = tci_view[['time', 'tci_signal']].dropna().copy()
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
            timeframe_widget = chart.topbar.get('timeframe') if chart else None
            timeframe_str = timeframe_widget.value if timeframe_widget else None
            if not timeframe_str:
                return
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
            period_widget = chart.topbar.get('period') if chart else None
            if period_widget:
                period_str = period_widget.value
                self.view_period = period_str
                self.set_bottom_period_active(period_str)
                self.log_message(f"Periodo cambiado a {period_str}")
                self.refresh_data()
            
        except Exception as e:
            self.log_message(f"Error al cambiar periodo: {e}")

    def on_symbol_change(self, chart):
        """Cambia el símbolo a operar desde la lista."""
        try:
            selector = chart.topbar.get('symbol_select') if chart else None
            symbol = selector.value if selector else None
        except Exception:
            self.log_message("No se pudo leer el símbolo seleccionado")
            return

        if not symbol:
            return

        try:
            mt5_connection.check_symbol(symbol)
            config.SYMBOL = symbol
            self.chart.watermark(symbol, color='rgba(180, 180, 200, 0.3)')
            self.log_message(f"Símbolo cambiado a {symbol}")
            self.refresh_data()
            self.update_quotes()
            self.chart.run_script(f'''
                ;(function() {{
                    var row = document.querySelector('.tv-side-item[data-key="symbol"] .tv-side-label');
                    if (row) row.innerText = "{symbol} · MT5";
                }})();
            ''')
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

            status_widget = self.chart.topbar.get('status')
            if status_widget:
                status_widget.set('Ejecutando')
            self.log_message("Bot iniciado")
            self._sync_strategy_status_ui()
            
        except Exception as e:
            self.log_message(f"Error al iniciar bot: {e}")
            self.bot_running = False
            self._sync_strategy_status_ui()
    
    def stop_bot(self, chart=None):
        """Detiene el bot."""
        if not self.bot_running:
            return
        
        self.bot_running = False
        self.stop_event.set()

        status_widget = self.chart.topbar.get('status')
        if status_widget:
            status_widget.set('Detenido')
        self.log_message("Bot detenido")
        self._sync_strategy_status_ui()
    
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
                    df = self._apply_strategy_processing(df)
                    
                    test_mode = getattr(config, "TEST_MODE", False)
                    if test_mode:
                        signal = self._get_strategy_signal(df, verbose=False)
                        market_open, market_status = True, "TEST_MODE (sin check)"
                    else:
                        signal = self._get_strategy_signal(df, verbose=False)
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
            self._sync_strategy_status_ui()
    
    def run(self):
        """Ejecuta la aplicación."""
        # Inicializar MT5
        if not self.init_mt5():
            self.log_message("No se pudo inicializar MT5. Ejecutando sin datos.")

        # Iniciar actualizaciones y cargar datos una vez visible el gráfico
        self.start_quote_updater()

        # Mostrar gráfico
        self.log_message("Iniciando interfaz grafica...")
        try:
            self.chart.show(block=False)
            for _ in range(50):
                if getattr(self.chart.win, "loaded", False):
                    break
                time.sleep(0.1)
            self.start_callback_pump()
            self.refresh_data()
            while self.chart.is_alive:
                time.sleep(0.1)
        finally:
            self.stop_quote_updater()
            self.stop_callback_pump()


def main():
    """Función principal."""
    app = TradingBotGUI()
    app.run()


if __name__ == "__main__":
    main()
