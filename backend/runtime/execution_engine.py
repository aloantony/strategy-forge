"""
ExecutionEngine v1.
Ejecuta acciones normalizadas usando los helpers técnicos de trading.py.
Persiste recursos canónicos (legs, entry_groups, fills) y eventos.
"""

import uuid
from datetime import datetime, timezone
from backend.brokers.interface import IBrokerAdapter


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return str(uuid.uuid4())


class ExecutionEngine:
    """
    Ejecuta un plan normalizado.

    Parámetros:
    - broker: IBrokerAdapter — adaptador de broker (reemplaza trading_module)
    - uow: UnitOfWork de persistencia
    - symbol: símbolo a operar
    - magic_number: magic number de la estrategia
    - strategy_key: clave de la estrategia
    - instance_id: ID de la instancia
    """

    def __init__(
        self,
        broker: IBrokerAdapter,
        uow,
        symbol: str,
        magic_number: int,
        strategy_key: str,
        instance_id: str,
        mode: str = "live",
    ):
        self._broker = broker
        self._uow = uow
        self._symbol = symbol
        self._magic = magic_number
        self._strategy_key = strategy_key
        self._instance_id = instance_id
        self._mode = mode

    def execute_plan(
        self,
        plan: dict,
        normalized_actions: list,
        state_revision_before: int = 0,
        new_state_revision: int = 0,
        iteration_id: str = "",
    ) -> dict:
        """
        Ejecuta todas las acciones normalizadas.
        Devuelve un execution_report dict.
        """
        plan_id = plan.get("plan_id", _new_id())
        report_id = _new_id()
        now = _now_utc()

        action_reports = []
        executed_count = 0
        error_count = 0

        for norm_action in normalized_actions:
            action_report = self._execute_action(
                norm_action, plan_id, report_id, iteration_id
            )
            action_reports.append(action_report)
            if action_report["status"] == "executed":
                executed_count += 1
            elif action_report["status"] in ("error", "rejected_broker", "rejected_technical"):
                error_count += 1

        overall_status = "executed"
        if executed_count == 0 and len(normalized_actions) > 0:
            overall_status = "error" if error_count > 0 else "executed"
        elif error_count > 0:
            overall_status = "partially_executed"

        # Actualizar status del plan en DB
        try:
            with self._uow.immediate():
                self._uow.plans.update_status(plan_id, overall_status)
                report_record = {
                    "report_id": report_id,
                    "plan_id": plan_id,
                    "instance_id": self._instance_id,
                    "strategy_key": self._strategy_key,
                    "symbol": self._symbol,
                    "status": overall_status,
                    "summary": f"{executed_count}/{len(normalized_actions)} acciones ejecutadas",
                    "previous_state_revision": state_revision_before,
                    "new_state_revision": new_state_revision,
                    "stats": {"executed": executed_count, "errors": error_count, "total": len(normalized_actions)},
                    "report": {"action_reports": action_reports},
                    "created_at": now,
                }
                self._uow.execution_reports.insert(report_record)
                for ar in action_reports:
                    self._uow.action_reports.insert({
                        **ar,
                        "report_id": report_id,
                        "plan_id": plan_id,
                    })
                self._uow.event_log.append({
                    "event_type": "plan_executed",
                    "iteration_id": iteration_id,
                    "mode": self._mode,
                    "strategy_key": self._strategy_key,
                    "instance_id": self._instance_id,
                    "symbol": self._symbol,
                    "plan_id": plan_id,
                    "report_id": report_id,
                    "payload": {"status": overall_status, "executed": executed_count},
                })
        except Exception:
            pass

        return {
            "report_id": report_id,
            "plan_id": plan_id,
            "status": overall_status,
            "summary": f"{executed_count}/{len(normalized_actions)} acciones ejecutadas",
            "action_reports": action_reports,
        }

    def _execute_action(
        self, norm_action: dict, plan_id: str, report_id: str, iteration_id: str
    ) -> dict:
        action_type = norm_action.get("type", "")
        action_id = norm_action.get("action_id", _new_id())
        symbol = norm_action.get("symbol", self._symbol)
        reason = norm_action.get("reason", "")

        try:
            if action_type in ("open_position", "add_to_position"):
                return self._execute_open(norm_action, plan_id, action_id, iteration_id)
            elif action_type == "close_position":
                return self._execute_close(norm_action, plan_id, action_id, iteration_id)
            elif action_type == "reduce_position":
                return self._execute_reduce(norm_action, plan_id, action_id, iteration_id)
            elif action_type == "move_stop_loss":
                return self._execute_move_sl(norm_action, plan_id, action_id)
            elif action_type == "move_take_profit":
                return self._execute_move_tp(norm_action, plan_id, action_id)
            else:
                return self._action_report(action_id, action_type, symbol, "not_supported",
                                           f"Tipo de acción no soportado: {action_type}")
        except Exception as exc:
            return self._action_report(action_id, action_type, symbol, "error", str(exc))

    def _execute_open(
        self, norm_action: dict, plan_id: str, action_id: str, iteration_id: str
    ) -> dict:
        resolved = norm_action.get("resolved", {})
        side = norm_action.get("side", "long")
        symbol = norm_action.get("symbol", self._symbol)
        reason = norm_action.get("reason", "")
        tags = norm_action.get("tags", {})

        volume = resolved.get("volume", 0.01)
        sl_price = resolved.get("sl_price")
        tp_price = resolved.get("tp_price")

        order_type = 0 if side == "long" else 1  # ORDER_TYPE_BUY / SELL

        result = self._broker.send_order(
            symbol=symbol,
            order_type=order_type,
            lot=volume,
            magic=self._magic,
            sl_price=sl_price,
            tp_price=tp_price,
            strategy_key=self._strategy_key,
            strategy_label=self._strategy_key,
            signal_reason=reason,
        )

        success = result.success
        broker_order_id = result.order_id if result.order_id else None
        broker_deal_id = result.deal_id if result.deal_id else None
        entry_price = resolved.get("entry_price", 0.0)

        # Persistir recursos canónicos si la orden fue exitosa
        if success:
            leg_id = _new_id()
            group_id = self._get_or_create_group(
                norm_action, plan_id, side, symbol, leg_id
            )
            self._persist_open_leg(
                leg_id=leg_id,
                entry_group_id=group_id,
                plan_id=plan_id,
                action_id=action_id,
                side=side,
                symbol=symbol,
                volume=volume,
                entry_price=entry_price,
                sl_price=sl_price,
                tp_price=tp_price,
                broker_order_id=broker_order_id,
                tags=tags,
            )
            self._persist_fill(
                leg_id=leg_id,
                entry_group_id=group_id,
                side=side,
                symbol=symbol,
                volume=volume,
                price=entry_price,
                fill_kind="open",
                broker_deal_id=broker_deal_id,
                broker_order_id=broker_order_id,
            )
            self._log_event("position_opened", plan_id=plan_id, action_id=action_id,
                            leg_id=leg_id, entry_group_id=group_id,
                            payload={"side": side, "volume": volume, "sl": sl_price, "tp": tp_price})
        else:
            retcode = result.retcode
            comment = result.comment
            return self._action_report(
                action_id, norm_action.get("type", "open_position"), symbol,
                "rejected_broker",
                f"MT5 retcode={retcode}: {comment}",
                broker_result={"retcode": retcode, "comment": comment},
            )

        return self._action_report(
            action_id, norm_action.get("type", "open_position"), symbol,
            "executed",
            f"Posición abierta: {side} {volume} @ {entry_price:.5f}",
            broker_result={"order": broker_order_id, "deal": broker_deal_id},
        )

    def _execute_close(
        self, norm_action: dict, plan_id: str, action_id: str, iteration_id: str
    ) -> dict:
        symbol = norm_action.get("symbol", self._symbol)
        reason = norm_action.get("reason", "")
        target = norm_action.get("target", {})

        # Determinar qué legs cerrar
        target_mode = target.get("mode", "")
        target_side = target.get("value", "")
        resource_type = target.get("resource_type", "")

        closed_legs = []
        try:
            open_legs = self._uow.legs.list_open_by_instance(self._instance_id)
            if resource_type == "owned_side" and target_side:
                legs_to_close = [l for l in open_legs if l.get("side") == target_side]
            elif resource_type == "entry_group" and target.get("mode") == "by_id":
                group_id = target.get("value", "")
                legs_to_close = self._uow.legs.list_open_by_group(group_id)
            else:
                legs_to_close = open_legs
        except Exception:
            legs_to_close = []

        success = self._broker.close_position(
            symbol=symbol,
            magic=self._magic,
            strategy_key=self._strategy_key,
            strategy_label=self._strategy_key,
            close_reason=reason,
        )

        if success:
            now = _now_utc()
            for leg in legs_to_close:
                leg_id = leg.get("leg_id", "")
                try:
                    with self._uow.immediate():
                        self._uow.legs.update_leg_state(leg_id, {
                            "status": "closed",
                            "remaining_volume": 0.0,
                            "closed_at": now,
                        })
                        group_id = leg.get("entry_group_id", "")
                        if group_id:
                            remaining = self._uow.legs.list_open_by_group(group_id)
                            if not remaining:
                                self._uow.entry_groups.update_group_state(
                                    group_id, "closed", now
                                )
                        self._log_event("position_closed", plan_id=plan_id, action_id=action_id,
                                        leg_id=leg_id, entry_group_id=group_id,
                                        payload={"reason": reason})
                except Exception:
                    pass
                closed_legs.append(leg_id)

        status = "executed" if success else "rejected_broker"
        msg = f"Cerradas {len(closed_legs)} legs" if success else "Error cerrando posición"
        return self._action_report(action_id, "close_position", symbol, status, msg)

    def _execute_reduce(
        self, norm_action: dict, plan_id: str, action_id: str, iteration_id: str
    ) -> dict:
        # Para v1 inicial, reduce_position usa el mismo mecanismo que close pero parcial
        # Delegamos a close como simplificación — en v2 se puede hacer parcial real
        return self._execute_close(norm_action, plan_id, action_id, iteration_id)

    def _execute_move_sl(self, norm_action: dict, plan_id: str, action_id: str) -> dict:
        symbol = norm_action.get("symbol", self._symbol)
        resolved = norm_action.get("resolved", {})
        new_sl = resolved.get("new_sl_price")

        if new_sl is None:
            return self._action_report(action_id, "move_stop_loss", symbol,
                                       "rejected_technical", "No se pudo resolver el nuevo SL")

        try:
            success = self._broker.modify_sl(
                symbol=symbol,
                magic=self._magic,
                new_sl_price=new_sl,
            )
        except Exception as exc:
            return self._action_report(action_id, "move_stop_loss", symbol, "error", str(exc))

        status = "executed" if success else "rejected_broker"
        msg = f"SL movido a {new_sl:.5f}" if success else "Error moviendo SL"
        return self._action_report(action_id, "move_stop_loss", symbol, status, msg)

    def _execute_move_tp(self, norm_action: dict, plan_id: str, action_id: str) -> dict:
        symbol = norm_action.get("symbol", self._symbol)
        resolved = norm_action.get("resolved", {})
        new_tp = resolved.get("new_tp_price")

        if new_tp is None:
            return self._action_report(action_id, "move_take_profit", symbol,
                                       "rejected_technical", "No se pudo resolver el nuevo TP")

        try:
            success = self._broker.modify_tp(
                symbol=symbol,
                magic=self._magic,
                new_tp_price=new_tp,
            )
        except Exception as exc:
            return self._action_report(action_id, "move_take_profit", symbol,
                                       "error", str(exc))

        status = "executed" if success else "rejected_broker"
        msg    = f"TP movido a {new_tp:.5f}" if success else "Error moviendo TP"
        return self._action_report(action_id, "move_take_profit", symbol, status, msg)

    # ------------------------------------------------------------------
    # Helpers de persistencia
    # ------------------------------------------------------------------

    def _get_or_create_group(
        self, norm_action: dict, plan_id: str, side: str, symbol: str, first_leg_id: str
    ) -> str:
        """Devuelve entry_group_id: crea uno nuevo o reutiliza el existente."""
        group_spec = norm_action.get("group_spec") or {}
        mode = group_spec.get("mode", "new_group")

        if mode == "existing_group":
            target = group_spec.get("target", {})
            if target.get("mode") == "by_id":
                return target["value"]

        # new_group: crear nuevo entry_group
        group_id = _new_id()
        try:
            with self._uow.immediate():
                self._uow.entry_groups.insert({
                    "entry_group_id": group_id,
                    "instance_id": self._instance_id,
                    "strategy_key": self._strategy_key,
                    "symbol": symbol,
                    "side": side,
                    "status": "open",
                    "created_by_plan_id": plan_id,
                    "tags": norm_action.get("tags", {}),
                })
                self._log_event("entry_group_created", plan_id=plan_id,
                                entry_group_id=group_id,
                                payload={"side": side, "symbol": symbol})
        except Exception:
            pass
        return group_id

    def _persist_open_leg(
        self, leg_id, entry_group_id, plan_id, action_id,
        side, symbol, volume, entry_price, sl_price, tp_price,
        broker_order_id, tags,
    ):
        now = _now_utc()
        try:
            with self._uow.immediate():
                self._uow.legs.insert({
                    "leg_id": leg_id,
                    "instance_id": self._instance_id,
                    "entry_group_id": entry_group_id,
                    "strategy_key": self._strategy_key,
                    "symbol": symbol,
                    "side": side,
                    "status": "open",
                    "opened_by_plan_id": plan_id,
                    "opened_by_action_id": action_id,
                    "origin_order_id": broker_order_id,
                    "requested_volume": volume,
                    "opened_volume": volume,
                    "remaining_volume": volume,
                    "avg_entry_price": entry_price,
                    "stop_loss": sl_price,
                    "take_profit": tp_price,
                    "opened_at": now,
                    "tags": tags,
                })
                # Actualizar root_leg si es la primera del grupo
                group = self._uow.entry_groups.get(entry_group_id)
                if group and not group.get("root_leg_id"):
                    self._uow.entry_groups.set_root_leg(entry_group_id, leg_id)
        except Exception:
            pass

    def _persist_fill(
        self, leg_id, entry_group_id, side, symbol,
        volume, price, fill_kind, broker_deal_id, broker_order_id,
    ):
        try:
            with self._uow.immediate():
                self._uow.fills.insert({
                    "fill_id": _new_id(),
                    "instance_id": self._instance_id,
                    "strategy_key": self._strategy_key,
                    "symbol": symbol,
                    "entry_group_id": entry_group_id,
                    "leg_id": leg_id,
                    "side": side,
                    "fill_kind": fill_kind,
                    "volume": volume,
                    "price": price if price > 0 else 1.0,
                    "broker_deal_id": broker_deal_id,
                    "broker_order_id": broker_order_id,
                })
        except Exception:
            pass

    def _log_event(self, event_type: str, **kwargs):
        payload = kwargs.pop("payload", {})
        try:
            self._uow.event_log.append({
                "event_type": event_type,
                "mode": self._mode,
                "strategy_key": self._strategy_key,
                "instance_id": self._instance_id,
                "symbol": self._symbol,
                "payload": payload,
                **kwargs,
            })
        except Exception:
            pass

    def _action_report(
        self,
        action_id: str,
        action_type: str,
        symbol: str,
        status: str,
        message: str,
        broker_result: dict | None = None,
    ) -> dict:
        return {
            "action_report_id": _new_id(),
            "action_id": action_id,
            "action_type": action_type,
            "symbol": symbol,
            "status": status,
            "message": message,
            "requested": {},
            "resolved_targets": {},
            "resolved_values": {},
            "normalization": {},
            "broker_result": broker_result or {},
            "resource_effects": {},
            "timing": {"created_at": _now_utc()},
            "created_at": _now_utc(),
        }
