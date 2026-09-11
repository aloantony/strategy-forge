# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
Interfaz gráfica del Bot de Trading usando Lightweight Charts (TradingView).
Gráficos profesionales, fluidos y con el mismo aspecto que TradingView.
"""

from lightweight_charts import Chart
from lightweight_charts.util import parse_event_message
import pandas as pd
import numpy as np
from backend.brokers.mt5_import import mt5
import threading
import time
import asyncio
import queue
import copy
import sys
import io
import importlib
import importlib.util
import os
import re
import base64
import zlib
from pathlib import Path
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import unquote

from backend.core import config
from backend.brokers.mt5 import connection as mt5_connection
from backend.data import data_feed
from backend.data.mt5_data_feed import get_rates_df as mt5_get_rates_df
from backend.brokers.mt5 import trading
from backend.application import BacktestService
from backend.brokers.mt5.adapter import MT5BrokerAdapter
from backend.analytics import trade_history
from backend.strategy.runtime import (
    apply_mtf_strategy_processing as runtime_apply_mtf_strategy_processing,
    apply_strategy_processing as runtime_apply_strategy_processing,
    build_timeframe_frames as runtime_build_timeframe_frames,
    get_strategy_signal_payload_mtf as runtime_get_strategy_signal_payload_mtf,
    get_strategy_signal_payload as runtime_get_strategy_signal_payload,
    get_strategy_timeframe as runtime_get_strategy_timeframe,
    lowest_timeframe_label as runtime_lowest_timeframe_label,
    normalize_signal as runtime_normalize_signal,
    normalize_signal_payload as runtime_normalize_signal_payload,
    resolve_timeframe_value as runtime_resolve_timeframe_value,
    timeframe_label as runtime_timeframe_label,
    timeframe_to_minutes as runtime_timeframe_to_minutes,
)


def _patch_lightweight_charts_js_worker():
    # esta funcion sirve para evitar que un error JS mate el worker de lightweight_charts.
    """Parche defensivo para errores JS sin line/column en lightweight_charts."""
    try:
        import lightweight_charts.chart as lw_chart_module
        from webview.errors import JavascriptException as WebviewJavascriptException
    except Exception:
        return

    pywv_cls = getattr(lw_chart_module, "PyWV", None)
    if pywv_cls is None:
        return
    if getattr(pywv_cls, "_safe_js_error_patch", False):
        return

    original_loop = pywv_cls.loop

    def patched_loop(self):
        while getattr(self, "is_alive", False):
            try:
                return original_loop(self)
            except KeyError as exc:
                missing_key = str(exc).strip("'\"")
                if missing_key in {"line", "column"}:
                    continue
                raise
            except WebviewJavascriptException as exc:
                # Error conocido en sync de crosshair cuando una serie queda sin valor.
                if "Value is null" in str(exc):
                    continue
                raise

    pywv_cls.loop = patched_loop
    pywv_cls._safe_js_error_patch = True

# Configurar stdout para UTF-8
try:
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except:
    pass


class TradingBotGUI:
    # esta clase controla la interfaz del bot (grafico, botones y paneles).
    """
    Interfaz gráfica del bot de trading usando Lightweight Charts.
    """
    
    def __init__(self):
        # esta funcion sirve para preparar todo al inicio.
        # Estado del bot
        self.bot_running = False
        self._mt5_available = False
        self.bot_thread = None
        self.stop_event = threading.Event()
        
        # Datos
        self.price_data = None
        self.view_period = "1D"
        self.current_timeframe = "M1"
        self.last_action_info = None
        self._action_tooltip_ready = False
        self._current_aggregate_risk_pct = 0.0
        self.action_markers = []
        # Handles de dibujos sobre el gráfico (líneas SL/TP y conectores entrada↔salida).
        self._level_line_handles = []
        self._trade_link_handles = []
        # Máximo de conectores entrada↔salida a dibujar (evita clutter/coste).
        self.max_trade_links = getattr(config, "MAX_TRADE_LINKS", 30)
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
        self._strategy_selection_seq = 0

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
        self.builder_preview_active = False
        self.builder_preview_entry = None
        self._strategy_builder_module_cache = None
        self.backtest_thread = None
        self.comparison_thread = None
        self.backtest_state = {
            "running": False,
            "error": "",
            "result": None,
            "form": {},
            "comparison_running": False,
            "comparison_result":  None,
            "comparison_error":   "",
        }
        self._init_strategy_registry()
        self._broker = MT5BrokerAdapter()
        self._backtest_service = BacktestService()

        _patch_lightweight_charts_js_worker()
        
        # Crear gráfico principal
        self.chart = Chart(
            toolbox=False,
            inner_width=0.78,
            inner_height=0.7,
            maximize=True
        )
        
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
        # esta funcion sirve para iniciar registro de estrategias.
        """Inicializa el registro de estrategias disponibles."""
        self.strategy_registry = {}
        raw_cfg_key = str(getattr(config, "STRATEGY_KEY", "") or "").strip()
        cfg_key = self._slugify(raw_cfg_key) if raw_cfg_key else ""
        cfg_module = str(getattr(config, "STRATEGY_MODULE", "") or "").strip()
        if cfg_module:
            custom_key = self._slugify(cfg_key or cfg_module)
            if custom_key not in self.strategy_registry:
                self._register_strategy(custom_key, cfg_key or custom_key, cfg_module)
            cfg_key = custom_key

        # Descubre estrategias adicionales guardadas en la carpeta strategies/
        self._sync_strategy_registry_from_disk(load_entries=False, force=True)
        default_key = cfg_key if cfg_key in self.strategy_registry else ""
        if not default_key and self.strategy_registry:
            default_key = next(iter(self.strategy_registry.keys()))

        active_from_config = getattr(config, "ACTIVE_STRATEGIES", None)
        if isinstance(active_from_config, (list, tuple, set)):
            requested_active = [self._slugify(str(k)) for k in active_from_config if str(k).strip()]
        else:
            requested_active = [default_key] if default_key else []

        active_keys = [k for k in requested_active if k in self.strategy_registry]
        if not active_keys and default_key:
            active_keys = [default_key]

        for key, entry in self.strategy_registry.items():
            self._load_strategy_entry(entry)
            entry["enabled"] = key in active_keys
        config.ACTIVE_STRATEGIES = list(active_keys)

        if default_key:
            self._set_strategy_by_key(default_key, refresh=False, sync_ui=False)
            return

        self.current_strategy_key = None
        self.strategy_module = None
        self.strategy_timeframe = None
        self.timeframe_locked = False
        config.STRATEGY_KEY = ""
        config.STRATEGY_MODULE = ""

    def _register_strategy(self, key: str, label: str, module_ref: str):
        # esta funcion sirve para registrar una estrategia.
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
            "last_signal_reason": "",
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
        # esta funcion sirve para calcular el numero magico de una estrategia.
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
        # esta funcion sirve para cargar una estrategia del registro.
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

        if not hasattr(module, "get_last_signal") and not hasattr(module, "get_last_signal_payload"):
            entry["module_obj"] = None
            entry["last_error"] = "La estrategia no define get_last_signal() ni get_last_signal_payload()."
            self.log_message(
                f"Estrategia inválida {entry.get('label', '')}: "
                "falta get_last_signal() o get_last_signal_payload()."
            )
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
        # esta funcion sirve para obtener una estrategia del registro.
        resolved_key = self._resolve_strategy_key(key)
        if not resolved_key:
            return None
        return self.strategy_registry.get(resolved_key)

    def _resolve_strategy_key(self, raw_key: str) -> str:
        # esta funcion sirve para normalizar una clave de estrategia recibida desde la interfaz.
        candidate = unquote(str(raw_key or "")).strip()
        if not candidate:
            return ""

        if candidate in self.strategy_registry:
            return candidate

        slug_candidate = self._slugify(candidate)
        if slug_candidate in self.strategy_registry:
            return slug_candidate

        lower_candidate = candidate.lower()
        for key, entry in self.strategy_registry.items():
            label = str(entry.get("label") or "")
            module_ref = str(entry.get("module") or "")
            if lower_candidate == label.lower():
                return key
            if self._slugify(label) == slug_candidate:
                return key
            if self._strategy_module_stem(module_ref) == lower_candidate:
                return key

        return ""

    def _get_selected_strategy_entry(self):
        # esta funcion sirve para obtener la estrategia seleccionada.
        preview_entry = self._get_builder_preview_entry()
        if preview_entry:
            return preview_entry
        entry = self._get_strategy_entry(self.current_strategy_key or "")
        if entry:
            return entry
        if self.strategy_registry:
            return next(iter(self.strategy_registry.values()))
        return None

    def _get_enabled_strategy_entries(self):
        # esta funcion sirve para obtener las estrategias activas.
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
        # esta funcion sirve para activar o desactivar una estrategia.
        resolved_key = self._resolve_strategy_key(key)
        entry = self.strategy_registry.get(resolved_key) if resolved_key else None
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
        # esta funcion sirve para obtener la carpeta de estrategias.
        base_dir = getattr(config, "STRATEGY_DIR", "strategies")
        if not os.path.isabs(base_dir):
            base_dir = os.path.join(os.path.dirname(__file__), base_dir)
        os.makedirs(base_dir, exist_ok=True)
        return base_dir

    def _sanitize_strategy_filename(self, filename: str) -> str:
        # esta funcion sirve para limpiar el nombre del archivo de estrategia.
        name = os.path.basename(filename or "").strip()
        name = name.replace(" ", "_")
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
        if not name:
            name = "strategy.py"
        if not name.lower().endswith(".py"):
            name = f"{name}.py"
        return name

    def _save_strategy_file(self, filename: str, content: bytes):
        # esta funcion sirve para guardar un archivo de estrategia.
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
        # esta funcion sirve para crear nombre corto.
        text = (text or "").strip().lower()
        text = re.sub(r"[^a-z0-9_]+", "_", text)
        text = text.strip("_")
        return text or "strategy"

    def _strategy_builder_name(self, key: str) -> str:
        # esta funcion sirve para obtener el nombre "builder" sin el prefijo strategy_.
        # El key del registro puede venir como "strategy_<name>" (stem del fichero) o "<name>";
        # los companions del Builder viven como strategy_<name>.json/.py.
        key = (key or "").strip()
        return key[len("strategy_"):] if key.startswith("strategy_") else key

    def _get_strategy_payload(self):
        # esta funcion sirve para armar la lista de estrategias para la interfaz.
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
                reason = str(entry.get("last_signal_reason") or "").strip()
                if reason:
                    short_reason = reason if len(reason) <= 46 else (reason[:43].rstrip() + "...")
                    status_parts.append(f"motivo: {short_reason}")
            market_status = (entry.get("last_market_status") or "").strip()
            if market_status and self.bot_running:
                status_parts.append(market_status)
            error_text = (entry.get("last_error") or "").strip()
            if error_text:
                status_parts.append(f"error: {error_text}")

            strategy_dir = self._get_strategy_dir()
            json_path = os.path.join(strategy_dir, f"strategy_{self._strategy_builder_name(entry['key'])}.json")
            has_config = os.path.isfile(json_path)

            params_schema = entry.get("params_schema")
            has_params = isinstance(params_schema, dict) and len(params_schema) > 0

            payload.append({
                "key": entry["key"],
                "label": entry["label"],
                "module": entry["module"],
                "enabled": bool(entry.get("enabled")),
                "timeframe": entry.get("timeframe_label") or (self._timeframe_label(config.TIMEFRAME) or self.current_timeframe or ""),
                "magic": int(entry.get("magic_number") or 0),
                "status": " | ".join(status_parts),
                "last_run": entry.get("last_run_at") or "",
                "has_config": has_config,
                "has_params": has_params,
            })
        return payload

    def _get_backtest_strategy_options(self):
        options = []
        for entry in self.strategy_registry.values():
            if entry.get("module_obj") is None:
                self._load_strategy_entry(entry)
            options.append({
                "key": entry["key"],
                "label": entry["label"],
                "timeframe": entry.get("timeframe_label") or "",
                "disabled": entry.get("module_obj") is None,
            })
        return options

    def _get_backtest_symbol_options(self):
        symbols = self.get_enabled_symbols(limit=50)
        if config.SYMBOL and config.SYMBOL not in symbols:
            symbols.insert(0, config.SYMBOL)
        return symbols

    def _get_backtest_preset_ranges(self):
        today = datetime.now().date()
        ytd_start = datetime(today.year, 1, 1).date()

        def _fmt(day_value):
            return day_value.strftime("%Y-%m-%d")

        return {
            "1M": {"start": _fmt(today - timedelta(days=30)), "end": _fmt(today)},
            "3M": {"start": _fmt(today - timedelta(days=90)), "end": _fmt(today)},
            "6M": {"start": _fmt(today - timedelta(days=180)), "end": _fmt(today)},
            "YTD": {"start": _fmt(ytd_start), "end": _fmt(today)},
            "1Y": {"start": _fmt(today - timedelta(days=365)), "end": _fmt(today)},
        }

    def _get_backtest_default_balance(self) -> str:
        try:
            account = mt5.account_info()
        except Exception:
            account = None
        balance = getattr(account, "balance", None) if account is not None else None
        if balance is None:
            balance = 10000.0
        return f"{float(balance):.2f}"

    def _get_backtest_form_state(self):
        form = dict(self.backtest_state.get("form") or {})
        strategy_options = self._get_backtest_strategy_options()
        symbols = self._get_backtest_symbol_options()
        presets = self._get_backtest_preset_ranges()

        valid_strategy_keys = [item["key"] for item in strategy_options if not item.get("disabled")]
        all_strategy_keys = [item["key"] for item in strategy_options]
        strategy_key = form.get("strategy_key") if form.get("strategy_key") in all_strategy_keys else ""
        if not strategy_key:
            strategy_key = valid_strategy_keys[0] if valid_strategy_keys else (all_strategy_keys[0] if all_strategy_keys else "")

        symbol = str(form.get("symbol") or "").strip()
        if symbol not in symbols:
            symbol = config.SYMBOL if config.SYMBOL else (symbols[0] if symbols else "")

        preset = str(form.get("preset") or "1M").upper()
        if preset not in presets:
            preset = "1M"

        start_date = str(form.get("start_date") or presets[preset]["start"])
        end_date = str(form.get("end_date") or presets[preset]["end"])
        initial_balance = str(form.get("initial_balance") or self._get_backtest_default_balance())

        data_source = str(form.get("data_source") or "mt5").lower()
        if data_source not in ("mt5", "dukascopy"):
            data_source = "mt5"

        form = {
            "strategy_key": strategy_key,
            "symbol": symbol,
            "preset": preset,
            "start_date": start_date,
            "end_date": end_date,
            "initial_balance": initial_balance,
            "data_source": data_source,
        }
        self.backtest_state["form"] = form
        return form

    @staticmethod
    def _check_dukascopy_available() -> bool:
        return BacktestService.dukascopy_available()

    def _get_backtest_payload(self):
        form = self._get_backtest_form_state()
        entry = self._get_strategy_entry(form.get("strategy_key", ""))
        timeframe_value = self._strategy_timeframe_value(entry, fallback=None)
        timeframe_text = self._timeframe_label(timeframe_value) if timeframe_value is not None else "--"
        return {
            "handler": getattr(self, "side_panel_handler", ""),
            "running": bool(self.backtest_state.get("running")),
            "error": str(self.backtest_state.get("error") or ""),
            "result": self.backtest_state.get("result"),
            "form": form,
            "timeframe": timeframe_text or "--",
            "strategies": self._get_backtest_strategy_options(),
            "symbols": self._get_backtest_symbol_options(),
            "presets": self._get_backtest_preset_ranges(),
            "comparison_running": bool(self.backtest_state.get("comparison_running")),
            "dukascopy_available": self._check_dukascopy_available(),
        }

    def _render_backtest_panel(self):
        handler = getattr(self, "side_panel_handler", None)
        if not handler or not getattr(self, "chart", None):
            return
        payload = self._get_backtest_payload()
        payload["handler"] = handler

        result_raw = payload.get("result") or {}
        equity_curve = result_raw.get("equity_curve") or []
        drawdown_curve = result_raw.get("drawdown_curve") or []
        initial_balance = float(result_raw.get("initial_balance") or 10000.0)

        result_for_panel = {k: v for k, v in result_raw.items()
                            if k not in ("equity_curve", "drawdown_curve")}
        panel_payload = dict(payload)
        panel_payload["result"] = result_for_panel if result_raw else None

        panel_json = json.dumps(panel_payload, ensure_ascii=False)
        self.chart.run_script(f'''
            ;(function() {{
                const payload = {panel_json};
                if (window.renderBacktestPanel) {{
                    window.renderBacktestPanel(payload);
                }}
            }})();
        ''')

        if equity_curve or drawdown_curve:
            charts_data = {
                "equity_curve": equity_curve,
                "drawdown_curve": drawdown_curve,
                "initial_balance": initial_balance,
            }
            charts_json = json.dumps(charts_data, ensure_ascii=False)
            self.chart.run_script(f'''
                ;(function() {{
                    const chartsData = {charts_json};
                    if (window.renderBacktestCharts) {{
                        window.renderBacktestCharts(chartsData);
                    }}
                }})();
            ''')

    def _parse_backtest_date(self, value: str, *, end_of_day: bool = False) -> datetime:
        return self._backtest_service.parse_date(value, end_of_day=end_of_day)

    def _run_backtest_worker(self, request: dict, data_source=None):
        result = self._backtest_service.execute_run(request, data_source=data_source)

        self.backtest_state["running"] = False
        if result.get("status") == "success":
            self.backtest_state["error"] = ""
            self.backtest_state["result"] = result
        else:
            self.backtest_state["error"] = str(result.get("error") or "Error al ejecutar backtest")
        self._render_backtest_panel()

    def _on_backtest_run(self, json_str: str):
        json_str = (json_str or "").strip()
        if not json_str:
            self.backtest_state["error"] = "Payload de backtest vacío"
            self._render_backtest_panel()
            return

        if self.backtest_state.get("running"):
            self.backtest_state["error"] = "Ya hay un backtest en ejecución"
            self._render_backtest_panel()
            return

        try:
            payload = json.loads(json_str)
        except Exception as error:
            self.backtest_state["error"] = f"Payload de backtest inválido: {error}"
            self._render_backtest_panel()
            return

        strategy_key = str(payload.get("strategy_key") or "").strip()
        entry = self._get_strategy_entry(strategy_key)
        if not entry:
            self.backtest_state["error"] = "Estrategia de backtest no encontrada"
            self._render_backtest_panel()
            return
        if entry.get("module_obj") is None and not self._load_strategy_entry(entry):
            self.backtest_state["error"] = entry.get("last_error") or "No se pudo cargar la estrategia para backtest"
            self._render_backtest_panel()
            return

        try:
            prepared = self._backtest_service.prepare_run(payload, entry)
        except ValueError as error:
            self.backtest_state["error"] = str(error)
            self._render_backtest_panel()
            return

        self.backtest_state["form"] = prepared.form
        self.backtest_state["running"] = True
        self.backtest_state["error"] = ""

        self._render_backtest_panel()
        self.backtest_thread = threading.Thread(
            target=self._run_backtest_worker,
            args=(prepared.request, prepared.data_source),
            daemon=True,
        )
        self.backtest_thread.start()

    def _on_backtest_compare(self, json_str: str):
        json_str = (json_str or "").strip()
        if not json_str:
            self.backtest_state["comparison_error"] = "Payload de comparación vacío"
            self._render_backtest_comparison_panel()
            return

        if self.backtest_state.get("comparison_running"):
            self.backtest_state["comparison_error"] = "Ya hay una comparación en ejecución"
            self._render_backtest_comparison_panel()
            return

        try:
            payload = json.loads(json_str)
        except Exception as error:
            self.backtest_state["comparison_error"] = f"Payload de comparación inválido: {error}"
            self._render_backtest_comparison_panel()
            return

        strategy_keys = list(payload.get("strategy_keys") or [])
        if len(strategy_keys) < 2:
            self.backtest_state["comparison_error"] = "Se requieren al menos 2 estrategias para comparar"
            self._render_backtest_comparison_panel()
            return

        strategy_entries = []
        for key in strategy_keys:
            entry = self._get_strategy_entry(key)
            if not entry:
                self.backtest_state["comparison_error"] = f"Estrategia no encontrada: {key}"
                self._render_backtest_comparison_panel()
                return
            if entry.get("module_obj") is None and not self._load_strategy_entry(entry):
                self.backtest_state["comparison_error"] = (
                    entry.get("last_error") or f"No se pudo cargar: {key}"
                )
                self._render_backtest_comparison_panel()
                return
            strategy_entries.append(entry)

        try:
            prepared = self._backtest_service.prepare_comparison(payload, strategy_entries)
        except ValueError as error:
            self.backtest_state["comparison_error"] = str(error)
            self._render_backtest_comparison_panel()
            return

        self.backtest_state["comparison_running"] = True
        self.backtest_state["comparison_error"]   = ""
        self._render_backtest_comparison_panel()

        self.comparison_thread = threading.Thread(
            target=self._run_backtest_comparison_worker,
            args=(prepared.request, prepared.data_source),
            daemon=True,
        )
        self.comparison_thread.start()

    def _run_backtest_comparison_worker(self, request: dict, data_source=None):
        result = self._backtest_service.execute_comparison(request, data_source=data_source)

        self.backtest_state["comparison_running"] = False
        if result.get("status") in ("success", "partial"):
            self.backtest_state["comparison_error"]  = result.get("error") or ""
            self.backtest_state["comparison_result"] = result
        else:
            self.backtest_state["comparison_error"]  = str(result.get("error") or "Error al ejecutar comparación")
            self.backtest_state["comparison_result"] = None
        self._render_backtest_comparison_panel()

    def _on_backtest_export_csv(self):
        import csv
        result = self.backtest_state.get("result")
        if not result or result.get("status") != "success":
            self.backtest_state["error"] = "No hay resultado de backtest disponible para exportar"
            self._render_backtest_panel()
            return
        trades = result.get("trades") or []
        form = self.backtest_state.get("form") or {}
        strategy_key = str(form.get("strategy_key") or "backtest").replace("/", "-").replace("\\", "-")
        symbol = str(form.get("symbol") or "unknown").replace("/", "-").replace("\\", "-")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backtest_{strategy_key}_{symbol}_{timestamp}.csv"
        filepath = Path.home() / "Downloads" / filename
        columns = ["id", "entry_time", "exit_time", "direction", "entry_price", "exit_price",
                   "volume", "profit", "reason", "signal", "signal_reason", "mode"]
        try:
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                for i, trade in enumerate(trades):
                    writer.writerow({
                        "id": i + 1,
                        "entry_time": str(trade.get("entry_time") or ""),
                        "exit_time": str(trade.get("exit_time") or ""),
                        "direction": trade.get("direction", ""),
                        "entry_price": trade.get("entry_price", ""),
                        "exit_price": trade.get("exit_price", ""),
                        "volume": trade.get("volume", ""),
                        "profit": trade.get("profit", ""),
                        "reason": trade.get("reason", ""),
                        "signal": trade.get("signal", ""),
                        "signal_reason": trade.get("signal_reason", ""),
                        "mode": trade.get("mode", ""),
                    })
            status_msg = json.dumps(f"CSV exportado: {filename}")
            self.chart.run_script(f'''
                ;(function() {{
                    const statusEl = document.getElementById("tv-backtest-status");
                    if (statusEl) statusEl.innerText = {status_msg};
                }})();
            ''')
        except Exception as e:
            self.backtest_state["error"] = f"Error al exportar CSV: {e}"
            self._render_backtest_panel()

    def _render_backtest_comparison_panel(self):
        handler = getattr(self, "side_panel_handler", None)
        if not handler or not getattr(self, "chart", None):
            return
        payload = {
            "comparison_running": bool(self.backtest_state.get("comparison_running")),
            "comparison_result":  self.backtest_state.get("comparison_result"),
            "comparison_error":   str(self.backtest_state.get("comparison_error") or ""),
        }
        payload_json = json.dumps(payload, ensure_ascii=False)
        self.chart.run_script(f'''
            ;(function() {{
                const data = {payload_json};
                if (window.renderBacktestComparison) {{
                    window.renderBacktestComparison(data);
                }}
            }})();
        ''')

    def _get_side_panel_icons(self):
        # esta funcion sirve para obtener los iconos del panel lateral.
        return {
            "chart": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><rect x='2' y='3' width='12' height='10' rx='1.5'/><path d='M4 10 L7 7 L9 9 L12 6'/></svg>",
            "line": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><path d='M2 11 L6 7 L9 9 L14 4'/></svg>",
            "bands": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><path d='M2 4 H14'/><path d='M2 8 H14'/><path d='M2 12 H14'/></svg>",
            "trend": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><path d='M2 12 L6 8 L10 10 L14 6'/><circle cx='6' cy='8' r='1.2'/><circle cx='10' cy='10' r='1.2'/></svg>",
            "hist": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><path d='M3 12 V7'/><path d='M7 12 V5'/><path d='M11 12 V9'/><path d='M14 12 H2'/></svg>",
            "long": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><path d='M8 12 V4'/><path d='M8 4 L5 7'/><path d='M8 4 L11 7'/></svg>",
            "short": "<svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4'><path d='M8 4 V12'/><path d='M8 12 L5 9'/><path d='M8 12 L11 9'/></svg>",
        }

    _DRAWING_TOGGLE_KEYS = {"sltp", "trade_links"}

    def _get_object_tree_catalog(self):
        # esta funcion sirve para obtener el catalogo del arbol de objetos.
        return {
            "baseline": {"label": "Baseline", "icon": "line", "toggle": True, "visible": True},
            "atr_bands": {"label": "ATR Bands", "icon": "bands", "toggle": True, "visible": True},
            "supertrend": {"label": "Supertrend w/ HMA", "icon": "trend", "toggle": True, "visible": True},
            "tci": {"label": "TuTCI", "icon": "hist", "toggle": True, "visible": True},
            "sltp": {"label": "SL/TP posiciones", "icon": "line", "toggle": True, "visible": True},
            "trade_links": {"label": "Entradas↔Salidas", "icon": "line", "toggle": True, "visible": False},
        }

    def _get_default_object_tree_items(self):
        # esta funcion sirve para obtener los elementos por defecto del arbol de objetos.
        defaults = getattr(config, "OBJECT_TREE_DEFAULT_ITEMS", None)
        if isinstance(defaults, (list, tuple)) and defaults:
            return list(defaults)
        return ["baseline", "atr_bands", "supertrend", "tci"]

    def _merge_object_tree_items(self, primary, fallback):
        # esta funcion sirve para unir listas de elementos del arbol de objetos.
        combined = []
        for items in (primary, fallback):
            if not items:
                continue
            if isinstance(items, (list, tuple, set)):
                combined.extend(list(items))
            else:
                combined.append(items)
        return combined

    _LABEL_ACRONYMS = {
        "atr", "rsi", "adx", "tci", "hma", "ema", "sma", "bb", "vwap",
        "di", "macd", "ohlc", "hlc", "hl", "ma",
    }

    def _humanize_label(self, key: str) -> str:
        # esta funcion sirve para convertir una clave en etiqueta legible respetando acronimos.
        words = []
        for word in str(key or "").replace("-", "_").split("_"):
            if not word:
                continue
            words.append(word.upper() if word.lower() in self._LABEL_ACRONYMS else word.capitalize())
        return " ".join(words)

    def _normalize_object_tree_items(self, items):
        # esta funcion sirve para ordenar y limpiar elementos del arbol de objetos.
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
                item["label"] = self._humanize_label(key)
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
        # esta funcion sirve para obtener elementos del arbol segun la estrategia.
        if module is None:
            preview_entry = self._get_builder_preview_entry()
            if preview_entry is not None:
                module = preview_entry.get("module_obj")
            else:
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
        # esta funcion sirve para unir elementos del arbol de todas las estrategias activas.
        items = []
        for entry in self._get_enabled_strategy_entries():
            module = entry.get("module_obj")
            if module is None:
                continue
            items.extend(self._get_strategy_object_tree_items(module=module))
        return items

    def _build_object_tree_items(self):
        # esta funcion sirve para construir la lista final del arbol de objetos.
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

        # Toggles globales de dibujo (no son series de estrategia): SL/TP y conectores.
        catalog = self._get_object_tree_catalog()
        for key in ("sltp", "trade_links"):
            if key in seen:
                continue
            base = catalog.get(key, {})
            combined.append({
                **base,
                "key": key,
                "toggle": True,
                "visible": bool(self.indicator_state.get(key, base.get("visible", True))),
            })
        return combined

    def _apply_indicator_visibility_for_items(self, items):
        # esta funcion sirve para aplicar visibilidad de indicadores en varios elementos.
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
        # esta funcion sirve para obtener la estrategia seleccionada en el selector.
        key = (self.current_strategy_key or "").strip()
        if key and key in self.strategy_registry:
            return key
        if self.strategy_registry:
            return next(iter(self.strategy_registry.keys()))
        return ""

    def _get_strategy_data_scope_options(self, items=None):
        # esta funcion sirve para construir opciones del selector de estrategias.
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
        # esta funcion sirve para refrescar el desplegable de datos de estrategia.
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
        # esta funcion sirve para refrescar el selector de estrategia en data window.
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
        # esta funcion sirve para aplicar la estrategia elegida en el selector.
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
        # esta funcion sirve para mostrar datos de todas las estrategias activas.
        enabled_entries = self._get_enabled_strategy_entries()
        if not enabled_entries:
            self.strategy_data_all_actives = False
            self.log_message("No hay estrategias activas para mostrar en Strategy Data.")
            self._render_strategy_data_scope_selector()
            return
        self.strategy_data_all_actives = True
        self._refresh_object_tree_items()

    def _render_object_tree(self, items=None):
        # esta funcion sirve para dibujar arbol de objetos.
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
        # esta funcion sirve para refrescar los elementos del arbol de objetos.
        items = self._build_object_tree_items()
        self.object_tree_items = items
        if self.indicator_series:
            self._apply_indicator_visibility_for_items(items)
        if render:
            self._render_object_tree(items)

    def _load_strategy_module(self, module_ref: str):
        # esta funcion sirve para cargar el modulo de una estrategia.
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
        # esta funcion sirve para convertir el marco de tiempo a su valor de MT5.
        return runtime_resolve_timeframe_value(value)

    def _timeframe_label(self, timeframe_value):
        # esta funcion sirve para crear la etiqueta de texto del marco de tiempo.
        return runtime_timeframe_label(timeframe_value)

    def _get_strategy_timeframe(self, module):
        # esta funcion sirve para obtener el marco de tiempo de una estrategia.
        return runtime_get_strategy_timeframe(module)

    def _apply_strategy_timeframe(self, module_or_entry, refresh: bool = True):
        # esta funcion sirve para aplicar el marco de tiempo elegido por la estrategia.
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
        # esta funcion sirve para cambiar la estrategia seleccionada por clave.
        resolved_key = self._resolve_strategy_key(key)
        entry = self.strategy_registry.get(resolved_key) if resolved_key else None
        if not entry:
            self.log_message(f"Estrategia desconocida: {key}")
            return

        loaded_ok = self._load_strategy_entry(entry)
        self.current_strategy_key = resolved_key
        self._strategy_selection_seq = int(getattr(self, "_strategy_selection_seq", 0)) + 1
        config.STRATEGY_KEY = resolved_key
        config.STRATEGY_MODULE = entry["module"]

        if loaded_ok:
            self.strategy_module = entry.get("module_obj")
            self.log_message(f"Interfaz activa: {entry['label']} ({entry['module']})")
            self._apply_strategy_timeframe(entry, refresh=False)
            self._refresh_object_tree_items()
        else:
            self.strategy_module = None
            self.strategy_timeframe = None
            self.timeframe_locked = False
            error_text = (entry.get("last_error") or "La estrategia no cumple la API minima").strip()
            self.log_message(
                f"Estrategia no disponible para visualizar: {entry.get('label', resolved_key)} ({error_text})"
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
                const tciHost = {self.tci_chart.id} && {self.tci_chart.id}.div ? {self.tci_chart.id}.div : null;
                if (!chartHost) return;
                const rootHost = window.containerDiv || document.body;
                let overlay = document.getElementById("tv-strategy-readiness-overlay");
                if (!overlay) {{
                    overlay = document.createElement("div");
                    overlay.id = "tv-strategy-readiness-overlay";
                    overlay.className = "tv-strategy-readiness-overlay";
                    rootHost.appendChild(overlay);
                }} else if (overlay.parentElement !== rootHost) {{
                    rootHost.appendChild(overlay);
                }}

                const sidePanel = document.getElementById("tv-side-panel");
                const sideToolbar = document.getElementById("tv-side-toolbar");
                const rightInset =
                    (sidePanel ? sidePanel.getBoundingClientRect().width : 0) +
                    (sideToolbar ? sideToolbar.getBoundingClientRect().width : 0);
                overlay.style.setProperty("--tv-readiness-right-inset", Math.max(0, Math.round(rightInset)) + "px");
                const expectedMarkup = `
                    <div class="tv-strategy-readiness-card">
                        <div class="tv-strategy-readiness-badge">Strategy setup</div>
                        <div class="tv-strategy-readiness-title" id="tv-strategy-readiness-title"></div>
                        <div class="tv-strategy-readiness-subtitle" id="tv-strategy-readiness-subtitle"></div>
                        <div class="tv-strategy-readiness-error" id="tv-strategy-readiness-error"></div>
                    </div>
                `;
                if (overlay.dataset.version !== "message_v2") {{
                    overlay.innerHTML = expectedMarkup;
                    overlay.dataset.version = "message_v2";
                }}

                const applyFogToChart = (enabled) => {{
                    [chartHost, tciHost].forEach((host) => {{
                        if (!host) return;
                        const targets = host.querySelectorAll("canvas");
                        targets.forEach((node) => {{
                            if (!(node instanceof HTMLElement)) return;
                            node.style.transition = "filter 0.2s ease";
                            if (enabled) {{
                                node.style.filter = "blur(2.8px) saturate(0.78) brightness(0.74)";
                            }} else {{
                                node.style.filter = "";
                            }}
                        }});
                    }});
                }};

                if (!payload || !payload.visible) {{
                    overlay.classList.remove("open");
                    applyFogToChart(false);
                    return;
                }}
                applyFogToChart(true);
                overlay.classList.add("open");

                const titleEl = overlay.querySelector("#tv-strategy-readiness-title");
                const subtitleEl = overlay.querySelector("#tv-strategy-readiness-subtitle");
                const errorEl = overlay.querySelector("#tv-strategy-readiness-error");

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
            }})();
        ''')

    def _add_strategy_from_input(self, label: str, module_ref: str):
        # esta funcion sirve para agregar una estrategia escrita por el usuario.
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
        # esta funcion sirve para agregar una estrategia arrastrando un archivo.
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
        # esta funcion sirve para dibujar el panel de estrategias.
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
                if (window.renderBuilderButtons) {{
                    window.renderBuilderButtons(payload);
                }}
            }})();
        ''')
        self._render_strategy_data_scope_selector()
        self._render_data_window_strategy_selector()
        self._render_backtest_panel()
        self._sync_strategy_status_ui()
        self._render_strategy_readiness_overlay()

    def _sync_strategy_status_ui(self):
        # esta funcion sirve para sincronizar en pantalla el estado de estrategias.
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

    def _build_strategy_builder_ui(self):
        # esta funcion sirve para construir la interfaz del constructor de estrategias.
        self.chart.run_script('''
            ;(function() {
                if (document.getElementById("tv-builder-form-view")) return;

                // --- CSS injection ---
                const style = document.createElement("style");
                style.textContent = `
                    #tv-builder-form-view { display: none; flex-direction: column; height: 100%; overflow: hidden; }
                    .tv-builder-form { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: var(--panel-bg, #1a1a2e); color: var(--text-color, #e0e0e0); font-size: 12px; }
                    .tv-builder-header { display: flex; align-items: center; justify-content: space-between; padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.1); flex-shrink: 0; }
                    .tv-builder-title { font-weight: 600; font-size: 13px; }
                    .tv-builder-cancel-btn { background: transparent; border: 1px solid rgba(255,255,255,0.2); color: #e0e0e0; border-radius: 4px; padding: 3px 10px; cursor: pointer; font-size: 11px; }
                    .tv-builder-cancel-btn:hover { background: rgba(255,255,255,0.08); }
                    .tv-builder-body { flex: 1; overflow-y: auto; padding: 8px 10px; }
                    .tv-builder-section { margin-bottom: 12px; }
                    .tv-builder-section label { display: block; font-size: 11px; color: rgba(255,255,255,0.55); margin-bottom: 2px; margin-top: 6px; }
                    .tv-builder-section input[type=text], .tv-builder-section select { width: 100%; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.15); color: #e0e0e0; border-radius: 4px; padding: 4px 6px; font-size: 12px; box-sizing: border-box; }
                    .tv-builder-section select, .tv-builder-col-sel, .tv-builder-op-sel { color-scheme: dark; }
                    .tv-builder-section select option, .tv-builder-col-sel option, .tv-builder-op-sel option { background: #1b2033; color: #eef2ff; }
                    .tv-builder-section-title { font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: rgba(255,255,255,0.45); margin-bottom: 6px; margin-top: 4px; }
                    .tv-builder-indicator-picker { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }
                    .tv-builder-indicator-picker select { flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.15); color: #e0e0e0; border-radius: 4px; padding: 4px 6px; font-size: 12px; }
                    .tv-builder-indicator-picker button { background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); color: #e0e0e0; border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 12px; flex-shrink: 0; }
                    .tv-builder-indicator-picker button:hover { background: rgba(255,255,255,0.18); }
                    .tv-builder-indicator-list { display: flex; flex-direction: column; gap: 4px; }
                    .tv-builder-indicator-row { display: flex; align-items: center; gap: 5px; background: rgba(255,255,255,0.04); border-radius: 4px; padding: 4px 6px; }
                    .tv-builder-indicator-label { font-size: 11px; font-weight: 600; min-width: 60px; }
                    .tv-builder-indicator-row input[type=number] { width: 60px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.15); color: #e0e0e0; border-radius: 4px; padding: 3px 5px; font-size: 11px; }
                    .tv-builder-indicator-row button { background: transparent; border: none; color: rgba(255,255,255,0.4); cursor: pointer; font-size: 12px; padding: 0 4px; margin-left: auto; }
                    .tv-builder-indicator-row button:hover { color: #e0e0e0; }
                    .tv-builder-tree { display: flex; flex-direction: column; gap: 4px; }
                    .tv-builder-condition-group { border-left: 2px solid rgba(255,255,255,0.15); padding-left: 8px; margin-left: 4px; }
                    .tv-builder-group-header { display: flex; align-items: center; gap: 5px; margin-bottom: 4px; flex-wrap: wrap; }
                    .tv-builder-group-type { background: rgba(74,144,226,0.25); border: 1px solid rgba(74,144,226,0.5); color: #7ab4f5; border-radius: 3px; padding: 2px 7px; cursor: pointer; font-size: 11px; font-weight: 600; }
                    .tv-builder-group-type:hover { background: rgba(74,144,226,0.4); }
                    .tv-builder-add-cond-btn, .tv-builder-add-group-btn { background: transparent; border: 1px solid rgba(255,255,255,0.2); color: rgba(255,255,255,0.65); border-radius: 3px; padding: 2px 7px; cursor: pointer; font-size: 11px; }
                    .tv-builder-add-cond-btn:hover, .tv-builder-add-group-btn:hover { background: rgba(255,255,255,0.08); }
                    .tv-builder-add-group-btn:disabled { opacity: 0.35; cursor: not-allowed; }
                    .tv-builder-group-children { display: flex; flex-direction: column; gap: 4px; }
                    .tv-builder-condition-leaf { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
                    .tv-builder-col-sel, .tv-builder-op-sel { min-width: 112px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.15); color: #e0e0e0; border-radius: 3px; padding: 2px 4px; font-size: 11px; }
                    .tv-builder-right-type { background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.2); color: #e0e0e0; border-radius: 3px; padding: 2px 6px; cursor: pointer; font-size: 10px; }
                    .tv-builder-num-inp { width: 70px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.15); color: #e0e0e0; border-radius: 3px; padding: 2px 4px; font-size: 11px; }
                    .tv-builder-remove-btn { background: transparent; border: none; color: rgba(255,255,255,0.35); cursor: pointer; font-size: 12px; padding: 0 3px; }
                    .tv-builder-remove-btn:hover { color: #e05c5c; }
                    .tv-builder-payload-row { display: grid; grid-template-columns: 1fr 80px 1fr 24px; gap: 4px; align-items: center; margin-bottom: 4px; }
                    .tv-builder-payload-row input, .tv-builder-payload-row select { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.15); color: #e0e0e0; border-radius: 3px; padding: 3px 5px; font-size: 11px; width: 100%; box-sizing: border-box; }
                    .tv-builder-payload-row input::placeholder { color: rgba(255,255,255,0.3); }
                    .tv-builder-add-payload-btn { background: transparent; border: 1px dashed rgba(255,255,255,0.2); color: rgba(255,255,255,0.45); border-radius: 3px; padding: 3px 8px; cursor: pointer; font-size: 11px; margin-top: 4px; width: 100%; }
                    .tv-builder-add-payload-btn:hover { border-color: rgba(74,144,226,0.5); color: #7ab4f5; }
                    .tv-builder-footer { padding: 8px 10px; border-top: 1px solid rgba(255,255,255,0.1); flex-shrink: 0; }
                    .tv-builder-error { background: rgba(220,50,50,0.15); border: 1px solid rgba(220,50,50,0.4); color: #f08080; border-radius: 4px; padding: 5px 8px; font-size: 11px; margin-bottom: 6px; }
                    .tv-builder-save-btn { width: 100%; background: rgba(74,144,226,0.3); border: 1px solid rgba(74,144,226,0.6); color: #7ab4f5; border-radius: 4px; padding: 6px 0; cursor: pointer; font-size: 13px; font-weight: 600; }
                    .tv-builder-save-btn:hover { background: rgba(74,144,226,0.5); }
                    .tv-builder-new-btn { width: 100%; background: rgba(74,144,226,0.2); border: 1px solid rgba(74,144,226,0.4); color: #7ab4f5; border-radius: 4px; padding: 6px 0; cursor: pointer; font-size: 12px; margin-top: 8px; }
                    .tv-builder-new-btn:hover { background: rgba(74,144,226,0.35); }
                    .tv-builder-edit-btn { background: rgba(74,144,226,0.18); border: 1px solid rgba(74,144,226,0.45); color: #9fc2ff; border-radius: 4px; padding: 3px 8px; cursor: pointer; font-size: 11px; font-weight: 600; flex-shrink: 0; }
                    .tv-builder-edit-btn:hover { background: rgba(74,144,226,0.4); color: #ffffff; }
                    #tv-strategy-panel.builder-mode > :not(#tv-builder-form-view) { display: none !important; }
                    #tv-strategy-panel.builder-mode > #tv-builder-form-view { display: flex; flex-direction: column; }
                    .tv-builder-vwap-d1-warn { color: #f0c040; font-size: 10px; margin-top: 4px; }
                    #tv-risk-widget { display: flex; align-items: center; gap: 6px; padding: 6px 10px 6px 10px; font-size: 12px; border-bottom: 1px solid rgba(255,255,255,0.07); margin-bottom: 4px; flex-shrink: 0; }
                    .tv-risk-label { color: rgba(255,255,255,0.45); font-size: 11px; }
                    #tv-risk-value { font-weight: 600; color: #4CAF50; min-width: 36px; }
                    .tv-risk-sep { color: rgba(255,255,255,0.3); font-size: 11px; }
                `;
                document.head.appendChild(style);

                // --- "Nueva estrategia" button ---
                const strategyPanel = document.getElementById("tv-strategy-panel");
                if (!strategyPanel) return;
                const newBtn = document.createElement("button");
                newBtn.id = "tv-builder-new-btn";
                newBtn.type = "button";
                newBtn.className = "tv-builder-new-btn";
                newBtn.innerText = "Nueva estrategia";
                newBtn.addEventListener("click", () => {
                    window.callbackFunction(window._strategyBuilderState._handler + "_~_strategy_builder_new");
                });
                strategyPanel.appendChild(newBtn);

                // --- Builder form view ---
                const formView = document.createElement("div");
                formView.id = "tv-builder-form-view";
                formView.className = "tv-builder-form";
                formView.innerHTML = `
                    <div class="tv-builder-header">
                        <span class="tv-builder-title" id="tv-builder-title">Nueva estrategia</span>
                        <button type="button" id="tv-builder-cancel" class="tv-builder-cancel-btn">Cancelar</button>
                    </div>
                    <div class="tv-builder-body">
                        <div class="tv-builder-section">
                            <label>Nombre visible</label>
                            <input id="tv-builder-display-name" type="text" placeholder="Mi Estrategia" />
                            <label>Id (autogenerado)</label>
                            <input id="tv-builder-name" type="text" placeholder="mi_estrategia" disabled />
                            <label>Temporalidad</label>
                            <select id="tv-builder-timeframe">
                                <option value="M1">M1</option>
                                <option value="M2">M2</option>
                                <option value="M3">M3</option>
                                <option value="M5">M5</option>
                                <option value="M10">M10</option>
                                <option value="M15">M15</option>
                                <option value="M30">M30</option>
                                <option value="H1">H1</option>
                                <option value="H4">H4</option>
                                <option value="D1">D1</option>
                            </select>
                        </div>
                        <div class="tv-builder-section">
                            <div class="tv-builder-section-title">Indicadores</div>
                            <div class="tv-builder-indicator-picker">
                                <select id="tv-builder-indicator-type">
                                    <option value="EMA">EMA</option>
                                    <option value="RSI">RSI</option>
                                    <option value="BB">Bollinger Bands</option>
                                    <option value="DONCHIAN">Donchian Channel</option>
                                    <option value="ATR">ATR</option>
                                    <option value="VORTEX">Vortex</option>
                                    <option value="ADX_DI">ADX + DI</option>
                                    <option value="VWAP">VWAP</option>
                                    <option value="VOLUME_RATIO">Volume Ratio</option>
                                    <option value="SMA">SMA</option>
                                    <option value="HMA">HMA (pre-computed)</option>
                                    <option value="SUPERTREND">Supertrend (pre-computed)</option>
                                    <option value="TCI">TCI (pre-computed)</option>
                                </select>
                                <button type="button" id="tv-builder-add-indicator">Añadir</button>
                            </div>
                            <div id="tv-builder-indicator-list" class="tv-builder-indicator-list"></div>
                        </div>
                        <div class="tv-builder-section">
                            <div class="tv-builder-section-title">Condición de Compra</div>
                            <div id="tv-builder-buy-tree" class="tv-builder-tree"></div>
                        </div>
                        <div class="tv-builder-section">
                            <div class="tv-builder-section-title">Condición de Venta</div>
                            <div id="tv-builder-sell-tree" class="tv-builder-tree"></div>
                        </div>
                        <div class="tv-builder-section">
                            <div class="tv-builder-section-title">Payload extra (opcional)</div>
                            <div id="tv-builder-payload-list"></div>
                            <button type="button" id="tv-builder-add-payload" class="tv-builder-add-payload-btn">+ Añadir campo</button>
                        </div>
                    </div>
                    <div class="tv-builder-footer">
                        <div id="tv-builder-error" class="tv-builder-error" style="display:none"></div>
                        <button type="button" id="tv-builder-save" class="tv-builder-save-btn">Guardar</button>
                    </div>
                `;
                strategyPanel.appendChild(formView);

                // --- Global builder state ---
                window._strategyBuilderState = {
                    is_new: true,
                    magic_number: 0,
                    editing_key: null,
                    buy_tree: null,
                    sell_tree: null,
                    indicators: [],
                    payload_extra_fields: [],
                    _handler: "",
                    _previewTimer: 0
                };

                window._builderClone = (value) => JSON.parse(JSON.stringify(value === undefined ? null : value));

                // Espejo de sanitize_name() del backend (sin el sufijo anti-colisión, que resuelve el backend).
                window._builderSlugify = (displayName) => {
                    let s = (displayName || "").toLowerCase();
                    s = s.replace(/[^a-z0-9_]/g, "_");
                    s = s.replace(/_+/g, "_");
                    s = s.replace(/^_+|_+$/g, "");
                    if (!s || /^[0-9]/.test(s)) {
                        s = "strategy_" + s;
                    }
                    return s;
                };

                window._builderCollectConfig = (strictMode) => {
                    const state = window._strategyBuilderState || {};
                    const nameEl = document.getElementById("tv-builder-name");
                    const displayNameEl = document.getElementById("tv-builder-display-name");
                    const timeframeEl = document.getElementById("tv-builder-timeframe");
                    const strict = !!strictMode;

                    let name = ((nameEl && nameEl.value) || "").trim();
                    if (!strict && !/^[a-z][a-z0-9_]*$/.test(name)) {
                        name = "builder_preview";
                    }

                    const displayNameRaw = ((displayNameEl && displayNameEl.value) || "").trim();
                    const displayName = strict ? displayNameRaw : (displayNameRaw || name || "Builder Preview");

                    return {
                        schema_version: 1,
                        name,
                        display_name: displayName,
                        description: "",
                        timeframe: ((timeframeEl && timeframeEl.value) || "M1").trim() || "M1",
                        magic_number: Number.isInteger(state.magic_number) ? state.magic_number : 10000,
                        indicators: window._builderClone(state.indicators || []),
                        buy_condition: window._builderClone(state.buy_tree || { type: "AND", children: [] }),
                        sell_condition: window._builderClone(state.sell_tree || { type: "AND", children: [] }),
                        payload_extra_fields: window._builderClone(state.payload_extra_fields || []),
                        _is_new: !!state.is_new,
                        _editing_key: state.editing_key || null
                    };
                };

                window._builderSchedulePreview = () => {
                    const state = window._strategyBuilderState;
                    if (!state || !state._handler || !window.callbackFunction) return;
                    if (state._previewTimer) {
                        window.clearTimeout(state._previewTimer);
                    }
                    state._previewTimer = window.setTimeout(() => {
                        state._previewTimer = 0;
                        const json = JSON.stringify(window._builderCollectConfig(false));
                        window.callbackFunction(state._handler + "_~_strategy_builder_preview;;;" + encodeURIComponent(json));
                    }, 120);
                };

                // --- openStrategyBuilder(config) ---
                window.openStrategyBuilder = (config) => {
                    window._strategyBuilderState.is_new = !!config.is_new;
                    window._strategyBuilderState.magic_number = config.magic_number || 0;
                    window._strategyBuilderState.editing_key = config.editing_key || null;
                    window._strategyBuilderState.indicators = config.indicators ? JSON.parse(JSON.stringify(config.indicators)) : [];
                    window._strategyBuilderState.buy_tree = config.buy_condition || { "type": "AND", "children": [] };
                    window._strategyBuilderState.sell_tree = config.sell_condition || { "type": "AND", "children": [] };
                    window._strategyBuilderState.payload_extra_fields = config.payload_extra_fields ? JSON.parse(JSON.stringify(config.payload_extra_fields)) : [];
                    window._strategyBuilderState._handler = config.handler || window._strategyBuilderState._handler;
                    if (window._strategyBuilderState._previewTimer) {
                        window.clearTimeout(window._strategyBuilderState._previewTimer);
                        window._strategyBuilderState._previewTimer = 0;
                    }

                    document.getElementById("tv-builder-title").innerText = config.is_new ? "Nueva estrategia" : ("Editar: " + (config.display_name || config.name || ""));
                    const nameInput = document.getElementById("tv-builder-name");
                    // El id es siempre de solo lectura: se deriva del nombre visible (sanitize_name en backend).
                    nameInput.value = config.name || window._builderSlugify(config.display_name || "");
                    nameInput.disabled = true;
                    document.getElementById("tv-builder-display-name").value = config.display_name || "";
                    document.getElementById("tv-builder-timeframe").value = config.timeframe || "M1";

                    window._builderRenderIndicators();
                    window._builderRenderTree("buy");
                    window._builderRenderTree("sell");
                    window._builderRenderPayloadFields();
                    window.setBuilderError("");

                    strategyPanel.classList.add("builder-mode");
                };

                // --- closeStrategyBuilder() ---
                window.closeStrategyBuilder = () => {
                    if (window._strategyBuilderState && window._strategyBuilderState._previewTimer) {
                        window.clearTimeout(window._strategyBuilderState._previewTimer);
                        window._strategyBuilderState._previewTimer = 0;
                    }
                    strategyPanel.classList.remove("builder-mode");
                };

                // --- openStrategyBuilderError(msg) ---
                window.openStrategyBuilderError = (msg) => {
                    const empty = document.getElementById("tv-strategy-empty");
                    if (empty) {
                        empty.style.display = "block";
                        empty.innerText = "Error: " + msg;
                    }
                };

                // --- setBuilderError(msg) ---
                window.setBuilderError = (msg) => {
                    const errEl = document.getElementById("tv-builder-error");
                    if (!errEl) return;
                    if (msg) {
                        errEl.innerText = msg;
                        errEl.style.display = "block";
                    } else {
                        errEl.innerText = "";
                        errEl.style.display = "none";
                    }
                };

                // --- renderBuilderButtons(data) ---
                // Obsoleto: los botones Editar/Params ahora se crean dentro de
                // renderStrategyList (junto a cada fila) para que persistan en re-renders.
                // Se mantiene como no-op para no romper llamadas existentes.
                window.renderBuilderButtons = (data) => {};

                // --- Indicator list rendering ---
                const INDICATOR_PARAM_DEFS = {
                    "EMA":          [{ key: "period", label: "Período", type: "int", min: 1, default: 9 }],
                    "RSI":          [{ key: "period", label: "Período", type: "int", min: 2, default: 14 }],
                    "BB":           [{ key: "period", label: "Período", type: "int", min: 2, default: 20 },
                                     { key: "multiplier", label: "Multiplicador", type: "float", min: 0.1, default: 2.0 }],
                    "DONCHIAN":     [{ key: "period", label: "Período", type: "int", min: 2, default: 12 }],
                    "ATR":          [{ key: "period", label: "Período", type: "int", min: 1, default: 14 }],
                    "VORTEX":       [{ key: "period", label: "Período", type: "int", min: 2, default: 14 }],
                    "ADX_DI":       [{ key: "period", label: "Período", type: "int", min: 2, default: 14 }],
                    "VWAP":         [],
                    "VOLUME_RATIO": [{ key: "lookback", label: "Lookback", type: "int", min: 2, default: 30 }],
                    "SMA":          [{ key: "period", label: "Período", type: "int", min: 1, default: 20 }],
                    "HMA":          [],
                    "SUPERTREND":   [],
                    "TCI":          []
                };

                window._indicatorColumns = (ind) => {
                    const p = ind.params || {};
                    switch (ind.id) {
                        case "EMA":          return [`ema_${p.period}`];
                        case "RSI":          return [`rsi_${p.period}`];
                        case "BB":           return [`bb_basis_${p.period}`, `bb_upper_${p.period}`, `bb_lower_${p.period}`, `bb_width_pct_${p.period}`];
                        case "DONCHIAN":     return [`donchian_high_${p.period}`, `donchian_low_${p.period}`, `donchian_mid_${p.period}`];
                        case "ATR":          return [`atr_${p.period}`, `atr_pct_${p.period}`];
                        case "VORTEX":       return [`vi_plus_${p.period}`, `vi_minus_${p.period}`, `vortex_dir_${p.period}`, `vortex_cross_up_${p.period}`, `vortex_cross_down_${p.period}`];
                        case "ADX_DI":       return [`adx_${p.period}`, `plus_di_${p.period}`, `minus_di_${p.period}`, `plus_di_cross_${p.period}`, `minus_di_cross_${p.period}`];
                        case "VWAP":         return ["vwap"];
                        case "VOLUME_RATIO": return [`volume_ratio_${p.lookback}`];
                        case "SMA":          return [`sma_${p.period}`];
                        case "HMA":          return ["hma"];
                        case "SUPERTREND":   return ["supertrend", "supertrend_dir", "supertrend_up", "supertrend_down"];
                        case "TCI":          return ["tci", "tci_signal", "tci_hist"];
                        default:             return [];
                    }
                };

                const ALWAYS_AVAILABLE_COLS = ["open", "high", "low", "close", "OHLC4", "HLC3", "HL2",
                                               "tick_volume", "average", "atr", "upper", "lower"];

                window._builderGetColumns = () => {
                    const cols = new Set(ALWAYS_AVAILABLE_COLS);
                    (window._strategyBuilderState.indicators || []).forEach((ind) => {
                        window._indicatorColumns(ind).forEach(c => cols.add(c));
                    });
                    return Array.from(cols).sort();
                };

                window._builderRenderIndicators = () => {
                    const list = document.getElementById("tv-builder-indicator-list");
                    if (!list) return;
                    list.innerHTML = "";
                    // VWAP + D1 warning
                    const tfSel = document.getElementById("tv-builder-timeframe");
                    const hasVWAP = (window._strategyBuilderState.indicators || []).some(i => i.id === "VWAP");
                    const isD1 = tfSel && tfSel.value === "D1";
                    if (hasVWAP && isD1) {
                        const warn = document.createElement("div");
                        warn.className = "tv-builder-vwap-d1-warn";
                        warn.innerText = "⚠ VWAP con D1 puede producir señales inesperadas.";
                        list.appendChild(warn);
                    }
                    (window._strategyBuilderState.indicators || []).forEach((ind, idx) => {
                        const row = document.createElement("div");
                        row.className = "tv-builder-indicator-row";
                        const label = document.createElement("span");
                        label.className = "tv-builder-indicator-label";
                        label.innerText = ind.id;
                        row.appendChild(label);
                        const paramDefs = INDICATOR_PARAM_DEFS[ind.id] || [];
                        paramDefs.forEach((def) => {
                            const inp = document.createElement("input");
                            inp.type = "number";
                            inp.min = def.min;
                            inp.step = def.type === "float" ? "0.1" : "1";
                            inp.value = (ind.params && ind.params[def.key] !== undefined) ? ind.params[def.key] : def.default;
                            inp.title = def.label;
                            inp.addEventListener("input", () => {
                                const val = def.type === "float" ? parseFloat(inp.value) : parseInt(inp.value, 10);
                                ind.params[def.key] = isNaN(val) ? def.default : val;
                                ind.columns = window._indicatorColumns(ind);
                                window._builderRenderTree("buy");
                                window._builderRenderTree("sell");
                                window._builderRenderPayloadFields();
                                window._builderSchedulePreview();
                            });
                            row.appendChild(inp);
                        });
                        const removeBtn = document.createElement("button");
                        removeBtn.type = "button";
                        removeBtn.innerText = "✕";
                        removeBtn.addEventListener("click", () => {
                            window._strategyBuilderState.indicators.splice(idx, 1);
                            window._builderRenderIndicators();
                            window._builderRenderTree("buy");
                            window._builderRenderTree("sell");
                            window._builderRenderPayloadFields();
                            window._builderSchedulePreview();
                        });
                        row.appendChild(removeBtn);
                        list.appendChild(row);
                    });
                };

                document.getElementById("tv-builder-add-indicator").addEventListener("click", () => {
                    const typeSelect = document.getElementById("tv-builder-indicator-type");
                    const id = typeSelect.value;
                    const paramDefs = INDICATOR_PARAM_DEFS[id] || [];
                    const params = {};
                    paramDefs.forEach(def => { params[def.key] = def.default; });
                    const preComputed = ["HMA", "SUPERTREND", "TCI"].includes(id);
                    const newInd = {
                        id,
                        params,
                        columns: window._indicatorColumns({ id, params }),
                        pre_computed: preComputed
                    };
                    window._strategyBuilderState.indicators.push(newInd);
                    window._builderRenderIndicators();
                    window._builderRenderTree("buy");
                    window._builderRenderTree("sell");
                    window._builderRenderPayloadFields();
                    window._builderSchedulePreview();
                });

                document.getElementById("tv-builder-timeframe").addEventListener("change", () => {
                    window._builderRenderIndicators();
                    window._builderSchedulePreview();
                });

                document.getElementById("tv-builder-display-name").addEventListener("input", () => {
                    const nameEl = document.getElementById("tv-builder-name");
                    const dispEl = document.getElementById("tv-builder-display-name");
                    if (nameEl && dispEl) {
                        nameEl.value = window._builderSlugify(dispEl.value);
                    }
                    window._builderSchedulePreview();
                });

                // --- Condition Tree rendering (recursive) ---
                const OPERATORS = ["<", ">", "<=", ">=", "==", "!="];

                window._builderRenderNode = (node, containerEl, onRemove, depth) => {
                    depth = depth || 0;
                    if (node.type === "condition") {
                        const row = document.createElement("div");
                        row.className = "tv-builder-condition-leaf";

                        const cols = window._builderGetColumns();
                        const fallbackCol = cols[0] || "close";
                        if (!cols.includes(node.left)) {
                            node.left = fallbackCol;
                        }
                        if (!OPERATORS.includes(node.op)) {
                            node.op = ">";
                        }
                        const rightIsColumn = typeof node.right === "string";
                        if (rightIsColumn && !cols.includes(node.right)) {
                            node.right = fallbackCol;
                        }

                        const leftSel = document.createElement("select");
                        leftSel.className = "tv-builder-col-sel";
                        cols.forEach(c => {
                            const opt = document.createElement("option");
                            opt.value = c; opt.text = c;
                            if (c === node.left) opt.selected = true;
                            leftSel.appendChild(opt);
                        });
                        leftSel.addEventListener("change", () => {
                            node.left = leftSel.value;
                            window._builderSchedulePreview();
                        });

                        const opSel = document.createElement("select");
                        opSel.className = "tv-builder-op-sel";
                        OPERATORS.forEach(op => {
                            const opt = document.createElement("option");
                            opt.value = op; opt.text = op;
                            if (op === node.op) opt.selected = true;
                            opSel.appendChild(opt);
                        });
                        opSel.addEventListener("change", () => {
                            node.op = opSel.value;
                            window._builderSchedulePreview();
                        });

                        const rightTypeBtn = document.createElement("button");
                        rightTypeBtn.type = "button";
                        rightTypeBtn.className = "tv-builder-right-type";
                        const isColumnRef = typeof node.right === "string";
                        rightTypeBtn.innerText = isColumnRef ? "col" : "val";
                        rightTypeBtn.title = isColumnRef ? "Cambiar a valor escalar" : "Cambiar a columna";

                        const rightColSel = document.createElement("select");
                        rightColSel.className = "tv-builder-col-sel";
                        rightColSel.style.display = isColumnRef ? "" : "none";
                        cols.forEach(c => {
                            const opt = document.createElement("option");
                            opt.value = c; opt.text = c;
                            if (c === node.right) opt.selected = true;
                            rightColSel.appendChild(opt);
                        });
                        rightColSel.addEventListener("change", () => {
                            node.right = rightColSel.value;
                            window._builderSchedulePreview();
                        });

                        const rightNumInp = document.createElement("input");
                        rightNumInp.type = "number";
                        rightNumInp.step = "any";
                        rightNumInp.className = "tv-builder-num-inp";
                        rightNumInp.style.display = isColumnRef ? "none" : "";
                        rightNumInp.value = isColumnRef ? 0 : node.right;
                        rightNumInp.addEventListener("input", () => {
                            const v = parseFloat(rightNumInp.value);
                            node.right = isNaN(v) ? 0 : v;
                            window._builderSchedulePreview();
                        });

                        rightTypeBtn.addEventListener("click", () => {
                            const nowCol = rightColSel.style.display !== "none";
                            if (nowCol) {
                                rightColSel.style.display = "none";
                                rightNumInp.style.display = "";
                                rightTypeBtn.innerText = "val";
                                node.right = parseFloat(rightNumInp.value) || 0;
                            } else {
                                rightNumInp.style.display = "none";
                                rightColSel.style.display = "";
                                rightTypeBtn.innerText = "col";
                                node.right = rightColSel.value || cols[0] || "close";
                            }
                            window._builderSchedulePreview();
                        });

                        const removeBtn = document.createElement("button");
                        removeBtn.type = "button";
                        removeBtn.className = "tv-builder-remove-btn";
                        removeBtn.innerText = "✕";
                        removeBtn.addEventListener("click", () => {
                            if (onRemove) onRemove();
                            window._builderSchedulePreview();
                        });

                        row.appendChild(leftSel);
                        row.appendChild(opSel);
                        row.appendChild(rightTypeBtn);
                        row.appendChild(rightColSel);
                        row.appendChild(rightNumInp);
                        row.appendChild(removeBtn);
                        containerEl.appendChild(row);

                    } else if (node.type === "AND" || node.type === "OR") {
                        const group = document.createElement("div");
                        group.className = "tv-builder-condition-group";
                        group.setAttribute("data-depth", depth);

                        const groupHeader = document.createElement("div");
                        groupHeader.className = "tv-builder-group-header";

                        const typeToggle = document.createElement("button");
                        typeToggle.type = "button";
                        typeToggle.className = "tv-builder-group-type";
                        typeToggle.innerText = node.type;
                        typeToggle.addEventListener("click", () => {
                            node.type = node.type === "AND" ? "OR" : "AND";
                            typeToggle.innerText = node.type;
                            window._builderSchedulePreview();
                        });

                        const addCondBtn = document.createElement("button");
                        addCondBtn.type = "button";
                        addCondBtn.className = "tv-builder-add-cond-btn";
                        addCondBtn.innerText = "+ Condición";
                        addCondBtn.addEventListener("click", () => {
                            const newLeaf = { type: "condition", left: "close", op: ">", right: 0 };
                            node.children.push(newLeaf);
                            renderChildren();
                            window._builderSchedulePreview();
                        });

                        const addGroupBtn = document.createElement("button");
                        addGroupBtn.type = "button";
                        addGroupBtn.className = "tv-builder-add-group-btn";
                        addGroupBtn.innerText = "+ Grupo";
                        addGroupBtn.disabled = depth >= 4;
                        addGroupBtn.addEventListener("click", () => {
                            if (depth >= 4) return;
                            const newGroup = { type: "AND", children: [] };
                            node.children.push(newGroup);
                            renderChildren();
                            window._builderSchedulePreview();
                        });

                        const removeGroupBtn = document.createElement("button");
                        removeGroupBtn.type = "button";
                        removeGroupBtn.className = "tv-builder-remove-btn";
                        removeGroupBtn.innerText = "✕";
                        removeGroupBtn.addEventListener("click", () => {
                            if (onRemove) onRemove();
                            window._builderSchedulePreview();
                        });

                        groupHeader.appendChild(typeToggle);
                        groupHeader.appendChild(addCondBtn);
                        if (depth > 0) {
                            groupHeader.appendChild(addGroupBtn);
                            groupHeader.appendChild(removeGroupBtn);
                        } else {
                            groupHeader.appendChild(addGroupBtn);
                        }
                        group.appendChild(groupHeader);

                        const childContainer = document.createElement("div");
                        childContainer.className = "tv-builder-group-children";
                        group.appendChild(childContainer);

                        const renderChildren = () => {
                            childContainer.innerHTML = "";
                            node.children.forEach((child, i) => {
                                window._builderRenderNode(child, childContainer, () => {
                                    node.children.splice(i, 1);
                                    renderChildren();
                                    window._builderSchedulePreview();
                                }, depth + 1);
                            });
                        };
                        renderChildren();

                        containerEl.appendChild(group);
                    }
                };

                window._builderRenderTree = (side) => {
                    const containerId = side === "buy" ? "tv-builder-buy-tree" : "tv-builder-sell-tree";
                    const container = document.getElementById(containerId);
                    if (!container) return;
                    container.innerHTML = "";
                    const tree = side === "buy" ? window._strategyBuilderState.buy_tree : window._strategyBuilderState.sell_tree;
                    if (!tree) return;
                    window._builderRenderNode(tree, container, null, 0);
                };

                // --- Payload extra fields ---
                window._builderRenderPayloadFields = () => {
                    const container = document.getElementById("tv-builder-payload-list");
                    if (!container) return;
                    container.innerHTML = "";
                    const fields = window._strategyBuilderState.payload_extra_fields || [];
                    const availableCols = (() => {
                        const cols = ["close", "open", "high", "low", "volume"];
                        (window._strategyBuilderState.indicators || []).forEach((ind) => {
                            window._indicatorColumns(ind).forEach(c => cols.push(c));
                        });
                        return cols;
                    })();

                    fields.forEach((field, idx) => {
                        const row = document.createElement("div");
                        row.className = "tv-builder-payload-row";

                        const keyInput = document.createElement("input");
                        keyInput.type = "text";
                        keyInput.placeholder = "clave";
                        keyInput.value = field.key || "";
                        keyInput.addEventListener("input", () => {
                            fields[idx].key = keyInput.value.trim();
                            window._builderSchedulePreview();
                        });

                        const typeSel = document.createElement("select");
                        ["literal", "column"].forEach(t => {
                            const opt = document.createElement("option");
                            opt.value = t; opt.textContent = t;
                            if (field.type === t) opt.selected = true;
                            typeSel.appendChild(opt);
                        });
                        typeSel.addEventListener("change", () => {
                            fields[idx].type = typeSel.value;
                            fields[idx].value = typeSel.value === "column" ? (availableCols[0] || "") : "";
                            window._builderRenderPayloadFields();
                            window._builderSchedulePreview();
                        });

                        let valueEl;
                        if (field.type === "column") {
                            valueEl = document.createElement("select");
                            availableCols.forEach(c => {
                                const opt = document.createElement("option");
                                opt.value = c; opt.textContent = c;
                                if (field.value === c) opt.selected = true;
                                valueEl.appendChild(opt);
                            });
                            valueEl.addEventListener("change", () => {
                                fields[idx].value = valueEl.value;
                                window._builderSchedulePreview();
                            });
                        } else {
                            valueEl = document.createElement("input");
                            valueEl.type = "text";
                            valueEl.placeholder = "valor";
                            valueEl.value = field.value === undefined ? "" : String(field.value);
                            valueEl.addEventListener("input", () => {
                                const raw = valueEl.value.trim();
                                if (raw === "true") fields[idx].value = true;
                                else if (raw === "false") fields[idx].value = false;
                                else if (raw !== "" && !isNaN(Number(raw))) fields[idx].value = Number(raw);
                                else fields[idx].value = raw;
                                window._builderSchedulePreview();
                            });
                        }

                        const removeBtn = document.createElement("button");
                        removeBtn.type = "button";
                        removeBtn.className = "tv-builder-remove-btn";
                        removeBtn.textContent = "✕";
                        removeBtn.title = "Eliminar campo";
                        removeBtn.addEventListener("click", () => {
                            fields.splice(idx, 1);
                            window._builderRenderPayloadFields();
                            window._builderSchedulePreview();
                        });

                        row.appendChild(keyInput);
                        row.appendChild(typeSel);
                        row.appendChild(valueEl);
                        row.appendChild(removeBtn);
                        container.appendChild(row);
                    });

                    const addBtn = document.getElementById("tv-builder-add-payload");
                    if (addBtn) {
                        addBtn.onclick = null;
                        addBtn.addEventListener("click", () => {
                            fields.push({ key: "", type: "literal", value: "" });
                            window._builderRenderPayloadFields();
                            window._builderSchedulePreview();
                        });
                    }
                };

                // --- Cancel button ---
                document.getElementById("tv-builder-cancel").addEventListener("click", () => {
                    window.closeStrategyBuilder();
                    const state = window._strategyBuilderState;
                    if (state && state._handler && window.callbackFunction) {
                        window.callbackFunction(state._handler + "_~_strategy_builder_close");
                    }
                });

                // --- Save button ---
                document.getElementById("tv-builder-save").addEventListener("click", () => {
                    window.setBuilderError("");
                    const state = window._strategyBuilderState;
                    const config = window._builderCollectConfig(true);
                    const displayName = config.display_name;
                    if (state._previewTimer) {
                        window.clearTimeout(state._previewTimer);
                        state._previewTimer = 0;
                    }

                    if (!displayName) { window.setBuilderError("El nombre visible es obligatorio."); return; }

                    const buyTree = state.buy_tree;
                    const sellTree = state.sell_tree;
                    if (!buyTree || !buyTree.children || buyTree.children.length === 0) {
                        window.setBuilderError("La condición de compra no puede estar vacía.");
                        return;
                    }
                    if (!sellTree || !sellTree.children || sellTree.children.length === 0) {
                        window.setBuilderError("La condición de venta no puede estar vacía.");
                        return;
                    }

                    const json = JSON.stringify(config);
                    window.callbackFunction(state._handler + "_~_strategy_builder_save;;;" + encodeURIComponent(json));
                });

                // --- Quick Params panel CSS ---
                const paramsStyle = document.createElement("style");
                paramsStyle.textContent = `
                    #tv-params-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.55); z-index: 9000; display: flex; align-items: center; justify-content: center; }
                    #tv-params-panel { background: #1e2230; border: 1px solid #333; border-radius: 6px; padding: 20px; min-width: 320px; max-width: 480px; max-height: 80vh; overflow-y: auto; color: #d1d4dc; font-family: inherit; font-size: 13px; }
                    #tv-params-panel h3 { margin: 0 0 14px 0; font-size: 14px; color: #e0e3ea; }
                    .tv-params-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; gap: 8px; }
                    .tv-params-row label { flex: 1; color: #9aa0ab; }
                    .tv-params-row input[type="number"] { width: 110px; background: #131722; border: 1px solid #444; border-radius: 3px; color: #d1d4dc; padding: 4px 6px; font-size: 13px; }
                    #tv-params-actions { display: flex; gap: 8px; margin-top: 16px; justify-content: flex-end; }
                    #tv-params-actions button { padding: 6px 16px; border-radius: 4px; border: none; cursor: pointer; font-size: 13px; }
                    #tv-params-save-btn { background: #2962ff; color: #fff; }
                    #tv-params-cancel-btn { background: #2a2e39; color: #9aa0ab; }
                    #tv-params-message { font-size: 12px; color: #26a69a; margin-top: 8px; min-height: 16px; }
                    .tv-params-btn { margin-left: 4px; padding: 2px 8px; font-size: 11px; background: #1a3a5e; color: #90b0e0; border: 1px solid #2962ff44; border-radius: 3px; cursor: pointer; }
                    .tv-params-btn:hover { background: #2962ff; color: #fff; }
                `;
                document.head.appendChild(paramsStyle);

                // --- openParamsPanel(payload) ---
                window.openParamsPanel = (payload) => {
                    const existing = document.getElementById("tv-params-overlay");
                    if (existing) existing.remove();

                    const overlay = document.createElement("div");
                    overlay.id = "tv-params-overlay";

                    const panel = document.createElement("div");
                    panel.id = "tv-params-panel";

                    const title = document.createElement("h3");
                    title.innerText = "Parámetros: " + (payload.label || payload.key);
                    panel.appendChild(title);

                    const schema = payload.schema || {};
                    const values = payload.values || {};

                    Object.keys(schema).forEach((paramKey) => {
                        const def = schema[paramKey];
                        const currentVal = (paramKey in values) ? values[paramKey] : def.default;

                        const row = document.createElement("div");
                        row.className = "tv-params-row";

                        const lbl = document.createElement("label");
                        lbl.innerText = def.label || paramKey;
                        lbl.htmlFor = "tv-param-" + paramKey;

                        const inp = document.createElement("input");
                        inp.type = "number";
                        inp.id = "tv-param-" + paramKey;
                        inp.dataset.paramKey = paramKey;
                        inp.dataset.paramType = def.type;
                        inp.min = String(def.min);
                        inp.max = String(def.max);
                        inp.step = (def.type === "int") ? "1" : "any";
                        inp.value = String(currentVal);

                        row.appendChild(lbl);
                        row.appendChild(inp);
                        panel.appendChild(row);
                    });

                    const msgEl = document.createElement("div");
                    msgEl.id = "tv-params-message";
                    panel.appendChild(msgEl);

                    const actions = document.createElement("div");
                    actions.id = "tv-params-actions";

                    const cancelBtn = document.createElement("button");
                    cancelBtn.id = "tv-params-cancel-btn";
                    cancelBtn.innerText = "Cancelar";
                    cancelBtn.addEventListener("click", () => {
                        if (window.closeParamsPanel) window.closeParamsPanel();
                    });

                    const saveBtn = document.createElement("button");
                    saveBtn.id = "tv-params-save-btn";
                    saveBtn.innerText = "Guardar";
                    saveBtn.addEventListener("click", () => {
                        const overrides = {};
                        panel.querySelectorAll("input[data-param-key]").forEach((inp) => {
                            const k = inp.dataset.paramKey;
                            const t = inp.dataset.paramType;
                            let v = parseFloat(inp.value);
                            if (isNaN(v)) return;
                            const minV = parseFloat(inp.min);
                            const maxV = parseFloat(inp.max);
                            if (!isNaN(minV) && v < minV) v = minV;
                            if (!isNaN(maxV) && v > maxV) v = maxV;
                            if (t === "int") v = Math.round(v);
                            overrides[k] = v;
                        });
                        const handler = payload.handler || "";
                        const encodedKey = encodeURIComponent(String(payload.key || ""));
                        const overridesJson = encodeURIComponent(JSON.stringify(overrides));
                        window.callbackFunction(handler + "_~_strategy_params_save;;;" + encodedKey + ";;;" + overridesJson);
                    });

                    actions.appendChild(cancelBtn);
                    actions.appendChild(saveBtn);
                    panel.appendChild(actions);

                    overlay.appendChild(panel);
                    document.body.appendChild(overlay);

                    overlay.addEventListener("click", (e) => {
                        if (e.target === overlay) {
                            if (window.closeParamsPanel) window.closeParamsPanel();
                        }
                    });
                };

                // --- closeParamsPanel() ---
                window.closeParamsPanel = () => {
                    const overlay = document.getElementById("tv-params-overlay");
                    if (overlay) overlay.remove();
                };

                // --- setParamsMessage(msg) ---
                window.setParamsMessage = (msg) => {
                    const msgEl = document.getElementById("tv-params-message");
                    if (msgEl) msgEl.innerText = msg || "";
                };

            })();
        ''')
        self.chart.run_script(f'''
            ;(function() {{
                if (window._strategyBuilderState) {{
                    window._strategyBuilderState._handler = "{self.side_panel_handler}";
                }}
            }})();
        ''')

    def _apply_strategy_processing_with_module(self, df: pd.DataFrame, module, strategy_key: str = "") -> pd.DataFrame:
        # esta funcion sirve para aplicar el procesado de una estrategia con su modulo.
        if module is None:
            return df
        label = strategy_key or self.current_strategy_key or ""
        try:
            df = runtime_apply_strategy_processing(
                df,
                module,
                enable_signals=bool(getattr(config, "ENABLE_SIGNALS", True)),
            )
        except Exception as e:
            self.log_message(f"Error en estrategia '{label}': {e}")
        return df

    def _apply_strategy_processing_for_entry(self, entry: dict, df: pd.DataFrame) -> pd.DataFrame:
        # esta funcion sirve para aplicar el procesado de una estrategia del registro.
        if not isinstance(entry, dict):
            return self._apply_strategy_processing_with_module(df, self.strategy_module, self.current_strategy_key or "")
        module = entry.get("module_obj")
        if module is None:
            return df
        if hasattr(module, "prepare_frames") or hasattr(module, "get_last_signal_payload_mtf"):
            try:
                required = list(getattr(module, "REQUIRED_TIMEFRAMES", []) or [])
                primary = str(getattr(module, "PRIMARY_TIMEFRAME", getattr(module, "TIMEFRAME", "")) or "").upper()
                if primary and primary not in required:
                    required.append(primary)
                if not required:
                    required = [self._timeframe_label(self._strategy_timeframe_value(entry, fallback=config.TIMEFRAME)) or "M1"]
                base_label = runtime_lowest_timeframe_label(required)
                frames = runtime_build_timeframe_frames(df, required, base_timeframe=base_label)
                frames = runtime_apply_mtf_strategy_processing(
                    frames,
                    module,
                    enable_signals=bool(getattr(config, "ENABLE_SIGNALS", True)),
                )
                entry["_last_mtf_frames"] = frames
                return frames.get(primary or base_label, df)
            except Exception as e:
                entry["_last_mtf_frames"] = {}
                self.log_message(f"Error MTF en estrategia '{entry.get('key', '')}': {e}")
                return df
        return self._apply_strategy_processing_with_module(df, module, entry.get("key", ""))

    def _apply_strategy_processing(self, df: pd.DataFrame) -> pd.DataFrame:
        # esta funcion sirve para aplicar estrategia procesado.
        entry = self._get_selected_strategy_entry()
        return self._apply_strategy_processing_for_entry(entry, df)

    def _normalize_signal_value(self, signal) -> str:
        # esta funcion sirve para normalizar valor de señal.
        return runtime_normalize_signal(signal)

    def _normalize_signal_payload(self, payload) -> dict:
        # esta funcion sirve para normalizar payload de señal.
        return runtime_normalize_signal_payload(payload)

    def _get_strategy_signal_payload_with_module(
        self,
        df: pd.DataFrame,
        module,
        strategy_key: str = "",
        verbose: bool = False
    ) -> dict:
        # esta funcion sirve para obtener payload de señal con modulo.
        if module is None:
            return {"signal": "none", "reason": ""}
        label = strategy_key or self.current_strategy_key or ""
        try:
            return runtime_get_strategy_signal_payload(
                df,
                module,
                verbose=verbose,
            )
        except Exception as e:
            self.log_message(f"Error al obtener señal ({label}): {e}")
            return {"signal": "none", "reason": ""}

    def _get_strategy_signal_with_module(self, df: pd.DataFrame, module, strategy_key: str = "", verbose: bool = False) -> str:
        # esta funcion sirve para obtener estrategia senal con modulo.
        payload = self._get_strategy_signal_payload_with_module(
            df, module, strategy_key=strategy_key, verbose=verbose
        )
        return payload.get("signal", "none")

    def _get_strategy_signal_payload_for_entry(self, entry: dict, df: pd.DataFrame, verbose: bool = False) -> dict:
        # esta funcion sirve para obtener payload de señal para entrada.
        if not isinstance(entry, dict):
            return self._get_strategy_signal_payload_with_module(
                df, self.strategy_module, self.current_strategy_key or "", verbose=verbose
            )
        module = entry.get("module_obj")
        if module is None:
            return {"signal": "none", "reason": ""}
        if hasattr(module, "get_last_signal_payload_mtf"):
            frames = entry.get("_last_mtf_frames") or {}
            try:
                return runtime_get_strategy_signal_payload_mtf(
                    frames,
                    module,
                    verbose=verbose,
                )
            except Exception as e:
                self.log_message(f"Error al obtener señal MTF ({entry.get('key', '')}): {e}")
                return {"signal": "none", "reason": ""}
        return self._get_strategy_signal_payload_with_module(
            df, module, entry.get("key", ""), verbose=verbose
        )

    def _get_strategy_signal_for_entry(self, entry: dict, df: pd.DataFrame, verbose: bool = False) -> str:
        # esta funcion sirve para obtener estrategia senal para entrada.
        payload = self._get_strategy_signal_payload_for_entry(entry, df, verbose=verbose)
        return payload.get("signal", "none")

    def _get_strategy_signal(self, df: pd.DataFrame, verbose: bool = False) -> str:
        # esta funcion sirve para obtener estrategia senal.
        entry = self._get_selected_strategy_entry()
        return self._get_strategy_signal_for_entry(entry, df, verbose=verbose)
        
    def setup_topbar(self):
        # esta funcion sirve para preparar barra superior.
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
        # esta funcion sirve para inyectar estilos personalizados.
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
                    .tv-strategy-edit-btn, .tv-strategy-params-btn {
                        background: #1a3a5e;
                        border: 1px solid #2962ff66;
                        color: #9fc2ff;
                        border-radius: 6px;
                        padding: 5px 8px;
                        font-size: 11px;
                        font-weight: 600;
                        cursor: pointer;
                        white-space: nowrap;
                        flex-shrink: 0;
                        margin-left: 4px;
                    }
                    .tv-strategy-edit-btn:hover, .tv-strategy-params-btn:hover {
                        background: #2962ff;
                        color: #ffffff;
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
                    #tv-strategy-panel {
                        overflow-y: auto;
                        scrollbar-width: thin;
                        scrollbar-color: #5a5a5a #1b1b1b;
                    }
                    #tv-strategy-panel::-webkit-scrollbar {
                        width: 10px;
                    }
                    #tv-strategy-panel::-webkit-scrollbar-track {
                        background: #1b1b1b;
                        border-left: 1px solid #2f2f2f;
                        border-radius: 8px;
                    }
                    #tv-strategy-panel::-webkit-scrollbar-thumb {
                        background: linear-gradient(180deg, #6a6a6a 0%, #585858 100%);
                        border: 2px solid #1b1b1b;
                        border-radius: 8px;
                    }
                    #tv-strategy-panel::-webkit-scrollbar-thumb:hover {
                        background: linear-gradient(180deg, #7a7a7a 0%, #666666 100%);
                    }
                    #tv-strategy-panel::-webkit-scrollbar-thumb:active {
                        background: linear-gradient(180deg, #8a8a8a 0%, #767676 100%);
                    }
                    .tv-backtest-panel {
                        scrollbar-width: thin;
                        scrollbar-color: #5a5a5a #1b1b1b;
                    }
                    .tv-backtest-panel::-webkit-scrollbar {
                        width: 10px;
                    }
                    .tv-backtest-panel::-webkit-scrollbar-track {
                        background: #1b1b1b;
                        border-left: 1px solid #2f2f2f;
                        border-radius: 8px;
                    }
                    .tv-backtest-panel::-webkit-scrollbar-thumb {
                        background: linear-gradient(180deg, #6a6a6a 0%, #585858 100%);
                        border: 2px solid #1b1b1b;
                        border-radius: 8px;
                    }
                    .tv-backtest-panel::-webkit-scrollbar-thumb:hover {
                        background: linear-gradient(180deg, #7a7a7a 0%, #666666 100%);
                    }
                    .tv-backtest-panel::-webkit-scrollbar-thumb:active {
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
                    .tv-legacy-panel {
                        flex: 1;
                        display: flex;
                        flex-direction: column;
                        overflow: hidden;
                    }
                    #tv-data-window {
                        flex: 1;
                        min-height: 0;
                        overflow-x: hidden;
                        overflow-y: auto;
                        padding: 10px 12px;
                        color: var(--tv-text-secondary);
                        display: flex;
                        flex-direction: column;
                        gap: 10px;
                        scrollbar-width: thin;
                        scrollbar-color: #5a5a5a #1b1b1b;
                    }
                    #tv-data-window::-webkit-scrollbar {
                        width: 10px;
                    }
                    #tv-data-window::-webkit-scrollbar-track {
                        background: #1b1b1b;
                        border-left: 1px solid #2f2f2f;
                        border-radius: 8px;
                    }
                    #tv-data-window::-webkit-scrollbar-thumb {
                        background: linear-gradient(180deg, #6a6a6a 0%, #585858 100%);
                        border: 2px solid #1b1b1b;
                        border-radius: 8px;
                    }
                    #tv-data-window::-webkit-scrollbar-thumb:hover {
                        background: linear-gradient(180deg, #7a7a7a 0%, #666666 100%);
                    }
                    #tv-data-window::-webkit-scrollbar-thumb:active {
                        background: linear-gradient(180deg, #8a8a8a 0%, #767676 100%);
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
                        flex: 0 0 auto;
                        min-height: 0;
                        display: flex;
                        flex-direction: column;
                        gap: 6px;
                        overflow: visible;
                    }
                    .tv-data-trades-list {
                        flex: 0 0 auto;
                        min-height: 0;
                        max-height: 480px;
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
                        min-width: 120px;
                        flex-shrink: 0;
                    }
                    .tv-strategy-actions {
                        display: flex;
                        flex-wrap: wrap;
                        gap: 4px;
                        justify-content: flex-end;
                    }
                    .tv-strategy-panel-title {
                        font-size: 13px;
                        font-weight: 600;
                        color: var(--tv-text-primary, #e0e0e0);
                        margin-bottom: 2px;
                    }
                    .tv-strategy-panel-hint {
                        font-size: 11px;
                        color: #8c8c8c;
                        margin-bottom: 10px;
                        line-height: 1.3;
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
                    .tv-backtest-panel {
                        display: flex;
                        flex-direction: column;
                        gap: 10px;
                        padding: 10px;
                        color: #d0d0d0;
                        overflow-y: auto;
                    }
                    .tv-backtest-header {
                        display: flex;
                        flex-direction: column;
                        gap: 2px;
                    }
                    .tv-backtest-title {
                        font-size: 14px;
                        font-weight: 700;
                        color: #f0f0f0;
                    }
                    .tv-backtest-subtitle {
                        font-size: 11px;
                        color: #8e8e8e;
                    }
                    .tv-backtest-form {
                        display: grid;
                        grid-template-columns: 1fr 1fr;
                        gap: 8px;
                    }
                    .tv-backtest-field {
                        display: flex;
                        flex-direction: column;
                        gap: 4px;
                    }
                    .tv-backtest-field label {
                        font-size: 11px;
                        color: #9b9b9b;
                    }
                    .tv-backtest-field select,
                    .tv-backtest-field input,
                    .tv-backtest-readonly {
                        background: #1a1a1a;
                        border: 1px solid #333333;
                        color: #f0f0f0;
                        padding: 7px 8px;
                        border-radius: 4px;
                        font-size: 12px;
                    }
                    .tv-backtest-readonly {
                        min-height: 32px;
                        display: flex;
                        align-items: center;
                    }
                    .tv-backtest-presets {
                        grid-column: 1 / -1;
                    }
                    .tv-backtest-preset-list {
                        display: flex;
                        flex-wrap: wrap;
                        gap: 6px;
                    }
                    .tv-backtest-preset-btn {
                        background: #232323;
                        color: #d9d9d9;
                        border: 1px solid #343434;
                        border-radius: 999px;
                        padding: 5px 10px;
                        font-size: 11px;
                        cursor: pointer;
                    }
                    .tv-backtest-preset-btn.active {
                        background: #163038;
                        border-color: #245565;
                        color: #b9ebff;
                    }
                    .tv-backtest-actions {
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        gap: 8px;
                    }
                    #tv-backtest-run {
                        background: #1f3a24;
                        color: #d9f2de;
                        border: 1px solid #2f5a35;
                        border-radius: 4px;
                        padding: 7px 12px;
                        font-size: 12px;
                        cursor: pointer;
                    }
                    #tv-backtest-run:disabled {
                        opacity: 0.6;
                        cursor: default;
                    }
                    .tv-backtest-export-btn {
                        background: #1a2a3a;
                        color: #9abfe0;
                        border: 1px solid #2a4a6a;
                        border-radius: 4px;
                        padding: 7px 12px;
                        font-size: 12px;
                        cursor: pointer;
                        margin-top: 8px;
                        width: 100%;
                    }
                    .tv-backtest-status {
                        font-size: 11px;
                        color: #8f8f8f;
                    }
                    .tv-backtest-error {
                        display: none;
                        background: rgba(180, 40, 40, 0.14);
                        border: 1px solid rgba(180, 40, 40, 0.4);
                        color: #ff9a9a;
                        border-radius: 6px;
                        padding: 8px 10px;
                        font-size: 11px;
                    }
                    .tv-backtest-results {
                        display: grid;
                        grid-template-columns: 1fr 1fr;
                        gap: 8px;
                    }
                    .tv-backtest-card {
                        background: #1f1f1f;
                        border: 1px solid #2f2f2f;
                        border-radius: 8px;
                        padding: 10px;
                        display: flex;
                        flex-direction: column;
                        gap: 4px;
                    }
                    .tv-backtest-card-label {
                        font-size: 10px;
                        color: #8f8f8f;
                        text-transform: uppercase;
                        letter-spacing: 0.05em;
                    }
                    .tv-backtest-card-value {
                        font-size: 14px;
                        font-weight: 700;
                        color: #f0f0f0;
                        font-variant-numeric: tabular-nums;
                    }
                    .tv-backtest-section {{
                        display: flex;
                        flex-direction: column;
                        gap: 6px;
                    }}
                    .tv-backtest-section-title {{
                        font-size: 11px;
                        color: #8f8f8f;
                        text-transform: uppercase;
                        letter-spacing: 0.05em;
                    }}
                    .tv-backtest-microchart {{
                        width: 100%;
                        height: 60px;
                        display: block;
                        border-radius: 4px;
                        background: #1a1a1a;
                        overflow: visible;
                    }}
                    .tv-backtest-trades-wrapper {{
                        overflow-x: auto;
                        max-height: 220px;
                        overflow-y: auto;
                    }}
                    .tv-backtest-trades-table {{
                        width: 100%;
                        border-collapse: collapse;
                        font-size: 10px;
                        color: #c0c0c0;
                        min-width: 420px;
                    }}
                    .tv-backtest-trades-table th {{
                        font-size: 9px;
                        color: #8f8f8f;
                        text-transform: uppercase;
                        letter-spacing: 0.04em;
                        padding: 4px 5px;
                        background: #1a1a1a;
                        position: sticky;
                        top: 0;
                        z-index: 1;
                        border-bottom: 1px solid #2f2f2f;
                        white-space: nowrap;
                    }}
                    .tv-backtest-trades-table td {{
                        padding: 4px 5px;
                        border-bottom: 1px solid #252525;
                        white-space: nowrap;
                        font-variant-numeric: tabular-nums;
                    }}
                    .tv-backtest-trades-table tr:hover td {{
                        background: #1f1f1f;
                    }}
                    .tv-backtest-trade-win {{
                        color: #5cb85c;
                    }}
                    .tv-backtest-trade-loss {{
                        color: #d9534f;
                    }}
                    .tv-backtest-mode-toggle {
                        display: flex;
                        gap: 4px;
                        margin-bottom: 6px;
                    }
                    .tv-backtest-mode-btn {
                        flex: 1;
                        font-size: 11px;
                        padding: 4px 0;
                        background: #1e1e1e;
                        color: #8f8f8f;
                        border: 1px solid #333;
                        border-radius: 3px;
                        cursor: pointer;
                    }
                    .tv-backtest-mode-btn.active {
                        background: #2962ff;
                        color: #ffffff;
                        border-color: #2962ff;
                    }
                    .tv-backtest-strategy-checks {
                        max-height: 110px;
                        overflow-y: auto;
                        display: flex;
                        flex-direction: column;
                        gap: 4px;
                        padding: 4px 0;
                    }
                    .tv-backtest-strategy-check-row {
                        display: flex;
                        align-items: center;
                        gap: 6px;
                        font-size: 12px;
                        color: #c0c0c0;
                        cursor: pointer;
                    }
                    .tv-backtest-strategy-check-row input[type="checkbox"] {
                        accent-color: #2962ff;
                        cursor: pointer;
                    }
                    .tv-backtest-strategy-check-row.disabled {
                        opacity: 0.4;
                        cursor: not-allowed;
                    }
                    .tv-backtest-comparison-wrapper {
                        overflow-x: auto;
                        margin-top: 8px;
                    }
                    .tv-backtest-comparison-table {
                        width: 100%;
                        border-collapse: collapse;
                        font-size: 10px;
                        color: #c0c0c0;
                        min-width: 260px;
                    }
                    .tv-backtest-comparison-table th {
                        font-size: 9px;
                        color: #8f8f8f;
                        text-transform: uppercase;
                        letter-spacing: 0.04em;
                        padding: 4px 4px;
                        background: #1a1a1a;
                        position: sticky;
                        top: 0;
                        z-index: 1;
                        border-bottom: 1px solid #2f2f2f;
                        white-space: nowrap;
                    }
                    .tv-backtest-comparison-table td {
                        padding: 4px 4px;
                        border-bottom: 1px solid #252525;
                        white-space: nowrap;
                        font-variant-numeric: tabular-nums;
                    }
                    .tv-backtest-comparison-table tr:hover td {
                        background: #1f1f1f;
                    }
                    .tv-backtest-comparison-table td.cmp-win {
                        color: #5cb85c;
                    }
                    .tv-backtest-comparison-table td.cmp-loss {
                        color: #d9534f;
                    }
                    .tv-backtest-comparison-table td.cmp-error {
                        color: #d9534f;
                        font-style: italic;
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
                        position: fixed;
                        top: var(--tv-topbar-height);
                        left: 0;
                        right: var(--tv-readiness-right-inset, 0px);
                        bottom: var(--tv-bottom-height);
                        padding: 18px;
                        box-sizing: border-box;
                        display: none;
                        align-items: center;
                        justify-content: center;
                        pointer-events: none;
                        z-index: 1008;
                        background: transparent;
                    }
                    .tv-strategy-readiness-overlay.open {
                        display: flex;
                        background:
                            radial-gradient(circle at 28% 18%, rgba(208, 220, 236, 0.14), rgba(208, 220, 236, 0.04) 36%, rgba(8, 11, 18, 0.58) 100%);
                        -webkit-backdrop-filter: blur(2px);
                        backdrop-filter: blur(2px);
                    }
                    .tv-strategy-readiness-card {
                        width: min(940px, calc(100% - 24px));
                        max-height: min(690px, calc(100% - 24px));
                        overflow: hidden;
                        pointer-events: auto;
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

                    /* ---- Micro-interacciones: transiciones globales ---- */
                    .tv-strategy-toggle,
                    .tv-strategy-enable,
                    .tv-strategy-run,
                    .tv-tool-btn,
                    .tv-period-btn,
                    .tv-side-tab,
                    .tv-backtest-preset-btn,
                    .tv-backtest-mode-btn,
                    .tv-confirm-btn,
                    .tv-params-btn,
                    #tv-params-save-btn,
                    #tv-params-cancel-btn,
                    .tv-builder-cancel-btn,
                    .tv-builder-save-btn,
                    .tv-builder-new-btn,
                    .tv-builder-add-cond-btn,
                    .tv-builder-add-group-btn,
                    .tv-builder-indicator-picker button,
                    .tv-strategy-data-all-btn,
                    .tv-backtest-export-btn,
                    #tv-backtest-run {
                        transition: background 0.14s ease, border-color 0.14s ease,
                                    color 0.14s ease, box-shadow 0.14s ease,
                                    transform 0.10s ease, opacity 0.14s ease;
                    }

                    /* ---- Escala en :active (feedback táctil) ---- */
                    .tv-strategy-toggle:active,
                    .tv-strategy-enable:active,
                    .tv-strategy-run:active,
                    .tv-tool-btn:active,
                    .tv-eye:active,
                    .tv-side-tab:active,
                    .tv-backtest-preset-btn:active,
                    .tv-backtest-mode-btn:active,
                    .tv-confirm-btn:active,
                    .tv-params-btn:active,
                    #tv-params-save-btn:active,
                    #tv-params-cancel-btn:active,
                    .tv-builder-cancel-btn:active,
                    .tv-builder-save-btn:active,
                    .tv-builder-new-btn:active,
                    .tv-builder-add-cond-btn:active,
                    .tv-builder-add-group-btn:active,
                    .tv-builder-indicator-picker button:active,
                    .tv-strategy-data-all-btn:active,
                    .tv-backtest-export-btn:active,
                    #tv-backtest-run:active {
                        transform: scale(0.97);
                    }

                    /* ---- Box-shadow en hover para botones primarios ---- */
                    #tv-backtest-run:hover:not(:disabled),
                    .tv-strategy-run:hover:not(.running),
                    .tv-confirm-btn.confirm:hover,
                    #tv-params-save-btn:hover,
                    .tv-builder-save-btn:hover {
                        box-shadow: 0 0 0 2px rgba(38, 166, 154, 0.30);
                    }

                    /* ---- Tab fade-in ---- */
                    @keyframes tvTabFadeIn {
                        from { opacity: 0; transform: translateY(4px); }
                        to   { opacity: 1; transform: translateY(0); }
                    }
                    .tv-tab-fade-in {
                        animation: tvTabFadeIn 0.18s ease forwards;
                    }

                    /* ---- Spinner en #tv-backtest-run cuando está disabled (running) ---- */
                    #tv-backtest-run {
                        position: relative;
                        padding-right: 28px;   /* espacio para el spinner */
                    }
                    #tv-backtest-run:not(:disabled) {
                        padding-right: 12px;   /* restaurar padding normal cuando no corre */
                    }
                    @keyframes tvSpinner {
                        to { transform: rotate(360deg); }
                    }
                    #tv-backtest-run:disabled::after {
                        content: '';
                        position: absolute;
                        right: 8px;
                        top: 50%;
                        width: 10px;
                        height: 10px;
                        margin-top: -5px;
                        border: 2px solid rgba(217, 242, 222, 0.3);
                        border-top-color: #d9f2de;
                        border-radius: 50%;
                        animation: tvSpinner 0.75s linear infinite;
                        box-sizing: border-box;
                    }

                    /* ---- Toast notification system ---- */
                    #tv-toast-container {
                        position: fixed;
                        bottom: 42px;   /* encima del #tv-bottom-bar (32px) + margen */
                        right: 50px;    /* a la izquierda del #tv-side-toolbar (40px) + margen */
                        z-index: 9999;
                        display: flex;
                        flex-direction: column-reverse;
                        gap: 8px;
                        pointer-events: none;
                        max-width: 300px;
                        width: 300px;
                    }
                    .tv-toast {
                        background: #1e1e1e;
                        border-radius: 6px;
                        border-left: 3px solid #4a90d9;
                        padding: 8px 12px;
                        font-size: 12px;
                        color: #e0e0e0;
                        box-shadow: 0 4px 16px rgba(0,0,0,0.45);
                        pointer-events: auto;
                        animation: tvToastIn 0.22s ease forwards;
                        will-change: transform, opacity;
                        line-height: 1.4;
                        word-break: break-word;
                    }
                    .tv-toast--success { border-left-color: #26a69a; }
                    .tv-toast--warn    { border-left-color: #e6a817; }
                    .tv-toast--error   { border-left-color: #ef5350; }
                    .tv-toast--info    { border-left-color: #4a90d9; }

                    @keyframes tvToastIn {
                        from { opacity: 0; transform: translateX(110%); }
                        to   { opacity: 1; transform: translateX(0); }
                    }
                    @keyframes tvToastOut {
                        from { opacity: 1; transform: translateX(0);    max-height: 80px; margin-bottom: 0; }
                        to   { opacity: 0; transform: translateX(110%); max-height: 0;    margin-bottom: -8px; }
                    }
                    .tv-toast--dismissing {
                        animation: tvToastOut 0.25s ease forwards;
                        pointer-events: none;
                    }
                `;
                document.head.appendChild(style);
            }
        ''')
        self.chart.run_script('''
            ;(function() {
                if (window.tvShowToast) return;

                const MAX_TOASTS = 4;

                function _dismissToast(toast) {
                    if (toast._dismissed) return;
                    toast._dismissed = true;
                    toast.classList.add('tv-toast--dismissing');
                    toast.addEventListener('animationend', function() {
                        if (toast.parentElement) toast.parentElement.removeChild(toast);
                    }, { once: true });
                }

                window.tvShowToast = function(message, type, duration) {
                    type = type || 'info';
                    duration = (typeof duration === 'number') ? duration : 3500;

                    const container = document.getElementById('tv-toast-container');
                    if (!container) return;

                    const visibleToasts = container.querySelectorAll('.tv-toast:not(.tv-toast--dismissing)');
                    if (visibleToasts.length >= MAX_TOASTS) {
                        const oldest = container.lastElementChild;
                        if (oldest) _dismissToast(oldest);
                    }

                    const toast = document.createElement('div');
                    toast.className = 'tv-toast tv-toast--' + type;
                    toast.textContent = message;
                    container.appendChild(toast);

                    const timer = setTimeout(function() { _dismissToast(toast); }, duration);
                    toast._dismissTimer = timer;

                    toast.addEventListener('click', function() {
                        clearTimeout(toast._dismissTimer);
                        _dismissToast(toast);
                    });
                };
            })();
        ''')
        self.chart.run_script('''
            window.renderBacktestCharts = (data) => {
                const equityCurve   = Array.isArray(data.equity_curve)   ? data.equity_curve   : [];
                const drawdownCurve = Array.isArray(data.drawdown_curve) ? data.drawdown_curve : [];
                const initialBal    = Number(data.initial_balance || 10000);

                const equitySection   = document.getElementById("tv-backtest-equity-section");
                const drawdownSection = document.getElementById("tv-backtest-drawdown-section");
                const equitySvg       = document.getElementById("tv-backtest-equity-svg");
                const drawdownSvg     = document.getElementById("tv-backtest-drawdown-svg");

                const downsample = (arr, maxPts) => {
                    if (arr.length <= maxPts) return arr;
                    const step = Math.floor(arr.length / maxPts);
                    return arr.filter((_, i) => i % step === 0);
                };

                const toPoints = (samples, getVal) => {
                    if (samples.length < 2) return [];
                    const vals = samples.map(getVal);
                    const minV = Math.min(...vals);
                    const maxV = Math.max(...vals);
                    const rangeV = maxV - minV || 1;
                    const W = 280, H = 60, PAD = 4;
                    return samples.map((_, i) => {
                        const x = (i / (samples.length - 1)) * W;
                        const y = PAD + (1 - (vals[i] - minV) / rangeV) * (H - 2 * PAD);
                        return x.toFixed(1) + "," + y.toFixed(1);
                    });
                };

                if (equitySvg && equityCurve.length >= 2) {
                    const samples   = downsample(equityCurve, 300);
                    const pts       = toPoints(samples, p => p.equity);
                    const finalEq   = samples[samples.length - 1].equity;
                    const lineColor = finalEq >= initialBal ? "#26a69a" : "#ef5350";
                    equitySvg.innerHTML = "";
                    const poly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
                    poly.setAttribute("points", pts.join(" "));
                    poly.setAttribute("fill", "none");
                    poly.setAttribute("stroke", lineColor);
                    poly.setAttribute("stroke-width", "1.5");
                    poly.setAttribute("stroke-linejoin", "round");
                    poly.setAttribute("stroke-linecap", "round");
                    equitySvg.appendChild(poly);
                    if (equitySection) equitySection.style.display = "";
                }

                if (drawdownSvg && drawdownCurve.length >= 2) {
                    const samples = downsample(drawdownCurve, 300);
                    const pts     = toPoints(samples, p => p.drawdown_pct);
                    const W = 280, PAD = 4;
                    const pathD = "M 0," + PAD + " L " + pts.join(" L ") + " L " + W + "," + PAD + " Z";
                    drawdownSvg.innerHTML = "";
                    const pathEl = document.createElementNS("http://www.w3.org/2000/svg", "path");
                    pathEl.setAttribute("d", pathD);
                    pathEl.setAttribute("fill", "rgba(239,83,80,0.25)");
                    pathEl.setAttribute("stroke", "#ef5350");
                    pathEl.setAttribute("stroke-width", "1.2");
                    pathEl.setAttribute("stroke-linejoin", "round");
                    drawdownSvg.appendChild(pathEl);
                    if (drawdownSection) drawdownSection.style.display = "";
                }
            };
        ''')
        self.chart.run_script('''
            window.renderBacktestComparison = (data) => {
                const cmpEl    = document.getElementById("tv-backtest-comparison-results");
                const tbody    = document.getElementById("tv-backtest-comparison-tbody");
                const statusEl = document.getElementById("tv-backtest-status");
                const errorEl  = document.getElementById("tv-backtest-error");
                if (!cmpEl || !tbody) return;

                const running = !!data.comparison_running;
                const err     = data.comparison_error || "";
                const result  = data.comparison_result || null;

                if (statusEl) {
                    if (running) statusEl.innerText = "Comparando estrategias...";
                    else if (result) statusEl.innerText = "Comparación completada";
                    else statusEl.innerText = "Sin ejecución todavía.";
                }
                if (errorEl) {
                    errorEl.innerText = err;
                    errorEl.style.display = err ? "block" : "none";
                }

                ["tv-backtest-results", "tv-backtest-extra-cards",
                 "tv-backtest-equity-section", "tv-backtest-drawdown-section",
                 "tv-backtest-trades-section"].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.style.display = "none";
                });

                if (!result || !Array.isArray(result.strategies) || result.strategies.length === 0) {
                    cmpEl.style.display = "none";
                    return;
                }

                tbody.innerHTML = "";
                result.strategies.forEach(entry => {
                    const tr = document.createElement("tr");
                    if (entry.status === "error") {
                        const td0 = document.createElement("td");
                        td0.innerText = entry.strategy_label || entry.strategy_key || "?";
                        const td1 = document.createElement("td");
                        td1.colSpan = 5;
                        td1.className = "cmp-error";
                        td1.innerText = "Error: " + (entry.error || "desconocido");
                        tr.appendChild(td0);
                        tr.appendChild(td1);
                    } else {
                        const retPct  = Number(entry.total_return_pct || 0);
                        const pf      = Number(entry.profit_factor    || 0);
                        const maxDD   = Number(entry.max_drawdown     || 0);
                        const winRate = Number(entry.win_rate         || 0);
                        const ops     = Number(entry.closed_trades    || 0);

                        const cells = [
                            {text: entry.strategy_label || entry.strategy_key || "?", cls: ""},
                            {text: String(ops),                                         cls: ""},
                            {text: winRate.toFixed(1) + "%",                            cls: winRate >= 50 ? "cmp-win" : "cmp-loss"},
                            {text: maxDD.toFixed(2) + "%",                              cls: maxDD > 10 ? "cmp-loss" : ""},
                            {text: (retPct >= 0 ? "+" : "") + retPct.toFixed(2) + "%", cls: retPct >= 0 ? "cmp-win" : "cmp-loss"},
                            {text: pf > 0 ? pf.toFixed(2) : "--",                       cls: pf >= 1 ? "cmp-win" : (pf > 0 ? "cmp-loss" : "")},
                        ];
                        cells.forEach(c => {
                            const td = document.createElement("td");
                            td.innerText = c.text;
                            if (c.cls) td.className = c.cls;
                            tr.appendChild(td);
                        });
                    }
                    tbody.appendChild(tr);
                });

                cmpEl.style.display = "";
            };
        ''')

    def _style_quote_widgets(self):
        # esta funcion sirve para aplicar estilo a los widgets de cotizacion.
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
        # esta funcion sirve para aplicar estilo al widget de balance.
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
        # esta funcion sirve para actualizar el widget de balance.
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
        # esta funcion sirve para conectar acciones de cotizacion.
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
        # esta funcion sirve para reaccionar a trade rapido.
        side = (side or "").lower()
        if side not in ("buy", "sell"):
            return
        try:
            market_open, market_status = self._broker.is_market_open(config.SYMBOL)
            if not market_open:
                self.log_message(f"Mercado cerrado ({market_status})")
                return
            selected_entry = self._get_selected_strategy_entry()
            timeframe_value = self._strategy_timeframe_value(selected_entry, fallback=config.TIMEFRAME)
            strategy_key = selected_entry.get("key", "") if isinstance(selected_entry, dict) else ""
            strategy_label = selected_entry.get("label", "") if isinstance(selected_entry, dict) else ""
            action_info = self._broker.apply_signal(
                config.SYMBOL,
                side,
                config.LOT,
                config.SL_POINTS,
                config.TP_POINTS,
                self._selected_strategy_magic(),
                strategy_key=strategy_key,
                strategy_label=strategy_label,
                signal_reason="trade_manual_rapido"
            )
            if action_info:
                self.update_last_action_ui(action_info)
        except Exception as e:
            self.log_message(f"Error al ejecutar {side.upper()}: {e}")

    def _hide_non_visual_widgets(self):
        # esta funcion sirve para ocultar widgets no visuales.
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
        # esta funcion sirve para actualizar la caja de cotizacion.
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
        # esta funcion sirve para actualizar cotizaciones.
        """Actualiza las cotizaciones BUY/SELL y el spread."""
        if not getattr(self, '_mt5_available', False):
            return
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
        # esta funcion sirve para iniciar cotizacion actualizador.
        """Inicia un hilo para refrescar cotizaciones periódicamente."""
        if self.quote_thread and self.quote_thread.is_alive():
            return
        self.quote_stop_event.clear()
        self.quote_thread = threading.Thread(target=self._quote_loop, daemon=True)
        self.quote_thread.start()

    def stop_quote_updater(self):
        # esta funcion sirve para detener cotizacion actualizador.
        """Detiene el hilo de cotizaciones."""
        self.quote_stop_event.set()

    def start_callback_pump(self):
        # esta funcion sirve para iniciar retorno bomba.
        """Inicia el loop que procesa callbacks JS (botones, selectores, etc.)."""
        if self.callback_thread and self.callback_thread.is_alive():
            return
        self.callback_stop_event.clear()
        self.callback_thread = threading.Thread(target=self._callback_loop, daemon=True)
        self.callback_thread.start()

    def stop_callback_pump(self):
        # esta funcion sirve para detener retorno bomba.
        """Detiene el loop de callbacks JS."""
        self.callback_stop_event.set()

    def _callback_loop(self):
        # esta funcion sirve para ciclo de retorno.
        last_queue_error_ts = 0.0
        while not self.callback_stop_event.is_set():
            try:
                response = Chart.WV.emit_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            except Exception as e:
                now_ts = time.time()
                if (now_ts - last_queue_error_ts) >= 5:
                    self.log_message(f"Error en cola de callbacks: {e}")
                    last_queue_error_ts = now_ts
                if self.callback_stop_event.wait(timeout=0.2):
                    break
                continue

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
        # esta funcion sirve para ciclo de cotizaciones.
        while not self.quote_stop_event.is_set():
            self.update_quotes()
            self.update_bottom_clock()
            if self.quote_stop_event.wait(timeout=2):
                break

    def setup_side_panel(self):
        # esta funcion sirve para preparar panel lateral.
        """Crea el panel lateral con noticias, sugerencias y panel clásico."""
        self.side_panel_handler = 'side_panel_evt'
        self.chart.win.handlers[self.side_panel_handler] = self.on_side_panel_event

        self._refresh_object_tree_items(render=False)
        items = self.object_tree_items
        self._build_side_panel(items)
        self._render_strategy_panel()
        self._build_strategy_builder_ui()

    def _build_side_panel(self, items):
        # esta funcion sirve para construir panel lateral.
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
            "backtest": self._get_backtest_payload(),
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
            const tabBacktest = document.createElement("div");
            tabBacktest.className = "tv-side-tab";
            tabBacktest.innerText = "Backtest";
            legacyTabs.appendChild(tabObjects);
            legacyTabs.appendChild(tabData);
            legacyTabs.appendChild(tabStrategies);
            legacyTabs.appendChild(tabBacktest);

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

            const backtestPanel = document.createElement("div");
            backtestPanel.id = "tv-backtest-panel";
            backtestPanel.className = "tv-backtest-panel";
            backtestPanel.style.display = "none";
            backtestPanel.innerHTML = `
                <div class="tv-backtest-header">
                    <div class="tv-backtest-title">Backtest</div>
                    <div class="tv-backtest-subtitle">Simulación histórica sin tocar el motor live.</div>
                </div>
                <div class="tv-backtest-form">
                    <div class="tv-backtest-field">
                        <div class="tv-backtest-mode-toggle">
                            <button type="button" class="tv-backtest-mode-btn active" id="tv-backtest-mode-single">Individual</button>
                            <button type="button" class="tv-backtest-mode-btn" id="tv-backtest-mode-compare">Comparar</button>
                        </div>
                        <label>Estrategia</label>
                        <select id="tv-backtest-strategy"></select>
                        <div class="tv-backtest-strategy-checks" id="tv-backtest-strategy-checks" style="display:none;"></div>
                    </div>
                    <div class="tv-backtest-field">
                        <label>Símbolo</label>
                        <select id="tv-backtest-symbol"></select>
                    </div>
                    <div class="tv-backtest-field">
                        <label>Fuente de datos</label>
                        <select id="tv-backtest-datasource">
                            <option value="mt5">MT5</option>
                            <option value="dukascopy">Dukascopy</option>
                        </select>
                        <div id="tv-backtest-dukascopy-warn" style="display:none; margin-top:5px; font-size:11px; color:#e6a817; line-height:1.4;">
                            Paquete no instalado. Ejecuta:<br>
                            <code style="user-select:all; color:#f0c060;">pip install "dukascopy-python&gt;=4.0.1"</code>
                        </div>
                    </div>
                    <div class="tv-backtest-field readonly">
                        <label>Timeframe</label>
                        <div class="tv-backtest-readonly" id="tv-backtest-timeframe">--</div>
                    </div>
                    <div class="tv-backtest-field tv-backtest-presets">
                        <label>Ventana</label>
                        <div class="tv-backtest-preset-list" id="tv-backtest-presets"></div>
                    </div>
                    <div class="tv-backtest-field">
                        <label>Fecha inicio</label>
                        <input id="tv-backtest-start" type="date" />
                    </div>
                    <div class="tv-backtest-field">
                        <label>Fecha fin</label>
                        <input id="tv-backtest-end" type="date" />
                    </div>
                    <div class="tv-backtest-field">
                        <label>Balance inicial</label>
                        <input id="tv-backtest-balance" type="number" min="0" step="0.01" />
                    </div>
                </div>
                <div class="tv-backtest-actions">
                    <button type="button" id="tv-backtest-run">Ejecutar backtest</button>
                    <button type="button" id="tv-backtest-compare-btn" style="display:none;">Comparar estrategias</button>
                    <div class="tv-backtest-status" id="tv-backtest-status">Sin ejecución todavía.</div>
                </div>
                <div class="tv-backtest-error" id="tv-backtest-error"></div>
                <div class="tv-backtest-results" id="tv-backtest-results"></div>
                <div class="tv-backtest-results" id="tv-backtest-extra-cards" style="display:none;"></div>
                <div class="tv-backtest-section" id="tv-backtest-equity-section" style="display:none;">
                    <div class="tv-backtest-section-title">Curva de equity</div>
                    <svg class="tv-backtest-microchart" id="tv-backtest-equity-svg"
                         viewBox="0 0 280 60" preserveAspectRatio="none"></svg>
                </div>
                <div class="tv-backtest-section" id="tv-backtest-drawdown-section" style="display:none;">
                    <div class="tv-backtest-section-title">Drawdown</div>
                    <svg class="tv-backtest-microchart" id="tv-backtest-drawdown-svg"
                         viewBox="0 0 280 60" preserveAspectRatio="none"></svg>
                </div>
                <div class="tv-backtest-section" id="tv-backtest-trades-section" style="display:none;">
                    <div class="tv-backtest-section-title">Trades</div>
                    <div class="tv-backtest-trades-wrapper">
                        <table class="tv-backtest-trades-table" id="tv-backtest-trades-table">
                            <thead>
                                <tr>
                                    <th>#</th>
                                    <th>Tipo</th>
                                    <th>Hora ent.</th>
                                    <th>Hora sal.</th>
                                    <th>P. ent.</th>
                                    <th>P. sal.</th>
                                    <th>P&amp;L</th>
                                    <th>Razón</th>
                                </tr>
                            </thead>
                            <tbody id="tv-backtest-trades-tbody"></tbody>
                        </table>
                    </div>
                </div>
                <div class="tv-backtest-section" id="tv-backtest-comparison-results" style="display:none;">
                    <div class="tv-backtest-section-title">Comparación de estrategias</div>
                    <div class="tv-backtest-comparison-wrapper">
                        <table class="tv-backtest-comparison-table" id="tv-backtest-comparison-table">
                            <thead>
                                <tr>
                                    <th>Estrategia</th>
                                    <th>Ops</th>
                                    <th>Win%</th>
                                    <th>Max DD%</th>
                                    <th>Ret%</th>
                                    <th>PF</th>
                                </tr>
                            </thead>
                            <tbody id="tv-backtest-comparison-tbody"></tbody>
                        </table>
                    </div>
                </div>
            `;

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

            let riskWidget = document.getElementById("tv-risk-widget");
            if (!riskWidget) {{
                riskWidget = document.createElement("div");
                riskWidget.id = "tv-risk-widget";
                riskWidget.className = "tv-risk-widget";

                const riskLabel = document.createElement("span");
                riskLabel.className = "tv-risk-label";
                riskLabel.innerText = "Riesgo:";

                const riskValue = document.createElement("span");
                riskValue.id = "tv-risk-value";
                riskValue.className = "tv-risk-value";
                riskValue.innerText = "--";

                const riskSep = document.createElement("span");
                riskSep.className = "tv-risk-sep";
                riskSep.innerText = "/ 3.0%";

                riskWidget.appendChild(riskLabel);
                riskWidget.appendChild(riskValue);
                riskWidget.appendChild(riskSep);
            }}
            const stratPanelTitle = document.createElement("div");
            stratPanelTitle.className = "tv-strategy-panel-title";
            stratPanelTitle.innerText = "Gestión de estrategias";
            const stratPanelHint = document.createElement("div");
            stratPanelHint.className = "tv-strategy-panel-hint";
            stratPanelHint.innerText = "Activa, edita (✎) o ajusta parámetros (⚙) de cada estrategia.";
            strategyPanel.appendChild(stratPanelTitle);
            strategyPanel.appendChild(stratPanelHint);

            strategyPanel.appendChild(riskWidget);

            strategyPanel.appendChild(strategyList);
            strategyPanel.appendChild(strategyEmpty);
            strategyPanel.appendChild(runBox);
            strategyPanel.appendChild(toggleBtn);
            strategyPanel.appendChild(addBox);

            legacyPanel.appendChild(legacyTabs);
            legacyPanel.appendChild(strategyDataPanel);
            legacyPanel.appendChild(dataWindow);
            legacyPanel.appendChild(strategyPanel);
            legacyPanel.appendChild(backtestPanel);

            tabObjects.addEventListener("click", () => {{
                tabObjects.classList.add("active");
                tabData.classList.remove("active");
                tabStrategies.classList.remove("active");
                tabBacktest.classList.remove("active");
                strategyDataPanel.style.display = "flex";
                requestAnimationFrame(function() {{ strategyDataPanel.classList.remove('tv-tab-fade-in'); void strategyDataPanel.offsetWidth; strategyDataPanel.classList.add('tv-tab-fade-in'); }});
                dataWindow.style.display = "none";
                strategyPanel.style.display = "none";
                backtestPanel.style.display = "none";
            }});
            tabData.addEventListener("click", () => {{
                tabData.classList.add("active");
                tabObjects.classList.remove("active");
                tabStrategies.classList.remove("active");
                tabBacktest.classList.remove("active");
                strategyDataPanel.style.display = "none";
                dataWindow.style.display = "flex";
                requestAnimationFrame(function() {{ dataWindow.classList.remove('tv-tab-fade-in'); void dataWindow.offsetWidth; dataWindow.classList.add('tv-tab-fade-in'); }});
                strategyPanel.style.display = "none";
                backtestPanel.style.display = "none";
            }});
            tabStrategies.addEventListener("click", () => {{
                tabStrategies.classList.add("active");
                tabObjects.classList.remove("active");
                tabData.classList.remove("active");
                tabBacktest.classList.remove("active");
                strategyDataPanel.style.display = "none";
                dataWindow.style.display = "none";
                strategyPanel.style.display = "block";
                requestAnimationFrame(function() {{ strategyPanel.classList.remove('tv-tab-fade-in'); void strategyPanel.offsetWidth; strategyPanel.classList.add('tv-tab-fade-in'); }});
                backtestPanel.style.display = "none";
            }});
            tabBacktest.addEventListener("click", () => {{
                tabBacktest.classList.add("active");
                tabObjects.classList.remove("active");
                tabData.classList.remove("active");
                tabStrategies.classList.remove("active");
                strategyDataPanel.style.display = "none";
                dataWindow.style.display = "none";
                strategyPanel.style.display = "none";
                backtestPanel.style.display = "block";
                requestAnimationFrame(function() {{ backtestPanel.classList.remove('tv-tab-fade-in'); void backtestPanel.offsetWidth; backtestPanel.classList.add('tv-tab-fade-in'); }});
            }});

            panel.appendChild(newsPanel);
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

            let toastContainer = document.getElementById('tv-toast-container');
            if (!toastContainer) {{
                toastContainer = document.createElement('div');
                toastContainer.id = 'tv-toast-container';
                document.body.appendChild(toastContainer);
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

            window.tvBacktest = window.tvBacktest || {{}};
            window.tvBacktest.formatMoney = (value) => {{
                const num = Number(value);
                if (!Number.isFinite(num)) return "--";
                return num.toLocaleString(undefined, {{
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                }});
            }};
            window.tvBacktest.formatDate = (epoch) => {{
                if (epoch === null || epoch === undefined) return "--";
                const dt = new Date(Number(epoch) * 1000);
                if (Number.isNaN(dt.getTime())) return "--";
                return dt.toLocaleDateString();
            }};
            window.tvBacktest.formatDateTime = (epoch) => {{
                if (epoch === null || epoch === undefined) return "--";
                const dt = new Date(Number(epoch) * 1000);
                if (Number.isNaN(dt.getTime())) return "--";
                const dateStr = dt.toLocaleDateString(undefined, {{ month: "2-digit", day: "2-digit" }});
                const timeStr = dt.toLocaleTimeString(undefined, {{ hour: "2-digit", minute: "2-digit", hour12: false }});
                return dateStr + " " + timeStr;
            }};
            window.renderBacktestPanel = (data) => {{
                const state = window.tvBacktest.state || (window.tvBacktest.state = {{ form: {{}} }});
                const payloadData = data || {{}};
                state.handler = payloadData.handler || payload.handler;
                state.running = !!payloadData.running;
                state.comparison_running = !!payloadData.comparison_running;
                state.error = payloadData.error || "";
                state.result = payloadData.result || null;
                state.presets = payloadData.presets || {{}};
                state.dukascopy_available = !!payloadData.dukascopy_available;
                state.strategies = Array.isArray(payloadData.strategies) ? payloadData.strategies : [];
                state.symbols = Array.isArray(payloadData.symbols) ? payloadData.symbols : [];
                state.form = Object.assign({{}}, payloadData.form || {{}}, state.form || {{}});

                const strategySel = document.getElementById("tv-backtest-strategy");
                const symbolSel = document.getElementById("tv-backtest-symbol");
                const timeframeEl = document.getElementById("tv-backtest-timeframe");
                const presetsEl = document.getElementById("tv-backtest-presets");
                const startEl = document.getElementById("tv-backtest-start");
                const endEl = document.getElementById("tv-backtest-end");
                const balanceEl = document.getElementById("tv-backtest-balance");
                const datasourceSel = document.getElementById("tv-backtest-datasource");
                const runBtn = document.getElementById("tv-backtest-run");
                const statusEl = document.getElementById("tv-backtest-status");
                const errorEl = document.getElementById("tv-backtest-error");
                const resultsEl = document.getElementById("tv-backtest-results");
                if (!strategySel || !symbolSel || !datasourceSel || !timeframeEl || !presetsEl || !startEl || !endEl || !balanceEl || !runBtn || !statusEl || !errorEl || !resultsEl) return;

                strategySel.innerHTML = "";
                state.strategies.forEach((entry) => {{
                    if (!entry || !entry.key) return;
                    const option = document.createElement("option");
                    option.value = entry.key;
                    option.innerText = entry.label || entry.key;
                    option.disabled = !!entry.disabled;
                    strategySel.appendChild(option);
                }});
                const enabledStrategy = state.strategies.find((item) => item && item.key && !item.disabled);
                const anyStrategy = state.strategies.find((item) => item && item.key);
                const selectedStrategy = state.strategies.find((item) => item && item.key === state.form.strategy_key && !item.disabled);
                state.form.strategy_key = selectedStrategy ? selectedStrategy.key : (enabledStrategy ? enabledStrategy.key : (anyStrategy ? anyStrategy.key : ""));
                strategySel.value = state.form.strategy_key || "";

                symbolSel.innerHTML = "";
                state.symbols.forEach((symbol) => {{
                    const option = document.createElement("option");
                    option.value = symbol;
                    option.innerText = symbol;
                    symbolSel.appendChild(option);
                }});
                if (!state.symbols.includes(state.form.symbol)) {{
                    state.form.symbol = state.symbols.length ? state.symbols[0] : "";
                }}
                symbolSel.value = state.form.symbol || "";

                const updateTimeframe = () => {{
                    const selected = state.strategies.find((item) => item && item.key === state.form.strategy_key);
                    timeframeEl.innerText = selected && selected.timeframe ? selected.timeframe : (payloadData.timeframe || "--");
                }};

                const renderPresetButtons = () => {{
                    presetsEl.innerHTML = "";
                    Object.keys(state.presets || {{}}).forEach((key) => {{
                        const range = state.presets[key] || {{}};
                        const btn = document.createElement("button");
                        btn.type = "button";
                        btn.className = "tv-backtest-preset-btn" + ((state.form.preset || "").toUpperCase() === key ? " active" : "");
                        btn.innerText = key;
                        btn.addEventListener("click", () => {{
                            state.form.preset = key;
                            state.form.start_date = range.start || "";
                            state.form.end_date = range.end || "";
                            startEl.value = state.form.start_date || "";
                            endEl.value = state.form.end_date || "";
                            renderPresetButtons();
                        }});
                        presetsEl.appendChild(btn);
                    }});
                }};

                if (!state.form.start_date || !state.form.end_date) {{
                    const presetKey = (state.form.preset || "1M").toUpperCase();
                    const range = state.presets[presetKey] || state.presets["1M"] || {{}};
                    state.form.preset = range.start ? presetKey : "CUSTOM";
                    state.form.start_date = state.form.start_date || range.start || "";
                    state.form.end_date = state.form.end_date || range.end || "";
                }}

                startEl.value = state.form.start_date || "";
                endEl.value = state.form.end_date || "";
                balanceEl.value = state.form.initial_balance || "";
                datasourceSel.value = state.form.data_source || "mt5";
                updateTimeframe();
                renderPresetButtons();

                strategySel.onchange = () => {{
                    state.form.strategy_key = strategySel.value || "";
                    updateTimeframe();
                }};
                symbolSel.onchange = () => {{
                    state.form.symbol = symbolSel.value || "";
                }};
                const dukascopyWarn = document.getElementById("tv-backtest-dukascopy-warn");
                const updateDukascopyWarn = () => {{
                    const isDukascopy = (datasourceSel.value === "dukascopy");
                    const notAvail = isDukascopy && !state.dukascopy_available;
                    if (dukascopyWarn) dukascopyWarn.style.display = notAvail ? "block" : "none";
                }};
                datasourceSel.onchange = () => {{
                    state.form.data_source = datasourceSel.value || "mt5";
                    updateDukascopyWarn();
                }};
                updateDukascopyWarn();
                startEl.onchange = () => {{
                    state.form.start_date = startEl.value || "";
                    state.form.preset = "CUSTOM";
                    renderPresetButtons();
                }};
                endEl.onchange = () => {{
                    state.form.end_date = endEl.value || "";
                    state.form.preset = "CUSTOM";
                    renderPresetButtons();
                }};
                balanceEl.onchange = () => {{
                    state.form.initial_balance = balanceEl.value || "";
                }};

                runBtn.disabled = state.running || !state.form.strategy_key || !state.form.symbol;
                runBtn.innerText = state.running ? "Ejecutando..." : "Ejecutar backtest";
                runBtn.onclick = () => {{
                    const request = {{
                        strategy_key: state.form.strategy_key || "",
                        symbol: state.form.symbol || "",
                        preset: state.form.preset || "CUSTOM",
                        start_date: startEl.value || "",
                        end_date: endEl.value || "",
                        initial_balance: balanceEl.value || "",
                        data_source: datasourceSel.value || "mt5",
                    }};
                    if (window.callbackFunction && state.handler) {{
                        window.callbackFunction(state.handler + "_~_backtest_run;;;" + encodeURIComponent(JSON.stringify(request)));
                    }}
                }};

                errorEl.innerText = state.error || "";
                errorEl.style.display = state.error ? "block" : "none";

                if (state.running) {{
                    statusEl.innerText = "Ejecutando backtest...";
                }} else if (state.result && state.result.status === "success") {{
                    statusEl.innerText = "Backtest completado";
                }} else {{
                    statusEl.innerText = "Sin ejecución todavía.";
                }}

                if (!state.result || state.result.status !== "success") {{
                    resultsEl.innerHTML = "";
                    return;
                }}

                const result = state.result;
                const cards = [
                    ["Balance final", window.tvBacktest.formatMoney(result.final_balance)],
                    ["Profit total", window.tvBacktest.formatMoney(result.total_profit)],
                    ["Retorno %", Number(result.total_return_pct || 0).toFixed(2) + "%"],
                    ["Operaciones", String(result.closed_trades || 0)],
                    ["Win rate", Number(result.win_rate || 0).toFixed(2) + "%"],
                    ["Max DD", Number(result.max_drawdown || 0).toFixed(2) + "%"],
                    ["Rango", window.tvBacktest.formatDate(result.start_date) + " - " + window.tvBacktest.formatDate(result.end_date)],
                    ["TF", result.timeframe || "--"]
                ];
                resultsEl.innerHTML = "";
                cards.forEach((item) => {{
                    const card = document.createElement("div");
                    card.className = "tv-backtest-card";
                    const label = document.createElement("div");
                    label.className = "tv-backtest-card-label";
                    label.innerText = item[0];
                    const value = document.createElement("div");
                    value.className = "tv-backtest-card-value";
                    value.innerText = item[1];
                    card.appendChild(label);
                    card.appendChild(value);
                    resultsEl.appendChild(card);
                }});

                const exportBtn = document.createElement("button");
                exportBtn.type = "button";
                exportBtn.className = "tv-backtest-export-btn";
                exportBtn.innerText = "Exportar CSV";
                exportBtn.onclick = () => {{
                    if (window.callbackFunction && state.handler) {{
                        window.callbackFunction(state.handler + "_~_backtest_export_csv");
                    }}
                }};
                resultsEl.appendChild(exportBtn);

                const extraCardsEl = document.getElementById("tv-backtest-extra-cards");
                const equitySection = document.getElementById("tv-backtest-equity-section");
                const drawdownSection = document.getElementById("tv-backtest-drawdown-section");
                const tradesSection = document.getElementById("tv-backtest-trades-section");

                if (extraCardsEl) extraCardsEl.style.display = "none";
                if (equitySection) equitySection.style.display = "none";
                if (drawdownSection) drawdownSection.style.display = "none";
                if (tradesSection) tradesSection.style.display = "none";

                if (extraCardsEl) {{
                    const extraCards = [
                        ["Profit Factor", Number(result.profit_factor || 0).toFixed(2)],
                        ["Avg Win", window.tvBacktest.formatMoney(result.avg_win)],
                        ["Avg Loss", window.tvBacktest.formatMoney(result.avg_loss)],
                        ["Expectancy", window.tvBacktest.formatMoney(result.expectancy)],
                    ];
                    extraCardsEl.innerHTML = "";
                    extraCards.forEach((item) => {{
                        const card = document.createElement("div");
                        card.className = "tv-backtest-card";
                        const labelEl = document.createElement("div");
                        labelEl.className = "tv-backtest-card-label";
                        labelEl.innerText = item[0];
                        const valueEl = document.createElement("div");
                        valueEl.className = "tv-backtest-card-value";
                        valueEl.innerText = item[1];
                        card.appendChild(labelEl);
                        card.appendChild(valueEl);
                        extraCardsEl.appendChild(card);
                    }});
                    extraCardsEl.style.display = "";
                }}

                const trades = Array.isArray(result.trades) ? result.trades : [];
                if (tradesSection && trades.length > 0) {{
                    const tbody = document.getElementById("tv-backtest-trades-tbody");
                    if (tbody) {{
                        tbody.innerHTML = "";
                        const bDigits = Number.isInteger(result.digits) ? result.digits : 2;
                        trades.forEach((trade, idx) => {{
                            const pnl = Number(trade.profit || 0);
                            const pnlClass = pnl > 0 ? "tv-backtest-trade-win" : pnl < 0 ? "tv-backtest-trade-loss" : "";
                            const tipo = trade.direction === 1 ? "BUY" : "SELL";
                            const entryTime = window.tvBacktest.formatDateTime(trade.entry_time);
                            const exitTime = window.tvBacktest.formatDateTime(trade.exit_time);
                            const entryPx = window.tvDataWindow._formatValue(trade.entry_price, "price", bDigits);
                            const exitPx = window.tvDataWindow._formatValue(trade.exit_price, "price", bDigits);
                            const pnlText = (pnl >= 0 ? "+" : "") + window.tvBacktest.formatMoney(pnl);
                            const reason = String(trade.reason || "");

                            const row = document.createElement("tr");
                            const cellData = [
                                String(idx + 1),
                                tipo,
                                entryTime,
                                exitTime,
                                entryPx,
                                exitPx,
                                pnlText,
                                reason,
                            ];
                            cellData.forEach((text, colIdx) => {{
                                const td = document.createElement("td");
                                if (colIdx === 6) td.className = pnlClass;
                                td.innerText = text;
                                row.appendChild(td);
                            }});
                            tbody.appendChild(row);
                        }});
                    }}
                    tradesSection.style.display = "";
                }}

                // --- Mode toggle setup ---
                const modeSingleBtn  = document.getElementById("tv-backtest-mode-single");
                const modeCompareBtn = document.getElementById("tv-backtest-mode-compare");
                const checksEl       = document.getElementById("tv-backtest-strategy-checks");
                const compareBtn     = document.getElementById("tv-backtest-compare-btn");
                const runBtn_ref     = document.getElementById("tv-backtest-run");

                if (!state.backtest_mode) state.backtest_mode = "single";

                const applyMode = (mode) => {{
                    state.backtest_mode = mode;
                    const isCompare = mode === "compare";
                    if (modeSingleBtn)  modeSingleBtn.classList.toggle("active", !isCompare);
                    if (modeCompareBtn) modeCompareBtn.classList.toggle("active", isCompare);
                    if (strategySel)    strategySel.style.display  = isCompare ? "none" : "";
                    if (checksEl)       checksEl.style.display      = isCompare ? "" : "none";
                    if (runBtn_ref)     runBtn_ref.style.display     = isCompare ? "none" : "";
                    if (compareBtn)     compareBtn.style.display     = isCompare ? "" : "none";
                    const singleResultIds = [
                        "tv-backtest-results", "tv-backtest-extra-cards",
                        "tv-backtest-equity-section", "tv-backtest-drawdown-section",
                        "tv-backtest-trades-section"
                    ];
                    singleResultIds.forEach(id => {{
                        const el = document.getElementById(id);
                        if (el) el.style.display = isCompare ? "none" : "";
                    }});
                    const cmpEl = document.getElementById("tv-backtest-comparison-results");
                    if (cmpEl) cmpEl.style.display = isCompare ? "" : "none";
                }};

                if (modeSingleBtn && !modeSingleBtn.dataset.modeBound) {{
                    modeSingleBtn.dataset.modeBound = "1";
                    modeSingleBtn.addEventListener("click", () => applyMode("single"));
                }}
                if (modeCompareBtn && !modeCompareBtn.dataset.modeBound) {{
                    modeCompareBtn.dataset.modeBound = "1";
                    modeCompareBtn.addEventListener("click", () => applyMode("compare"));
                }}

                if (checksEl) {{
                    const checkedKeys = new Set();
                    checksEl.querySelectorAll("input[type='checkbox']:checked").forEach(cb => checkedKeys.add(cb.value));
                    checksEl.innerHTML = "";
                    state.strategies.forEach(entry => {{
                        if (!entry || !entry.key) return;
                        const row = document.createElement("div");
                        row.className = "tv-backtest-strategy-check-row" + (entry.disabled ? " disabled" : "");
                        const cb = document.createElement("input");
                        cb.type = "checkbox";
                        cb.value = entry.key;
                        cb.disabled = !!entry.disabled;
                        cb.checked = checkedKeys.has(entry.key);
                        const lbl = document.createElement("label");
                        lbl.innerText = entry.label || entry.key;
                        row.appendChild(cb);
                        row.appendChild(lbl);
                        row.addEventListener("click", () => {{ if (!entry.disabled) cb.checked = !cb.checked; }});
                        cb.addEventListener("click", e => e.stopPropagation());
                        checksEl.appendChild(row);
                    }});
                }}

                if (compareBtn && !compareBtn.dataset.compareBound) {{
                    compareBtn.dataset.compareBound = "1";
                    compareBtn.addEventListener("click", () => {{
                        if (!checksEl) return;
                        const selectedKeys = [];
                        checksEl.querySelectorAll("input[type='checkbox']:checked").forEach(cb => {{
                            if (!cb.disabled) selectedKeys.push(cb.value);
                        }});
                        if (selectedKeys.length < 2) {{
                            const statusEl = document.getElementById("tv-backtest-status");
                            if (statusEl) statusEl.innerText = "Selecciona al menos 2 estrategias para comparar";
                            return;
                        }}
                        if (state.comparison_running) {{
                            const statusEl = document.getElementById("tv-backtest-status");
                            if (statusEl) statusEl.innerText = "Comparación en ejecución...";
                            return;
                        }}
                        const request = {{
                            strategy_keys:   selectedKeys,
                            symbol:          state.form.symbol || "",
                            preset:          state.form.preset || "CUSTOM",
                            start_date:      (document.getElementById("tv-backtest-start") || {{}}).value || "",
                            end_date:        (document.getElementById("tv-backtest-end") || {{}}).value || "",
                            initial_balance: (document.getElementById("tv-backtest-balance") || {{}}).value || "",
                            data_source:     (document.getElementById("tv-backtest-datasource") || {{}}).value || "mt5",
                        }};
                        if (window.callbackFunction && state.handler) {{
                            window.callbackFunction(state.handler + "_~_backtest_compare;;;" + encodeURIComponent(JSON.stringify(request)));
                        }}
                    }});
                }}

                applyMode(state.backtest_mode || "single");
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
                        const handler = (data && data.handler) ? data.handler : "";
                        const strategyKey = encodeURIComponent(String(strategy.key || ""));
                        if (!handler || !strategyKey) {{
                            return;
                        }}
                        const strategyName = strategy.label || strategy.key || "estrategia";
                        const actionText = strategy.enabled ? "desactivar" : "activar";
                        const runToggle = () => {{
                            window.callbackFunction(handler + "_~_strategy_enable_toggle;;;" + strategyKey);
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

                    // Acciones por fila (Editar/Params) integradas aquí para que persistan
                    // en cada re-render (antes vivían en una segunda pasada que se perdía).
                    const actions = document.createElement("div");
                    actions.className = "tv-strategy-actions";
                    if (strategy.has_config) {{
                        const editBtn = document.createElement("button");
                        editBtn.type = "button";
                        editBtn.className = "tv-strategy-edit-btn";
                        editBtn.innerText = "✎ Editar";
                        editBtn.title = "Editar esta estrategia en el Builder";
                        editBtn.addEventListener("click", (e) => {{
                            e.stopPropagation();
                            const handler = (data && data.handler) ? data.handler : "";
                            const k = encodeURIComponent(String(strategy.key || ""));
                            if (handler && k) window.callbackFunction(handler + "_~_strategy_builder_open;;;" + k);
                        }});
                        actions.appendChild(editBtn);
                    }}
                    if (strategy.has_params) {{
                        const paramsBtn = document.createElement("button");
                        paramsBtn.type = "button";
                        paramsBtn.className = "tv-strategy-params-btn";
                        paramsBtn.innerText = "⚙ Params";
                        paramsBtn.title = "Ajustar parámetros de esta estrategia";
                        paramsBtn.addEventListener("click", (e) => {{
                            e.stopPropagation();
                            const handler = (data && data.handler) ? data.handler : "";
                            const k = encodeURIComponent(String(strategy.key || ""));
                            if (handler && k) window.callbackFunction(handler + "_~_strategy_params_open;;;" + k);
                        }});
                        actions.appendChild(paramsBtn);
                    }}

                    left.appendChild(title);
                    left.appendChild(module);
                    left.appendChild(timeframe);
                    left.appendChild(statusLine);
                    right.appendChild(enableBtn);
                    if (actions.childNodes.length) right.appendChild(actions);
                    right.appendChild(lastRun);
                    row.appendChild(left);
                    row.appendChild(right);

                    row.addEventListener("click", () => {{
                        const handler = (data && data.handler) ? data.handler : "";
                        const strategyKey = encodeURIComponent(String(strategy.key || ""));
                        if (!handler || !strategyKey) {{
                            return;
                        }}
                        window.callbackFunction(handler + "_~_strategy_select;;;" + strategyKey);
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
                        status.innerText = "Motor activo · " + activeCount + " activa(s)";
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
            if (window.renderBacktestPanel) {{
                window.renderBacktestPanel(payload.backtest || {{}});
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
                if (!Number.isFinite(num)) return "--";
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
                    // 'percent' espera un ratio (0.05 -> "5.00%"), convencion de las estrategias generadas.
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
                    entry.innerText = trade.exit_cause
                        ? ((trade.entry || "OUT") + " · " + trade.exit_cause)
                        : (trade.entry || "");

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
                    if (typeof trade.profit === "number" && Number.isFinite(trade.profit)) {{
                        const sign = trade.profit >= 0 ? "+" : "";
                        const pl = (window.tvBacktest && window.tvBacktest.formatMoney)
                            ? window.tvBacktest.formatMoney(trade.profit)
                            : trade.profit.toFixed(2);
                        profit.innerText = "P/L " + sign + pl;
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

                    const tradeExtra = [];
                    if (trade.strategy) tradeExtra.push("Estrategia: " + trade.strategy);
                    if (trade.reason) tradeExtra.push("Motivo: " + trade.reason);
                    if (trade.comment) tradeExtra.push("MT5: " + trade.comment);
                    if (tradeExtra.length) {{
                        const comment = document.createElement("div");
                        comment.className = "tv-trade-comment";
                        comment.innerText = tradeExtra.join(" | ");
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
                }}
            ];
            const buttons = {{}};
            const activate = (key) => {{
                newsPanel.style.display = key === "news" ? "flex" : "none";
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
        # esta funcion sirve para reaccionar a panel lateral evento.
        action = (action or "").strip()
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
            key = unquote(args[0]) if len(args) > 0 else ""
            self._set_strategy_by_key(key)
            return
        if action == "strategy_enable_toggle" and args:
            key = unquote(args[0]) if len(args) > 0 else ""
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
        if action == "backtest_run" and args:
            json_str = unquote(args[0]) if len(args) > 0 else ""
            self._on_backtest_run(json_str)
            return
        if action == "backtest_compare" and args:
            json_str = unquote(args[0]) if len(args) > 0 else ""
            self._on_backtest_compare(json_str)
            return
        if action == "backtest_export_csv":
            self._on_backtest_export_csv()
            return
        if action == "strategy_builder_new":
            self._on_strategy_builder_new()
            return
        if action == "strategy_builder_open" and args:
            key = unquote(args[0]) if len(args) > 0 else ""
            self._on_strategy_builder_open(key)
            return
        if action == "strategy_builder_preview" and args:
            json_str = unquote(args[0]) if len(args) > 0 else ""
            self._on_strategy_builder_preview(json_str)
            return
        if action == "strategy_builder_close":
            self._clear_strategy_builder_preview(refresh=True)
            return
        if action == "strategy_builder_save" and args:
            json_str = unquote(args[0]) if len(args) > 0 else ""
            self._on_strategy_builder_save(json_str)
            return
        if action == "strategy_params_open" and args:
            key = unquote(args[0]) if len(args) > 0 else ""
            self._on_strategy_params_open(key)
            return
        if action == "strategy_params_save" and args:
            key = unquote(args[0]) if len(args) > 0 else ""
            overrides_json = unquote(args[1]) if len(args) > 1 else ""
            self._on_strategy_params_save(key, overrides_json)
            return

    def _on_strategy_params_open(self, key: str):
        # esta funcion sirve para abrir el panel de edición rápida de parámetros.
        key = (key or "").strip()
        entry = self._get_strategy_entry(key)
        if not entry:
            return
        params_schema = entry.get("params_schema")
        if not isinstance(params_schema, dict) or len(params_schema) == 0:
            return
        params_values = entry.get("params_values") or {}
        payload = json.dumps({
            "key": key,
            "label": entry.get("label") or key,
            "schema": params_schema,
            "values": params_values,
            "handler": self.side_panel_handler,
        })
        self.chart.run_script(f"""
            ;(function() {{
                const payload = {payload};
                if (window.openParamsPanel) {{
                    window.openParamsPanel(payload);
                }}
            }})();
        """)

    def _on_strategy_params_save(self, key: str, overrides_json: str):
        # esta funcion sirve para guardar parámetros editados de estrategia.
        key = (key or "").strip()
        entry = self._get_strategy_entry(key)
        if not entry:
            return
        params_schema = entry.get("params_schema")
        if not isinstance(params_schema, dict) or len(params_schema) == 0:
            return
        overrides_json = (overrides_json or "").strip()
        try:
            overrides = json.loads(overrides_json)
        except Exception:
            overrides = {}
        if not isinstance(overrides, dict):
            overrides = {}
        validated = {}
        for param_key, value in overrides.items():
            schema_entry = params_schema.get(param_key)
            if not schema_entry:
                continue
            type_str = schema_entry.get("type", "float")
            min_val = schema_entry.get("min")
            max_val = schema_entry.get("max")
            try:
                if type_str == "int":
                    coerced = int(round(float(value)))
                else:
                    coerced = float(value)
            except (TypeError, ValueError):
                continue
            if min_val is not None:
                coerced = max(min_val, coerced)
            if max_val is not None:
                coerced = min(max_val, coerced)
            validated[param_key] = coerced
        strategy_dir = self._get_strategy_dir()
        module_obj = entry.get("module_obj")
        module_file = getattr(module_obj, "__file__", None) if module_obj else None
        if module_file and not module_file.startswith("<"):
            params_json_path = os.path.splitext(module_file)[0] + ".params.json"
        else:
            params_json_path = os.path.join(strategy_dir, f"{key}.params.json")
        try:
            with open(params_json_path, "w", encoding="utf-8") as f:
                json.dump(validated, f, indent=2)
        except Exception as e:
            self.log_message(f"Error guardando .params.json para {key}: {e}")
            return
        self._load_strategy_entry(entry)
        # Actualizar params_values en el registry para que el panel refleje los nuevos valores
        merged = {k: entry["params_schema"][k]["default"] for k in entry["params_schema"]}
        merged.update(validated)
        entry["params_values"] = merged
        msg_escaped = json.dumps("Parámetros guardados. Se aplicarán en el próximo ciclo.")
        self.chart.run_script(f"""
            ;(function() {{
                if (window.setParamsMessage) {{
                    window.setParamsMessage({msg_escaped});
                }}
            }})();
        """)

    def _toggle_strategy_run(self):
        # este boton enciende o apaga el motor que ejecuta las estrategias.
        """Inicia o detiene el motor de estrategias desde el panel."""
        thread_alive = self.bot_thread is not None and self.bot_thread.is_alive()
        if self.bot_running and thread_alive:
            self.stop_bot()
            return
        if self.bot_running and not thread_alive:
            # Estado inconsistente: el hilo no está vivo pero el flag sigue activo.
            self.bot_running = False
        self.start_bot()

    def _on_strategy_builder_new(self):
        # esta funcion sirve para abrir el constructor de estrategias vacío.
        import random
        used_magics = {int(e.get("magic_number") or 0) for e in self.strategy_registry.values()}
        while True:
            magic = random.randint(10000, 99999)
            if magic not in used_magics:
                break
        payload = json.dumps({
            "is_new": True,
            "magic_number": magic,
            "editing_key": None,
            "name": "",
            "display_name": "",
            "timeframe": "M1",
            "indicators": [],
            "buy_condition": {"type": "AND", "children": []},
            "sell_condition": {"type": "AND", "children": []},
            "handler": self.side_panel_handler,
        })
        self._apply_strategy_builder_preview(payload)
        self.chart.run_script(f'''
            ;(function() {{
                const payload = {payload};
                if (window.openStrategyBuilder) {{
                    window.openStrategyBuilder(payload);
                }}
            }})();
        ''')

    def _on_strategy_builder_open(self, key: str):
        # esta funcion sirve para abrir el constructor de estrategias con datos existentes.
        key = (key or "").strip()
        entry = self._get_strategy_entry(key)
        if not entry:
            self.chart.run_script(f'''
                ;(function() {{
                    if (window.openStrategyBuilderError) {{
                        window.openStrategyBuilderError("Estrategia no encontrada: {key}");
                    }}
                }})();
            ''')
            return
        strategy_dir = self._get_strategy_dir()
        builder_name = self._strategy_builder_name(key)
        json_path = os.path.join(strategy_dir, f"strategy_{builder_name}.json")
        if not os.path.isfile(json_path):
            self.chart.run_script('''
                ;(function() {
                    if (window.openStrategyBuilderError) {
                        window.openStrategyBuilderError("No se encontró la configuración editable para esta estrategia.");
                    }
                })();
            ''')
            return
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception as e:
            err_escaped = json.dumps(str(e))
            self.chart.run_script(f'''
                ;(function() {{
                    if (window.openStrategyBuilderError) {{
                        window.openStrategyBuilderError("Error al leer configuración: " + {err_escaped});
                    }}
                }})();
            ''')
            return
        config_data["is_new"] = False
        # editing_key debe ser el nombre "builder" sin prefijo para que handle_save_edit
        # localice strategy_<name>.json al guardar.
        config_data["editing_key"] = builder_name
        config_data["handler"] = self.side_panel_handler
        self._apply_strategy_builder_preview(config_data)
        payload = json.dumps(config_data)
        self.chart.run_script(f'''
            ;(function() {{
                const payload = {payload};
                if (window.openStrategyBuilder) {{
                    window.openStrategyBuilder(payload);
                }}
            }})();
        ''')

    def _get_builder_preview_entry(self):
        # esta funcion sirve para obtener la estrategia temporal del builder.
        if not getattr(self, "builder_preview_active", False):
            return None
        entry = getattr(self, "builder_preview_entry", None)
        if not isinstance(entry, dict):
            return None
        if entry.get("module_obj") is None:
            return None
        return entry

    def _get_strategy_builder_module(self):
        # esta funcion sirve para cargar el modulo generador del builder.
        module = getattr(self, "_strategy_builder_module_cache", None)
        if module is not None:
            return module
        module = importlib.import_module("backend.strategy_builder.generator")
        self._strategy_builder_module_cache = module
        return module

    def _normalize_builder_preview_condition(self, node, available_columns: set):
        # esta funcion sirve para sanear una condicion para la previsualizacion.
        fallback_left = "close" if "close" in available_columns else next(iter(sorted(available_columns)), "open")
        if not isinstance(node, dict):
            return None

        node_type = str(node.get("type") or "").upper()
        if node_type == "CONDITION":
            left = node.get("left")
            if left not in available_columns:
                left = fallback_left

            op = node.get("op")
            if op not in {"<", ">", "<=", ">=", "==", "!="}:
                op = ">"

            right = node.get("right")
            if isinstance(right, str):
                if right not in available_columns:
                    right = 0
            elif not isinstance(right, (int, float)):
                right = 0

            return {
                "type": "condition",
                "left": left,
                "op": op,
                "right": right,
            }

        if node_type in {"AND", "OR"}:
            children = []
            for child in node.get("children", []):
                normalized = self._normalize_builder_preview_condition(child, available_columns)
                if normalized is not None:
                    children.append(normalized)

            if len(children) >= 2:
                return {"type": node_type, "children": children}
            if len(children) == 1:
                return children[0]
            return None

        return None

    def _build_strategy_builder_preview_config(self, config_data: dict) -> dict:
        # esta funcion sirve para preparar una configuracion valida para previsualizacion.
        preview_config = copy.deepcopy(config_data if isinstance(config_data, dict) else {})

        raw_name = str(preview_config.get("name") or "").strip()
        if not re.match(r'^[a-z][a-z0-9_]*$', raw_name):
            raw_name = "builder_preview"

        display_name = str(preview_config.get("display_name") or "").strip() or "Builder Preview"
        schema_version = int(preview_config.get("schema_version") or 1)
        if schema_version == 2:
            preview_config["schema_version"] = 2
            preview_config["mode"] = "multi_timeframe"
            preview_config["name"] = raw_name
            preview_config["display_name"] = display_name
            preview_config["magic_number"] = (
                preview_config.get("magic_number")
                if isinstance(preview_config.get("magic_number"), int)
                else 10000
            )
            preview_config.setdefault("primary_timeframe", preview_config.get("timeframe") or "M1")
            preview_config.setdefault("frames", [{"id": "M1", "timeframe": "M1"}])
            preview_config.setdefault("indicators", [])
            preview_config.setdefault("blocks", [])
            return preview_config

        timeframe = str(preview_config.get("timeframe") or "").strip().upper()
        if self._resolve_timeframe_value(timeframe) is None:
            timeframe = self.current_timeframe if self._resolve_timeframe_value(self.current_timeframe) is not None else "M1"

        magic_number = preview_config.get("magic_number")
        if not isinstance(magic_number, int) or not (10000 <= magic_number <= 99999):
            magic_number = 10000

        indicators = preview_config.get("indicators")
        if not isinstance(indicators, list):
            indicators = []

        available_columns = {
            "open", "high", "low", "close", "OHLC4", "HLC3", "HL2",
            "tick_volume", "average", "atr", "upper", "lower",
            "hma", "supertrend", "supertrend_dir", "supertrend_up", "supertrend_down",
            "tci", "tci_signal", "tci_hist",
        }
        for ind in indicators:
            if not isinstance(ind, dict):
                continue
            for col in ind.get("columns", []):
                if isinstance(col, str) and col:
                    available_columns.add(col)

        buy_condition = self._normalize_builder_preview_condition(
            preview_config.get("buy_condition"), available_columns
        )
        sell_condition = self._normalize_builder_preview_condition(
            preview_config.get("sell_condition"), available_columns
        )

        if buy_condition is None:
            buy_condition = {"type": "condition", "left": "close", "op": ">", "right": 0}
        if sell_condition is None:
            sell_condition = {"type": "condition", "left": "close", "op": "<", "right": 0}

        return {
            "schema_version": 1,
            "name": raw_name,
            "display_name": display_name,
            "description": str(preview_config.get("description") or ""),
            "timeframe": timeframe,
            "magic_number": magic_number,
            "indicators": indicators,
            "buy_condition": buy_condition,
            "sell_condition": sell_condition,
            "payload_extra_fields": copy.deepcopy(preview_config.get("payload_extra_fields", [])),
        }

    def _apply_strategy_builder_preview(self, config_data: dict):
        # esta funcion sirve para actualizar la estrategia temporal del builder.
        try:
            strategy_builder = self._get_strategy_builder_module()
            preview_config = self._build_strategy_builder_preview_config(config_data)
            preview_module = strategy_builder.build_strategy_module(
                preview_config,
                strategies_dir=Path(self._get_strategy_dir()),
                is_new=False,
                module_name="strategy_builder_preview",
            )
        except Exception:
            self._clear_strategy_builder_preview(refresh=True)
            return

        timeframe_value = self._resolve_timeframe_value(self._get_strategy_timeframe(preview_module))
        timeframe_label = self._timeframe_label(timeframe_value) if timeframe_value is not None else preview_config["timeframe"]

        self.builder_preview_entry = {
            "key": "__builder_preview__",
            "label": preview_config["display_name"],
            "module": "<builder preview>",
            "module_obj": preview_module,
            "enabled": False,
            "timeframe_value": timeframe_value,
            "timeframe_label": timeframe_label or preview_config["timeframe"],
            "magic_number": int(getattr(preview_module, "MAGIC_NUMBER", preview_config["magic_number"]) or preview_config["magic_number"]),
            "last_error": "",
            "last_df": None,
        }
        self.builder_preview_active = True
        self._refresh_object_tree_items()
        self.refresh_data(None, log_update=False)

    def _clear_strategy_builder_preview(self, refresh: bool = False):
        # esta funcion sirve para limpiar la previsualizacion temporal del builder.
        had_preview = bool(getattr(self, "builder_preview_active", False) or getattr(self, "builder_preview_entry", None))
        self.builder_preview_active = False
        self.builder_preview_entry = None
        if not had_preview:
            return

        self._refresh_object_tree_items()
        if refresh:
            self.refresh_data(None, log_update=False)

    def _on_strategy_builder_preview(self, json_str: str):
        # esta funcion sirve para recibir una previsualizacion desde el builder.
        json_str = (json_str or "").strip()
        if not json_str:
            self._clear_strategy_builder_preview(refresh=True)
            return
        try:
            config_data = json.loads(json_str)
        except Exception:
            self._clear_strategy_builder_preview(refresh=True)
            return
        self._apply_strategy_builder_preview(config_data)

    def _on_strategy_builder_save(self, json_str: str):
        # esta funcion sirve para guardar una estrategia desde el constructor.
        json_str = (json_str or "").strip()
        if not json_str:
            self._show_builder_error("Payload vacío.")
            return
        try:
            config_data = json.loads(json_str)
        except Exception as e:
            self._show_builder_error(f"JSON inválido: {e}")
            return

        display_name = (config_data.get("display_name") or "").strip()
        if not display_name:
            self._show_builder_error("El nombre visible es obligatorio.")
            return

        is_new = bool(config_data.get("_is_new", True))
        editing_key = (config_data.get("_editing_key") or "").strip() or None
        # El backend deriva el nombre de máquina y el magic; sólo le pasamos la config limpia.
        raw_config = {k: v for k, v in config_data.items() if not k.startswith("_")}

        strategies_dir = Path(self._get_strategy_dir())
        strategy_builder = self._get_strategy_builder_module()
        try:
            if is_new:
                py_path = strategy_builder.handle_save_new(
                    raw_config, strategies_dir=strategies_dir
                )
            else:
                if not editing_key:
                    self._show_builder_error("No se puede editar: falta la estrategia original.")
                    return
                py_path = strategy_builder.handle_save_edit(
                    raw_config, editing_key, strategies_dir=strategies_dir
                )
        except strategy_builder.NameCollisionError as e:
            self._show_builder_error(str(e))
            return
        except strategy_builder.ValidationError as e:
            self._show_builder_error(f"Configuración inválida: {e}")
            return
        except strategy_builder.GeneratorError as e:
            self._show_builder_error(f"Error al generar estrategia: {e}")
            return
        except Exception as e:
            self._show_builder_error(f"Error inesperado: {e}")
            return

        py_path = Path(py_path)
        stem = py_path.stem
        name = stem[len("strategy_"):] if stem.startswith("strategy_") else stem
        module_ref = str(py_path)

        # Edición con rename: el nombre derivado de display_name pudo cambiar; el backend
        # ya borró los ficheros antiguos, así que retiramos la entrada vieja del registro.
        if not is_new and editing_key and editing_key != name:
            self.strategy_registry.pop(editing_key, None)

        if name not in self.strategy_registry:
            self._register_strategy(name, display_name, module_ref)
        else:
            entry = self.strategy_registry[name]
            entry["label"] = display_name
            entry["module"] = module_ref
        entry = self.strategy_registry.get(name)
        if entry:
            self._load_strategy_entry(entry)
            entry["enabled"] = True
        config.ACTIVE_STRATEGIES = [e["key"] for e in self.strategy_registry.values() if e.get("enabled")]
        self._clear_strategy_builder_preview(refresh=False)
        self.chart.run_script('''
            ;(function() {
                if (window.closeStrategyBuilder) {
                    window.closeStrategyBuilder();
                }
            })();
        ''')
        self._set_strategy_by_key(name, refresh=True, sync_ui=True)

    def _show_builder_error(self, message: str):
        # esta funcion sirve para mostrar un error en el constructor de estrategias.
        msg_escaped = json.dumps(message)
        self.chart.run_script(f'''
            ;(function() {{
                if (window.setBuilderError) {{
                    window.setBuilderError({msg_escaped});
                }}
            }})();
        ''')

    def toggle_indicator(self, key: str):
        # esta funcion sirve para activar o desactivar indicador.
        default_visible = key not in {"trade_links"}
        visible = not self.indicator_state.get(key, default_visible)
        self.indicator_state[key] = visible
        if key in self._DRAWING_TOGGLE_KEYS:
            # Dibujos sobre el gráfico: no son series; redibujamos el chart.
            self._sync_indicator_ui(key, visible)
            try:
                if self.price_data is not None:
                    self.update_chart(self.price_data, strategy_entry=self._get_selected_strategy_entry())
            except Exception as e:
                self.log_message(f"Error al alternar dibujo {key}: {e}")
            return
        self._apply_indicator_visibility(key, visible)
        self._sync_indicator_ui(key, visible)
        if self.price_data is not None:
            try:
                self._update_data_window(self.price_data, strategy_entry=self._get_selected_strategy_entry())
            except Exception:
                pass

    def _apply_indicator_visibility(self, key: str, visible: bool):
        # esta funcion sirve para aplicar indicador visibilidad.
        series_list = self.indicator_series.get(key, [])
        for series in series_list:
            if series is None:
                continue
            if visible:
                series.show_data()
            else:
                series.hide_data()

    def _sync_indicator_ui(self, key: str, visible: bool):
        # esta funcion sirve para sincronizar indicador interfaz.
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
        # esta funcion sirve para preparar barra inferior.
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
        # esta funcion sirve para actualizar barra inferior periodo activo.
        self.chart.run_script(f'''
            ;(function() {{
                document.querySelectorAll(".tv-period-btn").forEach((btn) => {{
                    btn.classList.toggle("active", btn.dataset.period === "{period}");
                }});
            }})();
        ''')

    def on_bottom_bar_event(self, period):
        # esta funcion sirve para reaccionar a barra inferior evento.
        if period:
            self.view_period = period
            self.set_bottom_period_active(period)
            self.refresh_data()

    def update_bottom_clock(self):
        # esta funcion sirve para actualizar barra inferior reloj.
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
        # Imprime en consola para no tragar errores en silencio (diagnóstico).
        try:
            print(f"[gui] {message}", flush=True)
        except Exception:
            pass

    def show_toast(self, msg: str, type: str = 'info') -> None:
        """Muestra un toast notification en la GUI. Thread-safe."""
        try:
            import json as _json
            js = f"if (window.tvShowToast) window.tvShowToast({_json.dumps(str(msg))}, {_json.dumps(str(type))});"
            self.chart.run_script(js)
        except Exception:
            pass

    def init_mt5(self):
        # esta funcion sirve para iniciar mt5.
        """Inicializa la conexión con MT5."""
        if mt5 is None:
            return False
        try:
            if config.TIMEFRAME is None:
                config.TIMEFRAME = mt5.TIMEFRAME_M1
            
            mt5_connection.initialize_mt5()
            mt5_connection.check_symbol(config.SYMBOL)
            
            timeframe_label = self._timeframe_label(config.TIMEFRAME)
            if timeframe_label:
                self.current_timeframe = timeframe_label
            
            self.log_message("MT5 inicializado correctamente")
            self.update_balance()
            self.update_quotes()
            self.update_bottom_clock()
            return True
            
        except Exception as e:
            self.log_message(f"Error al inicializar MT5: {e}")
            return False

    def update_balance(self):
        # esta funcion sirve para actualizar balance.
        """Actualiza el balance en la barra superior."""
        if not getattr(self, '_mt5_available', False):
            return
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
        # esta funcion sirve para resumir posiciones long/short de la estrategia seleccionada.
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
        # esta funcion sirve para actualizar en pantalla el estado de long/short.
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
        # esta funcion sirve para pasar el marco de tiempo a minutos.
        return int(runtime_timeframe_to_minutes(timeframe_value, default=1))

    def get_timeframe_minutes(self):
        # esta funcion sirve para obtener marco de tiempo minutos.
        """Obtiene los minutos del timeframe actual."""
        return self._timeframe_to_minutes(config.TIMEFRAME)

    def _selected_strategy_magic(self) -> int:
        # esta funcion sirve para numero magico de la estrategia seleccionada.
        entry = self._get_selected_strategy_entry()
        if entry and isinstance(entry.get("magic_number"), int) and entry.get("magic_number") > 0:
            return int(entry.get("magic_number"))
        return int(getattr(config, "MAGIC_NUMBER", 0) or 0)

    def _get_marker_strategy_scope(self, strategy_entry=None):
        # esta funcion sirve para decidir que estrategias aparecen en marcadores.
        tracked_magics = set()
        magic_labels = {}

        entries = []
        if self.strategy_data_all_actives:
            entries = self._get_enabled_strategy_entries()
        elif isinstance(strategy_entry, dict):
            entries = [strategy_entry]
        else:
            selected_entry = self._get_selected_strategy_entry()
            if isinstance(selected_entry, dict):
                entries = [selected_entry]

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            magic_number = entry.get("magic_number")
            if not isinstance(magic_number, int) or magic_number <= 0:
                continue
            magic_number = int(magic_number)
            tracked_magics.add(magic_number)
            if magic_number in magic_labels:
                continue
            label = (entry.get("label") or entry.get("key") or "").strip()
            if label:
                magic_labels[magic_number] = label

        if not tracked_magics:
            fallback_magic = int(getattr(config, "MAGIC_NUMBER", 0) or 0)
            if fallback_magic > 0:
                tracked_magics.add(fallback_magic)

        return tracked_magics, magic_labels

    def _resolve_deal_strategy_label(self, deal, magic_labels=None) -> str:
        # esta funcion sirve para sacar el nombre de estrategia de un deal.
        if magic_labels is None:
            magic_labels = {}
        try:
            deal_magic = int(getattr(deal, "magic", 0) or 0)
        except Exception:
            deal_magic = 0

        if deal_magic in magic_labels:
            return magic_labels[deal_magic]
        try:
            comment_meta = trading.decode_trade_comment(getattr(deal, "comment", ""))
            if comment_meta.get("is_bot_comment") and comment_meta.get("strategy"):
                return comment_meta.get("strategy")
        except Exception:
            pass
        if deal_magic > 0:
            return f"Magic {deal_magic}"
        return "Sin estrategia"

    def _resolve_deal_reason_label(self, deal) -> str:
        # esta funcion sirve para obtener motivo de señal desde comentario de deal.
        comment = str(getattr(deal, "comment", "") or "").strip()
        if not comment:
            return ""
        try:
            parsed = trading.decode_trade_comment(comment)
            if parsed.get("is_bot_comment") and parsed.get("reason"):
                return parsed.get("reason")
        except Exception:
            pass
        if comment.lower() in {"bot trading", "cierre automático", "cierre automatico"}:
            return ""
        return comment

    def _resolve_group_reason_label(self, deals) -> str:
        # esta funcion sirve para escoger el motivo más relevante para un grupo de deals.
        if not deals:
            return ""
        try:
            ordered = sorted(deals, key=lambda d: getattr(d, "time", 0), reverse=True)
        except Exception:
            ordered = list(deals)
        for deal in ordered:
            reason = self._resolve_deal_reason_label(deal)
            if reason:
                return reason
        return ""

    def _resolve_deal_exit_cause(self, deal) -> str:
        # esta funcion sirve para traducir el motivo de cierre nativo de MT5 (deal.reason).
        return trade_history.resolve_exit_cause(deal)

    def _build_round_trips(self, deals, magic_labels=None) -> list:
        # esta funcion sirve para emparejar deals de entrada y salida por position_id.
        return trade_history.build_round_trips(
            deals,
            self._get_symbol_point(),
            strategy_resolver=lambda d: self._resolve_deal_strategy_label(d, magic_labels=magic_labels),
            reason_resolver=self._resolve_deal_reason_label,
        )

    def _format_duration(self, seconds) -> str:
        # esta funcion sirve para mostrar una duración legible (h/m/s).
        try:
            secs = int(seconds or 0)
        except (TypeError, ValueError):
            return ""
        if secs <= 0:
            return ""
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h {m}m"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"

    _MAGIC_PALETTE = [
        '#26a69a', '#42a5f5', '#ab47bc', '#ffa726',
        '#26c6da', '#ec407a', '#9ccc65', '#ff7043',
    ]

    def _magic_color(self, magic) -> str:
        # esta funcion sirve para asignar un color estable por magic.
        try:
            return self._MAGIC_PALETTE[int(magic) % len(self._MAGIC_PALETTE)]
        except (TypeError, ValueError):
            return self._MAGIC_PALETTE[0]

    def _clear_drawing_handles(self, handles):
        # esta funcion sirve para borrar dibujos previos del gráfico.
        for handle in handles:
            try:
                handle.delete()
            except Exception:
                pass
        handles.clear()

    def _draw_position_levels(self, tracked_magics):
        # esta funcion sirve para dibujar líneas SL/TP de posiciones abiertas.
        self._clear_drawing_handles(self._level_line_handles)
        if not self.indicator_state.get("sltp", True):
            return
        try:
            positions = mt5.positions_get(symbol=config.SYMBOL) or []
        except Exception:
            return
        digits = self._get_symbol_digits()
        for pos in positions:
            try:
                magic = int(getattr(pos, "magic", 0) or 0)
                if tracked_magics and magic not in tracked_magics:
                    continue
                sl = float(getattr(pos, "sl", 0) or 0)
                tp = float(getattr(pos, "tp", 0) or 0)
                if sl > 0:
                    self._level_line_handles.append(
                        self.chart.horizontal_line(
                            sl, color='#ef5350', width=1, style='dashed',
                            text=f"SL {sl:.{digits}f}"
                        )
                    )
                if tp > 0:
                    self._level_line_handles.append(
                        self.chart.horizontal_line(
                            tp, color='#26a69a', width=1, style='dashed',
                            text=f"TP {tp:.{digits}f}"
                        )
                    )
            except Exception:
                continue

    def _draw_trade_links(self, round_trips):
        # esta funcion sirve para dibujar conectores entrada->salida (opcional).
        self._clear_drawing_handles(self._trade_link_handles)
        if not self.indicator_state.get("trade_links", False):
            return
        if not round_trips:
            return
        rts = sorted(round_trips, key=lambda r: r.get("exit_time", 0))
        limit = self.max_trade_links or 30
        for rt in rts[-limit:]:
            try:
                entry_time = int(rt.get("entry_time", 0))
                exit_time = int(rt.get("exit_time", 0))
                ep = float(rt.get("entry_price", 0) or 0)
                xp = float(rt.get("exit_price", 0) or 0)
                if not ep or not xp or exit_time <= entry_time:
                    continue
                et = datetime.fromtimestamp(entry_time, tz=timezone.utc)
                xt = datetime.fromtimestamp(exit_time, tz=timezone.utc)
                color = '#26a69a' if rt.get("profit", 0) >= 0 else '#ef5350'
                self._trade_link_handles.append(
                    self.chart.trend_line(et, ep, xt, xp, line_color=color, width=1, style='dotted')
                )
            except Exception:
                continue

    def _strategy_timeframe_value(self, entry: dict, fallback=None):
        # esta funcion sirve para valor del marco de tiempo de la estrategia.
        if isinstance(entry, dict):
            tf_value = entry.get("timeframe_value")
            if isinstance(tf_value, int):
                return tf_value
        if fallback is not None:
            return fallback
        return config.TIMEFRAME

    def _strategy_feed_timeframe_value(self, entry: dict, fallback=None):
        # para estrategias MTF se descarga la menor temporalidad requerida y el resto se resamplea.
        if isinstance(entry, dict):
            module = entry.get("module_obj")
            required = list(getattr(module, "REQUIRED_TIMEFRAMES", []) or []) if module is not None else []
            if required:
                lowest = runtime_lowest_timeframe_label(required)
                value = self._resolve_timeframe_value(lowest)
                if value is not None:
                    return value
        return self._strategy_timeframe_value(entry, fallback=fallback)

    def _build_market_dataframe(self, timeframe_value, bars_needed):
        # esta funcion sirve para construir mercado tabla de datos.
        df = mt5_get_rates_df(config.SYMBOL, timeframe_value, bars_needed)
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
        # esta funcion sirve para obtener periodo velas.
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

    def _get_display_bars(self, timeframe_minutes: int) -> int:
        # esta funcion sirve para calcular cuantas velas debe ver el usuario.
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

        minutes = period_minutes.get(self.view_period, 1 * minutes_per_day)
        bars = minutes // timeframe_minutes
        return max(1, min(bars, 10000))

    def _get_analysis_bars(self, timeframe_minutes: int) -> int:
        # esta funcion sirve para pedir suficiente historia para calcular indicadores.
        history_floor = int(getattr(config, "BARS_HISTORY", 500) or 500)
        return max(history_floor, self.get_period_bars(self.view_period, timeframe_minutes))

    def _trim_df_for_display(self, df: pd.DataFrame, timeframe_minutes: int) -> pd.DataFrame:
        # esta funcion sirve para limitar lo que se pinta al periodo visible.
        if df is None or len(df) == 0:
            return df
        display_bars = self._get_display_bars(timeframe_minutes)
        trimmed = df.tail(int(display_bars)).copy()
        return trimmed.reset_index(drop=True)
    
    def refresh_data(self, chart=None, log_update: bool = True):
        # esta funcion sirve para refrescar datos.
        """Actualiza los datos del gráfico."""
        expected_strategy_key = (self.current_strategy_key or "").strip()
        expected_selection_seq = int(getattr(self, "_strategy_selection_seq", 0) or 0)

        def update_thread():
            # esta funcion sirve para actualizar hilo.
            try:
                self._refresh_data_once(
                    fit_view=True,
                    enforce_selection=True,
                    expected_strategy_key=expected_strategy_key,
                    expected_selection_seq=expected_selection_seq,
                    log_update=log_update
                )
            except Exception as e:
                self.log_message(f"Error al actualizar datos: {e}")

        threading.Thread(target=update_thread, daemon=True).start()

    def _refresh_data_once(
        self,
        fit_view: bool = True,
        enforce_selection: bool = False,
        expected_strategy_key: str = "",
        expected_selection_seq: int = 0,
        log_update: bool = True
    ) -> bool:
        # esta funcion sirve para cargar una tanda completa de datos.
        selected_entry = self._get_selected_strategy_entry()
        timeframe_value = self._strategy_feed_timeframe_value(selected_entry, fallback=config.TIMEFRAME)
        if timeframe_value is None:
            timeframe_value = mt5.TIMEFRAME_M1

        timeframe_minutes = self._timeframe_to_minutes(timeframe_value)
        bars_needed = self._get_analysis_bars(timeframe_minutes)
        df = self._build_market_dataframe(timeframe_value, bars_needed)
        df = self._apply_strategy_processing_for_entry(selected_entry, df)
        display_df = self._trim_df_for_display(df, timeframe_minutes)

        if len(display_df) < 2:
            return False

        if isinstance(selected_entry, dict):
            selected_entry["last_df"] = display_df

        if enforce_selection:
            current_key = (self.current_strategy_key or "").strip()
            current_seq = int(getattr(self, "_strategy_selection_seq", 0) or 0)
            if current_seq != expected_selection_seq or current_key != expected_strategy_key:
                return False

        self.price_data = display_df
        self.update_chart(display_df, fit_view=fit_view, strategy_entry=selected_entry)
        self.update_equity_chart()
        self.update_tci_chart(display_df)
        self.update_balance()
        self.update_quotes()

        if log_update:
            self.log_message(f"Datos actualizados: {len(display_df)} velas")
        return True
    
    def update_chart(self, df, fit_view: bool = False, strategy_entry=None):
        # esta funcion sirve para actualizar grafico.
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
                tracked_magics, magic_labels = self._get_marker_strategy_scope(strategy_entry=strategy_entry)
                if not tracked_magics:
                    tracked_magics = {selected_magic} if selected_magic else set()
                multi_strategy = len(tracked_magics) > 1

                markers = []
                action_markers = []
                filtered_deals = []

                if deals:
                    # Filtrar por las estrategias en alcance (1 seleccionada o todas las activas).
                    for deal in deals:
                        if deal.symbol != config.SYMBOL:
                            continue
                        deal_magic = int(getattr(deal, "magic", 0) or 0)
                        if tracked_magics and deal_magic not in tracked_magics:
                            continue
                        filtered_deals.append(deal)

                self._latest_deals_cache = filtered_deals
                self._latest_deals_range = (start_time, end_time)

                # Round-trips (entrada<->salida) por position_id para enriquecer cierres.
                round_trips_by_pos = {
                    rt["position_id"]: rt
                    for rt in self._build_round_trips(filtered_deals, magic_labels=magic_labels)
                }

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

                        # Clasificar la vela como ENTRADA o SALIDA y elegir una sola
                        # accion representativa (nunca MIX).
                        #   - Hay algun IN/INOUT -> ENTRADA (apertura o reversion).
                        #   - Solo OUT           -> SALIDA (SL/TP/cierre manual).
                        last_in_deal = None
                        for d in ordered_deals:
                            if getattr(d, "entry", None) in (mt5.DEAL_ENTRY_IN, mt5.DEAL_ENTRY_INOUT):
                                last_in_deal = d
                        is_exit = last_in_deal is None
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

                        exit_profit = None
                        exit_cause = ""
                        group_round_trips = []
                        if is_exit:
                            # Salida: marcador neutro (circulo) para distinguirla de las
                            # flechas de entrada. El color refleja el resultado (P/L).
                            exit_profit = sum(
                                float(getattr(d, "profit", 0) or 0)
                                for d in selected_deals
                                if getattr(d, "entry", None) in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT)
                            )
                            # Causa real del cierre (deal.reason nativo) y round-trips cerrados.
                            exit_cause = self._resolve_deal_exit_cause(selected_deal)
                            seen_pos = set()
                            for d in selected_deals:
                                pid = getattr(d, "position_id", None) or getattr(d, "ticket", None)
                                if pid is None or pid in seen_pos:
                                    continue
                                seen_pos.add(pid)
                                rt = round_trips_by_pos.get(pid)
                                if rt:
                                    group_round_trips.append(rt)
                            if exit_profit > 0:
                                color = '#26a69a'
                            elif exit_profit < 0:
                                color = '#ef5350'
                            else:
                                color = '#b2b5be'
                            shape = 'circle'
                            position = 'above'
                            offset_y = -12
                            if count > 1:
                                text = f"Cierre x{count}"
                            elif exit_cause:
                                text = f"Cierre · {exit_cause}"
                            else:
                                text = "Cierre"
                        elif direction == "BUY":
                            color = '#26a69a'
                            shape = 'arrow_up'
                            position = 'below'
                            offset_y = 12
                            text = "Compra" if count == 1 else f"Compra x{count}"
                        else:
                            color = '#ef5350'
                            shape = 'arrow_down'
                            position = 'above'
                            offset_y = -12
                            text = "Venta" if count == 1 else f"Venta x{count}"

                        # Multi-estrategia: color por magic en entradas + etiqueta de estrategia.
                        if multi_strategy:
                            deal_magic = int(getattr(selected_deal, "magic", 0) or 0)
                            if not is_exit:
                                color = self._magic_color(deal_magic)
                            strat_label = magic_labels.get(deal_magic, "")
                            if strat_label:
                                text = f"{text} · {strat_label[:14]}"

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
                            if is_exit:
                                marker_price = high
                            elif direction == "BUY":
                                marker_price = low
                            else:
                                marker_price = high
                        else:
                            first_price = getattr(selected_deals[0], "price", None) if selected_deals else None
                            if isinstance(first_price, (int, float)):
                                marker_price = float(first_price)

                        strategy_label = self._resolve_deal_strategy_label(selected_deal, magic_labels=magic_labels)
                        signal_reason = self._resolve_group_reason_label(selected_deals)

                        if isinstance(marker_price, (int, float)):
                            tooltip_text = self._format_deal_group_tooltip(
                                selected_deals,
                                direction,
                                strategy_label=strategy_label,
                                signal_reason=signal_reason,
                                is_exit=is_exit,
                                exit_profit=exit_profit,
                                exit_cause=exit_cause,
                                round_trips=group_round_trips
                            )
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

                # Dibujos auxiliares: líneas SL/TP de posiciones abiertas y conectores.
                try:
                    self._draw_position_levels(tracked_magics)
                except Exception as e:
                    self.log_message(f"Error al dibujar SL/TP: {e}")
                try:
                    self._draw_trade_links(list(round_trips_by_pos.values()))
                except Exception as e:
                    self.log_message(f"Error al dibujar conectores: {e}")

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
        # esta funcion sirve para actualizar ultima accion interfaz.
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

        try:
            _icon, _color_unused, _summary = self._build_action_summary(action_info)
            _actions = action_info.get("actions", []) if isinstance(action_info, dict) else []
            _has_open  = any(a.get("kind") == "open"  for a in _actions if isinstance(a, dict))
            _has_close = any(a.get("kind") == "close" for a in _actions if isinstance(a, dict))
            _any_failed = any(a.get("success") is False for a in _actions if isinstance(a, dict))
            if _any_failed:
                self.show_toast(_summary, 'error')
            elif _has_open and _has_close:
                self.show_toast(_summary, 'info')
            elif _has_open:
                self.show_toast(_summary, 'success')
            elif _has_close:
                self.show_toast(_summary, 'warn')
        except Exception:
            pass

        # El tooltip ahora se gestiona desde los marcadores del gráfico

    def _build_action_summary(self, action_info):
        # esta funcion sirve para construir un resumen de accion.
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

    def _format_deal_tooltip(self, deal, direction, strategy_label: str = "", signal_reason: str = ""):
        # esta funcion sirve para dar formato a operacion cartel.
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
        if strategy_label:
            lines.append(f"Estrategia: {strategy_label}")
        if signal_reason:
            lines.append(f"Motivo: {signal_reason}")

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

    def _format_deal_group_tooltip(
        self,
        deals,
        direction,
        strategy_label: str = "",
        signal_reason: str = "",
        is_exit: bool = False,
        exit_profit=None,
        exit_cause: str = "",
        round_trips=None,
        max_items: int = 8
    ):
        # esta funcion sirve para dar formato a operacion grupo cartel.
        """Construye el tooltip para un grupo de operaciones en la misma vela."""
        if not deals:
            return ""
        digits = self._get_symbol_digits()
        if is_exit:
            lines = ["Acción: Cierre"]
        else:
            verbo = "Compra" if direction == "BUY" else "Venta"
            lines = [f"Acción: {verbo} ({direction})"]
        if strategy_label:
            lines.append(f"Estrategia: {strategy_label}")
        if signal_reason:
            lines.append(f"Motivo: {signal_reason}")
        if is_exit and exit_cause:
            lines.append(f"Causa: {exit_cause}")
        if is_exit and isinstance(exit_profit, (int, float)):
            sign = "+" if exit_profit >= 0 else ""
            lines.append(f"Resultado: {sign}{exit_profit:.2f}")
        # Round-trips emparejados (entrada -> salida) cerrados en esta vela.
        for rt in (round_trips or []):
            sign = "+" if rt.get("profit", 0) >= 0 else ""
            lines.append(
                f"  {rt.get('direction', '')} "
                f"{rt.get('entry_price', 0):.{digits}f} → {rt.get('exit_price', 0):.{digits}f}  "
                f"{sign}{rt.get('profit', 0):.2f} "
                f"({sign}{rt.get('return_pct', 0):.2f}%, {sign}{rt.get('points', 0):.0f} pts) "
                f"{self._format_duration(rt.get('duration_s', 0))}"
            )
        lines.extend([f"Operaciones: {len(deals)}", ""])
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
                parts.append(f"@ {price:.{digits}f}")

            volume = getattr(deal, "volume", None)
            if isinstance(volume, (int, float)):
                parts.append(f"vol {volume:.2f}")

            profit = getattr(deal, "profit", None)
            if isinstance(profit, (int, float)) and abs(profit) > 0:
                parts.append(f"P {profit:.2f}")

            lines.append("   " + " ".join(parts))

        return "\n".join(lines).strip()

    def _ensure_action_tooltip(self):
        # esta funcion sirve para asegurar accion cartel.
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
        # esta funcion sirve para actualizar accion marcadores.
        """Actualiza la lista de marcadores para el tooltip."""
        self._ensure_action_tooltip()
        markers_js = json.dumps(markers or [])
        self.chart.run_script(f'window.actionMarkers = {markers_js}')

    def _get_symbol_digits(self) -> int:
        # esta funcion sirve para obtener simbolo decimales.
        """Devuelve los dígitos de precio del símbolo actual."""
        try:
            info = mt5.symbol_info(config.SYMBOL)
            if info and hasattr(info, "digits"):
                return int(info.digits)
        except Exception:
            pass
        return 2

    def _get_symbol_point(self) -> float:
        # esta funcion sirve para obtener el tamaño de punto del símbolo actual.
        """Devuelve el tamaño de punto del símbolo (fallback 10^-digits)."""
        try:
            info = mt5.symbol_info(config.SYMBOL)
            point = float(getattr(info, "point", 0) or 0)
            if point > 0:
                return point
        except Exception:
            pass
        return 10 ** (-self._get_symbol_digits())

    def _format_deals_for_data_window(self, deals, limit: int = 40, magic_labels=None):
        # esta funcion sirve para dar formato a operaciones para ventana de datos.
        """Convierte deals de MT5 en una lista amigable para el Data Window."""
        if not deals:
            return []
        if magic_labels is None:
            magic_labels = {}
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
                comment_text = str(comment) if comment else ""
                try:
                    parsed_comment = trading.decode_trade_comment(comment_text)
                except Exception:
                    parsed_comment = {}
                if parsed_comment.get("is_bot_comment"):
                    comment_text = ""
                strategy_label = self._resolve_deal_strategy_label(deal, magic_labels=magic_labels)
                signal_reason = self._resolve_deal_reason_label(deal)
                exit_cause = (
                    self._resolve_deal_exit_cause(deal)
                    if entry_label in ("OUT", "IN/OUT") else ""
                )

                trade = {
                    "time": int(deal_time),
                    "direction": direction,
                    "entry": entry_label,
                    "price": float(price) if isinstance(price, (int, float)) else None,
                    "volume": float(volume) if isinstance(volume, (int, float)) else None,
                    "profit": float(profit) if isinstance(profit, (int, float)) else None,
                    "ticket": str(ticket) if ticket is not None else "",
                    "comment": comment_text,
                    "strategy": strategy_label,
                    "reason": signal_reason,
                    "exit_cause": exit_cause,
                }
                trades.append(trade)
            except Exception:
                continue
            if limit and len(trades) >= limit:
                break

        return trades

    def _normalize_data_window_fields(self, fields):
        # esta funcion sirve para ordenar ventana de datos campos.
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
        # esta funcion sirve para obtener estrategia ventana de datos campos.
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
        # esta funcion sirve para construir ventana de datos paquete de datos.
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
            # esta funcion sirve para agregar un campo.
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
        _, magic_labels = self._get_marker_strategy_scope(strategy_entry=strategy_entry)
        trades = self._format_deals_for_data_window(
            getattr(self, "_latest_deals_cache", None),
            magic_labels=magic_labels
        )

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
        # esta funcion sirve para actualizar ventana de datos.
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
        # esta funcion sirve para actualizar equidad grafico.
        """Actualiza el gráfico de equity."""
        try:
            if self.equity_chart is None or self.equity_line is None:
                return
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=30)
            positions = mt5.history_deals_get(start_date, end_date)

            # Balance real de la cuenta como ancla (fallback a 10000 si MT5 no responde).
            acct = mt5.account_info() if mt5 is not None else None
            current_balance = float(acct.balance) if acct is not None else 10000.0

            if positions:
                selected_magic = self._selected_strategy_magic()
                filtered = [p for p in positions if hasattr(p, 'magic') and p.magic == selected_magic]

                if filtered:
                    equity_data = []
                    # Anclar el final de la curva al balance real: el inicio es ese balance
                    # menos el profit realizado por esta estrategia en la ventana.
                    realized = sum(d.profit for d in filtered if d.entry == mt5.DEAL_ENTRY_OUT)
                    balance = current_balance - realized

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

            # Si no hay datos, mostrar línea base con el balance real de la cuenta
            if self.price_data is not None and len(self.price_data) > 1:
                # Usar tiempo del precio de datos para la línea base
                first_time = self.price_data['time'].iloc[0]
                last_time = self.price_data['time'].iloc[-1]
                base_data = pd.DataFrame({
                    'time': [first_time, last_time],
                    'Equity': [current_balance, current_balance]
                })
            else:
                now = datetime.now(timezone.utc)
                base_data = pd.DataFrame({
                    'time': pd.to_datetime([now - timedelta(days=7), now], utc=True),
                    'Equity': [current_balance, current_balance]
                })
            
            base_data = base_data.reset_index(drop=True)
            self.equity_line.set(base_data)
            
        except Exception as e:
            self.log_message(f"Error al actualizar equity: {e}")
            import traceback
            traceback.print_exc()

    def _ensure_tci_visual_guard(self):
        # esta funcion sirve para mantener estable la escala del subchart TuTCI.
        """Evita que el panel TuTCI quede fuera de escala tras zoom/pan."""
        try:
            guard_key = f"tciAutoScaleGuard_{self.tci_chart.id}"
            self.chart.run_script(f'''
                ;(function() {{
                    try {{
                        if (window["{guard_key}"]) return;
                        const chartApi = {self.tci_chart.id}.chart;
                        const applyAutoScale = () => {{
                            try {{
                                let priceScale = null;
                                if (chartApi && typeof chartApi.priceScale === "function") {{
                                    try {{
                                        priceScale = chartApi.priceScale("right");
                                    }} catch (_) {{
                                        priceScale = chartApi.priceScale();
                                    }}
                                }}
                                if (priceScale && typeof priceScale.applyOptions === "function") {{
                                    priceScale.applyOptions({{ autoScale: true, mode: 0 }});
                                }}
                            }} catch (_) {{}}
                        }};
                        applyAutoScale();
                        if (chartApi && chartApi.timeScale) {{
                            const ts = chartApi.timeScale();
                            if (ts && typeof ts.subscribeVisibleLogicalRangeChange === "function") {{
                                ts.subscribeVisibleLogicalRangeChange(() => applyAutoScale());
                            }}
                            if (ts && typeof ts.subscribeVisibleTimeRangeChange === "function") {{
                                ts.subscribeVisibleTimeRangeChange(() => applyAutoScale());
                            }}
                        }}
                        window["{guard_key}"] = true;
                    }} catch (_) {{}}
                }})();
            ''')
        except Exception:
            pass

    def _set_tci_sync_line(self, df: pd.DataFrame):
        # esta funcion sirve para mantener timestamps sincronizados en el subchart TuTCI.
        if self.tci_sync_line is None:
            return
        if not isinstance(df, pd.DataFrame) or "time" not in df.columns:
            self.tci_sync_line.set(pd.DataFrame())
            return
        sync_df = df[["time"]].dropna().copy()
        if sync_df.empty:
            self.tci_sync_line.set(pd.DataFrame())
            return
        sync_df["TuTCI Sync"] = 0.0
        self.tci_sync_line.set(sync_df)

    def update_tci_chart(self, df: pd.DataFrame):
        # esta funcion sirve para actualizar tci grafico.
        """Actualiza el subchart TuTCI."""
        try:
            self._ensure_tci_visual_guard()
            if df is None or len(df) < 2:
                self.tci_hist.set(pd.DataFrame())
                self.tci_fill.set(pd.DataFrame())
                self.tci_signal.set(pd.DataFrame())
                self._set_tci_sync_line(df)
                return

            if 'tci_hist' not in df.columns or 'tci_signal' not in df.columns:
                self.tci_hist.set(pd.DataFrame())
                self.tci_fill.set(pd.DataFrame())
                self.tci_signal.set(pd.DataFrame())
                self._set_tci_sync_line(df)
                return

            self._set_tci_sync_line(df)

            tci_view = df[['time', 'tci_hist', 'tci_signal']].copy()
            # shift(1): se dibuja el valor de la vela cerrada (alineado con df.iloc[-2]),
            # no el de la vela en formacion. Intencional, no es un off-by-one.
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

            # Refrescar autoscale tras set() para evitar que el zoom deje el panel sin trazas visibles.
            self.chart.run_script(f'''
                ;(function() {{
                    try {{
                        const chartApi = {self.tci_chart.id}.chart;
                        let priceScale = null;
                        if (chartApi && typeof chartApi.priceScale === "function") {{
                            try {{
                                priceScale = chartApi.priceScale("right");
                            }} catch (_) {{
                                priceScale = chartApi.priceScale();
                            }}
                        }}
                        if (priceScale && typeof priceScale.applyOptions === "function") {{
                            priceScale.applyOptions({{ autoScale: true, mode: 0 }});
                        }}
                    }} catch (_) {{}}
                }})();
            ''')

        except Exception as e:
            self.log_message(f"Error al actualizar TuTCI: {e}")

    def get_enabled_symbols(self, pattern=None, limit=200):
        # esta funcion sirve para obtener simbolos activos.
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
        # esta funcion sirve para reaccionar a marco de tiempo cambio.
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
            
            timeframe_value = self._resolve_timeframe_value(timeframe_str)
            if timeframe_value is not None:
                config.TIMEFRAME = timeframe_value
                self.log_message(f"Timeframe cambiado a {timeframe_str}")
                self.refresh_data()
                
        except Exception as e:
            self.log_message(f"Error al cambiar timeframe: {e}")
    
    def on_period_change(self, chart):
        # esta funcion sirve para reaccionar a periodo cambio.
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
        # esta funcion sirve para reaccionar a simbolo cambio.
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
        # esta funcion sirve para recargar simbolos.
        """Recarga la lista de símbolos habilitados y actualiza el switcher."""
        symbols_enabled = self.get_enabled_symbols()
        if config.SYMBOL not in symbols_enabled:
            symbols_enabled.insert(0, config.SYMBOL)
        self.chart.topbar['symbol_select'].update(tuple(symbols_enabled[:50]))
        self.log_message(f"Lista de símbolos recargada ({len(symbols_enabled)} habilitados)")

    def on_filling_change(self, chart):
        # esta funcion sirve para reaccionar a llenado cambio.
        """Actualiza el modo de llenado desde la interfaz."""
        try:
            mode = chart.topbar['filling_mode'].value
        except Exception:
            self.log_message("No se pudo leer el filling mode")
            return
        config.FILLING_MODE_OVERRIDE = mode
        self.log_message(f"Filling mode configurado: {mode}")

    def start_bot(self, chart=None):
        # esta funcion sirve para iniciar bot.
        """Inicia el bot."""
        if not getattr(self, '_mt5_available', False):
            self.log_message(
                "MT5 no conectado. Verifica MT5LINUX_HOST y MT5LINUX_PORT en config.py."
            )
            return
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
        # esta funcion sirve para detener bot.
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
    
    def _update_risk_widget(self):
        # esta funcion sirve para actualizar el widget de riesgo agregado en el panel.
        try:
            selected_entry = self._get_selected_strategy_entry()
            if not isinstance(selected_entry, dict):
                risk_pct = 0.0
                color = "#888888"
            else:
                magic_number = int(selected_entry.get("magic_number") or 0)
                symbol = getattr(config, "SYMBOL", "")

                account = mt5.account_info()
                balance = account.balance if account is not None else 0.0
                if balance <= 0:
                    risk_pct = 0.0
                    color = "#888888"
                else:
                    symbol_info = mt5.symbol_info(symbol)
                    tick_size = getattr(symbol_info, "trade_tick_size", 0.0) or 0.0
                    tick_value = getattr(symbol_info, "trade_tick_value", 0.0) or 0.0
                    if tick_size <= 0 or tick_value <= 0:
                        risk_pct = 0.0
                        color = "#888888"
                    else:
                        value_per_unit = tick_value / tick_size
                        all_positions = mt5.positions_get(symbol=symbol)
                        risk_money = 0.0
                        if all_positions:
                            for pos in all_positions:
                                if getattr(pos, "magic", None) != magic_number:
                                    continue
                                if pos.type != mt5.ORDER_TYPE_BUY:
                                    continue
                                sl = pos.sl
                                if sl <= 0:
                                    continue
                                distance = pos.price_open - sl
                                if distance <= 0:
                                    continue
                                risk_money += pos.volume * distance * value_per_unit
                        risk_pct = (risk_money / balance) * 100.0

                        if risk_pct >= 3.0:
                            color = "#ef5350"
                        elif risk_pct >= 2.0:
                            color = "#ffaa00"
                        else:
                            color = "#4CAF50"

            self._current_aggregate_risk_pct = risk_pct

            payload = json.dumps({
                "risk_pct": round(risk_pct, 2),
                "color": color,
            })
            self.chart.run_script(f'''
                ;(function() {{
                    const payload = {payload};
                    const valEl = document.getElementById("tv-risk-value");
                    if (!valEl) return;
                    valEl.innerText = payload.risk_pct.toFixed(1) + "%";
                    valEl.style.color = payload.color;
                }})();
            ''')
        except Exception as e:
            self.log_message(f"Error actualizando widget de riesgo: {e}")

    def bot_loop(self):
        # esta funcion sirve para ciclo del bot.
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

                    market_open, market_status = self._broker.is_market_open(config.SYMBOL)

                    market_cache = {}

                    for entry in enabled_entries:
                        timeframe_value = self._strategy_feed_timeframe_value(entry, fallback=config.TIMEFRAME)
                        if timeframe_value is None:
                            timeframe_value = mt5.TIMEFRAME_M1

                        timeframe_minutes = self._timeframe_to_minutes(timeframe_value)
                        bars_needed = self._get_analysis_bars(timeframe_minutes)

                        if timeframe_value not in market_cache:
                            market_cache[timeframe_value] = self._build_market_dataframe(
                                timeframe_value, bars_needed
                            )

                        base_df = market_cache.get(timeframe_value)
                        if base_df is None or len(base_df) < 2:
                            entry["last_error"] = "No hay suficientes velas"
                            entry["last_run_at"] = datetime.now().strftime("%H:%M:%S")
                            continue

                        strategy_df = self._apply_strategy_processing_for_entry(entry, base_df.copy())
                        entry["last_df"] = self._trim_df_for_display(strategy_df, timeframe_minutes)
                        entry["last_run_at"] = datetime.now().strftime("%H:%M:%S")
                        entry["last_market_status"] = market_status
                        entry["last_error"] = ""

                        signal_payload = self._get_strategy_signal_payload_for_entry(
                            entry, strategy_df, verbose=False
                        )
                        signal = signal_payload.get("signal", "none")
                        signal_reason = str(signal_payload.get("reason") or "").strip()
                        pyramiding = bool(signal_payload.get("pyramiding", False))
                        atr_value = float(signal_payload.get("atr_value", 0.0) or 0.0)
                        dynamic_sizing = bool(signal_payload.get("dynamic_sizing", False))
                        volume_ratio = float(signal_payload.get("volume_ratio", 0.0) or 0.0)
                        sl_atr_mult = float(signal_payload.get("sl_atr_mult", 1.0) or 1.0)
                        tp_atr_mult = float(signal_payload.get("tp_atr_mult", 2.0) or 2.0)
                        pyramid_atr_mult = float(signal_payload.get("pyramid_atr_mult", 0.5) or 0.5)
                        risk_pct = float(signal_payload.get("risk_pct", 0.0) or 0.0)
                        max_entries = signal_payload.get("max_entries")
                        entry_index = signal_payload.get("entry_index")
                        entry["last_signal"] = signal
                        entry["last_signal_reason"] = signal_reason

                        if signal != "none" and market_open:
                            reason_txt = f" | motivo: {signal_reason}" if signal_reason else ""
                            self.log_message(f"[{entry['label']}] Senal detectada: {signal.upper()}{reason_txt}")
                            _toast_msg = f"Señal {signal.upper()}"
                            if signal_reason:
                                _toast_msg += f": {signal_reason[:60]}"
                            if entry.get('label'):
                                _toast_msg += f"\n[{entry['label']}]"
                            self.show_toast(_toast_msg, 'warn')
                            if pyramiding and atr_value > 0 and signal == "buy":
                                if risk_pct > 0:
                                    account = self._broker.get_account_info()
                                    balance = account.balance if account is not None else 0.0
                                    instrument_info = self._broker.get_instrument_info(config.SYMBOL)
                                    if instrument_info is not None and balance > 0:
                                        raw_lot = trading.calculate_risk_lot(
                                            atr_value,
                                            risk_pct,
                                            instrument_info,
                                            balance,
                                            sl_atr_mult=sl_atr_mult,
                                        )
                                    else:
                                        raw_lot = 0.0
                                    lot = raw_lot if raw_lot > 0 else config.LOT
                                elif dynamic_sizing and volume_ratio > 0:
                                    account = self._broker.get_account_info()
                                    balance = account.balance if account is not None else 0.0
                                    instrument_info = self._broker.get_instrument_info(config.SYMBOL)
                                    if instrument_info is not None and balance > 0:
                                        raw_lot = trading.calculate_dynamic_lot(
                                            atr_value,
                                            volume_ratio,
                                            instrument_info,
                                            balance,
                                        )
                                    else:
                                        raw_lot = 0.0
                                    lot = raw_lot if raw_lot > 0 else config.LOT
                                else:
                                    balance = None
                                    lot = config.LOT

                                action_info = self._broker.apply_pyramid_signal(
                                    config.SYMBOL,
                                    int(entry.get("magic_number") or config.MAGIC_NUMBER),
                                    atr_value,
                                    lot,
                                    strategy_key=entry.get("key", ""),
                                    strategy_label=entry.get("label", ""),
                                    signal_reason=signal_reason,
                                    balance=balance if (dynamic_sizing or risk_pct > 0) else None,
                                    sl_atr_mult=sl_atr_mult,
                                    tp_atr_mult=tp_atr_mult,
                                    pyramid_atr_mult=pyramid_atr_mult,
                                    max_entries=max_entries,
                                    entry_index=entry_index,
                                )
                            else:
                                action_info = self._broker.apply_signal(
                                    config.SYMBOL,
                                    signal,
                                    config.LOT,
                                    config.SL_POINTS,
                                    config.TP_POINTS,
                                    int(entry.get("magic_number") or config.MAGIC_NUMBER),
                                    strategy_key=entry.get("key", ""),
                                    strategy_label=entry.get("label", ""),
                                    signal_reason=signal_reason
                                )
                            if action_info:
                                action_info["strategy"] = entry.get("key", "")
                                action_info["strategy_label"] = entry.get("label", "")
                                if signal_reason and not action_info.get("signal_reason"):
                                    action_info["signal_reason"] = signal_reason
                                self.update_last_action_ui(action_info)
                        elif signal != "none":
                            self.log_message(f"[{entry['label']}] Skip: mercado cerrado ({market_status})")

                    selected_entry = self._get_selected_strategy_entry()
                    display_df = None
                    if isinstance(selected_entry, dict):
                        display_df = selected_entry.get("last_df")

                    if display_df is None and isinstance(selected_entry, dict):
                        timeframe_value = self._strategy_feed_timeframe_value(selected_entry, fallback=config.TIMEFRAME)
                        if timeframe_value is None:
                            timeframe_value = mt5.TIMEFRAME_M1

                        timeframe_minutes = self._timeframe_to_minutes(timeframe_value)
                        bars_needed = self._get_analysis_bars(timeframe_minutes)

                        if timeframe_value not in market_cache:
                            market_cache[timeframe_value] = self._build_market_dataframe(
                                timeframe_value, bars_needed
                            )
                        base_df = market_cache.get(timeframe_value)
                        if base_df is not None and len(base_df) > 1:
                            display_df = self._apply_strategy_processing_for_entry(
                                selected_entry, base_df.copy()
                            )
                            display_df = self._trim_df_for_display(display_df, timeframe_minutes)
                            selected_entry["last_df"] = display_df

                    if display_df is not None and len(display_df) > 1:
                        self.price_data = display_df
                        self.update_chart(display_df, strategy_entry=selected_entry)
                        self.update_tci_chart(display_df)

                    self.update_balance()
                    self._update_risk_widget()
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
        # esta funcion sirve para ejecutar el proceso completo.
        """Ejecuta la aplicación."""
        # Inicializar MT5
        if not self.init_mt5():
            self._mt5_available = False
            self.log_message(
                "[SIN MT5] No se pudo conectar a MT5. "
                "Verifica que el servidor mt5linux esté activo y que "
                "MT5LINUX_HOST/MT5LINUX_PORT estén correctos en config.py. "
                "Backtesting con Dukascopy sigue disponible."
            )
        else:
            self._mt5_available = True

        try:
            self._refresh_data_once(fit_view=True, log_update=False)
        except Exception as e:
            self.log_message(f"No se pudo precargar datos iniciales: {e}")

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
    # esta funcion sirve para arrancar todo el programa.
    """Función principal."""
    app = TradingBotGUI()
    app.run()


if __name__ == "__main__":
    main()

