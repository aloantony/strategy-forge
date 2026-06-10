"""
backend/application/strategy_catalog.py — Catálogo de estrategias en disco.

Servicio de aplicación (sin GUI, sin MT5): descubre los módulos de strategies/,
los carga y expone entradas listas para el servidor/CLI/backtest.
"""

import importlib.util
import json
import os
import re
from pathlib import Path

from backend.core import config
from backend.strategy.runtime import (
    get_strategy_timeframe,
    resolve_timeframe_value,
    timeframe_label,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def strategies_dir() -> Path:
    base = getattr(config, "STRATEGY_DIR", "strategies")
    path = Path(base)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return path


def _slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text).strip("_")
    return text or "strategy"


def _builder_name(key: str) -> str:
    """Nombre 'builder' sin el prefijo strategy_ (companions strategy_<name>.json)."""
    key = (key or "").strip()
    return key[len("strategy_"):] if key.startswith("strategy_") else key


def list_strategy_files() -> list[Path]:
    base = strategies_dir()
    if not base.is_dir():
        return []
    out = []
    for path in sorted(base.glob("*.py"), key=lambda p: p.name.lower()):
        stem = path.stem
        if not stem or stem.startswith("__"):
            continue
        out.append(path)
    return out


def load_strategy_module(path: Path):
    """Carga un módulo de estrategia desde su ruta (aislado, sin registrarlo)."""
    module_name = f"strategy_catalog_{_slugify(path.stem)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_strategy_entry(key: str) -> dict | None:
    """Entrada completa (con module_obj) para BacktestService / motor."""
    for path in list_strategy_files():
        if _slugify(path.stem) == _slugify(key):
            module = load_strategy_module(path)
            timeframe_value = resolve_timeframe_value(get_strategy_timeframe(module))
            return {
                "key": _slugify(path.stem),
                "label": path.stem,
                "module": str(path),
                "module_obj": module,
                "timeframe_value": timeframe_value,
                "timeframe_label": timeframe_label(timeframe_value) or "",
                "magic_number": int(getattr(module, "MAGIC_NUMBER", 0) or 0),
            }
    return None


def list_strategies(load_modules: bool = False) -> list[dict]:
    """Listado ligero para la API: key, label, timeframe, capacidades."""
    active = {str(k) for k in (getattr(config, "ACTIVE_STRATEGIES", []) or [])}
    base = strategies_dir()
    entries = []
    for path in list_strategy_files():
        key = _slugify(path.stem)
        json_path = base / f"strategy_{_builder_name(key)}.json"
        entry = {
            "key": key,
            "label": path.stem,
            "module": str(path),
            "has_config": json_path.is_file(),
            "enabled": key in active,
            "timeframe": "",
            "magic_number": 0,
            "has_params": False,
        }
        if load_modules:
            try:
                module = load_strategy_module(path)
                tf_value = resolve_timeframe_value(get_strategy_timeframe(module))
                entry["timeframe"] = timeframe_label(tf_value) or ""
                entry["magic_number"] = int(getattr(module, "MAGIC_NUMBER", 0) or 0)
                params = getattr(module, "PARAMS", None)
                entry["has_params"] = isinstance(params, dict) and len(params) > 0
            except Exception as exc:
                entry["error"] = str(exc)
        elif json_path.is_file():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                entry["timeframe"] = str(data.get("timeframe") or "")
                entry["magic_number"] = int(data.get("magic_number") or 0)
            except Exception:
                pass
        entries.append(entry)
    return entries
