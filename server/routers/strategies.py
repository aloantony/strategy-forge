"""server/routers/strategies.py — Listado y activación de estrategias."""

from fastapi import APIRouter, HTTPException

from backend.application import strategy_catalog
from backend.core import config
from server.schemas import StrategyItem

router = APIRouter(tags=["strategies"])


@router.get("/strategies", response_model=list[StrategyItem])
def list_strategies(load_modules: bool = False):
    return strategy_catalog.list_strategies(load_modules=load_modules)


@router.post("/strategies/{key}/enable")
def enable_strategy(key: str):
    return _set_enabled(key, True)


@router.post("/strategies/{key}/disable")
def disable_strategy(key: str):
    return _set_enabled(key, False)


def _set_enabled(key: str, enabled: bool) -> dict:
    known = {e["key"] for e in strategy_catalog.list_strategies()}
    if key not in known:
        raise HTTPException(status_code=404, detail=f"Estrategia no encontrada: {key}")
    active = [str(k) for k in (getattr(config, "ACTIVE_STRATEGIES", []) or [])]
    if enabled and key not in active:
        active.append(key)
    if not enabled and key in active:
        active.remove(key)
    config.ACTIVE_STRATEGIES = active
    return {"key": key, "enabled": enabled, "active_strategies": active}
