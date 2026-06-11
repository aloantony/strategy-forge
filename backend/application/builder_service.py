"""
backend/application/builder_service.py — Servicio del Strategy Builder para frontends.

Capa fina sobre backend/strategy_builder: expone el catálogo de indicadores con
etiquetas humanas (única fuente de verdad para la web y futuras apps móviles),
lee/guarda/valida/borra configs de estrategias del Builder. Los routers del
server no orquestan: llaman aquí.
"""

import json
from pathlib import Path

from backend.application import strategy_catalog
from backend.core import config as core_config
from backend.runtime.timeframes import TIMEFRAME_MINUTES
from backend.strategy_builder import generator
from backend.strategy_builder.generator import (  # noqa: F401 (re-export para routers)
    GeneratorError,
    NameCollisionError,
    ValidationError,
)

# El enrutado v1/v2 es interno del generador; aquí solo se consulta.
from backend.strategy_builder.generator import _is_mtf_config, _requested_schema_version

MAX_GROUP_DEPTH = 4

_OPERATORS = [
    {"op": ">", "label": "es mayor que"},
    {"op": "<", "label": "es menor que"},
    {"op": ">=", "label": "es mayor o igual que"},
    {"op": "<=", "label": "es menor o igual que"},
    {"op": "==", "label": "es igual a"},
    {"op": "!=", "label": "es distinto de"},
]

_BASE_COLUMNS = [
    {"column": "close", "label": "Precio de cierre", "group": "Precio"},
    {"column": "open", "label": "Precio de apertura", "group": "Precio"},
    {"column": "high", "label": "Máximo de la vela", "group": "Precio"},
    {"column": "low", "label": "Mínimo de la vela", "group": "Precio"},
    {"column": "OHLC4", "label": "Precio medio (OHLC4)", "group": "Precio"},
    {"column": "HLC3", "label": "Precio típico (HLC3)", "group": "Precio"},
    {"column": "HL2", "label": "Precio medio (HL2)", "group": "Precio"},
    {"column": "tick_volume", "label": "Volumen (ticks)", "group": "Volumen"},
    {"column": "average", "label": "Media base del gráfico", "group": "Gráfico"},
    {"column": "atr", "label": "ATR base del gráfico", "group": "Gráfico"},
    {"column": "upper", "label": "Banda superior base del gráfico", "group": "Gráfico"},
    {"column": "lower", "label": "Banda inferior base del gráfico", "group": "Gráfico"},
]

# Catálogo de indicadores con etiquetas humanas. Los templates de columna usan los
# mismos nombres que genera generator.py; "{period}"/"{lookback}" se interpolan con
# el valor del parámetro. La validación autoritativa sigue en el generador.
_INDICATORS = [
    {
        "id": "EMA",
        "label": "Media móvil exponencial (EMA)",
        "description": "Media que reacciona rápido a los cambios de precio.",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 9, "min": 2, "max": 500, "step": 1}],
        "columns": [{"template": "ema_{period}", "label": "EMA ({period})"}],
    },
    {
        "id": "SMA",
        "label": "Media móvil simple (SMA)",
        "description": "Media aritmética del precio en N velas.",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 20, "min": 2, "max": 500, "step": 1}],
        "columns": [{"template": "sma_{period}", "label": "SMA ({period})"}],
    },
    {
        "id": "RSI",
        "label": "Índice de fuerza relativa (RSI)",
        "description": "Oscilador 0-100: sobreventa por debajo de 30, sobrecompra por encima de 70.",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 14, "min": 2, "max": 200, "step": 1}],
        "columns": [{"template": "rsi_{period}", "label": "RSI ({period})"}],
    },
    {
        "id": "BB",
        "label": "Bandas de Bollinger",
        "description": "Bandas de volatilidad alrededor de una media.",
        "pre_computed": False,
        "params": [
            {"key": "period", "label": "Período", "type": "int", "default": 20, "min": 2, "max": 500, "step": 1},
            {"key": "multiplier", "label": "Multiplicador", "type": "float", "default": 2.0, "min": 0.1, "max": 10.0, "step": 0.1},
        ],
        "columns": [
            {"template": "bb_basis_{period}", "label": "Banda media de Bollinger ({period})"},
            {"template": "bb_upper_{period}", "label": "Banda superior de Bollinger ({period})"},
            {"template": "bb_lower_{period}", "label": "Banda inferior de Bollinger ({period})"},
            {"template": "bb_width_pct_{period}", "label": "Anchura de Bollinger % ({period})"},
        ],
    },
    {
        "id": "DONCHIAN",
        "label": "Canal de Donchian",
        "description": "Máximo y mínimo de las últimas N velas (ruptura de rangos).",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 12, "min": 2, "max": 500, "step": 1}],
        "columns": [
            {"template": "donchian_high_{period}", "label": "Canal Donchian superior ({period})"},
            {"template": "donchian_low_{period}", "label": "Canal Donchian inferior ({period})"},
            {"template": "donchian_mid_{period}", "label": "Canal Donchian medio ({period})"},
        ],
    },
    {
        "id": "ATR",
        "label": "Rango medio verdadero (ATR)",
        "description": "Mide la volatilidad: cuánto se mueve el precio por vela.",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 14, "min": 1, "max": 200, "step": 1}],
        "columns": [
            {"template": "atr_{period}", "label": "ATR ({period})"},
            {"template": "atr_pct_{period}", "label": "ATR % ({period})"},
        ],
    },
    {
        "id": "VWAP",
        "label": "Precio medio ponderado por volumen (VWAP)",
        "description": "Precio medio de la sesión ponderado por volumen.",
        "pre_computed": False,
        "params": [],
        "columns": [{"template": "vwap", "label": "VWAP"}],
    },
    {
        "id": "VOLUME_RATIO",
        "label": "Ratio de volumen",
        "description": "Volumen actual frente a su media: >1 significa volumen alto.",
        "pre_computed": False,
        "params": [{"key": "lookback", "label": "Velas de referencia", "type": "int", "default": 30, "min": 2, "max": 500, "step": 1}],
        "columns": [{"template": "volume_ratio_{lookback}", "label": "Ratio de volumen ({lookback})"}],
    },
    {
        "id": "ADX_DI",
        "label": "ADX + DI (fuerza de tendencia)",
        "description": "ADX mide la fuerza de la tendencia; DI+ y DI− su dirección.",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 14, "min": 2, "max": 200, "step": 1}],
        "columns": [
            {"template": "adx_{period}", "label": "ADX ({period})"},
            {"template": "plus_di_{period}", "label": "DI+ ({period})"},
            {"template": "minus_di_{period}", "label": "DI− ({period})"},
            {"template": "plus_di_cross_{period}", "label": "Cruce alcista del DI+ ({period})"},
            {"template": "minus_di_cross_{period}", "label": "Cruce bajista del DI− ({period})"},
        ],
    },
    {
        "id": "VORTEX",
        "label": "Vortex (cambios de tendencia)",
        "description": "Detecta giros de tendencia comparando los movimientos VI+ y VI−.",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 14, "min": 2, "max": 200, "step": 1}],
        "columns": [
            {"template": "vi_plus_{period}", "label": "Vortex VI+ ({period})"},
            {"template": "vi_minus_{period}", "label": "Vortex VI− ({period})"},
            {"template": "vortex_dir_{period}", "label": "Dirección Vortex ({period})"},
            {"template": "vortex_cross_up_{period}", "label": "Cruce alcista Vortex ({period})"},
            {"template": "vortex_cross_down_{period}", "label": "Cruce bajista Vortex ({period})"},
        ],
    },
    {
        "id": "HMA",
        "label": "Media de Hull (HMA)",
        "description": "Media suave y rápida ya calculada por el gráfico.",
        "pre_computed": True,
        "params": [],
        "columns": [{"template": "hma", "label": "HMA"}],
    },
    {
        "id": "SUPERTREND",
        "label": "Supertrend",
        "description": "Guía de tendencia que cambia de lado del precio (ya calculada).",
        "pre_computed": True,
        "params": [],
        "columns": [
            {"template": "supertrend", "label": "Supertrend"},
            {"template": "supertrend_dir", "label": "Dirección Supertrend (1 alcista / -1 bajista)"},
        ],
    },
    {
        "id": "TCI",
        "label": "Oscilador TCI",
        "description": "Oscilador de impulso normalizado por volatilidad (ya calculado).",
        "pre_computed": True,
        "params": [],
        "columns": [
            {"template": "tci", "label": "TCI"},
            {"template": "tci_signal", "label": "Señal TCI"},
            {"template": "tci_hist", "label": "Histograma TCI"},
        ],
    },
]

_MTF = {
    "indicator_ids": ["ATR", "VORTEX"],
    "block_defaults": {
        "atr_period": 14,
        "vortex_period": 14,
        "risk_tiers": [0.01],
        "sl_atr_mult": 1.5,
        "tp_rr": 2.0,
        "pyramid_atr_mult": 0.5,
    },
    "column_labels": [
        {"template": "atr_{period}", "label": "ATR ({period})"},
        {"template": "atr_pct_{period}", "label": "ATR % ({period})"},
        {"template": "vi_plus_{period}", "label": "Vortex VI+ ({period})"},
        {"template": "vi_minus_{period}", "label": "Vortex VI− ({period})"},
        {"template": "vortex_dir_{period}", "label": "Dirección Vortex ({period})"},
        {"template": "vortex_cross_up_{period}", "label": "Cruce alcista Vortex ({period})"},
        {"template": "vortex_cross_down_{period}", "label": "Cruce bajista Vortex ({period})"},
    ],
}


def get_builder_meta() -> dict:
    return {
        "timeframes": list(TIMEFRAME_MINUTES),
        "operators": _OPERATORS,
        "base_columns": _BASE_COLUMNS,
        "indicators": _INDICATORS,
        "max_group_depth": MAX_GROUP_DEPTH,
        "mtf": _MTF,
    }


def get_strategy_config(key: str) -> dict | None:
    """Config JSON de una estrategia del Builder, o None si no existe / no es Builder."""
    name = strategy_catalog._builder_name(key)
    json_path = strategy_catalog.strategies_dir() / f"strategy_{name}.json"
    if not json_path.is_file():
        return None
    return json.loads(json_path.read_text(encoding="utf-8"))


def save_strategy(config: dict, is_new: bool, editing_key: str | None = None) -> dict:
    """
    Crea o edita una estrategia del Builder. Devuelve un resumen con el nombre final.

    A diferencia de la GUI (que deja que sanitize_name auto-sufije _2, _3...), aquí
    un create con slug ya existente se rechaza con NameCollisionError para que el
    usuario decida (editar la existente o cambiar el nombre).
    """
    config = {k: v for k, v in dict(config or {}).items() if not str(k).startswith("_")}
    sdir = strategy_catalog.strategies_dir()

    if is_new:
        slug = generator.slugify_display_name(str(config.get("display_name") or ""))
        if (sdir / f"strategy_{slug}.py").exists():
            raise NameCollisionError(
                f"Ya existe una estrategia llamada '{slug}'. Edítala o usa otro nombre."
            )
        py_path = generator.handle_save_new(config, strategies_dir=sdir)
    else:
        original = strategy_catalog._builder_name(str(editing_key or "").strip())
        if not original:
            raise ValidationError("Falta la clave de la estrategia que se está editando.")
        py_path = generator.handle_save_edit(config, original, strategies_dir=sdir)

    stored = json.loads(py_path.with_suffix(".json").read_text(encoding="utf-8"))
    return {
        "key": py_path.stem,
        "name": stored.get("name", ""),
        "display_name": stored.get("display_name", ""),
        "magic_number": stored.get("magic_number", 0),
        "timeframe": stored.get("timeframe", ""),
        "schema_version": stored.get("schema_version", 1),
        "py_path": str(py_path),
    }


def validate_config(config: dict) -> list[str]:
    """
    Valida un config (sin name/magic definitivos) y devuelve errores legibles.
    Lista vacía = válido. No escribe nada en disco.
    """
    cfg = {k: v for k, v in dict(config or {}).items() if not str(k).startswith("_")}
    cfg.setdefault("description", "")
    display = str(cfg.get("display_name") or "").strip()
    cfg["name"] = generator.slugify_display_name(display) if display else "borrador"
    cfg["magic_number"] = 12345  # provisional, dentro del rango válido
    cfg["schema_version"] = _requested_schema_version(cfg)

    try:
        if _is_mtf_config(cfg):
            from backend.strategy_builder.mtf_generator import validate_mtf_strategy_config
            validate_mtf_strategy_config(cfg, is_new=False, strategies_dir=strategy_catalog.strategies_dir())
        else:
            generator.validate_strategy_config(cfg, is_new=False, strategies_dir=strategy_catalog.strategies_dir())
    except ValidationError as exc:
        return [str(exc)]
    return []


def delete_strategy(key: str) -> dict:
    """
    Borra una estrategia del Builder (.py + .json + .params.json) y la desactiva.

    Solo borra estrategias con companion .json (las hechas a mano se protegen).
    Raises LookupError si no existe; ValidationError si es hand-crafted.
    """
    sdir = strategy_catalog.strategies_dir()
    name = strategy_catalog._builder_name(key)
    py_path = sdir / f"strategy_{name}.py"
    json_path = sdir / f"strategy_{name}.json"

    if not py_path.exists() and not json_path.exists():
        raise LookupError(f"Estrategia no encontrada: {key}")
    if not json_path.exists():
        raise ValidationError(
            f"'{name}' es una estrategia hecha a mano (sin .json del Builder); no se borra desde aquí."
        )

    json_path.unlink(missing_ok=True)
    py_path.unlink(missing_ok=True)
    (sdir / f"strategy_{name}.params.json").unlink(missing_ok=True)

    stem = f"strategy_{name}"
    active = [str(k) for k in (getattr(core_config, "ACTIVE_STRATEGIES", []) or [])]
    core_config.ACTIVE_STRATEGIES = [k for k in active if k not in (stem, name)]
    return {"deleted": stem}
