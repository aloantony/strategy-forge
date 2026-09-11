# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
backend/application/builder_service.py — Servicio del Strategy Builder para frontends.

Capa fina sobre backend/strategy_builder: expone el catálogo de indicadores con
etiquetas humanas (derivado del registry único backend/strategy_builder/indicators.py),
lee/guarda/valida/borra configs de estrategias del Builder. Los routers del
server no orquestan: llaman aquí.
"""

import json

from backend.application import strategy_catalog
from backend.core import config as core_config
from backend.runtime.timeframes import TIMEFRAME_MINUTES
from backend.strategy_builder import generator
from backend.strategy_builder.generator import (  # noqa: F401 (re-export para routers)
    GeneratorError,
    NameCollisionError,
    ValidationError,
)
from backend.strategy_builder.indicators import (
    INDICATOR_SPECS,
    MTF_INDICATOR_IDS,
    catalog_for_meta,
    indicator_columns,
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


def _allowed_mtf_ids() -> list[str]:
    # La lista autoritativa vive en el validador MTF; el registry define el universo.
    from backend.strategy_builder.mtf_generator import VALID_MTF_INDICATOR_IDS
    return [iid for iid in MTF_INDICATOR_IDS if iid in VALID_MTF_INDICATOR_IDS]


def _mtf_column_labels() -> list[dict]:
    out = []
    for ind_id in _allowed_mtf_ids():
        for col in INDICATOR_SPECS[ind_id]["columns"]:
            out.append({"template": col["template"], "label": col["label"]})
    return out


def _mtf_meta() -> dict:
    return {
        "indicator_ids": _allowed_mtf_ids(),
        "directions": [
            {"id": "long", "label": "Largo (compra)"},
            {"id": "short", "label": "Corto (venta)"},
        ],
        "rules_mode": True,  # buy/sell_condition con refs TF.columna a nivel raíz
        "block_defaults": {
            "atr_period": 14,
            "vortex_period": 14,
            "risk_tiers": [0.01],
            "sl_atr_mult": 1.5,
            "tp_rr": 2.0,
            "pyramid_atr_mult": 0.5,
        },
        "column_labels": _mtf_column_labels(),
    }


def get_builder_meta() -> dict:
    return {
        "timeframes": list(TIMEFRAME_MINUTES),
        "operators": _OPERATORS,
        "base_columns": _BASE_COLUMNS,
        "indicators": catalog_for_meta(),
        "max_group_depth": MAX_GROUP_DEPTH,
        "mtf": _mtf_meta(),
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
