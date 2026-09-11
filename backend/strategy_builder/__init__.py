# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""Strategy Builder helpers and code generator package."""

from .generator import (
    GeneratorError,
    NameCollisionError,
    ValidationError,
    build_strategy_module,
    emit_condition,
    generate_strategy_file,
    handle_save_edit,
    handle_save_new,
    render_strategy_source,
    sanitize_name,
    slugify_display_name,
    validate_strategy_config,
)

__all__ = [
    "GeneratorError",
    "NameCollisionError",
    "ValidationError",
    "build_strategy_module",
    "emit_condition",
    "generate_strategy_file",
    "handle_save_edit",
    "handle_save_new",
    "render_strategy_source",
    "sanitize_name",
    "slugify_display_name",
    "validate_strategy_config",
]
