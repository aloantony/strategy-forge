# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""server/routers/builder.py — API REST del Strategy Builder (crear/editar/validar/borrar)."""

from fastapi import APIRouter, Body, HTTPException

from backend.application import builder_service
from backend.application.builder_service import (
    GeneratorError,
    NameCollisionError,
    ValidationError,
)
from server.schemas import BuilderSaveResponse, BuilderValidateResponse

router = APIRouter(tags=["builder"])


@router.get("/builder/meta")
def builder_meta():
    return builder_service.get_builder_meta()


@router.get("/builder/strategies/{key}")
def get_strategy_config(key: str):
    config = builder_service.get_strategy_config(key)
    if config is None:
        raise HTTPException(status_code=404, detail=f"No hay config del Builder para: {key}")
    return config


@router.post("/builder/strategies", response_model=BuilderSaveResponse, status_code=201)
def create_strategy(config: dict = Body(...)):
    return _save(config, is_new=True, editing_key=None)


@router.put("/builder/strategies/{key}", response_model=BuilderSaveResponse)
def edit_strategy(key: str, config: dict = Body(...)):
    return _save(config, is_new=False, editing_key=key)


@router.delete("/builder/strategies/{key}")
def delete_strategy(key: str):
    try:
        return builder_service.delete_strategy(key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/builder/validate", response_model=BuilderValidateResponse)
def validate_config(config: dict = Body(...)):
    errors = builder_service.validate_config(config)
    return {"valid": not errors, "errors": errors}


def _save(config: dict, is_new: bool, editing_key: str | None):
    try:
        return builder_service.save_strategy(config, is_new=is_new, editing_key=editing_key)
    except NameCollisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValidationError as exc:
        # Edits sobre estrategias inexistentes llegan como ValidationError tipado
        detail = str(exc)
        status = 404 if "no existe" in detail else 400
        raise HTTPException(status_code=status, detail=detail)
    except GeneratorError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
