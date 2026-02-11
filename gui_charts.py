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
import zlib
from datetime import datetime, timedelta, timezone
import json
import urllib.error
import urllib.request
from urllib.parse import unquote, urlparse, urlunparse

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
    # Para peques: esta clase controla la interfaz del bot (grafico, botones y paneles).
    """
    Interfaz gráfica del bot de trading usando Lightweight Charts.
    """
    
    def __init__(self):
        # Para peques: esta funcion sirve para preparar todo al inicio.
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
        # None/0 = sin límite (mostrar todas las operaciones)
        self.max_action_markers = getattr(config, "MAX_ACTION_MARKERS", None)
        self.quote_thread = None
        self.quote_stop_event = threading.Event()
        self.callback_thread = None
        self.callback_stop_event = threading.Event()
        self._latest_deals_cache = []
        self._latest_deals_range = None
        self.strategy_timeframe = None
        self.timeframe_locked = False
        self._last_strategy_sync_ts = 0.0

        # Panel de indicadores
        self.indicator_panel = None
        self.indicator_rows = {}
        self.indicator_state = {}
        self.indicator_series = {}
        self.object_tree_items = []
        self.position_state = {
            "long_active": False,
            "short_active": False,
            "long_count": 0,
            "short_count": 0,
        }
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
        self.strategy_data_all_actives = False
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
        # Para peques: esta funcion sirve para iniciar registro de estrategias.
        """Inicializa el registro de estrategias disponibles."""
        self.strategy_registry = {}
        baseline_module = "strategies.strategy_baseline"
        legacy_baseline_module = "strategy_baseline"
        self._register_strategy(
            key="baseline",
            label="Baseline (Dir_1)",
            module_ref=baseline_module
        )
        self._register_strategy(
            key="m1_test",
            label="M1 Test (EMA Cross)",
            module_ref="strategies.strategy_m1_test"
        )
        self._register_strategy(
            key="m1_candle",
            label="M1 Candle Confirmed",
            module_ref="strategies.strategy_m1_candle"
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

        # Descubre estrategias adicionales guardadas en la carpeta strategies/
        self._sync_strategy_registry_from_disk(load_entries=False, force=True)
        default_key = cfg_key
        if default_key not in self.strategy_registry:
            default_key = "baseline"

        active_from_config = getattr(config, "ACTIVE_STRATEGIES", None)
        if isinstance(active_from_config, (list, tuple, set)):
            requested_active = [self._slugify(str(k)) for k in active_from_config if str(k).strip()]
        else:
            requested_active = [default_key]

        active_keys = [k for k in requested_active if k in self.strategy_registry]
        if not active_keys:
            active_keys = [default_key]

        for key, entry in self.strategy_registry.items():
            self._load_strategy_entry(entry)
            entry["enabled"] = key in active_keys
        config.ACTIVE_STRATEGIES = list(active_keys)

        self._set_strategy_by_key(default_key, refresh=False, sync_ui=False)

    def _register_strategy(self, key: str, label: str, module_ref: str):
        # Para peques: esta funcion sirve para registrar una estrategia.
        self.strategy_registry[key] = {
            "key": key,
            "label": label,
            "module": module_ref,
            "module_obj": None,
            "enabled": False,
            "timeframe_value": None,
            "timeframe_label": "",
            "magic_number": None,
            "last_signal": "none",
            "last_market_status": "",
            "last_error": "",
            "last_run_at": "",
            "last_df": None,
        }

    def _strategy_module_stem(self, module_ref: str) -> str:
        module_ref = (module_ref or "").strip()
        if not module_ref:
            return ""
        path_like = module_ref.endswith(".py") or any(
            sep in module_ref for sep in (os.sep, os.altsep) if sep
        )
        if path_like:
            return os.path.splitext(os.path.basename(module_ref))[0].strip().lower()
        return module_ref.split(".")[-1].strip().lower()

    def _normalize_strategy_module_ref(self, module_ref: str) -> str:
        module_ref = (module_ref or "").strip()
        if not module_ref:
            return ""
        path_like = module_ref.endswith(".py") or any(
            sep in module_ref for sep in (os.sep, os.altsep) if sep
        )
        if path_like:
            path = module_ref
            if not os.path.isabs(path):
                path = os.path.join(os.path.dirname(__file__), path)
            return os.path.normcase(os.path.normpath(path))
        return module_ref

    def _discover_strategies_from_dir(self):
        base_dir = self._get_strategy_dir()
        reserved_stems = {
            "__init__",
            "strategy_baseline",
            "strategy_m1_test",
            "strategy_m1_candle",
        }
        discovered = []

        try:
            filenames = sorted(os.listdir(base_dir), key=str.lower)
        except Exception as e:
            self.log_message(f"No se pudo escanear directorio de estrategias: {e}")
            return discovered

        project_root = os.path.dirname(__file__)
        for filename in filenames:
            path = os.path.join(base_dir, filename)
            if not os.path.isfile(path):
                continue
            if not filename.lower().endswith(".py"):
                continue

            stem = os.path.splitext(filename)[0]
            stem_lower = stem.lower()
            if not stem_lower or stem_lower in reserved_stems or stem_lower.startswith("__"):
                continue

            try:
                module_ref = os.path.relpath(path, project_root)
            except Exception:
                module_ref = path

            discovered.append({
                "key": self._slugify(stem),
                "label": stem,
                "module": module_ref,
                "stem": stem_lower,
            })

        return discovered

    def _sync_strategy_registry_from_disk(self, load_entries: bool = False, force: bool = False) -> int:
        now_ts = time.time()
        last_sync = getattr(self, "_last_strategy_sync_ts", 0.0)
        if not force and (now_ts - last_sync) < 1.0:
            return 0
        self._last_strategy_sync_ts = now_ts

        discovered = self._discover_strategies_from_dir()
        if not discovered:
            return 0

        existing_modules = set()
        existing_stems = set()
        for entry in self.strategy_registry.values():
            module_ref = entry.get("module", "")
            normalized = self._normalize_strategy_module_ref(module_ref)
            stem = self._strategy_module_stem(module_ref)
            if normalized:
                existing_modules.add(normalized)
            if stem:
                existing_stems.add(stem)

        added = 0
        for item in discovered:
            module_ref = item.get("module", "")
            normalized = self._normalize_strategy_module_ref(module_ref)
            stem = (item.get("stem") or "").strip().lower()

            if normalized in existing_modules:
                continue
            if stem and stem in existing_stems:
                continue

            base_key = item.get("key") or "strategy"
            key = base_key
            suffix = 2
            while key in self.strategy_registry:
                key = f"{base_key}_{suffix}"
                suffix += 1

            self._register_strategy(key, item.get("label") or key, module_ref)
            existing_modules.add(normalized)
            if stem:
                existing_stems.add(stem)
            added += 1

            if load_entries:
                entry = self.strategy_registry.get(key)
                if entry is not None:
                    self._load_strategy_entry(entry)

        return added

    def _resolve_strategy_magic_number(self, key: str, module) -> int:
        # Para peques: esta funcion sirve para calcular el numero magico de una estrategia.
        """Genera un magic number estable por estrategia."""
        module_magic = getattr(module, "MAGIC_NUMBER", None) if module is not None else None
        if isinstance(module_magic, int) and module_magic > 0:
            return int(module_magic)

        base_magic = int(getattr(config, "MAGIC_NUMBER", 1) or 1)
        offset = (zlib.crc32((key or "").encode("utf-8")) % 997) + 1

        candidate = base_magic * 1000 + offset
        if candidate > 2147483646:
            candidate = base_magic + offset
        return int(candidate)

    def _load_strategy_entry(self, entry: dict) -> bool:
        # Para peques: esta funcion sirve para cargar una estrategia del registro.
        """Carga y valida una estrategia del registro."""
        if not isinstance(entry, dict):
            return False

        try:
            module = self._load_strategy_module(entry.get("module", ""))
        except Exception as e:
            entry["module_obj"] = None
            entry["last_error"] = str(e)
            self.log_message(f"No se pudo cargar estrategia {entry.get('label', '')}: {e}")
            return False

        if module is None:
            entry["module_obj"] = None
            entry["last_error"] = "No se pudo cargar el módulo"
            return False

        if not hasattr(module, "get_last_signal"):
            entry["module_obj"] = None
            entry["last_error"] = "La estrategia no define get_last_signal()."
            self.log_message(f"Estrategia inválida {entry.get('label', '')}: falta get_last_signal().")
            return False

        raw_value = self._get_strategy_timeframe(module)
        timeframe_value = self._resolve_timeframe_value(raw_value) if raw_value is not None else None
        timeframe_label = ""
        if timeframe_value is not None:
            timeframe_label = self._timeframe_label(timeframe_value)
            if not timeframe_label and isinstance(raw_value, str):
                timeframe_label = raw_value.strip().upper()
        elif raw_value is not None:
            self.log_message(f"Timeframe inválido en estrategia '{entry.get('label', '')}': {raw_value}")

        entry["module_obj"] = module
        entry["timeframe_value"] = timeframe_value
        entry["timeframe_label"] = timeframe_label or ""
        entry["magic_number"] = self._resolve_strategy_magic_number(entry.get("key", ""), module)
        entry["last_error"] = ""
        return True

    def _get_strategy_entry(self, key: str):
        # Para peques: esta funcion sirve para obtener una estrategia del registro.
        return self.strategy_registry.get((key or "").strip())

    def _get_selected_strategy_entry(self):
        # Para peques: esta funcion sirve para obtener la estrategia seleccionada.
        entry = self._get_strategy_entry(self.current_strategy_key or "")
        if entry:
            return entry
        if self.strategy_registry:
            return next(iter(self.strategy_registry.values()))
        return None

    def _get_enabled_strategy_entries(self):
        # Para peques: esta funcion sirve para obtener las estrategias activas.
        entries = []
        for entry in self.strategy_registry.values():
            if not entry.get("enabled"):
                continue
            if entry.get("module_obj") is None:
                if not self._load_strategy_entry(entry):
                    continue
            entries.append(entry)
        return entries

    def _set_strategy_enabled(self, key: str, enabled: bool, sync_ui: bool = True):
        # Para peques: esta funcion sirve para activar o desactivar una estrategia.
        entry = self._get_strategy_entry(key)
        if not entry:
            self.log_message(f"Estrategia desconocida: {key}")
            return

        if enabled and entry.get("module_obj") is None:
            if not self._load_strategy_entry(entry):
                return

        entry["enabled"] = bool(enabled)
        state_text = "activa" if entry["enabled"] else "inactiva"
        self.log_message(f"Estrategia {entry['label']} -> {state_text}")
        config.ACTIVE_STRATEGIES = [e["key"] for e in self.strategy_registry.values() if e.get("enabled")]

        if self.bot_running and not self._get_enabled_strategy_entries():
            self.log_message("No hay estrategias activas. Se detiene el bot.")
            self.stop_bot()

        if sync_ui:
            self._render_strategy_panel()

    def _get_strategy_dir(self) -> str:
        # Para peques: esta funcion sirve para obtener la carpeta de estrategias.
        base_dir = getattr(config, "STRATEGY_DIR", "strategies")
        if not os.path.isabs(base_dir):
            base_dir = os.path.join(os.path.dirname(__file__), base_dir)
        os.makedirs(base_dir, exist_ok=True)
        return base_dir

    def _sanitize_strategy_filename(self, filename: str) -> str:
        # Para peques: esta funcion sirve para limpiar el nombre del archivo de estrategia.
        name = os.path.basename(filename or "").strip()
        name = name.replace(" ", "_")
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
        if not name:
            name = "strategy.py"
        if not name.lower().endswith(".py"):
            name = f"{name}.py"
        return name

    def _save_strategy_file(self, filename: str, content: bytes):
        # Para peques: esta funcion sirve para guardar un archivo de estrategia.
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
        # Para peques: esta funcion sirve para crear nombre corto.
        text = (text or "").strip().lower()
        text = re.sub(r"[^a-z0-9_]+", "_", text)
        text = text.strip("_")
        return text or "strategy"

    def _get_strategy_payload(self):
        # Para peques: esta funcion sirve para armar la lista de estrategias para la interfaz.
        payload = []
        for entry in self.strategy_registry.values():
            signal = (entry.get("last_signal") or "none").upper()
            status_parts = []
            if entry.get("enabled"):
                status_parts.append("activa")
            else:
                status_parts.append("inactiva")
            if signal and signal != "NONE":
                status_parts.append(f"senal: {signal}")
            market_status = (entry.get("last_market_status") or "").strip()
            if market_status:
                status_parts.append(market_status)
            error_text = (entry.get("last_error") or "").strip()
            if error_text:
                status_parts.append(f"error: {error_text}")

            payload.append({
                "key": entry["key"],
                "label": entry["label"],
                "module": entry["module"],
                "enabled": bool(entry.get("enabled")),
                "timeframe": entry.get("timeframe_label") or (self._timeframe_label(config.TIMEFRAME) or self.current_timeframe or ""),
                "magic": int(entry.get("magic_number") or 0),
                "status": " | ".join(status_parts),
                "last_run": entry.get("last_run_at") or "",
            })
        return payload

    def _get_side_panel_icons(self):
        # Para peques: esta funcion sirve para obtener los iconos del panel lateral.
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
        # Para peques: esta funcion sirve para obtener el catalogo del arbol de objetos.
        return {
            "baseline": {"label": "Baseline", "icon": "line", "toggle": True, "visible": True},
            "atr_bands": {"label": "ATR Bands", "icon": "bands", "toggle": True, "visible": True},
            "supertrend": {"label": "Supertrend w/ HMA", "icon": "trend", "toggle": True, "visible": True},
            "tci": {"label": "TuTCI", "icon": "hist", "toggle": True, "visible": True},
        }

    def _get_default_object_tree_items(self):
        # Para peques: esta funcion sirve para obtener los elementos por defecto del arbol de objetos.
        defaults = getattr(config, "OBJECT_TREE_DEFAULT_ITEMS", None)
        if isinstance(defaults, (list, tuple)) and defaults:
            return list(defaults)
        return ["baseline", "atr_bands", "supertrend", "tci"]

    def _merge_object_tree_items(self, primary, fallback):
        # Para peques: esta funcion sirve para unir listas de elementos del arbol de objetos.
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
        # Para peques: esta funcion sirve para ordenar y limpiar elementos del arbol de objetos.
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

    def _get_strategy_object_tree_items(self, module=None):
        # Para peques: esta funcion sirve para obtener elementos del arbol segun la estrategia.
        if module is None:
            module = self.strategy_module
        if module is None:
            return []
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

        if not strategy_items:
            return []
        if isinstance(strategy_items, (list, tuple, set)):
            combined = list(strategy_items)
        else:
            combined = [strategy_items]
        return self._normalize_object_tree_items(combined)

    def _get_active_strategies_object_tree_items(self):
        # Para peques: esta funcion sirve para unir elementos del arbol de todas las estrategias activas.
        items = []
        for entry in self._get_enabled_strategy_entries():
            module = entry.get("module_obj")
            if module is None:
                continue
            items.extend(self._get_strategy_object_tree_items(module=module))
        return items

    def _build_object_tree_items(self):
        # Para peques: esta funcion sirve para construir la lista final del arbol de objetos.
        if self.strategy_data_all_actives:
            items = list(self._get_active_strategies_object_tree_items())
        else:
            items = list(self._get_strategy_object_tree_items())

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
        # Para peques: esta funcion sirve para aplicar visibilidad de indicadores en varios elementos.
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

    def _get_strategy_data_scope(self, items=None) -> str:
        # Para peques: esta funcion sirve para obtener la estrategia seleccionada en el selector.
        key = (self.current_strategy_key or "").strip()
        if key and key in self.strategy_registry:
            return key
        if self.strategy_registry:
            return next(iter(self.strategy_registry.keys()))
        return ""

    def _get_strategy_data_scope_options(self, items=None):
        # Para peques: esta funcion sirve para construir opciones del selector de estrategias.
        options = []
        seen = set()
        for strategy in self._get_strategy_payload():
            key = (strategy.get("key") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            label = (strategy.get("label") or key).strip()
            options.append({"key": key, "label": label})
        return options

    def _render_strategy_data_scope_selector(self, items=None):
        # Para peques: esta funcion sirve para refrescar el desplegable de datos de estrategia.
        handler = getattr(self, "side_panel_handler", None)
        if not handler:
            return
        if items is None:
            items = self.object_tree_items
        payload = json.dumps({
            "options": self._get_strategy_data_scope_options(items),
            "selected": self._get_strategy_data_scope(items),
            "all_actives": bool(self.strategy_data_all_actives),
            "handler": handler,
        }, ensure_ascii=False)
        self.chart.run_script(f'''
            ;(function() {{
                const payload = {payload};
                if (window.renderStrategyDataSelector) {{
                    window.renderStrategyDataSelector(payload);
                }}
            }})();
        ''')

    def _render_data_window_strategy_selector(self, items=None):
        # Para peques: esta funcion sirve para refrescar el selector de estrategia en data window.
        handler = getattr(self, "side_panel_handler", None)
        if not handler:
            return
        if items is None:
            items = self.object_tree_items
        payload = json.dumps({
            "options": self._get_strategy_data_scope_options(items),
            "selected": self._get_strategy_data_scope(items),
            "handler": handler,
        }, ensure_ascii=False)
        self.chart.run_script(f'''
            ;(function() {{
                const payload = {payload};
                if (window.renderDataWindowStrategySelector) {{
                    window.renderDataWindowStrategySelector(payload);
                }}
            }})();
        ''')

    def _set_strategy_data_scope(self, scope: str):
        # Para peques: esta funcion sirve para aplicar la estrategia elegida en el selector.
        scope = (scope or "").strip()
        if not scope:
            scope = self._get_strategy_data_scope()
        if not scope:
            self.log_message("No hay estrategias disponibles para mostrar datos.")
            return
        self.strategy_data_all_actives = False
        if scope not in self.strategy_registry:
            self.log_message(f"Estrategia desconocida en selector: {scope}")
            self._render_strategy_data_scope_selector()
            self._render_data_window_strategy_selector()
            return
        self._set_strategy_by_key(scope, refresh=True, sync_ui=True)

    def _set_strategy_data_all_actives(self):
        # Para peques: esta funcion sirve para mostrar datos de todas las estrategias activas.
        enabled_entries = self._get_enabled_strategy_entries()
        if not enabled_entries:
            self.strategy_data_all_actives = False
            self.log_message("No hay estrategias activas para mostrar en Strategy Data.")
            self._render_strategy_data_scope_selector()
            return
        self.strategy_data_all_actives = True
        self._refresh_object_tree_items()

    def _render_object_tree(self, items=None):
        # Para peques: esta funcion sirve para dibujar arbol de objetos.
        handler = getattr(self, "side_panel_handler", None)
        if not handler:
            return
        if items is None:
            items = self.object_tree_items
        payload = json.dumps({
            "items": items or [],
            "icons": self._get_side_panel_icons(),
            "handler": handler,
            "strategy_data_options": self._get_strategy_data_scope_options(items),
            "strategy_data_selected": self._get_strategy_data_scope(items),
            "strategy_data_all_actives": bool(self.strategy_data_all_actives),
            "position_state": self.position_state,
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
        # Para peques: esta funcion sirve para refrescar los elementos del arbol de objetos.
        items = self._build_object_tree_items()
        self.object_tree_items = items
        if self.indicator_series:
            self._apply_indicator_visibility_for_items(items)
        if render:
            self._render_object_tree(items)

    def _load_strategy_module(self, module_ref: str):
        # Para peques: esta funcion sirve para cargar el modulo de una estrategia.
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

        importlib.invalidate_caches()
        module = importlib.import_module(module_ref)
        return importlib.reload(module)

    def _resolve_timeframe_value(self, value):
        # Para peques: esta funcion sirve para convertir el marco de tiempo a su valor de MT5.
        if value is None:
            return None
        timeframe_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1
        }
        if isinstance(value, str):
            key = value.strip().upper()
            return timeframe_map.get(key)
        if isinstance(value, int):
            if value in timeframe_map.values():
                return value
        return None

    def _timeframe_label(self, timeframe_value):
        # Para peques: esta funcion sirve para crear la etiqueta de texto del marco de tiempo.
        reverse_map = {
            mt5.TIMEFRAME_M1: "M1",
            mt5.TIMEFRAME_M5: "M5",
            mt5.TIMEFRAME_M15: "M15",
            mt5.TIMEFRAME_M30: "M30",
            mt5.TIMEFRAME_H1: "H1",
            mt5.TIMEFRAME_H4: "H4",
            mt5.TIMEFRAME_D1: "D1"
        }
        return reverse_map.get(timeframe_value, "")

    def _get_strategy_timeframe(self, module):
        # Para peques: esta funcion sirve para obtener el marco de tiempo de una estrategia.
        if module is None:
            return None
        if hasattr(module, "get_timeframe"):
            try:
                return module.get_timeframe()
            except Exception:
                return None
        for key in ("TIMEFRAME", "STRATEGY_TIMEFRAME", "TIMEFRAME_STR"):
            if hasattr(module, key):
                try:
                    return getattr(module, key)
                except Exception:
                    return None
        return None

    def _apply_strategy_timeframe(self, module_or_entry, refresh: bool = True):
        # Para peques: esta funcion sirve para aplicar el marco de tiempo elegido por la estrategia.
        if isinstance(module_or_entry, dict):
            timeframe_value = module_or_entry.get("timeframe_value")
            label = module_or_entry.get("timeframe_label") or ""
            raw_value = label or timeframe_value
        else:
            raw_value = self._get_strategy_timeframe(module_or_entry)
            timeframe_value = self._resolve_timeframe_value(raw_value) if raw_value is not None else None
            label = self._timeframe_label(timeframe_value) if timeframe_value is not None else ""

        if timeframe_value is None:
            self.strategy_timeframe = None
            self.timeframe_locked = False
            return False

        if not label:
            if isinstance(raw_value, str):
                label = raw_value.strip().upper()
            else:
                label = self._timeframe_label(timeframe_value)
        if not label:
            self.log_message(f"Timeframe inválido en estrategia: {raw_value}")
            self.strategy_timeframe = None
            self.timeframe_locked = False
            return False

        self.strategy_timeframe = label or None
        self.timeframe_locked = True

        changed = config.TIMEFRAME != timeframe_value
        if changed:
            config.TIMEFRAME = timeframe_value
        if label:
            self.current_timeframe = label

        if changed:
            self.log_message(f"Timeframe por estrategia: {self.current_timeframe}")
            if refresh:
                self.refresh_data()
        return changed

    def _set_strategy_by_key(self, key: str, refresh: bool = True, sync_ui: bool = True):
        # Para peques: esta funcion sirve para cambiar la estrategia seleccionada por clave.
        entry = self.strategy_registry.get(key)
        if not entry:
            self.log_message(f"Estrategia desconocida: {key}")
            return

        loaded_ok = self._load_strategy_entry(entry)
        self.current_strategy_key = key
        config.STRATEGY_KEY = key
        config.STRATEGY_MODULE = entry["module"]

        if loaded_ok:
            self.strategy_module = entry.get("module_obj") or strategy_baseline
            self.log_message(f"Interfaz activa: {entry['label']} ({entry['module']})")
            self._apply_strategy_timeframe(entry, refresh=False)
            self._refresh_object_tree_items()
        else:
            self.strategy_module = None
            self.strategy_timeframe = None
            self.timeframe_locked = False
            error_text = (entry.get("last_error") or "La estrategia no cumple la API minima").strip()
            self.log_message(
                f"Estrategia no disponible para visualizar: {entry.get('label', key)} ({error_text})"
            )
            self._refresh_object_tree_items()

        try:
            self.position_state = self._collect_selected_position_state()
            self._sync_position_state_ui(self.position_state)
        except Exception:
            pass

        if sync_ui:
            self._render_strategy_panel()
        else:
            self._render_strategy_readiness_overlay(entry)
        if refresh:
            self.refresh_data()

    def _resolve_strategy_source_path(self, entry: dict) -> str:
        if not isinstance(entry, dict):
            return ""

        module_ref = (entry.get("module") or "").strip()
        if not module_ref:
            return ""

        candidates = []
        path_like = module_ref.endswith(".py") or any(
            sep in module_ref for sep in (os.sep, os.altsep) if sep
        )
        if path_like:
            candidates.append(module_ref)
            if not module_ref.lower().endswith(".py"):
                candidates.append(f"{module_ref}.py")
        else:
            stem = self._strategy_module_stem(module_ref)
            if stem:
                candidates.append(os.path.join(self._get_strategy_dir(), f"{stem}.py"))

        checked = set()
        base_dir = os.path.dirname(__file__)
        for candidate in candidates:
            if not candidate:
                continue
            expanded = os.path.expandvars(os.path.expanduser(candidate))
            probe_paths = [expanded]
            if not os.path.isabs(expanded):
                probe_paths.append(os.path.join(base_dir, expanded))
            for probe in probe_paths:
                normalized = os.path.normcase(os.path.normpath(probe))
                if normalized in checked:
                    continue
                checked.add(normalized)
                if os.path.isfile(probe):
                    return os.path.abspath(probe)
        return ""

    def _inspect_strategy_source_code(self, source_path: str) -> dict:
        info = {
            "exists": False,
            "has_code": False,
            "has_get_last_signal": False,
            "has_prepare_dataframe": False,
            "has_compute_signals": False,
            "has_timeframe": False,
            "has_data_window_fields": False,
        }
        if not source_path or not os.path.isfile(source_path):
            return info

        info["exists"] = True
        try:
            with open(source_path, "r", encoding="utf-8", errors="replace") as source_file:
                source = source_file.read()
        except Exception:
            return info

        info["has_code"] = bool(source.strip())

        def _has(pattern: str) -> bool:
            return re.search(pattern, source, flags=re.MULTILINE) is not None

        info["has_get_last_signal"] = _has(r"^\s*def\s+get_last_signal\s*\(")
        info["has_prepare_dataframe"] = _has(r"^\s*def\s+prepare_dataframe\s*\(")
        info["has_compute_signals"] = _has(
            r"^\s*def\s+(compute_dir1_and_signals|compute_signals)\s*\("
        )
        info["has_timeframe"] = (
            _has(r"^\s*(TIMEFRAME|STRATEGY_TIMEFRAME|TIMEFRAME_STR)\s*=")
            or _has(r"^\s*def\s+get_timeframe\s*\(")
        )
        info["has_data_window_fields"] = _has(
            r"^\s*(DATA_WINDOW_FIELDS|DATA_FIELDS|INTERFACE_FIELDS)\s*="
        )
        return info

    def _build_strategy_readiness_payload(self, entry: dict):
        if not isinstance(entry, dict):
            return {"visible": False}

        error_text = (entry.get("last_error") or "").strip()
        if entry.get("module_obj") is not None and not error_text:
            return {"visible": False}

        source_path = self._resolve_strategy_source_path(entry)
        source_info = self._inspect_strategy_source_code(source_path)

        checks = [
            {
                "ok": bool(entry.get("module_obj") is not None),
                "required": True,
                "text": "El modulo debe cargar sin errores de sintaxis/importacion.",
            },
            {
                "ok": bool(source_info.get("has_get_last_signal")),
                "required": True,
                "text": "Define get_last_signal(df, verbose=False) y retorna buy/sell/none.",
            },
            {
                "ok": bool(
                    source_info.get("has_prepare_dataframe") or source_info.get("has_compute_signals")
                ),
                "required": True,
                "text": (
                    "Agrega prepare_dataframe(df) o "
                    "compute_signals/compute_dir1_and_signals(df, enable_signals)."
                ),
            },
            {
                "ok": bool(source_info.get("has_timeframe")),
                "required": False,
                "text": "Declara TIMEFRAME='M1' (o get_timeframe()) para fijar el marco temporal.",
            },
            {
                "ok": bool(source_info.get("has_data_window_fields")),
                "required": False,
                "text": "Opcional: define DATA_WINDOW_FIELDS para mostrar metricas propias.",
            },
        ]

        if not source_info.get("exists"):
            fallback_error = "No se encontro el archivo de la estrategia."
        elif not source_info.get("has_code"):
            fallback_error = "El archivo esta vacio. La estrategia aun no tiene implementacion."
        else:
            fallback_error = "La estrategia aun no cumple la API minima requerida por la GUI."

        subtitle_parts = []
        module_ref = (entry.get("module") or "").strip()
        if module_ref:
            subtitle_parts.append(f"Modulo: {module_ref}")
        if source_path:
            subtitle_parts.append(f"Archivo: {source_path}")

        strategy_name = entry.get("label") or entry.get("key") or "sin_nombre"
        return {
            "visible": True,
            "title": f"Estrategia incompleta: {strategy_name}",
            "subtitle": " | ".join(subtitle_parts),
            "error": error_text or fallback_error,
            "checks": checks,
        }

    def _render_strategy_readiness_overlay(self, entry: dict = None):
        if not hasattr(self, "chart") or self.chart is None:
            return

        if entry is None:
            entry = self._get_selected_strategy_entry()
        payload = self._build_strategy_readiness_payload(entry)
        payload_json = json.dumps(payload, ensure_ascii=False)

        self.chart.run_script(f'''
            ;(function() {{
                const payload = {payload_json};
                const chartHost = {self.chart.id} && {self.chart.id}.div ? {self.chart.id}.div : null;
                if (!chartHost) return;

                if (!chartHost.style.position || chartHost.style.position === "static") {{
                    chartHost.style.position = "relative";
                }}

                let overlay = chartHost.querySelector("#tv-strategy-readiness-overlay");
                if (!overlay) {{
                    overlay = document.createElement("div");
                    overlay.id = "tv-strategy-readiness-overlay";
                    overlay.className = "tv-strategy-readiness-overlay";
                    overlay.innerHTML = `
                        <div class="tv-strategy-readiness-card">
                            <div class="tv-strategy-readiness-badge">Strategy setup</div>
                            <div class="tv-strategy-readiness-title" id="tv-strategy-readiness-title"></div>
                            <div class="tv-strategy-readiness-subtitle" id="tv-strategy-readiness-subtitle"></div>
                            <div class="tv-strategy-readiness-error" id="tv-strategy-readiness-error"></div>
                            <div class="tv-strategy-readiness-section">Checklist para visualizar</div>
                            <div class="tv-strategy-readiness-list" id="tv-strategy-readiness-list"></div>
                        </div>
                    `;
                    chartHost.appendChild(overlay);
                }}

                if (!payload || !payload.visible) {{
                    overlay.classList.remove("open");
                    return;
                }}
                overlay.classList.add("open");

                const titleEl = overlay.querySelector("#tv-strategy-readiness-title");
                const subtitleEl = overlay.querySelector("#tv-strategy-readiness-subtitle");
                const errorEl = overlay.querySelector("#tv-strategy-readiness-error");
                const listEl = overlay.querySelector("#tv-strategy-readiness-list");

                if (titleEl) {{
                    titleEl.textContent = payload.title || "Estrategia incompleta";
                }}
                if (subtitleEl) {{
                    subtitleEl.textContent = payload.subtitle || "";
                    subtitleEl.style.display = payload.subtitle ? "block" : "none";
                }}
                if (errorEl) {{
                    errorEl.textContent = payload.error || "";
                    errorEl.style.display = payload.error ? "block" : "none";
                }}
                if (listEl) {{
                    listEl.innerHTML = "";
                    const checks = Array.isArray(payload.checks) ? payload.checks : [];
                    checks.forEach((check) => {{
                        const row = document.createElement("div");
                        row.className = "tv-strategy-readiness-item" + (check && check.ok ? " done" : " pending");

                        const icon = document.createElement("span");
                        icon.className = "tv-strategy-readiness-icon";
                        icon.textContent = check && check.ok ? "OK" : "TODO";

                        const text = document.createElement("span");
                        text.className = "tv-strategy-readiness-text";
                        text.textContent = check && check.text ? check.text : "";

                        const level = document.createElement("span");
                        level.className = "tv-strategy-readiness-level";
                        level.textContent = check && check.required ? "Requerido" : "Opcional";

                        row.appendChild(icon);
                        row.appendChild(text);
                        row.appendChild(level);
                        listEl.appendChild(row);
                    }});
                }}
            }})();
        ''')

    def _add_strategy_from_input(self, label: str, module_ref: str):
        # Para peques: esta funcion sirve para agregar una estrategia escrita por el usuario.
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

        self._register_strategy(key, label or key, module_ref)
        entry = self.strategy_registry.get(key)
        if not self._load_strategy_entry(entry):
            if entry:
                entry["enabled"] = False
            config.ACTIVE_STRATEGIES = [e["key"] for e in self.strategy_registry.values() if e.get("enabled")]
            self.log_message("La estrategia se guardó, pero no se pudo cargar. Revisa el estado en la lista.")
            self._render_strategy_panel()
            return
        entry["enabled"] = True
        config.ACTIVE_STRATEGIES = [e["key"] for e in self.strategy_registry.values() if e.get("enabled")]
        self._set_strategy_by_key(key, refresh=True, sync_ui=True)

    def _add_strategy_from_drop(self, filename: str, data_uri: str):
        # Para peques: esta funcion sirve para agregar una estrategia arrastrando un archivo.
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
        entry = self.strategy_registry.get(key)
        if not self._load_strategy_entry(entry):
            if entry:
                entry["enabled"] = False
            config.ACTIVE_STRATEGIES = [e["key"] for e in self.strategy_registry.values() if e.get("enabled")]
            self.log_message("La estrategia se guardó, pero no se pudo cargar. Revisa el estado en la lista.")
            self._render_strategy_panel()
            return
        entry["enabled"] = True
        config.ACTIVE_STRATEGIES = [e["key"] for e in self.strategy_registry.values() if e.get("enabled")]
        self._set_strategy_by_key(key, refresh=True, sync_ui=True)

    def _render_strategy_panel(self):
        # Para peques: esta funcion sirve para dibujar el panel de estrategias.
        self._sync_strategy_registry_from_disk(load_entries=True)
        if self.strategy_data_all_actives:
            self._refresh_object_tree_items()
        payload = json.dumps({
            "strategies": self._get_strategy_payload(),
            "selected": self.current_strategy_key or "",
            "handler": self.side_panel_handler,
            "active_count": len([e for e in self.strategy_registry.values() if e.get("enabled")]),
        })
        self.chart.run_script(f'''
            ;(function() {{
                const payload = {payload};
                if (window.renderStrategyList) {{
                    window.renderStrategyList(payload);
                }}
            }})();
        ''')
        self._render_strategy_data_scope_selector()
        self._render_data_window_strategy_selector()
        self._sync_strategy_status_ui()
        self._render_strategy_readiness_overlay()

    def _sync_strategy_status_ui(self):
        # Para peques: esta funcion sirve para sincronizar en pantalla el estado de estrategias.
        payload = json.dumps({
            "running": bool(self.bot_running),
            "active_count": len([e for e in self.strategy_registry.values() if e.get("enabled")]),
            "selected": self.current_strategy_key or "",
        })
        self.chart.run_script(f'''
            ;(function() {{
                if (window.setStrategyStatus) {{
                    window.setStrategyStatus({payload});
                }}
            }})();
        ''')

    def _apply_strategy_processing_with_module(self, df: pd.DataFrame, module, strategy_key: str = "") -> pd.DataFrame:
        # Para peques: esta funcion sirve para aplicar el procesado de una estrategia con su modulo.
        module = module or strategy_baseline
        label = strategy_key or self.current_strategy_key or "baseline"
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
            self.log_message(f"Error en estrategia '{label}': {e}")
        return df

    def _apply_strategy_processing_for_entry(self, entry: dict, df: pd.DataFrame) -> pd.DataFrame:
        # Para peques: esta funcion sirve para aplicar el procesado de una estrategia del registro.
        if not isinstance(entry, dict):
            return self._apply_strategy_processing_with_module(df, self.strategy_module, self.current_strategy_key or "")
        module = entry.get("module_obj")
        if module is None:
            return df
        return self._apply_strategy_processing_with_module(df, module, entry.get("key", ""))

    def _apply_strategy_processing(self, df: pd.DataFrame) -> pd.DataFrame:
        # Para peques: esta funcion sirve para aplicar estrategia procesado.
        entry = self._get_selected_strategy_entry()
        return self._apply_strategy_processing_for_entry(entry, df)

    def _get_strategy_signal_with_module(self, df: pd.DataFrame, module, strategy_key: str = "", verbose: bool = False) -> str:
        # Para peques: esta funcion sirve para obtener estrategia senal con modulo.
        module = module or strategy_baseline
        label = strategy_key or self.current_strategy_key or "baseline"
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
                self.log_message(f"Error al obtener señal ({label}): {e}")
        return "none"

    def _get_strategy_signal_for_entry(self, entry: dict, df: pd.DataFrame, verbose: bool = False) -> str:
        # Para peques: esta funcion sirve para obtener estrategia senal para entrada.
        if not isinstance(entry, dict):
            return self._get_strategy_signal_with_module(df, self.strategy_module, self.current_strategy_key or "", verbose=verbose)
        module = entry.get("module_obj")
        if module is None:
            return "none"
        return self._get_strategy_signal_with_module(df, module, entry.get("key", ""), verbose=verbose)

    def _get_strategy_signal(self, df: pd.DataFrame, verbose: bool = False) -> str:
        # Para peques: esta funcion sirve para obtener estrategia senal.
        entry = self._get_selected_strategy_entry()
        return self._get_strategy_signal_for_entry(entry, df, verbose=verbose)
        
    def setup_topbar(self):
        # Para peques: esta funcion sirve para preparar barra superior.
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
        self._style_balance_widget()
        self._bind_quote_actions()
        self._hide_non_visual_widgets()
        self._ensure_action_tooltip()

    def _inject_custom_styles(self):
        # Para peques: esta funcion sirve para inyectar estilos personalizados.
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
                        position: relative;
                        overflow: visible;
                    }
                    .topbar-container {
                        gap: 6px;
                        align-items: center;
                    }
                    .topbar-textbox {
                        color: var(--tv-text-secondary);
                    }
                    .tv-balance-box {
                        position: absolute;
                        left: 60%;
                        top: 50%;
                        transform: translate(-50%, -50%);
                        background: #242424;
                        border: 1px solid #333333;
                        border-radius: 8px;
                        padding: 4px 10px;
                        display: flex;
                        align-items: center;
                        gap: 8px;
                        color: var(--tv-text-primary);
                        font-weight: 600;
                        font-size: 12px;
                        min-width: 140px;
                        justify-content: center;
                        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
                    }
                    .tv-balance-box .balance-label {
                        font-size: 10px;
                        letter-spacing: 0.08em;
                        text-transform: uppercase;
                        color: var(--tv-text-secondary);
                        font-weight: 600;
                    }
                    .tv-balance-box .balance-value {
                        font-size: 12px;
                        color: var(--tv-text-primary);
                    }
                    @media (max-width: 980px) {
                        .tv-balance-box {
                            left: auto;
                            right: 10px;
                            transform: translateY(-50%);
                            min-width: 120px;
                        }
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
                    .tv-strategy-data-panel {
                        flex: 1;
                        display: flex;
                        flex-direction: column;
                        min-height: 0;
                    }
                    .tv-strategy-data-header {
                        display: flex;
                        align-items: center;
                        gap: 8px;
                        padding: 8px 8px 4px 8px;
                        border-bottom: 1px solid #2f2f2f;
                    }
                    .tv-strategy-data-label {
                        font-size: 11px;
                        color: #9a9a9a;
                        white-space: nowrap;
                    }
                    .tv-strategy-data-select {
                        width: 100%;
                        min-width: 0;
                        background: #1d1d1d;
                        border: 1px solid #333333;
                        color: var(--tv-text-primary);
                        border-radius: 6px;
                        padding: 5px 8px;
                        font-size: 11px;
                        outline: none;
                    }
                    .tv-strategy-data-select:focus {
                        border-color: #4a4a4a;
                    }
                    .tv-strategy-data-all-btn {
                        background: #232323;
                        border: 1px solid #383838;
                        color: #d0d0d0;
                        border-radius: 6px;
                        padding: 5px 8px;
                        font-size: 11px;
                        font-weight: 600;
                        cursor: pointer;
                        white-space: nowrap;
                        flex-shrink: 0;
                    }
                    .tv-strategy-data-all-btn:hover {
                        background: #2b2b2b;
                    }
                    .tv-strategy-data-all-btn.active {
                        background: #1f3a24;
                        border-color: #2d6a38;
                        color: #b2e5bc;
                    }
                    .tv-strategy-data-all-btn:disabled {
                        opacity: 0.45;
                        cursor: default;
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
                    .tv-side-item.position-long-active {
                        color: #8ff0c4;
                        background: rgba(46, 204, 113, 0.14);
                    }
                    .tv-side-item.position-long-active.selected {
                        background: rgba(46, 204, 113, 0.2);
                    }
                    .tv-side-item.position-long-active .tv-side-icon {
                        color: #52d68a;
                    }
                    .tv-side-item.position-short-active {
                        color: #ffb5ad;
                        background: rgba(231, 76, 60, 0.14);
                    }
                    .tv-side-item.position-short-active.selected {
                        background: rgba(231, 76, 60, 0.2);
                    }
                    .tv-side-item.position-short-active .tv-side-icon {
                        color: #ff7f73;
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
                    .tv-side-count {
                        min-width: 16px;
                        height: 16px;
                        padding: 0 5px;
                        display: inline-flex;
                        align-items: center;
                        justify-content: center;
                        border-radius: 999px;
                        border: 1px solid #3a3a3a;
                        background: #222222;
                        color: #cfcfcf;
                        font-size: 10px;
                        line-height: 1;
                    }
                    .tv-side-item.position-long-active .tv-side-count {
                        border-color: rgba(82, 214, 138, 0.55);
                        background: rgba(46, 204, 113, 0.2);
                        color: #bff9da;
                    }
                    .tv-side-item.position-short-active .tv-side-count {
                        border-color: rgba(255, 127, 115, 0.55);
                        background: rgba(231, 76, 60, 0.2);
                        color: #ffd0cb;
                    }
                    .tv-eye {
                        width: 24px;
                        height: 24px;
                        display: inline-flex;
                        align-items: center;
                        justify-content: center;
                        border: 1px solid #383838;
                        border-radius: 7px;
                        background: linear-gradient(180deg, #272727 0%, #1f1f1f 100%);
                        color: #d6d6d6;
                        opacity: 0.95;
                        cursor: pointer;
                        padding: 0;
                        transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease, opacity 0.15s ease;
                    }
                    .tv-eye svg {
                        width: 13px;
                        height: 13px;
                        stroke: currentColor;
                        fill: none;
                        stroke-width: 1.5;
                        stroke-linecap: round;
                        stroke-linejoin: round;
                        pointer-events: none;
                    }
                    .tv-eye:hover {
                        border-color: #5a5a5a;
                        background: #2c2c2c;
                    }
                    .tv-eye:focus-visible {
                        outline: 1px solid #6ea8ff;
                        outline-offset: 1px;
                    }
                    .tv-eye.hidden {
                        opacity: 0.7;
                        color: #8e8e8e;
                        border-color: #323232;
                        background: #1b1b1b;
                    }
                    .tv-eye.placeholder {
                        visibility: hidden;
                        pointer-events: none;
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
                    .tv-side-list,
                    .tv-side-content {
                        scrollbar-width: thin;
                        scrollbar-color: #5a5a5a #1b1b1b;
                    }
                    .tv-side-list::-webkit-scrollbar,
                    .tv-side-content::-webkit-scrollbar {
                        width: 10px;
                    }
                    .tv-side-list::-webkit-scrollbar-track,
                    .tv-side-content::-webkit-scrollbar-track {
                        background: #1b1b1b;
                        border-left: 1px solid #2f2f2f;
                        border-radius: 8px;
                    }
                    .tv-side-list::-webkit-scrollbar-thumb,
                    .tv-side-content::-webkit-scrollbar-thumb {
                        background: linear-gradient(180deg, #6a6a6a 0%, #585858 100%);
                        border: 2px solid #1b1b1b;
                        border-radius: 8px;
                    }
                    .tv-side-list::-webkit-scrollbar-thumb:hover,
                    .tv-side-content::-webkit-scrollbar-thumb:hover {
                        background: linear-gradient(180deg, #7a7a7a 0%, #666666 100%);
                    }
                    .tv-side-list::-webkit-scrollbar-thumb:active,
                    .tv-side-content::-webkit-scrollbar-thumb:active {
                        background: linear-gradient(180deg, #8a8a8a 0%, #767676 100%);
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
                    .tv-feedback-actions {
                        display: flex;
                        gap: 8px;
                        align-items: center;
                    }
                    .tv-feedback-refresh {
                        background: #2b2b2b;
                        color: var(--tv-text-primary);
                        border: 1px solid #3a3a3a;
                        padding: 6px 10px;
                        border-radius: 6px;
                        font-size: 11px;
                        cursor: pointer;
                    }
                    .tv-feedback-refresh:hover {
                        background: #3a3a3a;
                    }
                    .tv-feedback-list-status {
                        font-size: 11px;
                        color: #9aa0a6;
                        min-height: 14px;
                    }
                    .tv-feedback-list-status.success {
                        color: #5fd6a3;
                    }
                    .tv-feedback-list-status.error {
                        color: #ff8a80;
                    }
                    .tv-feedback-list {
                        display: flex;
                        flex-direction: column;
                        gap: 8px;
                    }
                    .tv-feedback-item {
                        background: #1f1f1f;
                        border: 1px solid #2a2a2a;
                        border-radius: 6px;
                        padding: 8px;
                        display: flex;
                        flex-direction: column;
                        gap: 4px;
                    }
                    .tv-feedback-item-title {
                        font-size: 12px;
                        font-weight: 600;
                        color: var(--tv-text-primary);
                    }
                    .tv-feedback-item-message {
                        font-size: 11px;
                        color: #c8c8c8;
                        white-space: pre-wrap;
                        line-height: 1.4;
                    }
                    .tv-feedback-item-meta {
                        font-size: 10px;
                        color: #8c8c8c;
                        display: flex;
                        flex-wrap: wrap;
                        gap: 8px;
                    }
                    .tv-feedback-empty {
                        font-size: 11px;
                        color: #7a7a7a;
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
                    .tv-data-controls {
                        display: flex;
                        align-items: center;
                        gap: 8px;
                    }
                    .tv-data-control-label {
                        font-size: 11px;
                        color: #9a9a9a;
                        white-space: nowrap;
                    }
                    .tv-data-select {
                        width: 100%;
                        min-width: 0;
                        background: #1d1d1d;
                        border: 1px solid #333333;
                        color: var(--tv-text-primary);
                        border-radius: 6px;
                        padding: 5px 8px;
                        font-size: 11px;
                        outline: none;
                    }
                    .tv-data-select:focus {
                        border-color: #4a4a4a;
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
                        scrollbar-width: thin;
                        scrollbar-color: #5a5a5a #1b1b1b;
                    }
                    .tv-data-trades-list::-webkit-scrollbar {
                        width: 10px;
                    }
                    .tv-data-trades-list::-webkit-scrollbar-track {
                        background: #1b1b1b;
                        border-left: 1px solid #2f2f2f;
                        border-radius: 8px;
                    }
                    .tv-data-trades-list::-webkit-scrollbar-thumb {
                        background: linear-gradient(180deg, #6a6a6a 0%, #585858 100%);
                        border: 2px solid #1b1b1b;
                        border-radius: 8px;
                    }
                    .tv-data-trades-list::-webkit-scrollbar-thumb:hover {
                        background: linear-gradient(180deg, #7a7a7a 0%, #666666 100%);
                    }
                    .tv-data-trades-list::-webkit-scrollbar-thumb:active {
                        background: linear-gradient(180deg, #8a8a8a 0%, #767676 100%);
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
                        align-items: flex-start;
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
                        border: 1px solid #3a3a3a;
                    }
                    .tv-strategy-left {
                        display: flex;
                        flex-direction: column;
                        gap: 2px;
                        overflow: hidden;
                        flex: 1;
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
                    .tv-strategy-timeframe {
                        font-size: 10px;
                        color: #9a9a9a;
                    }
                    .tv-strategy-statusline {
                        font-size: 10px;
                        color: #7e7e7e;
                        line-height: 1.2;
                    }
                    .tv-strategy-right {
                        display: flex;
                        flex-direction: column;
                        align-items: flex-end;
                        gap: 4px;
                        min-width: 98px;
                    }
                    .tv-strategy-enable {
                        background: #2a2a2a;
                        color: #d0d0d0;
                        border: 1px solid #3a3a3a;
                        border-radius: 999px;
                        font-size: 12px;
                        font-weight: 600;
                        padding: 6px 12px;
                        min-width: 86px;
                        cursor: pointer;
                    }
                    .tv-strategy-enable.active {
                        background: #1f3a24;
                        border-color: #2d6a38;
                        color: #a7e2b3;
                    }
                    .tv-strategy-last-run {
                        font-size: 10px;
                        color: #777777;
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
                    .tv-confirm-overlay {
                        position: fixed;
                        inset: 0;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        background: rgba(0, 0, 0, 0.58);
                        z-index: 10030;
                        padding: 14px;
                        opacity: 0;
                        visibility: hidden;
                        pointer-events: none;
                        transition: opacity 0.16s ease, visibility 0s linear 0.16s;
                    }
                    .tv-confirm-overlay.open {
                        opacity: 1;
                        visibility: visible;
                        pointer-events: auto;
                        transition: opacity 0.16s ease;
                    }
                    .tv-confirm-dialog {
                        width: min(360px, calc(100vw - 28px));
                        background: #1d1d1d;
                        border: 1px solid #343434;
                        border-radius: 10px;
                        box-shadow: 0 14px 30px rgba(0, 0, 0, 0.45);
                        padding: 14px;
                        display: flex;
                        flex-direction: column;
                        gap: 10px;
                        color: var(--tv-text-primary);
                        transform: translateY(8px) scale(0.98);
                        opacity: 0;
                        transition: transform 0.17s ease, opacity 0.17s ease;
                    }
                    .tv-confirm-overlay.open .tv-confirm-dialog {
                        transform: translateY(0) scale(1);
                        opacity: 1;
                    }
                    .tv-confirm-title {
                        font-size: 14px;
                        font-weight: 700;
                        color: #f2f2f2;
                    }
                    .tv-confirm-message {
                        font-size: 12px;
                        line-height: 1.35;
                        color: #cbcbcb;
                        white-space: pre-wrap;
                    }
                    .tv-confirm-actions {
                        display: flex;
                        justify-content: flex-end;
                        gap: 8px;
                        margin-top: 2px;
                    }
                    .tv-confirm-btn {
                        border-radius: 6px;
                        border: 1px solid #3a3a3a;
                        background: #2b2b2b;
                        color: #f0f0f0;
                        padding: 7px 12px;
                        font-size: 12px;
                        font-weight: 600;
                        cursor: pointer;
                    }
                    .tv-confirm-btn:hover {
                        background: #363636;
                    }
                    .tv-confirm-btn.cancel {
                        background: #232323;
                        color: #d0d0d0;
                    }
                    .tv-confirm-btn.confirm {
                        background: #1f3a24;
                        border-color: #2d6a38;
                        color: #b5e9bf;
                    }
                    .tv-confirm-btn.confirm:hover {
                        background: #23462b;
                    }

                    .tv-strategy-readiness-overlay {
                        position: absolute;
                        inset: 14px;
                        display: none;
                        align-items: center;
                        justify-content: center;
                        pointer-events: none;
                        z-index: 1008;
                    }
                    .tv-strategy-readiness-overlay.open {
                        display: flex;
                    }
                    .tv-strategy-readiness-card {
                        width: min(760px, calc(100% - 20px));
                        max-height: calc(100% - 20px);
                        overflow: auto;
                        background:
                            linear-gradient(150deg, rgba(40, 24, 24, 0.92), rgba(22, 22, 22, 0.96)),
                            radial-gradient(circle at top right, rgba(183, 28, 28, 0.22), transparent 52%);
                        border: 1px solid rgba(180, 65, 65, 0.58);
                        border-radius: 14px;
                        box-shadow: 0 18px 34px rgba(0, 0, 0, 0.5);
                        padding: 16px 18px;
                        display: flex;
                        flex-direction: column;
                        gap: 9px;
                        color: #ebebeb;
                        animation: tvStrategyReadinessIn 0.22s ease;
                    }
                    .tv-strategy-readiness-badge {
                        align-self: flex-start;
                        background: rgba(183, 28, 28, 0.28);
                        border: 1px solid rgba(198, 89, 89, 0.55);
                        border-radius: 999px;
                        padding: 4px 9px;
                        font-size: 10px;
                        letter-spacing: 0.08em;
                        text-transform: uppercase;
                        color: #ffd7d7;
                        font-weight: 700;
                    }
                    .tv-strategy-readiness-title {
                        font-size: 18px;
                        line-height: 1.2;
                        font-weight: 700;
                        color: #ffffff;
                    }
                    .tv-strategy-readiness-subtitle {
                        font-size: 11px;
                        line-height: 1.35;
                        color: #bababa;
                        word-break: break-all;
                    }
                    .tv-strategy-readiness-error {
                        font-size: 12px;
                        line-height: 1.4;
                        color: #ffc1c1;
                        background: rgba(138, 37, 37, 0.38);
                        border: 1px solid rgba(201, 99, 99, 0.45);
                        border-radius: 8px;
                        padding: 8px 9px;
                        white-space: pre-wrap;
                    }
                    .tv-strategy-readiness-section {
                        font-size: 12px;
                        font-weight: 700;
                        letter-spacing: 0.04em;
                        text-transform: uppercase;
                        color: #f4d0d0;
                        margin-top: 2px;
                    }
                    .tv-strategy-readiness-list {
                        display: flex;
                        flex-direction: column;
                        gap: 7px;
                    }
                    .tv-strategy-readiness-item {
                        display: grid;
                        grid-template-columns: auto 1fr auto;
                        align-items: center;
                        gap: 10px;
                        padding: 8px 10px;
                        border-radius: 9px;
                        border: 1px solid #3d3434;
                        background: rgba(31, 31, 31, 0.72);
                        color: #dedede;
                    }
                    .tv-strategy-readiness-item.done {
                        border-color: rgba(61, 136, 83, 0.7);
                        background: rgba(24, 58, 37, 0.55);
                    }
                    .tv-strategy-readiness-item.pending {
                        border-color: rgba(146, 62, 62, 0.68);
                    }
                    .tv-strategy-readiness-icon {
                        min-width: 42px;
                        text-align: center;
                        border-radius: 999px;
                        border: 1px solid #665454;
                        background: rgba(70, 52, 52, 0.6);
                        color: #f2d4d4;
                        font-size: 10px;
                        font-weight: 700;
                        letter-spacing: 0.06em;
                        padding: 3px 6px;
                    }
                    .tv-strategy-readiness-item.done .tv-strategy-readiness-icon {
                        border-color: rgba(95, 178, 118, 0.72);
                        background: rgba(38, 88, 52, 0.65);
                        color: #c9f0d4;
                    }
                    .tv-strategy-readiness-text {
                        font-size: 12px;
                        line-height: 1.35;
                    }
                    .tv-strategy-readiness-level {
                        font-size: 10px;
                        text-transform: uppercase;
                        letter-spacing: 0.07em;
                        color: #c8b0b0;
                        background: rgba(46, 46, 46, 0.72);
                        border-radius: 999px;
                        padding: 3px 8px;
                    }
                    .tv-strategy-readiness-item.done .tv-strategy-readiness-level {
                        color: #c7e6d0;
                    }
                    @keyframes tvStrategyReadinessIn {
                        from {
                            opacity: 0;
                            transform: translateY(10px) scale(0.985);
                        }
                        to {
                            opacity: 1;
                            transform: translateY(0) scale(1);
                        }
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
        # Para peques: esta funcion sirve para aplicar estilo a los widgets de cotizacion.
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

    def _style_balance_widget(self):
        # Para peques: esta funcion sirve para aplicar estilo al widget de balance.
        """Posiciona el balance como un indicador visible en la topbar."""
        try:
            balance_id = self.chart.topbar['balance'].id
        except Exception:
            return
        self.chart.run_script(f'''
            (function() {{
                var balance = {balance_id};
                if (balance && balance.elem) balance = balance.elem;
                if (!balance) return;
                balance.classList.add("tv-balance-box");
                var topbar = document.querySelector(".topbar");
                if (topbar && balance.parentElement !== topbar) {{
                    topbar.appendChild(balance);
                }}
            }})();
        ''')
        self._set_balance_widget("---", None)

    def _set_balance_widget(self, balance_text: str, currency=None):
        # Para peques: esta funcion sirve para actualizar el widget de balance.
        widget = self.chart.topbar.get('balance')
        if not widget:
            return
        value = (balance_text or "---").strip()
        if currency:
            value = f"{value} {currency}"
        html = f"<span class='balance-label'>Balance</span><span class='balance-value'>{value}</span>"
        widget_id = widget.id
        self.chart.run_script(f'''
            (function() {{
                var balance = {widget_id};
                if (balance && balance.elem) balance = balance.elem;
                if (!balance) return;
                balance.innerHTML = {json.dumps(html)};
            }})();
        ''')

    def _bind_quote_actions(self):
        # Para peques: esta funcion sirve para conectar acciones de cotizacion.
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
        # Para peques: esta funcion sirve para reaccionar a trade rapido.
        side = (side or "").lower()
        if side not in ("buy", "sell"):
            return
        try:
            market_open, market_status = trading.is_market_open(config.SYMBOL)
            if not market_open:
                self.log_message(f"Mercado cerrado ({market_status})")
                return
            selected_entry = self._get_selected_strategy_entry()
            timeframe_value = self._strategy_timeframe_value(selected_entry, fallback=config.TIMEFRAME)
            action_info = trading.apply_signal(
                config.SYMBOL,
                side,
                config.LOT,
                config.SL_POINTS,
                config.TP_POINTS,
                self._selected_strategy_magic(),
                timeframe_value=timeframe_value
            )
            if action_info:
                self.update_last_action_ui(action_info)
        except Exception as e:
            self.log_message(f"Error al ejecutar {side.upper()}: {e}")

    def _hide_non_visual_widgets(self):
        # Para peques: esta funcion sirve para ocultar widgets no visuales.
        """Oculta widgets de control para no alterar el layout visual."""
        keys = ['status', 'action_icon', 'action_text', 'start', 'stop', 'refresh']
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
        # Para peques: esta funcion sirve para actualizar la caja de cotizacion.
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
        # Para peques: esta funcion sirve para actualizar cotizaciones.
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
        # Para peques: esta funcion sirve para iniciar cotizacion actualizador.
        """Inicia un hilo para refrescar cotizaciones periódicamente."""
        if self.quote_thread and self.quote_thread.is_alive():
            return
        self.quote_stop_event.clear()
        self.quote_thread = threading.Thread(target=self._quote_loop, daemon=True)
        self.quote_thread.start()

    def stop_quote_updater(self):
        # Para peques: esta funcion sirve para detener cotizacion actualizador.
        """Detiene el hilo de cotizaciones."""
        self.quote_stop_event.set()

    def start_callback_pump(self):
        # Para peques: esta funcion sirve para iniciar retorno bomba.
        """Inicia el loop que procesa callbacks JS (botones, selectores, etc.)."""
        if self.callback_thread and self.callback_thread.is_alive():
            return
        self.callback_stop_event.clear()
        self.callback_thread = threading.Thread(target=self._callback_loop, daemon=True)
        self.callback_thread.start()

    def stop_callback_pump(self):
        # Para peques: esta funcion sirve para detener retorno bomba.
        """Detiene el loop de callbacks JS."""
        self.callback_stop_event.set()

    def _callback_loop(self):
        # Para peques: esta funcion sirve para ciclo de retorno.
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
        # Para peques: esta funcion sirve para ciclo de cotizaciones.
        while not self.quote_stop_event.is_set():
            self.update_quotes()
            self.update_bottom_clock()
            if self.quote_stop_event.wait(timeout=2):
                break

    def setup_side_panel(self):
        # Para peques: esta funcion sirve para preparar panel lateral.
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
        feedback_list_url = ""
        list_url_getter = getattr(self, "_get_feedback_list_url", None)
        if callable(list_url_getter):
            feedback_list_url = list_url_getter()
        self._build_side_panel(items, feedback_target, feedback_list_url)
        self._render_strategy_panel()

    def _build_side_panel(self, items, feedback_target: str, feedback_list_url: str):
        # Para peques: esta funcion sirve para construir panel lateral.
        icons = self._get_side_panel_icons()

        payload = json.dumps({
            "items": items,
            "icons": icons,
            "handler": self.side_panel_handler,
            "strategies": self._get_strategy_payload(),
            "selected_strategy": self.current_strategy_key or "",
            "active_count": len([e for e in self.strategy_registry.values() if e.get("enabled")]),
            "strategy_data_options": self._get_strategy_data_scope_options(items),
            "strategy_data_selected": self._get_strategy_data_scope(items),
            "strategy_data_all_actives": bool(self.strategy_data_all_actives),
            "feedback_target": feedback_target or "Archivo local",
            "feedback_list_url": feedback_list_url or "",
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
            feedbackDesc.innerText = "Escribe tu sugerencia o petición.";

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

            const listTitle = document.createElement("div");
            listTitle.className = "tv-section-title";
            listTitle.innerText = "Mensajes recibidos";

            const listDesc = document.createElement("div");
            listDesc.className = "tv-section-desc";
            listDesc.innerText = "Últimos mensajes guardados en el servidor.";

            const listActions = document.createElement("div");
            listActions.className = "tv-feedback-actions";
            const refreshBtn = document.createElement("button");
            refreshBtn.type = "button";
            refreshBtn.className = "tv-feedback-refresh";
            refreshBtn.innerText = "Actualizar";
            const listStatus = document.createElement("div");
            listStatus.id = "tv-feedback-list-status";
            listStatus.className = "tv-feedback-list-status";
            listActions.appendChild(refreshBtn);
            listActions.appendChild(listStatus);

            const listContainer = document.createElement("div");
            listContainer.id = "tv-feedback-list";
            listContainer.className = "tv-feedback-list";

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

            const setListStatus = (text, kind) => {{
                listStatus.innerText = text || "";
                listStatus.classList.remove("success", "error");
                if (kind === "success") {{
                    listStatus.classList.add("success");
                }}
                if (kind === "error") {{
                    listStatus.classList.add("error");
                }}
            }};

            const requestList = () => {{
                if (!payload.feedback_list_url) {{
                    setListStatus("Servidor no configurado.", "error");
                    return;
                }}
                setListStatus("Cargando...", "");
                window.callbackFunction(payload.handler + "_~_feedback_list");
            }};

            sendBtn.addEventListener("click", sendFeedback);
            messageInput.addEventListener("keydown", (e) => {{
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {{
                    sendFeedback();
                }}
            }});
            refreshBtn.addEventListener("click", requestList);

            form.appendChild(subjectInput);
            form.appendChild(messageInput);
            form.appendChild(sendBtn);
            form.appendChild(statusLine);
            form.appendChild(feedbackHint);

            feedbackPanel.appendChild(feedbackTitle);
            feedbackPanel.appendChild(feedbackDesc);
            feedbackPanel.appendChild(form);
            feedbackPanel.appendChild(listTitle);
            feedbackPanel.appendChild(listDesc);
            feedbackPanel.appendChild(listActions);
            feedbackPanel.appendChild(listContainer);

            const legacyPanel = document.createElement("div");
            legacyPanel.id = "tv-legacy-panel";
            legacyPanel.className = "tv-legacy-panel";
            legacyPanel.style.display = "none";

            const legacyTabs = document.createElement("div");
            legacyTabs.className = "tv-side-tabs";
            const tabObjects = document.createElement("div");
            tabObjects.className = "tv-side-tab active";
            tabObjects.innerText = "Strategy Data";
            const tabData = document.createElement("div");
            tabData.className = "tv-side-tab";
            tabData.innerText = "Data Window";
            const tabStrategies = document.createElement("div");
            tabStrategies.className = "tv-side-tab";
            tabStrategies.innerText = "Estrategias";
            legacyTabs.appendChild(tabObjects);
            legacyTabs.appendChild(tabData);
            legacyTabs.appendChild(tabStrategies);

            const strategyDataPanel = document.createElement("div");
            strategyDataPanel.className = "tv-strategy-data-panel";

            const strategyDataHeader = document.createElement("div");
            strategyDataHeader.className = "tv-strategy-data-header";
            const strategyDataLabel = document.createElement("span");
            strategyDataLabel.className = "tv-strategy-data-label";
            strategyDataLabel.innerText = "Estrategia:";
            const strategyDataSelect = document.createElement("select");
            strategyDataSelect.id = "tv-strategy-data-select";
            strategyDataSelect.className = "tv-strategy-data-select";
            strategyDataSelect.addEventListener("change", () => {{
                const handler = strategyDataSelect.dataset.handler || payload.handler;
                const selected = encodeURIComponent(strategyDataSelect.value || "");
                window.callbackFunction(handler + "_~_strategy_data_scope;;;" + selected);
            }});
            const strategyDataAllActivesBtn = document.createElement("button");
            strategyDataAllActivesBtn.type = "button";
            strategyDataAllActivesBtn.id = "tv-strategy-data-all-actives";
            strategyDataAllActivesBtn.className = "tv-strategy-data-all-btn";
            strategyDataAllActivesBtn.innerText = "All actives";
            strategyDataAllActivesBtn.addEventListener("click", () => {{
                const handler = strategyDataSelect.dataset.handler || strategyDataAllActivesBtn.dataset.handler || payload.handler;
                window.callbackFunction(handler + "_~_strategy_data_scope_all_actives");
            }});
            strategyDataHeader.appendChild(strategyDataLabel);
            strategyDataHeader.appendChild(strategyDataSelect);
            strategyDataHeader.appendChild(strategyDataAllActivesBtn);

            const list = document.createElement("div");
            list.className = "tv-side-list";
            list.id = "tv-side-list";
            strategyDataPanel.appendChild(strategyDataHeader);
            strategyDataPanel.appendChild(list);

            const dataWindow = document.createElement("div");
            dataWindow.id = "tv-data-window";
            dataWindow.className = "tv-data-window";
            dataWindow.style.display = "none";
            dataWindow.innerHTML = `
                <div class="tv-data-header">
                    <div class="tv-data-title">Data Window</div>
                    <div class="tv-data-controls">
                        <span class="tv-data-control-label">Estrategia:</span>
                        <select id="tv-data-strategy-select" class="tv-data-select"></select>
                    </div>
                    <div class="tv-data-meta">
                        <div class="tv-data-row">
                            <span class="tv-data-label">Estrategia</span>
                            <span class="tv-data-value" id="tv-data-strategy">--</span>
                        </div>
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
            const dataWindowStrategySelect = dataWindow.querySelector("#tv-data-strategy-select");
            if (dataWindowStrategySelect) {{
                dataWindowStrategySelect.addEventListener("change", () => {{
                    const handler = dataWindowStrategySelect.dataset.handler || payload.handler;
                    const selected = encodeURIComponent(dataWindowStrategySelect.value || "");
                    window.callbackFunction(handler + "_~_strategy_data_scope;;;" + selected);
                }});
            }}

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
            runBtn.innerText = "Iniciar motor";
            const runStatus = document.createElement("div");
            runStatus.id = "tv-strategy-status";
            runStatus.className = "tv-strategy-status";
            runStatus.innerText = "Motor detenido";
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
            legacyPanel.appendChild(strategyDataPanel);
            legacyPanel.appendChild(dataWindow);
            legacyPanel.appendChild(strategyPanel);

            tabObjects.addEventListener("click", () => {{
                tabObjects.classList.add("active");
                tabData.classList.remove("active");
                tabStrategies.classList.remove("active");
                strategyDataPanel.style.display = "flex";
                dataWindow.style.display = "none";
                strategyPanel.style.display = "none";
            }});
            tabData.addEventListener("click", () => {{
                tabData.classList.add("active");
                tabObjects.classList.remove("active");
                tabStrategies.classList.remove("active");
                strategyDataPanel.style.display = "none";
                dataWindow.style.display = "flex";
                strategyPanel.style.display = "none";
            }});
            tabStrategies.addEventListener("click", () => {{
                tabStrategies.classList.add("active");
                tabObjects.classList.remove("active");
                tabData.classList.remove("active");
                strategyDataPanel.style.display = "none";
                dataWindow.style.display = "none";
                strategyPanel.style.display = "block";
            }});

            panel.appendChild(newsPanel);
            panel.appendChild(feedbackPanel);
            panel.appendChild(legacyPanel);
            if (!panel.parentElement) {{
                container.appendChild(panel);
            }}

            let confirmOverlay = document.getElementById("tv-confirm-overlay");
            if (!confirmOverlay) {{
                confirmOverlay = document.createElement("div");
                confirmOverlay.id = "tv-confirm-overlay";
                confirmOverlay.className = "tv-confirm-overlay";
                confirmOverlay.setAttribute("aria-hidden", "true");
                confirmOverlay.innerHTML = `
                    <div class="tv-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="tv-confirm-title">
                        <div class="tv-confirm-title" id="tv-confirm-title">Confirmar acción</div>
                        <div class="tv-confirm-message" id="tv-confirm-message">¿Deseas continuar?</div>
                        <div class="tv-confirm-actions">
                            <button type="button" class="tv-confirm-btn cancel" id="tv-confirm-cancel">Cancelar</button>
                            <button type="button" class="tv-confirm-btn confirm" id="tv-confirm-ok">Confirmar</button>
                        </div>
                    </div>
                `;
                document.body.appendChild(confirmOverlay);
            }}

            const confirmTitleEl = document.getElementById("tv-confirm-title");
            const confirmMessageEl = document.getElementById("tv-confirm-message");
            const confirmCancelBtn = document.getElementById("tv-confirm-cancel");
            const confirmOkBtn = document.getElementById("tv-confirm-ok");

            const hideConfirmDialog = () => {{
                if (!confirmOverlay) return;
                confirmOverlay.classList.remove("open");
                confirmOverlay.setAttribute("aria-hidden", "true");
                confirmOverlay.dataset.open = "0";
                confirmOverlay._onConfirm = null;
            }};

            if (!confirmOverlay.dataset.bound) {{
                confirmOverlay.dataset.bound = "1";
                confirmOverlay.dataset.open = "0";
                confirmOverlay._onConfirm = null;

                confirmOverlay.addEventListener("click", (e) => {{
                    if (e.target === confirmOverlay) {{
                        hideConfirmDialog();
                    }}
                }});

                if (confirmCancelBtn) {{
                    confirmCancelBtn.addEventListener("click", () => {{
                        hideConfirmDialog();
                    }});
                }}

                if (confirmOkBtn) {{
                    confirmOkBtn.addEventListener("click", () => {{
                        const onConfirm = confirmOverlay._onConfirm;
                        hideConfirmDialog();
                        if (typeof onConfirm === "function") {{
                            onConfirm();
                        }}
                    }});
                }}

                document.addEventListener("keydown", (e) => {{
                    if (!confirmOverlay || confirmOverlay.dataset.open !== "1") return;
                    if (e.key === "Escape") {{
                        e.preventDefault();
                        hideConfirmDialog();
                        return;
                    }}
                    if (e.key === "Enter") {{
                        e.preventDefault();
                        const onConfirm = confirmOverlay._onConfirm;
                        hideConfirmDialog();
                        if (typeof onConfirm === "function") {{
                            onConfirm();
                        }}
                    }}
                }});
            }}

            window.tvShowConfirm = (message, onConfirm, options) => {{
                const opts = options || {{}};
                if (confirmTitleEl) {{
                    confirmTitleEl.innerText = opts.title || "Confirmar acción";
                }}
                if (confirmMessageEl) {{
                    confirmMessageEl.innerText = message || "¿Deseas continuar?";
                }}
                if (confirmCancelBtn) {{
                    confirmCancelBtn.innerText = opts.cancelLabel || "Cancelar";
                }}
                if (confirmOkBtn) {{
                    confirmOkBtn.innerText = opts.confirmLabel || "Confirmar";
                }}
                if (confirmOverlay) {{
                    confirmOverlay._onConfirm = typeof onConfirm === "function" ? onConfirm : null;
                    confirmOverlay.setAttribute("aria-hidden", "false");
                    confirmOverlay.dataset.open = "1";
                    confirmOverlay.classList.add("open");
                }}
                if (confirmOkBtn) {{
                    setTimeout(() => confirmOkBtn.focus(), 0);
                }}
            }};

            window.renderStrategyDataSelector = (data) => {{
                const selector = document.getElementById("tv-strategy-data-select");
                const allActivesBtn = document.getElementById("tv-strategy-data-all-actives");
                if (!selector) return;
                const payloadData = data || {{}};
                const options = Array.isArray(payloadData.options) ? payloadData.options : [];
                const selected = payloadData.selected || "";
                const allActives = !!payloadData.all_actives;
                const handler = payloadData.handler || payload.handler;
                selector.innerHTML = "";

                options.forEach((entry) => {{
                    if (!entry || !entry.key) return;
                    const option = document.createElement("option");
                    option.value = entry.key;
                    option.innerText = entry.label || entry.key;
                    option.disabled = !!entry.disabled;
                    selector.appendChild(option);
                }});

                if (!selector.options.length) {{
                    const fallback = document.createElement("option");
                    fallback.value = "";
                    fallback.innerText = "Sin estrategias";
                    fallback.disabled = true;
                    selector.appendChild(fallback);
                }}

                const hasSelected = Array.from(selector.options).some((opt) => opt.value === selected);
                if (hasSelected) {{
                    selector.value = selected;
                }} else {{
                    selector.selectedIndex = 0;
                }}
                selector.dataset.handler = handler;
                if (allActivesBtn) {{
                    allActivesBtn.dataset.handler = handler;
                    allActivesBtn.classList.toggle("active", allActives);
                    allActivesBtn.disabled = !options.length;
                }}
            }};

            window.renderDataWindowStrategySelector = (data) => {{
                const selector = document.getElementById("tv-data-strategy-select");
                if (!selector) return;
                const payloadData = data || {{}};
                const options = Array.isArray(payloadData.options) ? payloadData.options : [];
                const selected = payloadData.selected || "";
                const handler = payloadData.handler || payload.handler;
                selector.innerHTML = "";

                options.forEach((entry) => {{
                    if (!entry || !entry.key) return;
                    const option = document.createElement("option");
                    option.value = entry.key;
                    option.innerText = entry.label || entry.key;
                    option.disabled = !!entry.disabled;
                    selector.appendChild(option);
                }});

                if (!selector.options.length) {{
                    const fallback = document.createElement("option");
                    fallback.value = "";
                    fallback.innerText = "Sin estrategias";
                    fallback.disabled = true;
                    selector.appendChild(fallback);
                }}

                const hasSelected = Array.from(selector.options).some((opt) => opt.value === selected);
                if (hasSelected) {{
                    selector.value = selected;
                }} else {{
                    selector.selectedIndex = 0;
                }}
                selector.dataset.handler = handler;
            }};

            window.tvEyeSvg = (isVisible) => {{
                if (isVisible) {{
                    return "<svg viewBox='0 0 16 16' aria-hidden='true'><path d='M1.5 8s2.5-4 6.5-4 6.5 4 6.5 4-2.5 4-6.5 4-6.5-4-6.5-4Z'></path><circle cx='8' cy='8' r='2.2'></circle></svg>";
                }}
                return "<svg viewBox='0 0 16 16' aria-hidden='true'><path d='M1.5 8s2.5-4 6.5-4 6.5 4 6.5 4-2.5 4-6.5 4-6.5-4-6.5-4Z'></path><circle cx='8' cy='8' r='2.2'></circle><path d='M3 13 L13 3'></path></svg>";
            }};

            window.setSidePositionState = (state) => {{
                state = state || {{}};
                const longRow = document.querySelector('.tv-side-item[data-key="long_pos"]');
                const shortRow = document.querySelector('.tv-side-item[data-key="short_pos"]');

                const updateCount = (row, count) => {{
                    if (!row) return;
                    const badge = row.querySelector(".tv-side-count");
                    if (!badge) return;
                    const value = Math.max(0, Number(count || 0));
                    badge.innerText = String(value);
                    badge.title = "Numero de posiciones abiertas";
                    badge.setAttribute("aria-label", "Numero de posiciones abiertas");
                }};

                const applyState = (row, active, variant) => {{
                    if (!row) return;
                    row.classList.remove("position-long-active", "position-short-active");
                    row.classList.add("dim");
                    if (active) {{
                        row.classList.remove("dim");
                        row.classList.add(variant === "long" ? "position-long-active" : "position-short-active");
                    }}
                }};

                applyState(longRow, !!state.long_active, "long");
                applyState(shortRow, !!state.short_active, "short");
                updateCount(longRow, state.long_count);
                updateCount(shortRow, state.short_count);
            }};

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

                    if (item.key === "long_pos" || item.key === "short_pos") {{
                        const count = document.createElement("span");
                        count.className = "tv-side-count";
                        count.innerText = "0";
                        count.title = "Numero de posiciones abiertas";
                        count.setAttribute("aria-label", "Numero de posiciones abiertas");
                        left.appendChild(count);
                    }}

                    const eye = document.createElement("button");
                    eye.type = "button";
                    eye.className = "tv-eye" + (item.visible ? "" : " hidden");
                    if (item.toggle) {{
                        eye.innerHTML = window.tvEyeSvg ? window.tvEyeSvg(!!item.visible) : "👁";
                        eye.setAttribute("aria-label", item.visible ? "Ocultar indicador" : "Mostrar indicador");
                        eye.title = item.visible ? "Ocultar indicador" : "Mostrar indicador";
                    }} else {{
                        eye.classList.add("placeholder");
                        eye.setAttribute("aria-hidden", "true");
                        eye.tabIndex = -1;
                    }}

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
                if (window.renderStrategyDataSelector) {{
                    window.renderStrategyDataSelector({{
                        options: tree.strategy_data_options || [],
                        selected: tree.strategy_data_selected || "",
                        all_actives: !!tree.strategy_data_all_actives,
                        handler: tree.handler
                    }});
                }}
                if (window.renderDataWindowStrategySelector) {{
                    window.renderDataWindowStrategySelector({{
                        options: tree.strategy_data_options || [],
                        selected: tree.strategy_data_selected || "",
                        handler: tree.handler
                    }});
                }}
                if (window.setSidePositionState) {{
                    window.setSidePositionState(tree.position_state || {{}});
                }}
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

                    const timeframe = document.createElement("div");
                    timeframe.className = "tv-strategy-timeframe";
                    const tfText = strategy.timeframe ? ("TF: " + strategy.timeframe) : "TF: --";
                    const magicText = strategy.magic ? (" | M: " + strategy.magic) : "";
                    timeframe.innerText = tfText + magicText;

                    const statusLine = document.createElement("div");
                    statusLine.className = "tv-strategy-statusline";
                    statusLine.innerText = strategy.status || "";

                    const right = document.createElement("div");
                    right.className = "tv-strategy-right";

                    const enableBtn = document.createElement("button");
                    enableBtn.type = "button";
                    enableBtn.className = "tv-strategy-enable" + (strategy.enabled ? " active" : "");
                    enableBtn.innerText = strategy.enabled ? "Activa" : "Inactiva";
                    enableBtn.addEventListener("click", (e) => {{
                        e.stopPropagation();
                        const strategyName = strategy.label || strategy.key || "estrategia";
                        const actionText = strategy.enabled ? "desactivar" : "activar";
                        const runToggle = () => {{
                            window.callbackFunction(data.handler + "_~_strategy_enable_toggle;;;" + strategy.key);
                        }};
                        if (typeof window.tvShowConfirm === "function") {{
                            window.tvShowConfirm(
                                '¿Confirmas ' + actionText + ' la estrategia "' + strategyName + '"?',
                                runToggle,
                                {{
                                    title: strategy.enabled ? "Desactivar estrategia" : "Activar estrategia",
                                    confirmLabel: strategy.enabled ? "Desactivar" : "Activar",
                                    cancelLabel: "Cancelar"
                                }}
                            );
                            return;
                        }}
                        const confirmed = window.confirm('¿Confirmas ' + actionText + ' la estrategia "' + strategyName + '"?');
                        if (confirmed) {{
                            runToggle();
                        }}
                    }});

                    const lastRun = document.createElement("div");
                    lastRun.className = "tv-strategy-last-run";
                    lastRun.innerText = strategy.last_run ? ("Run: " + strategy.last_run) : "";

                    left.appendChild(title);
                    left.appendChild(module);
                    left.appendChild(timeframe);
                    left.appendChild(statusLine);
                    right.appendChild(enableBtn);
                    right.appendChild(lastRun);
                    row.appendChild(left);
                    row.appendChild(right);

                    row.addEventListener("click", () => {{
                        window.callbackFunction(data.handler + "_~_strategy_select;;;" + strategy.key);
                    }});

                    list.appendChild(row);
                }});
                if (empty) {{
                    empty.style.display = (data.strategies && data.strategies.length) ? "none" : "block";
                }}
            }};

            window.setStrategyStatus = (state) => {{
                if (typeof state === "boolean") {{
                    state = {{ running: state }};
                }}
                state = state || {{}};
                const running = !!state.running;
                const activeCount = Number(state.active_count || 0);
                const btn = document.getElementById("tv-strategy-run");
                const status = document.getElementById("tv-strategy-status");
                if (btn) {{
                    btn.innerText = running ? "Detener motor" : "Iniciar motor";
                    btn.classList.toggle("running", running);
                }}
                if (status) {{
                    if (running) {{
                        status.innerText = "Motor activo · " + activeCount + " estrategia(s)";
                    }} else {{
                        status.innerText = "Motor detenido · " + activeCount + " activa(s)";
                    }}
                }}
            }};

            if (window.renderStrategyList) {{
                window.renderStrategyList({{
                    strategies: payload.strategies,
                    selected: payload.selected_strategy,
                    handler: payload.handler,
                    active_count: payload.active_count || 0
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
                state.strategyEl = document.getElementById("tv-data-strategy");
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
                const strategyLabel = (state.meta && (state.meta.strategy_label || state.meta.strategy)) || "--";
                if (state.strategyEl) state.strategyEl.innerText = strategyLabel;
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
            let feedbackLoaded = false;

            const activate = (key) => {{
                newsPanel.style.display = key === "news" ? "flex" : "none";
                feedbackPanel.style.display = key === "feedback" ? "flex" : "none";
                legacyPanel.style.display = key === "legacy" ? "flex" : "none";
                Object.keys(buttons).forEach((btnKey) => {{
                    buttons[btnKey].classList.toggle("active", btnKey === key);
                }});
                if (key === "feedback" && !feedbackLoaded) {{
                    feedbackLoaded = true;
                    requestList();
                }}
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
        # Para peques: esta funcion sirve para reaccionar a panel lateral evento.
        action = (action or "").strip()
        if action == "feedback_send":
            subject = unquote(args[0]) if len(args) > 0 else ""
            message = unquote(args[1]) if len(args) > 1 else ""
            self._handle_feedback_send(subject, message)
            return
        if action == "feedback_list":
            self._handle_feedback_list()
            return
        if action == "toggle" and args:
            self.toggle_indicator(args[0])
            return
        if action == "strategy_data_scope":
            scope = unquote(args[0]) if len(args) > 0 else ""
            self._set_strategy_data_scope(scope)
            return
        if action == "strategy_data_scope_all_actives":
            self._set_strategy_data_all_actives()
            return
        if action == "strategy_select" and args:
            self._set_strategy_by_key(args[0])
            return
        if action == "strategy_enable_toggle" and args:
            key = args[0]
            entry = self._get_strategy_entry(key)
            if entry:
                self._set_strategy_enabled(key, not bool(entry.get("enabled")), sync_ui=True)
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
        # Para peques: esta funcion sirve para gestionar envio de comentarios.
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
        # Para peques: esta funcion sirve para guardar comentarios local.
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
        # Para peques: esta funcion sirve para publicar comentarios webhook.
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

    def _get_feedback_list_url(self) -> str:
        # Para peques: esta funcion sirve para obtener la URL de la lista de comentarios.
        list_url = (getattr(config, "FEEDBACK_LIST_URL", "") or "").strip()
        if list_url:
            return list_url

        webhook_url = (getattr(config, "FEEDBACK_WEBHOOK_URL", "") or "").strip()
        if not webhook_url:
            return ""
        try:
            parsed = urlparse(webhook_url)
            path = parsed.path or ""
            if path.endswith("/feedback"):
                path = path[:-len("/feedback")] + "/feedback/list"
            else:
                path = path.rstrip("/") + "/feedback/list"
            return urlunparse(parsed._replace(path=path))
        except Exception:
            return ""

    def _handle_feedback_list(self):
        # Para peques: esta funcion sirve para gestionar la lista de comentarios.
        list_url = self._get_feedback_list_url()
        if not list_url:
            self._set_feedback_list([], "Servidor no configurado.", "error")
            return
        try:
            request = urllib.request.Request(list_url, headers={"Accept": "application/json"})
            timeout = getattr(config, "FEEDBACK_TIMEOUT_SECONDS", 4) or 4
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read().decode("utf-8")
            payload = json.loads(data)
            items = payload.get("items", []) if isinstance(payload, dict) else []
            if not isinstance(items, list):
                items = []
            status_text = f"{len(items)} mensajes"
            self._set_feedback_list(items, status_text, "success")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                msg = "Token inválido o faltante (401)."
                self.log_message(f"Error cargando feedback: {e}")
            elif e.code == 404:
                msg = "Endpoint /feedback/list no disponible (404)."
                if not getattr(self, "_feedback_list_404_seen", False):
                    self.log_message(f"Error cargando feedback: {e}")
                    self._feedback_list_404_seen = True
            else:
                msg = f"Error HTTP {e.code}."
                self.log_message(f"Error cargando feedback: {e}")
            self._set_feedback_list([], msg, "error")
        except Exception as e:
            self._set_feedback_list([], "No se pudo cargar.", "error")
            self.log_message(f"Error cargando feedback: {e}")

    def _set_feedback_list(self, items, status_text: str = "", kind: str = ""):
        # Para peques: esta funcion sirve para actualizar la lista de comentarios.
        try:
            items_js = json.dumps(items or [])
        except Exception:
            items_js = "[]"
        status_js = json.dumps(status_text or "")
        kind_js = json.dumps(kind or "")
        self.chart.run_script(f'''
            ;(function() {{
                var list = document.getElementById("tv-feedback-list");
                var status = document.getElementById("tv-feedback-list-status");
                if (status) {{
                    status.textContent = {status_js};
                    status.classList.remove("success", "error");
                    var kind = {kind_js};
                    if (kind === "success") status.classList.add("success");
                    if (kind === "error") status.classList.add("error");
                }}
                if (!list) return;
                list.innerHTML = "";
                var items = {items_js};
                if (!items || !items.length) {{
                    var empty = document.createElement("div");
                    empty.className = "tv-feedback-empty";
                    empty.innerText = "Sin mensajes.";
                    list.appendChild(empty);
                    return;
                }}
                items.forEach((item) => {{
                    if (!item) return;
                    var card = document.createElement("div");
                    card.className = "tv-feedback-item";

                    var title = document.createElement("div");
                    title.className = "tv-feedback-item-title";
                    title.innerText = item.subject || "Sin asunto";

                    var message = document.createElement("div");
                    message.className = "tv-feedback-item-message";
                    message.innerText = item.message || "";

                    var meta = document.createElement("div");
                    meta.className = "tv-feedback-item-meta";
                    var timeText = item.received_at || item.timestamp || "";
                    if (timeText) {{
                        var time = document.createElement("span");
                        time.innerText = timeText;
                        meta.appendChild(time);
                    }}
                    if (item.symbol) {{
                        var symbol = document.createElement("span");
                        symbol.innerText = item.symbol;
                        meta.appendChild(symbol);
                    }}
                    if (item.strategy) {{
                        var strat = document.createElement("span");
                        strat.innerText = item.strategy;
                        meta.appendChild(strat);
                    }}
                    if (item.timeframe) {{
                        var tf = document.createElement("span");
                        tf.innerText = item.timeframe;
                        meta.appendChild(tf);
                    }}

                    card.appendChild(title);
                    card.appendChild(message);
                    if (meta.childNodes.length) {{
                        card.appendChild(meta);
                    }}
                    list.appendChild(card);
                }});
            }})();
        ''')

    def _set_feedback_status(self, text: str, kind: str = ""):
        # Para peques: esta funcion sirve para actualizar comentarios estado.
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
        # Para peques: este boton enciende o apaga el motor que ejecuta las estrategias.
        """Inicia o detiene el motor de estrategias desde el panel."""
        thread_alive = self.bot_thread is not None and self.bot_thread.is_alive()
        if self.bot_running and thread_alive:
            self.stop_bot()
            return
        if self.bot_running and not thread_alive:
            # Estado inconsistente: el hilo no está vivo pero el flag sigue activo.
            self.bot_running = False
        self.start_bot()

    def toggle_indicator(self, key: str):
        # Para peques: esta funcion sirve para activar o desactivar indicador.
        visible = not self.indicator_state.get(key, True)
        self.indicator_state[key] = visible
        self._apply_indicator_visibility(key, visible)
        self._sync_indicator_ui(key, visible)
        if self.price_data is not None:
            try:
                self._update_data_window(self.price_data, strategy_entry=self._get_selected_strategy_entry())
            except Exception:
                pass

    def _apply_indicator_visibility(self, key: str, visible: bool):
        # Para peques: esta funcion sirve para aplicar indicador visibilidad.
        series_list = self.indicator_series.get(key, [])
        for series in series_list:
            if series is None:
                continue
            if visible:
                series.show_data()
            else:
                series.hide_data()

    def _sync_indicator_ui(self, key: str, visible: bool):
        # Para peques: esta funcion sirve para sincronizar indicador interfaz.
        visible_flag = "1" if visible else "0"
        hidden_class = "" if visible else "hidden"
        visible_js = str(visible).lower()
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
                        if (window.tvEyeSvg) {{
                            eye.innerHTML = window.tvEyeSvg({visible_js});
                        }} else {{
                            eye.innerHTML = "👁";
                        }}
                        eye.setAttribute("aria-label", {visible_js} ? "Ocultar indicador" : "Mostrar indicador");
                        eye.title = {visible_js} ? "Ocultar indicador" : "Mostrar indicador";
                    }}
                    row.classList.toggle("dim", !{str(visible).lower()});
                }}
            }})();
        ''')

    def setup_bottom_bar(self):
        # Para peques: esta funcion sirve para preparar barra inferior.
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
        # Para peques: esta funcion sirve para actualizar barra inferior periodo activo.
        self.chart.run_script(f'''
            ;(function() {{
                document.querySelectorAll(".tv-period-btn").forEach((btn) => {{
                    btn.classList.toggle("active", btn.dataset.period === "{period}");
                }});
            }})();
        ''')

    def on_bottom_bar_event(self, period):
        # Para peques: esta funcion sirve para reaccionar a barra inferior evento.
        if period:
            self.view_period = period
            self.set_bottom_period_active(period)
            self.refresh_data()

    def update_bottom_clock(self):
        # Para peques: esta funcion sirve para actualizar barra inferior reloj.
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
        # Para peques: esta funcion sirve para escribir en el log mensaje.
        """Registra un mensaje."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        try:
            print(f"[{timestamp}] {message}")
        except:
            pass
    
    def init_mt5(self):
        # Para peques: esta funcion sirve para iniciar mt5.
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
        # Para peques: esta funcion sirve para actualizar balance.
        """Actualiza el balance en la barra superior."""
        try:
            info = mt5.account_info()
            if info is None:
                balance = "---"
                currency = None
            else:
                balance = f"{info.balance:,.2f}"
                currency = getattr(info, "currency", "") or None
            self._set_balance_widget(balance, currency)
        except Exception as e:
            self.log_message(f"Error al actualizar balance: {e}")
        finally:
            try:
                state = self._collect_selected_position_state()
                self.position_state = state
                self._sync_position_state_ui(state)
            except Exception:
                pass

    def _collect_selected_position_state(self) -> dict:
        # Para peques: esta funcion sirve para resumir posiciones long/short de la estrategia seleccionada.
        state = {
            "long_active": False,
            "short_active": False,
            "long_count": 0,
            "short_count": 0,
        }

        try:
            selected_magic = int(self._selected_strategy_magic() or 0)
        except Exception:
            selected_magic = 0

        try:
            positions = mt5.positions_get(symbol=config.SYMBOL) or []
        except Exception:
            positions = []

        for pos in positions:
            try:
                pos_magic = int(getattr(pos, "magic", 0) or 0)
            except Exception:
                pos_magic = 0

            if selected_magic > 0 and pos_magic != selected_magic:
                continue

            pos_type = getattr(pos, "type", None)
            if pos_type == mt5.ORDER_TYPE_BUY:
                state["long_count"] += 1
            elif pos_type == mt5.ORDER_TYPE_SELL:
                state["short_count"] += 1

        state["long_active"] = state["long_count"] > 0
        state["short_active"] = state["short_count"] > 0
        return state

    def _sync_position_state_ui(self, state: dict = None):
        # Para peques: esta funcion sirve para actualizar en pantalla el estado de long/short.
        if state is None:
            state = self.position_state
        if not isinstance(state, dict):
            return
        payload = json.dumps(state)
        self.chart.run_script(f'''
            ;(function() {{
                const state = {payload};
                if (window.setSidePositionState) {{
                    window.setSidePositionState(state);
                }}
            }})();
        ''')

    def _timeframe_to_minutes(self, timeframe_value) -> int:
        # Para peques: esta funcion sirve para pasar el marco de tiempo a minutos.
        timeframe_minutes = {
            mt5.TIMEFRAME_M1: 1,
            mt5.TIMEFRAME_M5: 5,
            mt5.TIMEFRAME_M15: 15,
            mt5.TIMEFRAME_M30: 30,
            mt5.TIMEFRAME_H1: 60,
            mt5.TIMEFRAME_H4: 240,
            mt5.TIMEFRAME_D1: 1440
        }
        return int(timeframe_minutes.get(timeframe_value, 1))

    def get_timeframe_minutes(self):
        # Para peques: esta funcion sirve para obtener marco de tiempo minutos.
        """Obtiene los minutos del timeframe actual."""
        return self._timeframe_to_minutes(config.TIMEFRAME)

    def _selected_strategy_magic(self) -> int:
        # Para peques: esta funcion sirve para numero magico de la estrategia seleccionada.
        entry = self._get_selected_strategy_entry()
        if entry and isinstance(entry.get("magic_number"), int) and entry.get("magic_number") > 0:
            return int(entry.get("magic_number"))
        return int(getattr(config, "MAGIC_NUMBER", 0) or 0)

    def _strategy_timeframe_value(self, entry: dict, fallback=None):
        # Para peques: esta funcion sirve para valor del marco de tiempo de la estrategia.
        if isinstance(entry, dict):
            tf_value = entry.get("timeframe_value")
            if isinstance(tf_value, int):
                return tf_value
        if fallback is not None:
            return fallback
        return config.TIMEFRAME

    def _build_market_dataframe(self, timeframe_value, bars_needed):
        # Para peques: esta funcion sirve para construir mercado tabla de datos.
        df = data_feed.get_rates_df(config.SYMBOL, timeframe_value, bars_needed)
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
        return df
    
    def get_period_bars(self, period_str, timeframe_minutes):
        # Para peques: esta funcion sirve para obtener periodo velas.
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
        # Para peques: esta funcion sirve para refrescar datos.
        """Actualiza los datos del gráfico."""
        def update_thread():
            # Para peques: esta funcion sirve para actualizar hilo.
            try:
                selected_entry = self._get_selected_strategy_entry()
                timeframe_value = self._strategy_timeframe_value(selected_entry, fallback=config.TIMEFRAME)
                if timeframe_value is None:
                    timeframe_value = mt5.TIMEFRAME_M1

                timeframe_minutes = self._timeframe_to_minutes(timeframe_value)
                bars_needed = self.get_period_bars(self.view_period, timeframe_minutes)

                df = self._build_market_dataframe(timeframe_value, bars_needed)
                df = self._apply_strategy_processing_for_entry(selected_entry, df)
                
                if len(df) < 2:
                    return

                if isinstance(selected_entry, dict):
                    selected_entry["last_df"] = df

                self.price_data = df
                self.update_chart(df, fit_view=True, strategy_entry=selected_entry)
                self.update_equity_chart()
                self.update_tci_chart(df)
                self.update_balance()
                self.update_quotes()
                
                self.log_message(f"Datos actualizados: {len(df)} velas")
                
            except Exception as e:
                self.log_message(f"Error al actualizar datos: {e}")
        
        threading.Thread(target=update_thread, daemon=True).start()
    
    def update_chart(self, df, fit_view: bool = False, strategy_entry=None):
        # Para peques: esta funcion sirve para actualizar grafico.
        """Actualiza el gráfico de velas."""
        try:
            # Preparar datos para Lightweight Charts
            chart_data = df[['time', 'open', 'high', 'low', 'close', 'tick_volume']].copy()
            chart_data = chart_data.rename(columns={'tick_volume': 'volume'})
            
            chart_data['time'] = pd.to_datetime(chart_data['time'], utc=True)
            
            # Establecer datos de velas
            self.chart.set(chart_data)
            self.chart.run_script(f'{self.chart.id}.series.applyOptions({{visible: true}})')
            try:
                self.chart.show_data()
                self.chart.run_script(f'{self.chart.id}.volumeSeries.applyOptions({{visible: true}})')
            except Exception:
                pass
            # Ajustar viewport solo cuando se solicita (evita resetear el zoom en cada tick)
            if fit_view:
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
                else:
                    self.upper_line.set(pd.DataFrame())
            else:
                self.upper_line.set(pd.DataFrame())
            
            if 'average' in df.columns and not df['average'].isna().all():
                avg_data = df[['time', 'average']].dropna().copy()
                avg_data = avg_data.reset_index(drop=True)
                avg_data = avg_data.rename(columns={'average': 'Average'})
                if len(avg_data) > 0:
                    self.average_line.set(avg_data)
                else:
                    self.average_line.set(pd.DataFrame())
            else:
                self.average_line.set(pd.DataFrame())
            
            if 'lower' in df.columns and not df['lower'].isna().all():
                lower_data = df[['time', 'lower']].dropna().copy()
                lower_data = lower_data.reset_index(drop=True)
                lower_data = lower_data.rename(columns={'lower': 'Lower'})
                if len(lower_data) > 0:
                    self.lower_line.set(lower_data)
                else:
                    self.lower_line.set(pd.DataFrame())
            else:
                self.lower_line.set(pd.DataFrame())

            # Supertrend
            if 'supertrend_up' in df.columns:
                st_up = df[['time', 'supertrend_up']].dropna().copy()
                st_up = st_up.reset_index(drop=True)
                st_up = st_up.rename(columns={'supertrend_up': 'Supertrend Up'})
                if len(st_up) > 0:
                    self.supertrend_up_line.set(st_up)
                else:
                    self.supertrend_up_line.set(pd.DataFrame())
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
            else:
                self.supertrend_down_line.set(pd.DataFrame())
            
            # Marcar operaciones reales (deals BUY/SELL con el magic number)
            try:
                timeframe_minutes = self.get_timeframe_minutes()
                try:
                    bucket_seconds = max(60, int(timeframe_minutes) * 60)
                except Exception:
                    bucket_seconds = 60

                candle_epochs = []
                candle_time_map = {}
                ohlc_map = {}
                try:
                    candle_time_series = pd.to_datetime(df["time"], errors="coerce", utc=True)
                    for row, candle_ts in zip(
                        df[['time', 'low', 'high']].itertuples(index=False),
                        candle_time_series
                    ):
                        if pd.isna(candle_ts):
                            continue
                        key = int(candle_ts.value // 10 ** 9)
                        low = getattr(row, "low", None)
                        high = getattr(row, "high", None)
                        candle_epochs.append(key)
                        if pd.notna(candle_ts) and key not in candle_time_map:
                            try:
                                candle_time_map[key] = candle_ts.to_pydatetime()
                            except Exception:
                                pass
                        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
                            ohlc_map[key] = (float(low), float(high))
                except Exception:
                    candle_epochs = []
                    candle_time_map = {}
                    ohlc_map = {}

                if candle_epochs:
                    start_epoch = int(candle_epochs[0])
                    end_epoch = int(candle_epochs[-1]) + int(bucket_seconds)
                else:
                    start_epoch = int(pd.Timestamp(df['time'].iloc[0]).value // 10 ** 9)
                    end_epoch = int(pd.Timestamp(df['time'].iloc[-1]).value // 10 ** 9) + int(bucket_seconds)

                start_time = datetime.fromtimestamp(start_epoch, tz=timezone.utc)
                end_time = datetime.fromtimestamp(end_epoch, tz=timezone.utc)
                deals = mt5.history_deals_get(start_time, end_time)

                selected_magic = self._selected_strategy_magic()

                markers = []
                action_markers = []
                filtered_deals = []

                if deals:
                    # Deduplicar por position_id (evitar múltiples fills por la misma operación)
                    for deal in deals:
                        if deal.symbol != config.SYMBOL:
                            continue
                        if hasattr(deal, "magic") and deal.magic != selected_magic:
                            continue
                        filtered_deals.append(deal)

                self._latest_deals_cache = filtered_deals
                self._latest_deals_range = (start_time, end_time)

                if filtered_deals:
                    # Deduplicar por (position_id, entry) para evitar múltiples fills
                    dedup = {}
                    passthrough = []
                    for deal in filtered_deals:
                        if getattr(deal, "type", None) not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                            continue
                        position_id = getattr(deal, "position_id", None) or getattr(deal, "ticket", None)
                        entry = getattr(deal, "entry", None)
                        if position_id is None:
                            passthrough.append(deal)
                            continue
                        key = (position_id, entry)
                        prev = dedup.get(key)
                        if prev is None:
                            dedup[key] = deal
                            continue
                        prev_time = getattr(prev, "time", 0)
                        curr_time = getattr(deal, "time", 0)
                        if entry == mt5.DEAL_ENTRY_IN:
                            if curr_time < prev_time:
                                dedup[key] = deal
                        else:
                            if curr_time > prev_time:
                                dedup[key] = deal

                    trade_deals = list(dedup.values()) + passthrough

                    # Orden cronológico y límite opcional
                    trade_deals = sorted(trade_deals, key=lambda d: getattr(d, "time", 0))
                    if self.max_action_markers and len(trade_deals) > self.max_action_markers:
                        trade_deals = trade_deals[-self.max_action_markers:]

                    grouped = {}
                    for deal in trade_deals:
                        deal_time = int(getattr(deal, "time", 0) or 0)
                        bucket_time = int(deal_time // bucket_seconds) * bucket_seconds

                        group = grouped.get(bucket_time)
                        if group is None:
                            group = {
                                "bucket_time": bucket_time,
                                "aligned_marker_time": candle_time_map.get(
                                    bucket_time,
                                    datetime.fromtimestamp(bucket_time, tz=timezone.utc)
                                ),
                                "deals": []
                            }
                            grouped[bucket_time] = group
                        group["deals"].append(deal)

                    for bucket_time in sorted(grouped.keys()):
                        group = grouped[bucket_time]
                        deals = group["deals"]
                        ordered_deals = sorted(deals, key=lambda d: getattr(d, "time", 0))

                        # Nunca mostrar MIX: elegir una sola direccion por vela.
                        # Prioridad:
                        # 1) Ultimo DEAL_ENTRY_IN del minuto (accion efectiva de apertura/reversion).
                        # 2) Si no hay IN, ultimo deal del minuto.
                        last_in_deal = None
                        for d in ordered_deals:
                            if getattr(d, "entry", None) == mt5.DEAL_ENTRY_IN:
                                last_in_deal = d
                        selected_deal = last_in_deal or (ordered_deals[-1] if ordered_deals else None)

                        if getattr(selected_deal, "type", None) == mt5.DEAL_TYPE_BUY:
                            direction = "BUY"
                        else:
                            direction = "SELL"

                        selected_deals = [
                            d for d in ordered_deals
                            if (
                                direction == "BUY" and getattr(d, "type", None) == mt5.DEAL_TYPE_BUY
                            ) or (
                                direction == "SELL" and getattr(d, "type", None) == mt5.DEAL_TYPE_SELL
                            )
                        ]
                        if not selected_deals and selected_deal is not None:
                            selected_deals = [selected_deal]

                        count = len(selected_deals)

                        if direction == "BUY":
                            color = '#26a69a'
                            shape = 'arrow_up'
                            position = 'below'
                            offset_y = 12
                        else:
                            color = '#ef5350'
                            shape = 'arrow_down'
                            position = 'above'
                            offset_y = -12

                        text = direction if count == 1 else f"{direction} x{count}"

                        markers.append({
                            "time": group["aligned_marker_time"],
                            "position": position,
                            "shape": shape,
                            "color": color,
                            "text": text
                        })

                        # Coordenadas para tooltip (alineadas al timeframe)
                        marker_price = None
                        if bucket_time in ohlc_map:
                            low, high = ohlc_map[bucket_time]
                            if direction == "BUY":
                                marker_price = low
                            else:
                                marker_price = high
                        else:
                            first_price = getattr(selected_deals[0], "price", None) if selected_deals else None
                            if isinstance(first_price, (int, float)):
                                marker_price = float(first_price)

                        if isinstance(marker_price, (int, float)):
                            tooltip_text = self._format_deal_group_tooltip(selected_deals, direction)
                            action_markers.append({
                                "time": bucket_time,
                                "price": float(marker_price),
                                "tooltip": tooltip_text,
                                "direction": direction,
                                "offsetY": offset_y
                            })

                # Limpiar y reponer marcadores para evitar duplicados
                self.chart.clear_markers()
                if markers:
                    self.chart.marker_list(markers)

                self._set_action_markers(action_markers)

            except Exception as e:
                self.log_message(f"Error al marcar operaciones: {e}")

            try:
                self._update_data_window(df, strategy_entry=strategy_entry)
            except Exception as e:
                self.log_message(f"Error al actualizar data window: {e}")
            try:
                self._render_strategy_readiness_overlay(strategy_entry)
            except Exception as e:
                self.log_message(f"Error al actualizar aviso de estrategia: {e}")

        except Exception as e:
            self.log_message(f"Error al actualizar grafico: {e}")
            import traceback
            traceback.print_exc()

    def update_last_action_ui(self, action_info):
        # Para peques: esta funcion sirve para actualizar ultima accion interfaz.
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
        # Para peques: esta funcion sirve para construir un resumen de accion.
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
        # Para peques: esta funcion sirve para dar formato a operacion cartel.
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

    def _format_deal_group_tooltip(self, deals, direction, max_items: int = 8):
        # Para peques: esta funcion sirve para dar formato a operacion grupo cartel.
        """Construye el tooltip para un grupo de operaciones en la misma vela."""
        if not deals:
            return ""
        lines = [f"Señal: {direction}", f"Operaciones: {len(deals)}", ""]
        try:
            ordered = sorted(deals, key=lambda d: getattr(d, "time", 0))
        except Exception:
            ordered = list(deals)

        for i, deal in enumerate(ordered):
            if max_items and i >= max_items:
                remaining = len(ordered) - max_items
                if remaining > 0:
                    lines.append(f"... y {remaining} más")
                break

            try:
                deal_time = datetime.fromtimestamp(deal.time).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                deal_time = "hora desconocida"

            deal_type = getattr(deal, "type", None)
            if deal_type == mt5.DEAL_TYPE_BUY:
                deal_dir = "BUY"
            elif deal_type == mt5.DEAL_TYPE_SELL:
                deal_dir = "SELL"
            else:
                deal_dir = "OTHER"

            entry = getattr(deal, "entry", None)
            if entry == mt5.DEAL_ENTRY_IN:
                entry_label = "IN"
            elif entry == mt5.DEAL_ENTRY_OUT:
                entry_label = "OUT"
            elif entry == mt5.DEAL_ENTRY_INOUT:
                entry_label = "IN/OUT"
            else:
                entry_label = ""

            parts = [deal_time, deal_dir]
            if entry_label:
                parts.append(entry_label)

            price = getattr(deal, "price", None)
            if isinstance(price, (int, float)):
                parts.append(f"@ {price:.5f}")

            volume = getattr(deal, "volume", None)
            if isinstance(volume, (int, float)):
                parts.append(f"vol {volume:.2f}")

            profit = getattr(deal, "profit", None)
            if isinstance(profit, (int, float)) and abs(profit) > 0:
                parts.append(f"P {profit:.2f}")

            lines.append("   " + " ".join(parts))

        return "\n".join(lines).strip()

    def _ensure_action_tooltip(self):
        # Para peques: esta funcion sirve para asegurar accion cartel.
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
                window.actionHoverRadius = 28;
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
                        const yShifted = y + (marker.offsetY || 0);
                        const dx = param.point.x - x;
                        const dy = param.point.y - yShifted;
                        const dist = Math.sqrt(dx * dx + dy * dy);
                        if (dist < minDist) {{
                            minDist = dist;
                            closest = {{ marker, x, y: yShifted }};
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
        # Para peques: esta funcion sirve para actualizar accion marcadores.
        """Actualiza la lista de marcadores para el tooltip."""
        self._ensure_action_tooltip()
        markers_js = json.dumps(markers or [])
        self.chart.run_script(f'window.actionMarkers = {markers_js}')

    def _get_symbol_digits(self) -> int:
        # Para peques: esta funcion sirve para obtener simbolo decimales.
        """Devuelve los dígitos de precio del símbolo actual."""
        try:
            info = mt5.symbol_info(config.SYMBOL)
            if info and hasattr(info, "digits"):
                return int(info.digits)
        except Exception:
            pass
        return 2

    def _format_deals_for_data_window(self, deals, limit: int = 40):
        # Para peques: esta funcion sirve para dar formato a operaciones para ventana de datos.
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

    def _normalize_data_window_fields(self, fields):
        # Para peques: esta funcion sirve para ordenar ventana de datos campos.
        normalized = []
        if not isinstance(fields, (list, tuple)):
            return normalized

        for item in fields:
            if isinstance(item, str):
                key = (item or "").strip()
                if not key:
                    continue
                normalized.append({
                    "key": key,
                    "label": key.replace("_", " ").title(),
                    "format": "number",
                    "section": "Estrategia",
                    "group": None,
                    "shift": 0,
                })
                continue

            if not isinstance(item, dict):
                continue

            key = str(item.get("key") or "").strip()
            if not key:
                continue
            try:
                shift_value = int(item.get("shift") or 0)
            except Exception:
                shift_value = 0
            normalized.append({
                "key": key,
                "label": str(item.get("label") or key.replace("_", " ").title()),
                "format": str(item.get("format") or "number"),
                "section": str(item.get("section") or "Estrategia"),
                "group": item.get("group"),
                "shift": shift_value,
            })

        return normalized

    def _get_strategy_data_window_fields(self, module):
        # Para peques: esta funcion sirve para obtener estrategia ventana de datos campos.
        if module is None:
            return []
        candidates = ("DATA_WINDOW_FIELDS", "DATA_FIELDS", "INTERFACE_FIELDS")
        for name in candidates:
            if not hasattr(module, name):
                continue
            try:
                fields = getattr(module, name)
            except Exception:
                fields = None
            normalized = self._normalize_data_window_fields(fields)
            if normalized:
                return normalized
        return []

    def _build_data_window_payload(self, df: pd.DataFrame, strategy_entry=None):
        # Para peques: esta funcion sirve para construir ventana de datos paquete de datos.
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
                    pd.to_datetime(df["time"], utc=True).astype("int64") // 10 ** 9
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

        module = None
        timeframe_label = getattr(self, "current_timeframe", "")
        strategy_key = self.current_strategy_key or ""
        strategy_label = strategy_key
        if isinstance(strategy_entry, dict):
            module = strategy_entry.get("module_obj")
            strategy_key = (strategy_entry.get("key") or strategy_key or "").strip()
            strategy_label = (strategy_entry.get("label") or strategy_label or "").strip()
            entry_timeframe = (strategy_entry.get("timeframe_label") or "").strip()
            if entry_timeframe:
                timeframe_label = entry_timeframe
        if (not strategy_label) and strategy_key:
            entry_lookup = self._get_strategy_entry(strategy_key)
            if isinstance(entry_lookup, dict):
                strategy_label = (entry_lookup.get("label") or strategy_key).strip()
            else:
                strategy_label = strategy_key
        if module is None and not isinstance(strategy_entry, dict):
            module = self.strategy_module
        strategy_fields = self._get_strategy_data_window_fields(module)

        for field in strategy_fields:
            key = field.get("key")
            if not key or key not in df.columns:
                continue
            series = df[key]
            shift_value = int(field.get("shift") or 0)
            if shift_value != 0:
                series = series.shift(shift_value)
            data_df[key] = series

        fields = []
        seen_fields = set()

        def add_field(key, label, fmt, section, group=None):
            # Para peques: esta funcion sirve para agregar un campo.
            if key not in data_df.columns:
                return
            if key in seen_fields:
                return
            visible = True
            if group:
                visible = bool(self.indicator_state.get(group, True))
            seen_fields.add(key)
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

        for field in strategy_fields:
            add_field(
                field.get("key", ""),
                field.get("label", ""),
                field.get("format", "number"),
                field.get("section", "Estrategia"),
                field.get("group"),
            )

        data_df = data_df.astype(object).where(pd.notnull(data_df), None)
        records = data_df.to_dict(orient="records")
        latest_time = time_values[-1] if time_values else None
        trades = self._format_deals_for_data_window(getattr(self, "_latest_deals_cache", None))

        return {
            "meta": {
                "symbol": getattr(config, "SYMBOL", ""),
                "timeframe": timeframe_label,
                "strategy": strategy_key,
                "strategy_label": strategy_label,
                "digits": self._get_symbol_digits(),
            },
            "fields": fields,
            "data": records,
            "latest": latest_time,
            "trades": trades
        }

    def _update_data_window(self, df: pd.DataFrame, strategy_entry=None):
        # Para peques: esta funcion sirve para actualizar ventana de datos.
        """Envía los datos del Data Window al frontend."""
        payload = self._build_data_window_payload(df, strategy_entry=strategy_entry)
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
        # Para peques: esta funcion sirve para actualizar equidad grafico.
        """Actualiza el gráfico de equity."""
        try:
            if self.equity_chart is None or self.equity_line is None:
                return
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=30)
            positions = mt5.history_deals_get(start_date, end_date)
            
            if positions:
                selected_magic = self._selected_strategy_magic()
                filtered = [p for p in positions if hasattr(p, 'magic') and p.magic == selected_magic]
                
                if filtered:
                    equity_data = []
                    balance = 10000.0
                    
                    for deal in sorted(filtered, key=lambda x: x.time):
                        if deal.entry == mt5.DEAL_ENTRY_OUT:
                            balance += deal.profit
                            equity_data.append({
                                'time': datetime.fromtimestamp(deal.time, tz=timezone.utc),
                                'Equity': float(balance)
                            })
                    
                    if equity_data:
                        equity_df = pd.DataFrame(equity_data)
                        equity_df['time'] = pd.to_datetime(equity_df['time'], utc=True)
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
                now = datetime.now(timezone.utc)
                base_data = pd.DataFrame({
                    'time': pd.to_datetime([now - timedelta(days=7), now], utc=True),
                    'Equity': [10000.0, 10000.0]
                })
            
            base_data = base_data.reset_index(drop=True)
            self.equity_line.set(base_data)
            
        except Exception as e:
            self.log_message(f"Error al actualizar equity: {e}")
            import traceback
            traceback.print_exc()

    def update_tci_chart(self, df: pd.DataFrame):
        # Para peques: esta funcion sirve para actualizar tci grafico.
        """Actualiza el subchart TuTCI."""
        try:
            if df is None or len(df) < 2:
                self.tci_hist.set(pd.DataFrame())
                self.tci_fill.set(pd.DataFrame())
                self.tci_signal.set(pd.DataFrame())
                if self.tci_sync_line is not None:
                    self.tci_sync_line.set(pd.DataFrame())
                return

            if 'tci_hist' not in df.columns or 'tci_signal' not in df.columns:
                self.tci_hist.set(pd.DataFrame())
                self.tci_fill.set(pd.DataFrame())
                self.tci_signal.set(pd.DataFrame())
                if self.tci_sync_line is not None:
                    self.tci_sync_line.set(pd.DataFrame())
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
        # Para peques: esta funcion sirve para obtener simbolos activos.
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
        # Para peques: esta funcion sirve para reaccionar a marco de tiempo cambio.
        """Maneja el cambio de timeframe."""
        try:
            timeframe_widget = chart.topbar.get('timeframe') if chart else None
            timeframe_str = timeframe_widget.value if timeframe_widget else None
            if not timeframe_str:
                return
            if getattr(self, "timeframe_locked", False) and self.strategy_timeframe:
                self.log_message(f"Timeframe bloqueado por estrategia ({self.strategy_timeframe}).")
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
        # Para peques: esta funcion sirve para reaccionar a periodo cambio.
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
        # Para peques: esta funcion sirve para reaccionar a simbolo cambio.
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
        # Para peques: esta funcion sirve para recargar simbolos.
        """Recarga la lista de símbolos habilitados y actualiza el switcher."""
        symbols_enabled = self.get_enabled_symbols()
        if config.SYMBOL not in symbols_enabled:
            symbols_enabled.insert(0, config.SYMBOL)
        self.chart.topbar['symbol_select'].update(tuple(symbols_enabled[:50]))
        self.log_message(f"Lista de símbolos recargada ({len(symbols_enabled)} habilitados)")

    def on_filling_change(self, chart):
        # Para peques: esta funcion sirve para reaccionar a llenado cambio.
        """Actualiza el modo de llenado desde la interfaz."""
        try:
            mode = chart.topbar['filling_mode'].value
        except Exception:
            self.log_message("No se pudo leer el filling mode")
            return
        config.FILLING_MODE_OVERRIDE = mode
        self.log_message(f"Filling mode configurado: {mode}")

    def start_bot(self, chart=None):
        # Para peques: esta funcion sirve para iniciar bot.
        """Inicia el bot."""
        if self.bot_running:
            return

        enabled_entries = self._get_enabled_strategy_entries()
        if not enabled_entries:
            self.log_message("Activa al menos una estrategia antes de iniciar el bot.")
            self._sync_strategy_status_ui()
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
        # Para peques: esta funcion sirve para detener bot.
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
        # Para peques: esta funcion sirve para ciclo del bot.
        """Bucle principal del bot."""
        try:
            while self.bot_running and not self.stop_event.is_set():
                try:
                    enabled_entries = self._get_enabled_strategy_entries()
                    if not enabled_entries:
                        self.log_message("No hay estrategias activas. Esperando...")
                        if self.stop_event.wait(timeout=2):
                            break
                        continue

                    test_mode = getattr(config, "TEST_MODE", False)
                    if test_mode:
                        market_open, market_status = True, "TEST_MODE (sin check)"
                    else:
                        market_open, market_status = trading.is_market_open(config.SYMBOL)

                    market_cache = {}
                    selected_entry = self._get_selected_strategy_entry()

                    for entry in enabled_entries:
                        timeframe_value = self._strategy_timeframe_value(entry, fallback=config.TIMEFRAME)
                        if timeframe_value is None:
                            timeframe_value = mt5.TIMEFRAME_M1

                        if timeframe_value not in market_cache:
                            market_cache[timeframe_value] = self._build_market_dataframe(
                                timeframe_value, config.BARS_HISTORY
                            )

                        base_df = market_cache.get(timeframe_value)
                        if base_df is None or len(base_df) < 2:
                            entry["last_error"] = "No hay suficientes velas"
                            entry["last_run_at"] = datetime.now().strftime("%H:%M:%S")
                            continue

                        strategy_df = self._apply_strategy_processing_for_entry(entry, base_df.copy())
                        entry["last_df"] = strategy_df
                        entry["last_run_at"] = datetime.now().strftime("%H:%M:%S")
                        entry["last_market_status"] = market_status
                        entry["last_error"] = ""

                        signal = self._get_strategy_signal_for_entry(entry, strategy_df, verbose=False)
                        entry["last_signal"] = signal

                        if signal != "none" and market_open:
                            self.log_message(f"[{entry['label']}] Senal detectada: {signal.upper()}")
                            action_info = trading.apply_signal(
                                config.SYMBOL,
                                signal,
                                config.LOT,
                                config.SL_POINTS,
                                config.TP_POINTS,
                                int(entry.get("magic_number") or config.MAGIC_NUMBER),
                                timeframe_value=timeframe_value
                            )
                            if action_info:
                                action_info["strategy"] = entry.get("key", "")
                                self.update_last_action_ui(action_info)
                        elif signal != "none":
                            self.log_message(f"[{entry['label']}] Skip: mercado cerrado ({market_status})")

                    display_df = None
                    if isinstance(selected_entry, dict):
                        display_df = selected_entry.get("last_df")

                    if display_df is None and isinstance(selected_entry, dict):
                        timeframe_value = self._strategy_timeframe_value(selected_entry, fallback=config.TIMEFRAME)
                        if timeframe_value is None:
                            timeframe_value = mt5.TIMEFRAME_M1
                        if timeframe_value not in market_cache:
                            market_cache[timeframe_value] = self._build_market_dataframe(
                                timeframe_value, config.BARS_HISTORY
                            )
                        base_df = market_cache.get(timeframe_value)
                        if base_df is not None and len(base_df) > 1:
                            display_df = self._apply_strategy_processing_for_entry(
                                selected_entry, base_df.copy()
                            )
                            selected_entry["last_df"] = display_df

                    if display_df is not None and len(display_df) > 1:
                        self.price_data = display_df
                        self.update_chart(display_df, strategy_entry=selected_entry)
                        self.update_tci_chart(display_df)

                    self.update_balance()
                    self.update_quotes()
                    self._render_strategy_panel()
                    
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
        # Para peques: esta funcion sirve para ejecutar el proceso completo.
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
    # Para peques: esta funcion sirve para arrancar todo el programa.
    """Función principal."""
    app = TradingBotGUI()
    app.run()


if __name__ == "__main__":
    main()
