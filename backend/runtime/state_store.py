# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
StrategyStateStore v1.
Carga y persiste el estado estratégico por instancia.
"""

from datetime import datetime, timezone


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StrategyStateStore:
    """
    Gestiona el ciclo de vida del state de una estrategia.

    El state devuelto a la estrategia es solo la parte strategy_state (libre).
    El envelope técnico lo gestiona el store internamente.
    """

    def __init__(self, uow):
        self._uow = uow

    def load(self, instance_id: str) -> tuple[dict, int]:
        """
        Carga el state de la instancia.
        Devuelve (strategy_state_dict, revision).
        Si no existe, devuelve ({}, 0).
        """
        record = self._uow.strategy_state.get(instance_id)
        if record is None:
            return {}, 0
        state_payload = record.get("state", {})
        strategy_state = state_payload.get("strategy_state", state_payload)
        revision = record.get("revision", 0)
        return strategy_state, revision

    def save(
        self,
        instance_id: str,
        strategy_key: str,
        symbol: str,
        strategy_state: dict,
        schema_version: int = 1,
        last_decision_id: str | None = None,
        expected_revision: int | None = None,
    ) -> int:
        """
        Persiste el nuevo state de la estrategia.
        Si expected_revision se especifica, usa control optimista de concurrencia.
        Devuelve la nueva revision.
        """
        existing = self._uow.strategy_state.get(instance_id)
        now = _now_utc()

        if existing is None:
            new_revision = 1
            record = {
                "instance_id": instance_id,
                "strategy_key": strategy_key,
                "symbol": symbol,
                "schema_version": schema_version,
                "revision": new_revision,
                "last_decision_id": last_decision_id,
                "state": {"strategy_state": strategy_state},
                "created_at": now,
            }
            self._uow.strategy_state.upsert(record)
            return new_revision

        current_revision = existing.get("revision", 0)
        new_revision = current_revision + 1

        new_record = {
            "schema_version": schema_version,
            "revision": new_revision,
            "last_decision_id": last_decision_id,
            "state": {"strategy_state": strategy_state},
        }

        if expected_revision is not None:
            self._uow.strategy_state.update_if_revision_matches(
                instance_id, expected_revision, new_record
            )
        else:
            # Upsert directo sin control de concurrencia
            self._uow.strategy_state.upsert({
                **new_record,
                "instance_id": instance_id,
                "strategy_key": strategy_key,
                "symbol": symbol,
            })

        return new_revision

    def get_or_initialize(
        self,
        instance_id: str,
        strategy_key: str,
        symbol: str,
        module,
        context: dict,
    ) -> tuple[dict, int]:
        """
        Carga el state existente o llama a initial_state() del módulo v1.
        Devuelve (strategy_state_dict, revision).
        """
        strategy_state, revision = self.load(instance_id)
        if revision == 0 and hasattr(module, "initial_state"):
            try:
                strategy_state = module.initial_state(context) or {}
            except Exception:
                strategy_state = {}
        return strategy_state, revision
